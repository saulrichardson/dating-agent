from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Optional
from xml.etree import ElementTree


class HingeObservationError(RuntimeError):
    pass


@dataclass(frozen=True)
class UiNode:
    ordinal: int
    class_name: Optional[str]
    resource_id: Optional[str]
    text: Optional[str]
    content_desc: Optional[str]
    clickable: bool
    enabled: bool
    bounds: Optional[list[int]]


_BOUNDS_RE = re.compile(r"\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]")
_PROMPT_ANSWER_RE = re.compile(
    r"^\\s*prompt:\\s*(?P<prompt>.*?)\\s*answer:\\s*(?P<answer>.*)\\s*$",
    flags=re.IGNORECASE,
)
_PHOTO_NAME_RE = re.compile(r"^(?P<name>.+?)['’]s photo$", flags=re.IGNORECASE)

# "Chrome" = app-level UI labels that are not candidate profile content.
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
    "send like",
    "add a comment",
    "edit comment",
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
    "send like with message",
    "undo the previous pass rating",
]


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload or b"").hexdigest()


def sha256_json(payload: Any) -> str:
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def parse_bounds(bounds_raw: Optional[str]) -> Optional[list[int]]:
    if not bounds_raw:
        return None
    match = _BOUNDS_RE.search(bounds_raw)
    if not match:
        return None
    x1, y1, x2, y2 = (int(match.group(i)) for i in range(1, 5))
    return [x1, y1, x2, y2]


def xml_to_root(page_source_xml: str) -> ElementTree.Element:
    raw = (page_source_xml or "").strip()
    if not raw:
        raise HingeObservationError("page_source_xml was empty")
    try:
        return ElementTree.fromstring(raw)
    except Exception as e:
        raise HingeObservationError(f"Failed to parse page source XML: {e}") from e


def extract_package_name(root: ElementTree.Element) -> Optional[str]:
    for node in root.iter():
        package = (node.attrib or {}).get("package")
        if package:
            return str(package)
    return None


def extract_ui_nodes(*, root: ElementTree.Element, max_nodes: int = 3500) -> list[UiNode]:
    if max_nodes <= 0:
        raise HingeObservationError("max_nodes must be > 0")
    out: list[UiNode] = []
    for idx, node in enumerate(root.iter(), 1):
        if idx > max_nodes:
            break
        attrib = node.attrib or {}
        bounds = parse_bounds(attrib.get("bounds"))
        out.append(
            UiNode(
                ordinal=idx,
                class_name=attrib.get("class") or None,
                resource_id=attrib.get("resource-id") or None,
                text=attrib.get("text") or None,
                content_desc=attrib.get("content-desc") or None,
                clickable=(attrib.get("clickable") == "true"),
                enabled=(attrib.get("enabled") == "true"),
                bounds=bounds,
            )
        )
    return out


def _is_chrome_text(text: str) -> bool:
    lowered = (text or "").lower().strip()
    if not lowered:
        return True
    if lowered in _CHROME_EXACT:
        return True
    if any(k in lowered for k in _CHROME_SUBSTR):
        return True
    if lowered.startswith("like "):
        return True
    if lowered.startswith("prompt:"):
        return True
    return False


def _node_label(node: UiNode) -> str:
    # Prefer content-desc because it's more likely to represent interactive affordances.
    label = (node.content_desc or "").strip()
    if not label:
        label = (node.text or "").strip()
    return label


def _center(bounds: list[int]) -> tuple[int, int]:
    x1, y1, x2, y2 = bounds
    return int((x1 + x2) / 2), int((y1 + y2) / 2)


def extract_profile_snapshot(*, strings: list[str], nodes: list[UiNode], screen_type: str) -> dict[str, Any]:
    """
    Best-effort extraction of profile content from accessible strings + node labels.

    This is intentionally conservative: it is meant to power decision-making and QA,
    not to perfectly reconstruct Hinge's internal profile model.
    """
    name_candidates: list[str] = []
    prompt_pairs: list[dict[str, str]] = []
    quality_flags: set[str] = set()
    like_targets: list[str] = []
    bio_candidates: list[str] = []
    photo_labels: list[str] = []

    for s in strings:
        lowered = (s or "").lower().strip()
        photo_match = _PHOTO_NAME_RE.match((s or "").strip())
        if photo_match:
            candidate = photo_match.group("name").strip()
            if candidate:
                name_candidates.append(candidate)
            photo_labels.append(s.strip())

        prompt_match = _PROMPT_ANSWER_RE.match(s or "")
        if prompt_match:
            prompt_text = prompt_match.group("prompt").strip()
            answer_text = prompt_match.group("answer").strip()
            prompt_pairs.append({"prompt": prompt_text, "answer": answer_text})

        if lowered.startswith("like "):
            like_targets.append((s or "").strip())

        if "selfie verified" in lowered:
            quality_flags.add("selfie_verified")
        if "active today" in lowered:
            quality_flags.add("active_today")
        if "voice prompt" in lowered:
            quality_flags.add("has_voice_prompt")

        if not _is_chrome_text(s or ""):
            normalized = (s or "").strip()
            if 3 <= len(normalized) <= 180:
                bio_candidates.append(normalized)

    node_text_values: list[str] = []
    for node in nodes:
        for key in ("text", "content_desc"):
            value = getattr(node, key)
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


