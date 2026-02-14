#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from automation_service.mobile.config import load_json_file
from automation_service.mobile.validation_helpers import (
    load_screenshot_bytes,
    packet_from_action_log_row,
    read_json_list,
)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Build a local LLM regression dataset from a live_hinge_agent action log. "
            "WARNING: action logs + screenshots may contain private user data. "
            "The output is intended to live under artifacts/ (gitignored)."
        )
    )
    p.add_argument("--action-log", required=True, help="Path to a run_live_hinge_agent action_log.json")
    p.add_argument(
        "--profile-json",
        default="",
        help=(
            "Optional profile JSON to embed/copy into the dataset. If omitted, you can still run regression "
            "by providing --profile-json to scripts/run-llm-regression.py."
        ),
    )
    p.add_argument(
        "--command-query",
        default="",
        help="Optional NL query to store in each case (default empty).",
    )
    p.add_argument(
        "--max-rows",
        type=int,
        default=50,
        help="Max action log rows to convert into cases (default 50).",
    )
    p.add_argument(
        "--screen-types",
        default="",
        help="Optional comma-separated filter of screen_type values (example: hinge_discover_card,hinge_chat).",
    )
    p.add_argument(
        "--include-screenshot-base64",
        action="store_true",
        help="Inline packet screenshot bytes as base64 (can be large; do not commit).",
    )
    p.add_argument(
        "--copy-screenshots",
        action="store_true",
        help="Copy screenshots into the dataset directory and reference them by relative path (recommended for stability).",
    )
    p.add_argument(
        "--out",
        default="",
        help="Output directory. Defaults to artifacts/regression_datasets/hinge_llm_<ts>/",
    )
    return p


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe_id(value: str) -> str:
    out = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in (value or "").strip())
    return out or "case"


def _relpath_or_abs(path: Path, *, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except Exception:
        return str(path.resolve())


def main() -> int:
    args = _parser().parse_args()

    action_log_path = Path(args.action_log).expanduser().resolve()
    if not action_log_path.exists():
        raise SystemExit(f"action log not found: {action_log_path}")

    ts = _now_tag()
    out_dir = Path(args.out).expanduser().resolve() if args.out else (REPO_ROOT / "artifacts" / "regression_datasets" / f"hinge_llm_{ts}").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    profile_ref = None
    if args.profile_json:
        profile_path = Path(args.profile_json).expanduser().resolve()
        if not profile_path.exists():
            raise SystemExit(f"profile json not found: {profile_path}")
        # Copy into dataset so it is self-contained (still under artifacts/, so gitignored).
        profile_payload = load_json_file(str(profile_path))
        profile_ref = "profile.json"
        (out_dir / profile_ref).write_text(json.dumps(profile_payload, indent=2), encoding="utf-8")

    screen_type_allow: Optional[set[str]] = None
    if str(args.screen_types or "").strip():
        screen_type_allow = {s.strip() for s in str(args.screen_types).split(",") if s.strip()}

    rows = read_json_list(action_log_path)
    rows = rows[: max(0, int(args.max_rows))]

    cases_path = out_dir / "cases.jsonl"
    screenshots_dir = out_dir / "screenshots"
    if args.copy_screenshots:
        screenshots_dir.mkdir(parents=True, exist_ok=True)

    cases_written = 0
    with cases_path.open("w", encoding="utf-8") as f:
        for row in rows:
            packet = packet_from_action_log_row(row)
            screen_type = str(packet.get("screen_type") or "unknown")
            if screen_type_allow is not None and screen_type not in screen_type_allow:
                continue

            iteration = row.get("iteration")
            base_id = f"iter_{iteration}_{screen_type}" if iteration is not None else f"{screen_type}"
            case_id = _safe_id(base_id)

            screenshot_obj: dict[str, Any] = {"type": "none"}
            screenshot_path_raw = packet.get("packet_screenshot_path")
            if isinstance(screenshot_path_raw, str) and screenshot_path_raw.strip():
                screenshot_path = Path(screenshot_path_raw).expanduser()
                if screenshot_path.exists() and screenshot_path.is_file() and screenshot_path.suffix.lower() == ".png":
                    if args.copy_screenshots:
                        dst = screenshots_dir / f"{case_id}.png"
                        try:
                            shutil.copyfile(screenshot_path, dst)
                            screenshot_obj = {"type": "path", "path": _relpath_or_abs(dst, base=out_dir)}
                        except Exception:
                            screenshot_obj = {"type": "path", "path": str(screenshot_path.resolve())}
                    elif args.include_screenshot_base64:
                        b = load_screenshot_bytes(str(screenshot_path))
                        if b is not None:
                            screenshot_obj = {
                                "type": "base64",
                                "mime": "image/png",
                                "base64": base64.b64encode(b).decode("ascii"),
                            }
                        else:
                            screenshot_obj = {"type": "path", "path": str(screenshot_path.resolve())}
                    else:
                        screenshot_obj = {"type": "path", "path": str(screenshot_path.resolve())}

            case = {
                "contract_version": "hinge_llm_regression_case.v1",
                "case_id": case_id,
                "created_at": datetime.now().isoformat(),
                "profile_ref": profile_ref,
                "nl_query": (str(args.command_query).strip() or None),
                "packet": packet,
                "screenshot": screenshot_obj,
                "source": {
                    "action_log_path": str(action_log_path),
                    "iteration": iteration,
                    "screen_type": screen_type,
                    "quality_score_v1": packet.get("quality_score_v1"),
                    "available_actions": packet.get("available_actions"),
                    "action_taken": row.get("action"),
                    "reason_taken": row.get("reason"),
                },
            }
            f.write(json.dumps(case, ensure_ascii=False) + "\n")
            cases_written += 1

    meta = {
        "contract_version": "hinge_llm_regression_dataset_meta.v1",
        "created_at": datetime.now().isoformat(),
        "out_dir": str(out_dir),
        "cases_path": str(cases_path),
        "cases_written": cases_written,
        "source_action_log": str(action_log_path),
        "profile_ref": profile_ref,
        "warning": "This dataset may contain private user data. Keep it under artifacts/ (gitignored).",
    }
    (out_dir / "dataset_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"dataset_dir={out_dir}")
    print(f"cases_jsonl={cases_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

