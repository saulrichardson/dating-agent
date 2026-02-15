from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def read_json_list(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(x, dict) for x in payload):
        raise ValueError(f"Expected a JSON array of objects: {path}")
    return payload


def packet_from_action_log_row(row: dict[str, Any]) -> dict[str, Any]:
    """
    Convert a live action log row into a "packet" object compatible with the LLM decision schema.

    This is intentionally tolerant of missing fields so we can reuse real-world action logs
    as offline regression inputs.
    """
    quality_features = row.get("quality_features")
    if not isinstance(quality_features, dict):
        quality_features = {
            "profile_name_candidate": row.get("profile_name_candidate"),
            "prompt_answer": None,
            "like_targets": [],
            "quality_flags": row.get("quality_flags") or [],
        }

    observed_strings = row.get("observed_strings")
    if not isinstance(observed_strings, list):
        observed_strings = []

    available_actions = row.get("available_actions")
    if not isinstance(available_actions, list):
        available_actions = ["wait"]

    like_candidates = row.get("like_candidates")
    if not isinstance(like_candidates, list):
        like_candidates = []

    profile_summary = row.get("profile_summary")
    if not isinstance(profile_summary, dict):
        profile_summary = None

    return {
        "ts": row.get("ts"),
        "screen_type": row.get("screen_type"),
        "package_name": row.get("package_name"),
        "quality_score_v1": row.get("quality_score_v1") or 0,
        "quality_features": quality_features,
        "profile_fingerprint": row.get("profile_fingerprint"),
        "profile_summary": profile_summary,
        "like_candidates": like_candidates,
        "profile_bundle_path": row.get("profile_bundle_path"),
        "available_actions": [str(x) for x in available_actions if isinstance(x, str)],
        "observed_strings": [str(x) for x in observed_strings if isinstance(x, str)],
        "packet_screenshot_path": row.get("packet_screenshot_path"),
        "packet_xml_path": row.get("packet_xml_path"),
    }


def load_screenshot_bytes(path_value: Any) -> Optional[bytes]:
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    p = Path(path_value).expanduser()
    if not p.exists() or p.is_dir():
        return None
    if p.suffix.lower() != ".png":
        return None
    return p.read_bytes()
