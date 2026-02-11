from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree

from .android_accessibility import extract_accessible_strings
from .config import load_json_file


class OfflineArtifactExtractionError(RuntimeError):
    pass


@dataclass(frozen=True)
class OfflineArtifactExtractionResult:
    screens_jsonl_path: Path
    summary_json_path: Path
    nodes_jsonl_path: Optional[Path]
    processed_xml_files: int
    failed_xml_files: int


_TS_SUFFIX_RE = re.compile(r"^(?P<base>.+)_(?P<ts>\d{8}-\d{6}-\d{6})$")
_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
_PROMPT_ANSWER_RE = re.compile(
    r"^\s*prompt:\s*(?P<prompt>.*?)\s*answer:\s*(?P<answer>.*)\s*$",
    flags=re.IGNORECASE,
)


def _as_non_empty_str(value: Any, *, field: str, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OfflineArtifactExtractionError(f"{context}: '{field}' must be a non-empty string")
    return value.strip()


def _as_positive_int(value: Any, *, field: str, context: str) -> int:
    try:
        parsed = int(value)
    except Exception as e:
        raise OfflineArtifactExtractionError(f"{context}: '{field}' must be an integer") from e
    if parsed <= 0:
        raise OfflineArtifactExtractionError(f"{context}: '{field}' must be > 0")
    return parsed


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _parse_timestamp_suffix(stem: str) -> tuple[str, Optional[datetime]]:
    match = _TS_SUFFIX_RE.match(stem)
    if not match:
        return stem, None

    base = match.group("base")
    ts_raw = match.group("ts")
    try:
        parsed = datetime.strptime(ts_raw, "%Y%m%d-%H%M%S-%f")
    except Exception:
        return base, None
    return base, parsed


def _normalize_pairing_base(base: str) -> str:
    out = base
    for suffix in ("_source", "_screenshot", "_page_source", "_page", "_screen"):
        if out.endswith(suffix):
            out = out[: -len(suffix)]
    return out


def _pair_screenshots_with_xml(artifacts_dir: Path) -> dict[Path, Optional[Path]]:
    xml_paths = sorted(p for p in artifacts_dir.glob("*.xml") if p.is_file())
    png_paths = sorted(p for p in artifacts_dir.glob("*.png") if p.is_file())

    png_index: dict[str, list[tuple[Optional[datetime], Path]]] = {}
    for png in png_paths:
        base, ts = _parse_timestamp_suffix(png.stem)
        key = _normalize_pairing_base(base)
        png_index.setdefault(key, []).append((ts, png))

    pairings: dict[Path, Optional[Path]] = {}
    for xml in xml_paths:
        xml_base, xml_ts = _parse_timestamp_suffix(xml.stem)
        key = _normalize_pairing_base(xml_base)
        candidates = png_index.get(key, [])
        if not candidates:
            pairings[xml] = None
            continue

        if xml_ts is None:
            pairings[xml] = candidates[-1][1]
            continue

        nearest_path: Optional[Path] = None
        nearest_delta: Optional[float] = None
        for candidate_ts, candidate_path in candidates:
            if candidate_ts is None:
                continue
            delta = abs((candidate_ts - xml_ts).total_seconds())
            if nearest_delta is None or delta < nearest_delta:
                nearest_delta = delta
                nearest_path = candidate_path

        if nearest_path is None:
            pairings[xml] = candidates[-1][1]
        else:
            pairings[xml] = nearest_path

    return pairings


def _parse_bounds(bounds_raw: Optional[str]) -> Optional[tuple[int, int, int, int]]:
    if not bounds_raw:
        return None
    match = _BOUNDS_RE.search(bounds_raw)
    if not match:
        return None
    x1, y1, x2, y2 = (int(match.group(i)) for i in range(1, 5))
    return x1, y1, x2, y2


def _classify_hinge_screen(strings: list[str]) -> str:
    lowered = [s.lower() for s in strings]

    if any("no matches yet" in s for s in lowered):
        return "hinge_matches_empty"
    if any("when a like is mutual" in s for s in lowered):
        return "hinge_matches_empty"
    if any(s.startswith("skip ") for s in lowered) and any(s.startswith("like ") for s in lowered):
        return "hinge_discover_card"
    if any("send" in s for s in lowered) and any("match" in s for s in lowered):
        return "hinge_chat_or_inbox"
    if "matches" in lowered and "discover" in lowered:
        return "hinge_tab_shell"
    return "hinge_unknown"


def _extract_hinge_quality_features(strings: list[str]) -> dict[str, Any]:
    profile_name = None
    prompt_text = None
    prompt_answer = None
    like_targets: list[str] = []
    quality_flags: list[str] = []

    for s in strings:
        lowered = s.lower()
        if lowered.endswith("'s photo") or lowered.endswith("’s photo"):
            if profile_name is None:
                profile_name = s.split("'s photo")[0].split("’s photo")[0].strip()

        if lowered.startswith("prompt:"):
            match = _PROMPT_ANSWER_RE.match(s)
            if match:
                prompt_text = match.group("prompt").strip() or None
                prompt_answer = match.group("answer").strip() or None
            else:
                prompt_text = s

        if lowered.startswith("like "):
            like_targets.append(s)

        if "selfie verified" in lowered:
            quality_flags.append("selfie_verified")
        if "active today" in lowered:
            quality_flags.append("active_today")
        if "voice prompt" in lowered:
            quality_flags.append("has_voice_prompt")

    return {
        "profile_name_candidate": profile_name,
        "prompt_text": prompt_text,
        "prompt_answer": prompt_answer,
        "like_targets": like_targets,
        "quality_flags": sorted(set(quality_flags)),
    }


def _score_hinge_quality_v1(*, screen_type: str, quality_features: dict[str, Any]) -> dict[str, Any]:
    """
    Simple deterministic baseline score for downstream ranking experiments.

    Score range is intentionally bounded to 0..100 so it can be used directly
    in sorting/filtering pipelines.
    """
    score = 0
    reasons: list[str] = []

    if screen_type == "hinge_discover_card":
        score += 20
        reasons.append("discover_card_surface")
    if screen_type == "hinge_matches_empty":
        score = 0
        reasons.append("matches_empty_state")
        return {"quality_score_v1": score, "quality_reasons_v1": reasons}

    flags = set(quality_features.get("quality_flags") or [])
    if "selfie_verified" in flags:
        score += 20
        reasons.append("selfie_verified")
    if "active_today" in flags:
        score += 15
        reasons.append("active_today")
    if "has_voice_prompt" in flags:
        score += 10
        reasons.append("has_voice_prompt")

    prompt_answer = (quality_features.get("prompt_answer") or "").strip()
    if prompt_answer:
        score += 15
        reasons.append("has_prompt_answer")

    like_targets = quality_features.get("like_targets") or []
    if isinstance(like_targets, list) and like_targets:
        capped = min(len(like_targets), 3)
        score += capped * 8
        reasons.append(f"like_targets:{capped}")

    profile_name = (quality_features.get("profile_name_candidate") or "").strip()
    if profile_name:
        score += 8
        reasons.append("name_visible")

    score = max(0, min(score, 100))
    return {"quality_score_v1": score, "quality_reasons_v1": reasons}


def _extract_package_name(root: ElementTree.Element) -> Optional[str]:
    for node in root.iter():
        package = (node.attrib or {}).get("package")
        if package:
            return package
    return None


def _extract_nodes(
    *,
    root: ElementTree.Element,
    max_nodes_per_screen: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, node in enumerate(root.iter(), 1):
        if idx > max_nodes_per_screen:
            break
        attrib = node.attrib or {}
        bounds = _parse_bounds(attrib.get("bounds"))
        out.append(
            {
                "ordinal": idx,
                "class_name": attrib.get("class") or None,
                "resource_id": attrib.get("resource-id") or None,
                "text": attrib.get("text") or None,
                "content_desc": attrib.get("content-desc") or None,
                "clickable": (attrib.get("clickable") == "true"),
                "enabled": (attrib.get("enabled") == "true"),
                "bounds": list(bounds) if bounds is not None else None,
            }
        )
    return out


def run_offline_artifact_extraction(*, config_json_path: str) -> OfflineArtifactExtractionResult:
    """
    Read captured mobile artifacts (XML + optional screenshots) and export normalized JSONL.

    Config schema:
      {
        "artifacts_dir": "artifacts",
        "xml_glob": "*.xml",
        "app": "hinge",
        "output_dir": "artifacts/offline_exports",
        "output_prefix": "hinge_offline",
        "max_files": 200,
        "max_nodes_per_screen": 3000,
        "include_node_rows": true,
        "package_allowlist": ["co.hinge.app"]
      }
    """
    config = load_json_file(config_json_path)

    artifacts_dir = Path(
        _as_non_empty_str(config.get("artifacts_dir") or "artifacts", field="artifacts_dir", context=config_json_path)
    ).resolve()
    if not artifacts_dir.exists() or not artifacts_dir.is_dir():
        raise OfflineArtifactExtractionError(
            f"{config_json_path}: artifacts_dir does not exist or is not a directory: {artifacts_dir}"
        )

    xml_glob = _as_non_empty_str(config.get("xml_glob") or "*.xml", field="xml_glob", context=config_json_path)
    app = str(config.get("app") or "auto").strip().lower()
    output_dir = Path(str(config.get("output_dir") or "artifacts/offline_exports")).resolve()
    output_prefix = _as_non_empty_str(
        config.get("output_prefix") or "mobile_offline_export",
        field="output_prefix",
        context=config_json_path,
    )
    max_files = _as_positive_int(config.get("max_files", 200), field="max_files", context=config_json_path)
    max_nodes_per_screen = _as_positive_int(
        config.get("max_nodes_per_screen", 3000),
        field="max_nodes_per_screen",
        context=config_json_path,
    )
    include_node_rows = bool(config.get("include_node_rows", True))
    package_allowlist_raw = config.get("package_allowlist")
    package_allowlist: Optional[set[str]] = None
    if package_allowlist_raw is not None:
        if (
            not isinstance(package_allowlist_raw, list)
            or not package_allowlist_raw
            or not all(isinstance(x, str) and x.strip() for x in package_allowlist_raw)
        ):
            raise OfflineArtifactExtractionError(
                f"{config_json_path}: package_allowlist must be a non-empty list of strings when provided"
            )
        package_allowlist = {x.strip() for x in package_allowlist_raw}

    _ensure_dir(output_dir)
    now = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    screens_jsonl_path = output_dir / f"{output_prefix}_screens_{now}.jsonl"
    summary_json_path = output_dir / f"{output_prefix}_summary_{now}.json"
    nodes_jsonl_path = output_dir / f"{output_prefix}_nodes_{now}.jsonl" if include_node_rows else None

    xml_paths = sorted(p for p in artifacts_dir.glob(xml_glob) if p.is_file())
    if not xml_paths:
        raise OfflineArtifactExtractionError(
            f"{config_json_path}: no XML files matched glob {xml_glob!r} in {artifacts_dir}"
        )
    xml_paths = xml_paths[:max_files]

    screenshot_pairs = _pair_screenshots_with_xml(artifacts_dir)

    processed = 0
    failed = 0
    skipped_by_package = 0
    screen_type_counts: dict[str, int] = {}
    package_counts: dict[str, int] = {}
    errors: list[dict[str, str]] = []

    with screens_jsonl_path.open("w", encoding="utf-8") as screens_f:
        nodes_f = nodes_jsonl_path.open("w", encoding="utf-8") if nodes_jsonl_path is not None else None
        try:
            for xml_path in xml_paths:
                try:
                    xml_raw = xml_path.read_text(encoding="utf-8")
                    root = ElementTree.fromstring(xml_raw)

                    strings = extract_accessible_strings(xml_raw, limit=max_nodes_per_screen)
                    package_name = _extract_package_name(root)
                    if package_allowlist is not None and package_name not in package_allowlist:
                        skipped_by_package += 1
                        continue
                    screen_type = "unknown"
                    quality_features: dict[str, Any] = {}

                    if app == "hinge" or (app == "auto" and package_name == "co.hinge.app"):
                        screen_type = _classify_hinge_screen(strings)
                        quality_features = _extract_hinge_quality_features(strings)
                    quality_score_block = (
                        _score_hinge_quality_v1(screen_type=screen_type, quality_features=quality_features)
                        if package_name == "co.hinge.app"
                        else {"quality_score_v1": None, "quality_reasons_v1": []}
                    )

                    base_stem, capture_ts = _parse_timestamp_suffix(xml_path.stem)
                    source_id = base_stem
                    screenshot_path = screenshot_pairs.get(xml_path)

                    nodes = _extract_nodes(root=root, max_nodes_per_screen=max_nodes_per_screen)

                    screen_row = {
                        "source_id": source_id,
                        "source_path": str(xml_path.resolve()),
                        "screenshot_path": None if screenshot_path is None else str(screenshot_path.resolve()),
                        "capture_timestamp": None if capture_ts is None else capture_ts.isoformat(),
                        "app_mode": app,
                        "package_name": package_name,
                        "screen_type": screen_type,
                        "accessible_strings_count": len(strings),
                        "accessible_strings": strings,
                        "quality_features": quality_features,
                        **quality_score_block,
                        "node_count": len(nodes),
                    }
                    screens_f.write(json.dumps(screen_row, ensure_ascii=False) + "\n")

                    if nodes_f is not None:
                        for node in nodes:
                            node_row = {
                                "source_id": source_id,
                                "source_path": str(xml_path.resolve()),
                                "package_name": package_name,
                                "screen_type": screen_type,
                                **node,
                            }
                            nodes_f.write(json.dumps(node_row, ensure_ascii=False) + "\n")

                    processed += 1
                    screen_type_counts[screen_type] = screen_type_counts.get(screen_type, 0) + 1
                    if package_name:
                        package_counts[package_name] = package_counts.get(package_name, 0) + 1
                except Exception as e:
                    failed += 1
                    errors.append({"source_path": str(xml_path.resolve()), "error": str(e)})
        finally:
            if nodes_f is not None:
                nodes_f.close()

    summary = {
        "config_path": str(Path(config_json_path).resolve()),
        "artifacts_dir": str(artifacts_dir),
        "xml_glob": xml_glob,
        "app_mode": app,
        "processed_xml_files": processed,
        "failed_xml_files": failed,
        "skipped_by_package": skipped_by_package,
        "screen_type_counts": screen_type_counts,
        "package_counts": package_counts,
        "screens_jsonl_path": str(screens_jsonl_path),
        "nodes_jsonl_path": None if nodes_jsonl_path is None else str(nodes_jsonl_path),
        "errors": errors,
    }
    summary_json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    return OfflineArtifactExtractionResult(
        screens_jsonl_path=screens_jsonl_path,
        summary_json_path=summary_json_path,
        nodes_jsonl_path=nodes_jsonl_path,
        processed_xml_files=processed,
        failed_xml_files=failed,
    )