def merge_profile_snapshots(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    name = None
    prompt_pairs_set: set[tuple[str, str]] = set()
    prompt_pairs: list[dict[str, str]] = []
    quality_flags: set[str] = set()
    like_targets: set[str] = set()
    bio_candidates: list[str] = []
    photo_labels: set[str] = set()

    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        if name is None and isinstance(snap.get("profile_name_candidate"), str) and snap.get("profile_name_candidate"):
            name = snap.get("profile_name_candidate")
        for p in (snap.get("prompt_pairs") or []):
            if not isinstance(p, dict):
                continue
            prompt = str(p.get("prompt") or "").strip()
            answer = str(p.get("answer") or "").strip()
            if not prompt or not answer:
                continue
            key = (prompt, answer)
            if key in prompt_pairs_set:
                continue
            prompt_pairs_set.add(key)
            prompt_pairs.append({"prompt": prompt, "answer": answer})
        for f in (snap.get("quality_flags") or []):
            if isinstance(f, str) and f.strip():
                quality_flags.add(f.strip())
        for lt in (snap.get("like_targets") or []):
            if isinstance(lt, str) and lt.strip():
                like_targets.add(lt.strip())
        for bio in (snap.get("bio_candidates") or []):
            if isinstance(bio, str) and bio.strip():
                bio_candidates.append(bio.strip())
        for pl in (snap.get("photo_labels") or []):
            if isinstance(pl, str) and pl.strip():
                photo_labels.add(pl.strip())

    # Keep ordering stable: prompt pairs in first-seen order, everything else sorted/deduped.
    seen_bio: set[str] = set()
    deduped_bio: list[str] = []
    for item in bio_candidates:
        if item in seen_bio:
            continue
        seen_bio.add(item)
        deduped_bio.append(item)

    return {
        "profile_name_candidate": name,
        "prompt_pairs": prompt_pairs,
        "quality_flags": sorted(quality_flags),
        "like_targets": sorted(like_targets),
        "bio_candidates": deduped_bio[:60],
        "photo_labels": sorted(photo_labels),
        "media_count": len(photo_labels),
    }


def extract_interaction_targets(
    *,
    nodes: list[UiNode],
    view_index: int,
    max_targets: int = 160,
) -> list[dict[str, Any]]:
    """
    Extract an "interaction map" from UI nodes.

    Output is intentionally a JSON-serializable list of targets; each target includes:
    - a stable-ish id within the capture (`target_id`)
    - kind (like_button/pass_button/comment_input/send_like/etc.)
    - label and tap point (center of bounds)
    - optional context_text for like buttons (nearby content nodes)
    """
    if max_targets <= 0:
        raise HingeObservationError("max_targets must be > 0")

    text_nodes: list[tuple[UiNode, str, list[int], tuple[int, int]]] = []
    for node in nodes:
        if not node.bounds:
            continue
        label = _node_label(node)
        if not label:
            continue
        if _is_chrome_text(label):
            continue
        if len(label) > 220:
            continue
        text_nodes.append((node, label, node.bounds, _center(node.bounds)))

    targets: list[dict[str, Any]] = []
    other_clickables: list[tuple[str, UiNode]] = []

    for node in nodes:
        if not node.clickable or not node.enabled:
            continue
        if not node.bounds:
            continue
        label = _node_label(node)
        if not label:
            continue

        lowered = label.lower().strip()
        kind = None
        if lowered.startswith("like "):
            kind = "like_button"
        elif lowered == "skip" or lowered.startswith("skip "):
            kind = "pass_button"
        elif lowered in {"send like", "send"}:
            kind = "send_like"
        elif ("add a comment" in lowered) or ("edit comment" in lowered):
            kind = "comment_input"
        elif lowered in {"close", "close sheet"}:
            kind = "close_overlay"
        else:
            other_clickables.append((label, node))

        if kind is None:
            continue

        bounds = node.bounds
        cx, cy = _center(bounds)
        target_id = f"{kind}:{view_index}:{node.ordinal}"
        entry: dict[str, Any] = {
            "target_id": target_id,
            "kind": kind,
            "label": label,
            "bounds": list(bounds),
            "tap": {"x": cx, "y": cy},
            "view_index": int(view_index),
            "node_ordinal": int(node.ordinal),
            "resource_id": node.resource_id,
        }

        if kind == "like_button":
            # Attach nearby text context to help the LLM pick which Like to tap.
            like_cx, like_cy = cx, cy
            scored: list[tuple[float, str]] = []
            for _, txt, tb, (tcx, tcy) in text_nodes:
                # Prefer content to the left and vertically aligned with the Like affordance.
                if abs(tcy - like_cy) > 260:
                    continue
                if tcx >= like_cx:
                    continue
                dx = abs(tcx - like_cx)
                dy = abs(tcy - like_cy)
                score = float(dy) + (float(dx) * 0.25)
                scored.append((score, txt))
            scored.sort(key=lambda x: x[0])
            context: list[str] = []
            seen: set[str] = set()
            for _, txt in scored:
                normalized = " ".join(txt.split()).strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                context.append(normalized)
                if len(context) >= 2:
                    break
            entry["context_text"] = context

        targets.append(entry)

    # "Other" clickables are helpful for drift/debug but can be large; keep a capped sample.
    other_clickables = other_clickables[: max(0, max_targets - len(targets))]
    for label, node in other_clickables:
        if not node.bounds:
            continue
        cx, cy = _center(node.bounds)
        targets.append(
            {
                "target_id": f"clickable_other:{view_index}:{node.ordinal}",
                "kind": "clickable_other",
                "label": label,
                "bounds": list(node.bounds),
                "tap": {"x": cx, "y": cy},
                "view_index": int(view_index),
                "node_ordinal": int(node.ordinal),
                "resource_id": node.resource_id,
            }
        )

    return targets[:max_targets]
