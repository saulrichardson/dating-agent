#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from automation_service.mobile.android_accessibility import extract_accessible_strings
from automation_service.mobile import live_hinge_agent as lha
from automation_service.mobile.hinge_observation import (
    extract_interaction_targets,
    extract_profile_snapshot,
    extract_ui_nodes,
    sha256_json,
    sha256_text,
    xml_to_root,
)


def _now_iso() -> str:
    return datetime.now().isoformat()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _derive_like_candidates(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in targets:
        if not isinstance(t, dict):
            continue
        if t.get("kind") != "like_button":
            continue
        out.append(
            {
                "target_id": t.get("target_id"),
                "label": t.get("label"),
                "view_index": t.get("view_index"),
                "context_text": t.get("context_text") if isinstance(t.get("context_text"), list) else [],
                "tap": t.get("tap"),
            }
        )
    return out


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract a Hinge observation (profile snapshot + interaction map) from a UIAutomator XML artifact.",
    )
    parser.add_argument("--xml", required=True, help="Path to a UIAutomator XML (Appium getPageSource output).")
    parser.add_argument("--out", required=True, help="Output JSON path to write.")
    parser.add_argument("--max-nodes", type=int, default=3500)
    parser.add_argument("--max-accessible-strings", type=int, default=2500)
    parser.add_argument("--max-targets", type=int, default=200)
    args = parser.parse_args(argv)

    xml_path = Path(args.xml).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    xml = _read_text(xml_path)
    strings = extract_accessible_strings(xml, limit=int(args.max_accessible_strings))
    screen_type = lha._classify_hinge_screen(strings)

    root = xml_to_root(xml)
    nodes = extract_ui_nodes(root=root, max_nodes=int(args.max_nodes))
    profile_snapshot = extract_profile_snapshot(strings=strings, nodes=nodes, screen_type=screen_type)
    profile_fingerprint = None
    try:
        if int(profile_snapshot.get("signal_strength") or 0) > 0:
            profile_fingerprint = sha256_json(profile_snapshot)
    except Exception:
        profile_fingerprint = None

    targets = extract_interaction_targets(nodes=nodes, view_index=0, max_targets=int(args.max_targets))
    like_candidates = _derive_like_candidates(targets)
    kind_counts: dict[str, int] = {}
    for t in targets:
        if not isinstance(t, dict):
            continue
        k = str(t.get("kind") or "unknown")
        kind_counts[k] = kind_counts.get(k, 0) + 1

    payload = {
        "derived_at": _now_iso(),
        "source": {
            "xml_path": str(xml_path),
            "xml_sha256": sha256_text(xml),
        },
        "screen_type": screen_type,
        "profile_fingerprint": profile_fingerprint,
        "profile_snapshot": profile_snapshot,
        "interaction_targets": targets,
        "like_candidates": like_candidates,
        "stats": {
            "accessible_strings_count": len(strings),
            "nodes_count": len(nodes),
            "targets_count": len(targets),
            "kind_counts": kind_counts,
        },
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

