from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree

from .android_accessibility import extract_accessible_strings
from .appium_http_client import AppiumHTTPClient, WebDriverElementRef
from .config import load_json_file, require_key


class FullFidelityHingeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Locator:
    using: str
    value: str


@dataclass(frozen=True)
class NavigationConfig:
    mode: str
    poll_every_iterations: int
    execute: bool


@dataclass(frozen=True)
class FullFidelityHingeResult:
    session_id: str
    iterations: int
    frames_jsonl_path: Path
    profiles_jsonl_path: Path
    messages_jsonl_path: Path
    nodes_jsonl_path: Path
    summary_json_path: Path
    session_dir: Path


_PROMPT_ANSWER_RE = re.compile(
    r"^\s*prompt:\s*(?P<prompt>.*?)\s*answer:\s*(?P<answer>.*)\s*$",
    flags=re.IGNORECASE,
)
_PHOTO_NAME_RE = re.compile(r"^(?P<name>.+?)['’]s photo$", flags=re.IGNORECASE)
_CHROME_EXACT = {
    "discover",
    "matches",
    "likes you",
    "standouts",
    "profile hub",
    "back",
    "more",
    "send",
    "skip",
    "close sheet",
    "boost your profile",
    "upgrade to hingex",
}
_CHROME_SUBSTR = [
    "type a message",
    "when a like is mutual",
    "you’re new, no matches yet",
    "you're new, no matches yet",
    "like photo",
    "like prompt",
    "voice prompt",
    "rose",
]


def _as_non_empty_str(value: Any, *, field: str, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FullFidelityHingeError(f"{context}: '{field}' must be a non-empty string")
    return value.strip()


def _as_positive_int(value: Any, *, field: str, context: str) -> int:
    try:
        parsed = int(value)
    except Exception as e:
        raise FullFidelityHingeError(f"{context}: '{field}' must be an integer") from e
    if parsed <= 0:
        raise FullFidelityHingeError(f"{context}: '{field}' must be > 0")
    return parsed


def _as_non_negative_float(value: Any, *, field: str, context: str) -> float:
    try:
        parsed = float(value)
    except Exception as e:
        raise FullFidelityHingeError(f"{context}: '{field}' must be numeric") from e
    if parsed < 0:
        raise FullFidelityHingeError(f"{context}: '{field}' must be >= 0")
    return parsed


def _parse_locator(raw: Any, *, context: str) -> Locator:
    if not isinstance(raw, dict):
        raise FullFidelityHingeError(f"{context}: locator must be an object")
    using = _as_non_empty_str(raw.get("using"), field="using", context=context)
    value = _as_non_empty_str(raw.get("value"), field="value", context=context)
    return Locator(using=using, value=value)


def _parse_locators(raw: Any, *, field: str, context: str) -> list[Locator]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise FullFidelityHingeError(f"{context}: '{field}' must be a list when provided")
    out: list[Locator] = []
    for idx, item in enumerate(raw, 1):
        out.append(_parse_locator(item, context=f"{context}: {field}[{idx}]"))
    return out


def _parse_navigation(raw: Any, *, context: str) -> NavigationConfig:
    if raw is None:
        return NavigationConfig(mode="observe", poll_every_iterations=3, execute=False)
    if not isinstance(raw, dict):
        raise FullFidelityHingeError(f"{context}: navigation must be an object")
    mode = _as_non_empty_str(raw.get("mode") or "observe", field="mode", context=context).lower()
    if mode not in {"observe", "matches_poll"}:
        raise FullFidelityHingeError(f"{context}: navigation.mode must be 'observe' or 'matches_poll'")
    poll_every_iterations = _as_positive_int(
        raw.get("poll_every_iterations", 3),
        field="poll_every_iterations",
        context=f"{context}: navigation",
    )
    execute = bool(raw.get("execute", False))
    return NavigationConfig(
        mode=mode,
        poll_every_iterations=poll_every_iterations,
        execute=execute,
    )


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _artifact_path(*, artifacts_dir: Path, stem: str, ext: str) -> Path:
    safe_stem = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in stem.strip())
    if not safe_stem:
        safe_stem = "artifact"
    return artifacts_dir / f"{safe_stem}_{_timestamp()}.{ext.lstrip('.')}"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _extract_package_name(root: ElementTree.Element) -> Optional[str]:
    for node in root.iter():
        package = (node.attrib or {}).get("package")
        if package:
            return package
    return None


def _parse_bounds(bounds_raw: Optional[str]) -> Optional[tuple[int, int, int, int]]:
    if not bounds_raw:
        return None
    match = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_raw)
    if not match:
        return None
    return tuple(int(match.group(i)) for i in range(1, 5))


def _extract_nodes(*, root: ElementTree.Element, max_nodes_per_frame: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, node in enumerate(root.iter(), 1):
        if idx > max_nodes_per_frame:
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


def _classify_hinge_screen(strings: list[str]) -> str:
    lowered = [s.lower() for s in strings]
    if any("close sheet" in s for s in lowered) and any("rose" in s for s in lowered):
        return "hinge_overlay_rose_sheet"
    if any("no matches yet" in s for s in lowered):
        return "hinge_matches_empty"
    if any("when a like is mutual" in s for s in lowered):
        return "hinge_matches_empty"
    if any(s.startswith("skip ") or s == "skip" for s in lowered) and any(s.startswith("like ") for s in lowered):
        return "hinge_discover_card"
    if any("type a message" in s for s in lowered):
        return "hinge_chat"
    if "matches" in lowered and "discover" in lowered:
        return "hinge_tab_shell"
    return "hinge_unknown"


def _is_chrome_text(text: str) -> bool:
    lowered = text.lower().strip()
    if lowered in _CHROME_EXACT:
        return True
    if any(k in lowered for k in _CHROME_SUBSTR):
        return True
    if lowered.startswith("like "):
        return True
    if lowered.startswith("prompt:"):
        return True
    return False


def _extract_profile_snapshot(
    *,
    strings: list[str],
    nodes: list[dict[str, Any]],
    screen_type: str,
) -> dict[str, Any]:
    name_candidates: list[str] = []
    prompt_pairs: list[dict[str, str]] = []
    quality_flags: set[str] = set()
    like_targets: list[str] = []
    bio_candidates: list[str] = []
    photo_labels: list[str] = []

    for s in strings:
        lowered = s.lower().strip()
        photo_match = _PHOTO_NAME_RE.match(s.strip())
        if photo_match:
            candidate = photo_match.group("name").strip()
            if candidate:
                name_candidates.append(candidate)
            photo_labels.append(s.strip())

        prompt_match = _PROMPT_ANSWER_RE.match(s)
        if prompt_match:
            prompt_text = prompt_match.group("prompt").strip()
            answer_text = prompt_match.group("answer").strip()
            prompt_pairs.append({"prompt": prompt_text, "answer": answer_text})

        if lowered.startswith("like "):
            like_targets.append(s)

        if "selfie verified" in lowered:
            quality_flags.add("selfie_verified")
        if "active today" in lowered:
            quality_flags.add("active_today")
        if "voice prompt" in lowered:
            quality_flags.add("has_voice_prompt")

        if not _is_chrome_text(s):
            normalized = s.strip()
            if 3 <= len(normalized) <= 180:
                bio_candidates.append(normalized)

    node_text_values = []
    for node in nodes:
        for key in ("text", "content_desc"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                node_text_values.append(value.strip())

    profile_name = name_candidates[0] if name_candidates else None
    prompt_answers = [p["answer"] for p in prompt_pairs if p.get("answer")]
    media_count = len(photo_labels)
    signal_strength = 0
    if profile_name:
        signal_strength += 1
    if prompt_pairs:
        signal_strength += 1
    if like_targets:
        signal_strength += 1
    if quality_flags:
        signal_strength += 1
    if bio_candidates:
        signal_strength += 1
    completeness_pct = int(round((signal_strength / 5.0) * 100))

    return {
        "screen_type": screen_type,
        "profile_name_candidate": profile_name,
        "name_candidates": sorted(set(name_candidates)),
        "prompt_pairs": prompt_pairs,
        "prompt_answers": prompt_answers,
        "like_targets": like_targets,
        "quality_flags": sorted(quality_flags),
        "bio_candidates": bio_candidates[:30],
        "photo_labels": photo_labels,
        "media_count": media_count,
        "node_text_samples": node_text_values[:40],
        "signal_strength": signal_strength,
        "completeness_pct": completeness_pct,
    }


def _extract_thread_key(strings: list[str]) -> str:
    for s in strings:
        normalized = s.strip()
        lowered = normalized.lower()
        if not normalized:
            continue
        if _is_chrome_text(normalized):
            continue
        if lowered.endswith("'s photo") or lowered.endswith("’s photo"):
            continue
        if len(normalized) > 40:
            continue
        if re.search(r"[0-9]", normalized):
            continue
        if normalized.startswith("Prompt:"):
            continue
        if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{0,38}", normalized):
            return normalized.lower().replace(" ", "_")
    return "__unknown_thread__"


def _extract_chat_messages(strings: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for s in strings:
        normalized = s.strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if _is_chrome_text(normalized):
            continue
        if lowered.endswith("'s photo") or lowered.endswith("’s photo"):
            continue
        if lowered.startswith("prompt:"):
            continue
        if len(normalized) < 2:
            continue
        if len(normalized) > 300:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _compute_new_messages(previous: list[str], current: list[str]) -> list[str]:
    if not previous:
        return current
    previous_counts = Counter(previous)
    new_items: list[str] = []
    for item in current:
        if previous_counts[item] > 0:
            previous_counts[item] -= 1
        else:
            new_items.append(item)
    return new_items


def _find_first_any(client: AppiumHTTPClient, *, locators: list[Locator]) -> tuple[Locator, WebDriverElementRef]:
    for locator in locators:
        elements = client.find_elements(using=locator.using, value=locator.value)
        if elements:
            return locator, elements[0]
    locator_debug = "; ".join(f"{l.using}:{l.value}" for l in locators)
    raise FullFidelityHingeError(f"No elements found for locator candidates: {locator_debug}")


def _has_any(client: AppiumHTTPClient, *, locators: list[Locator]) -> bool:
    if not locators:
        return False
    for locator in locators:
        try:
            elements = client.find_elements(using=locator.using, value=locator.value)
        except Exception:
            continue
        if elements:
            return True
    return False


def _click_any(client: AppiumHTTPClient, *, locators: list[Locator]) -> Locator:
    matched, element = _find_first_any(client, locators=locators)
    client.click(element)
    return matched


def _decide_navigation_action(
    *,
    screen_type: str,
    iteration_idx: int,
    navigation: NavigationConfig,
    locator_map: dict[str, list[Locator]],
    client: AppiumHTTPClient,
) -> tuple[str, str]:
    if navigation.mode == "observe":
        return "none", "observe_mode"

    if screen_type == "hinge_overlay_rose_sheet":
        return "back", "overlay_recovery"

    if screen_type in {"hinge_tab_shell", "hinge_matches_empty"} and _has_any(
        client, locators=locator_map["open_thread"]
    ):
        return "open_thread", "matches_poll_open_thread"

    if iteration_idx % navigation.poll_every_iterations == 0:
        if _has_any(client, locators=locator_map["matches_tab"]):
            return "goto_matches", "matches_poll_interval"
    return "none", "no_nav_needed"


def run_hinge_full_fidelity_capture(*, config_json_path: str) -> FullFidelityHingeResult:
    """
    Capture full-fidelity Hinge session artifacts for downstream automation pipelines.

    Captures:
    - raw XML + screenshot per frame
    - node graph rows
    - normalized profile snapshots (Discover/main-card surfaces)
    - normalized message snapshots and deltas (chat surfaces)

    Config schema:
      {
        "appium_server_url": "http://127.0.0.1:4723",
        "capabilities_json_path": "automation_service/mobile_examples/android_capabilities.example.json",
        "artifacts_dir": "artifacts/full_fidelity_hinge",
        "session_name": "hinge_full_fidelity",
        "pause_before_start": true,
        "max_iterations": 60,
        "loop_sleep_s": 1.0,
        "capture_screenshots": true,
        "capture_xml_artifacts": true,
        "max_nodes_per_frame": 3500,
        "max_accessible_strings": 2500,
        "target_package": "co.hinge.app",
        "navigation": {
          "mode": "observe",
          "poll_every_iterations": 3,
          "execute": false
        },
        "locators": {
          "matches_tab": [...],
          "discover_tab": [...],
          "open_thread": [...],
          "back": [...]
        }
      }
    """
    config = load_json_file(config_json_path)
    context = config_json_path

    appium_server_url = _as_non_empty_str(
        require_key(config, "appium_server_url", context=context),
        field="appium_server_url",
        context=context,
    )
    capabilities_json_path = _as_non_empty_str(
        require_key(config, "capabilities_json_path", context=context),
        field="capabilities_json_path",
        context=context,
    )
    artifacts_dir = Path(str(config.get("artifacts_dir") or "artifacts/full_fidelity_hinge")).resolve()
    session_name = _as_non_empty_str(
        config.get("session_name") or "hinge_full_fidelity",
        field="session_name",
        context=context,
    )
    pause_before_start = bool(config.get("pause_before_start", False))
    max_iterations = _as_positive_int(config.get("max_iterations", 60), field="max_iterations", context=context)
    loop_sleep_s = _as_non_negative_float(config.get("loop_sleep_s", 1.0), field="loop_sleep_s", context=context)
    capture_screenshots = bool(config.get("capture_screenshots", True))
    capture_xml_artifacts = bool(config.get("capture_xml_artifacts", True))
    max_nodes_per_frame = _as_positive_int(
        config.get("max_nodes_per_frame", 3500),
        field="max_nodes_per_frame",
        context=context,
    )
    max_accessible_strings = _as_positive_int(
        config.get("max_accessible_strings", 2500),
        field="max_accessible_strings",
        context=context,
    )
    target_package = _as_non_empty_str(
        config.get("target_package") or "co.hinge.app",
        field="target_package",
        context=context,
    )

    navigation = _parse_navigation(config.get("navigation"), context=context)
    locators_raw = config.get("locators", {})
    if locators_raw is None:
        locators_raw = {}
    if not isinstance(locators_raw, dict):
        raise FullFidelityHingeError(f"{context}: locators must be an object when provided")
    locator_map = {
        "matches_tab": _parse_locators(locators_raw.get("matches_tab"), field="matches_tab", context=context),
        "discover_tab": _parse_locators(locators_raw.get("discover_tab"), field="discover_tab", context=context),
        "open_thread": _parse_locators(locators_raw.get("open_thread"), field="open_thread", context=context),
        "back": _parse_locators(locators_raw.get("back"), field="back", context=context),
    }
    if navigation.mode == "matches_poll" and navigation.execute and not locator_map["matches_tab"]:
        raise FullFidelityHingeError(
            f"{context}: locators.matches_tab must be provided when navigation.mode='matches_poll' and execute=true"
        )

    capabilities_payload = load_json_file(capabilities_json_path)
    require_key(capabilities_payload, "capabilities", context=capabilities_json_path)

    _ensure_dir(artifacts_dir)
    session_dir = artifacts_dir / f"{session_name}_{_timestamp()}"
    captures_dir = session_dir / "captures"
    _ensure_dir(captures_dir)

    frames_jsonl_path = session_dir / "frames.jsonl"
    profiles_jsonl_path = session_dir / "profiles.jsonl"
    messages_jsonl_path = session_dir / "messages.jsonl"
    nodes_jsonl_path = session_dir / "nodes.jsonl"
    summary_json_path = session_dir / "summary.json"

    client = AppiumHTTPClient(appium_server_url)
    session_id = client.create_session(capabilities_payload)
    started = time.time()

    profile_rows = 0
    message_rows = 0
    screen_type_counts: dict[str, int] = {}
    package_counts: dict[str, int] = {}
    nav_counts: dict[str, int] = {}
    thread_state: dict[str, list[str]] = {}
    thread_updates = 0
    captured_iterations = 0

    try:
        print("\n=== Hinge Full Fidelity Capture ===")
        print(f"Config: {Path(config_json_path).resolve()}")
        print(f"Session started: {session_id}")
        print(f"Target package: {target_package}")
        print(f"Navigation mode: {navigation.mode} (execute={navigation.execute})")
        print(f"Output dir: {session_dir}")
        if pause_before_start:
            input("Session started. Open Hinge at the desired surface, then press Enter to start capture...")

        with (
            frames_jsonl_path.open("w", encoding="utf-8") as frames_f,
            profiles_jsonl_path.open("w", encoding="utf-8") as profiles_f,
            messages_jsonl_path.open("w", encoding="utf-8") as messages_f,
            nodes_jsonl_path.open("w", encoding="utf-8") as nodes_f,
        ):
            for iteration_idx in range(1, max_iterations + 1):
                captured_iterations = iteration_idx
                ts = datetime.now().isoformat()

                xml_raw = client.get_page_source()
                xml_sha256 = _sha256_text(xml_raw)
                try:
                    root = ElementTree.fromstring(xml_raw)
                except Exception as e:
                    raise FullFidelityHingeError(f"Failed to parse page source XML: {e}") from e

                package_name = _extract_package_name(root)
                strings = extract_accessible_strings(xml_raw, limit=max_accessible_strings)
                screen_type = (
                    _classify_hinge_screen(strings)
                    if package_name == target_package
                    else "outside_target_package"
                )
                nodes = _extract_nodes(root=root, max_nodes_per_frame=max_nodes_per_frame)
                node_count = len(nodes)
                frame_id = f"{session_id}-{iteration_idx:05d}"

                screenshot_path: Optional[Path] = None
                screenshot_sha256: Optional[str] = None
                if capture_screenshots:
                    screenshot_bytes = client.get_screenshot_png_bytes()
                    screenshot_sha256 = _sha256_bytes(screenshot_bytes)
                    screenshot_path = _artifact_path(
                        artifacts_dir=captures_dir,
                        stem=f"frame_{iteration_idx:05d}_screenshot",
                        ext="png",
                    )
                    screenshot_path.write_bytes(screenshot_bytes)

                xml_path: Optional[Path] = None
                if capture_xml_artifacts:
                    xml_path = _artifact_path(
                        artifacts_dir=captures_dir,
                        stem=f"frame_{iteration_idx:05d}_source",
                        ext="xml",
                    )
                    xml_path.write_text(xml_raw, encoding="utf-8")

                profile_snapshot = _extract_profile_snapshot(
                    strings=strings,
                    nodes=nodes,
                    screen_type=screen_type,
                )
                profile_signal_strength = int(profile_snapshot.get("signal_strength") or 0)
                profile_fingerprint = _sha256_text(
                    json.dumps(profile_snapshot, ensure_ascii=False, sort_keys=True)
                )
                if package_name == target_package and profile_signal_strength > 0:
                    profile_row = {
                        "ts": ts,
                        "session_id": session_id,
                        "frame_id": frame_id,
                        "iteration": iteration_idx,
                        "screen_type": screen_type,
                        "profile_fingerprint": profile_fingerprint,
                        "profile_snapshot": profile_snapshot,
                        "source_path": None if xml_path is None else str(xml_path.resolve()),
                        "screenshot_path": None if screenshot_path is None else str(screenshot_path.resolve()),
                    }
                    profiles_f.write(json.dumps(profile_row, ensure_ascii=False) + "\n")
                    profile_rows += 1

                if package_name == target_package and screen_type == "hinge_chat":
                    thread_key = _extract_thread_key(strings)
                    messages = _extract_chat_messages(strings)
                    prev_messages = thread_state.get(thread_key, [])
                    changed = messages != prev_messages
                    new_messages = _compute_new_messages(prev_messages, messages)
                    event_type = (
                        "thread_first_seen"
                        if thread_key not in thread_state
                        else ("thread_updated" if changed else "thread_unchanged")
                    )
                    if changed:
                        thread_updates += 1
                    thread_state[thread_key] = list(messages)
                    message_row = {
                        "ts": ts,
                        "session_id": session_id,
                        "frame_id": frame_id,
                        "iteration": iteration_idx,
                        "screen_type": screen_type,
                        "thread_key": thread_key,
                        "event_type": event_type,
                        "messages_count": len(messages),
                        "messages": messages,
                        "new_messages": new_messages,
                        "source_path": None if xml_path is None else str(xml_path.resolve()),
                        "screenshot_path": None if screenshot_path is None else str(screenshot_path.resolve()),
                    }
                    messages_f.write(json.dumps(message_row, ensure_ascii=False) + "\n")
                    message_rows += 1
                elif package_name == target_package and screen_type == "hinge_matches_empty":
                    message_row = {
                        "ts": ts,
                        "session_id": session_id,
                        "frame_id": frame_id,
                        "iteration": iteration_idx,
                        "screen_type": screen_type,
                        "thread_key": "__inbox__",
                        "event_type": "matches_empty",
                        "messages_count": 0,
                        "messages": [],
                        "new_messages": [],
                        "source_path": None if xml_path is None else str(xml_path.resolve()),
                        "screenshot_path": None if screenshot_path is None else str(screenshot_path.resolve()),
                    }
                    messages_f.write(json.dumps(message_row, ensure_ascii=False) + "\n")
                    message_rows += 1

                for node in nodes:
                    node_row = {
                        "ts": ts,
                        "session_id": session_id,
                        "frame_id": frame_id,
                        "iteration": iteration_idx,
                        "package_name": package_name,
                        "screen_type": screen_type,
                        "source_path": None if xml_path is None else str(xml_path.resolve()),
                        **node,
                    }
                    nodes_f.write(json.dumps(node_row, ensure_ascii=False) + "\n")

                nav_action = "none"
                nav_reason = "not_requested"
                nav_status = "skipped"
                nav_error: Optional[str] = None
                nav_locator: Optional[dict[str, str]] = None
                if package_name == target_package:
                    nav_action, nav_reason = _decide_navigation_action(
                        screen_type=screen_type,
                        iteration_idx=iteration_idx,
                        navigation=navigation,
                        locator_map=locator_map,
                        client=client,
                    )
                    if nav_action == "none":
                        nav_status = "not_needed"
                    elif not navigation.execute:
                        nav_status = "planned_not_executed"
                    else:
                        try:
                            if nav_action == "goto_matches":
                                matched = _click_any(client, locators=locator_map["matches_tab"])
                                nav_locator = {"using": matched.using, "value": matched.value}
                                nav_status = "executed"
                            elif nav_action == "open_thread":
                                matched = _click_any(client, locators=locator_map["open_thread"])
                                nav_locator = {"using": matched.using, "value": matched.value}
                                nav_status = "executed"
                            elif nav_action == "back":
                                if locator_map["back"]:
                                    matched = _click_any(client, locators=locator_map["back"])
                                    nav_locator = {"using": matched.using, "value": matched.value}
                                else:
                                    client.press_keycode(keycode=4)
                                nav_status = "executed"
                            elif nav_action == "goto_discover":
                                matched = _click_any(client, locators=locator_map["discover_tab"])
                                nav_locator = {"using": matched.using, "value": matched.value}
                                nav_status = "executed"
                            else:
                                nav_status = "unsupported_action"
                                nav_error = f"Unsupported nav action: {nav_action}"
                        except Exception as e:
                            nav_status = "failed"
                            nav_error = str(e)

                frame_row = {
                    "ts": ts,
                    "session_id": session_id,
                    "frame_id": frame_id,
                    "iteration": iteration_idx,
                    "package_name": package_name,
                    "target_package": target_package,
                    "screen_type": screen_type,
                    "xml_sha256": xml_sha256,
                    "screenshot_sha256": screenshot_sha256,
                    "source_path": None if xml_path is None else str(xml_path.resolve()),
                    "screenshot_path": None if screenshot_path is None else str(screenshot_path.resolve()),
                    "accessible_strings_count": len(strings),
                    "accessible_strings": strings,
                    "node_count": node_count,
                    "profile_signal_strength": profile_signal_strength,
                    "profile_fingerprint": profile_fingerprint if profile_signal_strength > 0 else None,
                    "nav_action": nav_action,
                    "nav_reason": nav_reason,
                    "nav_status": nav_status,
                    "nav_error": nav_error,
                    "nav_locator": nav_locator,
                }
                frames_f.write(json.dumps(frame_row, ensure_ascii=False) + "\n")

                screen_type_counts[screen_type] = screen_type_counts.get(screen_type, 0) + 1
                if package_name:
                    package_counts[package_name] = package_counts.get(package_name, 0) + 1
                nav_counts[nav_action] = nav_counts.get(nav_action, 0) + 1

                print(
                    f"[{iteration_idx}] screen={screen_type} package={package_name!r} "
                    f"profile_signal={profile_signal_strength} nav={nav_action}/{nav_status}"
                )
                if loop_sleep_s > 0:
                    time.sleep(loop_sleep_s)

        elapsed_s = round(time.time() - started, 3)
        summary = {
            "config_path": str(Path(config_json_path).resolve()),
            "session_id": session_id,
            "session_dir": str(session_dir),
            "iterations": captured_iterations,
            "elapsed_s": elapsed_s,
            "target_package": target_package,
            "navigation": {
                "mode": navigation.mode,
                "poll_every_iterations": navigation.poll_every_iterations,
                "execute": navigation.execute,
            },
            "files": {
                "frames_jsonl_path": str(frames_jsonl_path),
                "profiles_jsonl_path": str(profiles_jsonl_path),
                "messages_jsonl_path": str(messages_jsonl_path),
                "nodes_jsonl_path": str(nodes_jsonl_path),
            },
            "counts": {
                "profile_rows": profile_rows,
                "message_rows": message_rows,
                "thread_keys_seen": len(thread_state),
                "thread_updates": thread_updates,
            },
            "screen_type_counts": screen_type_counts,
            "package_counts": package_counts,
            "navigation_action_counts": nav_counts,
        }
        summary_json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote summary: {summary_json_path}")

        return FullFidelityHingeResult(
            session_id=session_id,
            iterations=captured_iterations,
            frames_jsonl_path=frames_jsonl_path,
            profiles_jsonl_path=profiles_jsonl_path,
            messages_jsonl_path=messages_jsonl_path,
            nodes_jsonl_path=nodes_jsonl_path,
            summary_json_path=summary_json_path,
            session_dir=session_dir,
        )
    finally:
        client.delete_session()
