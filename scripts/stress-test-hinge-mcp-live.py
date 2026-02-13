#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from automation_service.mobile import hinge_agent_mcp as mcpmod


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Run a live stress probe against hinge_agent_mcp tools using a real Appium session. "
            "This exercises high-level and low-level control surfaces and writes a JSON report."
        )
    )
    p.add_argument(
        "--config",
        default="automation_service/mobile_examples/live_hinge_agent.example.json",
        help="Path to live_hinge_agent config JSON.",
    )
    p.add_argument(
        "--session-name",
        default="probe",
        help="Session name used by the MCP module.",
    )
    p.add_argument(
        "--steps",
        type=int,
        default=4,
        help="How many step() calls to execute.",
    )
    p.add_argument(
        "--mode",
        choices=["deterministic", "llm"],
        default="deterministic",
        help="Decision mode for step()/decide() calls.",
    )
    p.add_argument(
        "--live",
        action="store_true",
        help="Execute real actions (dry_run=false). Default is dry-run behavior for step/execute.",
    )
    p.add_argument(
        "--report-path",
        default="",
        help="Optional output JSON path. Defaults to artifacts/live_hinge_mcp_probe/<timestamp>.json",
    )
    return p


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def main() -> int:
    args = _parser().parse_args()
    if args.steps <= 0:
        print("ERROR: --steps must be > 0", file=sys.stderr)
        return 1

    now = datetime.now().strftime("%Y%m%d-%H%M%S")
    default_report = (REPO_ROOT / "artifacts" / "live_hinge_mcp_probe" / f"probe_{now}.json").resolve()
    report_path = Path(args.report_path).resolve() if args.report_path else default_report
    report_path.parent.mkdir(parents=True, exist_ok=True)

    session_name = f"{args.session_name}-{now}"
    report: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "config": str(Path(args.config).resolve()),
        "session_name": session_name,
        "mode": args.mode,
        "live_actions": bool(args.live),
        "steps_requested": args.steps,
        "calls": [],
        "errors": [],
    }

    def call(name: str, fn, **kwargs):
        payload = {"tool": name, "args": kwargs}
        try:
            result = fn(**kwargs)
            payload["ok"] = True
            payload["result"] = _json_safe(result)
            report["calls"].append(payload)
            return result
        except Exception as e:
            payload["ok"] = False
            payload["error"] = str(e)
            report["calls"].append(payload)
            report["errors"].append(f"{name}: {e}")
            raise

    try:
        call("start_session", mcpmod.start_session, config_json_path=args.config, session_name=session_name)
        call("action_catalog", mcpmod.action_catalog)
        observed = call("observe", mcpmod.observe, session_name=session_name, include_screenshot=True)

        # Probe low-level element inspection around Discover/Like affordances.
        call(
            "find_elements_like",
            mcpmod.find_elements,
            session_name=session_name,
            using="-android uiautomator",
            value='new UiSelector().descriptionContains("Like")',
            limit=5,
            include_text=True,
            include_rect=True,
        )
        call(
            "find_elements_discover",
            mcpmod.find_elements,
            session_name=session_name,
            using="-android uiautomator",
            value='new UiSelector().descriptionContains("Discover")',
            limit=5,
            include_text=True,
            include_rect=True,
        )
        call("capture_screenshot", mcpmod.capture_screenshot, session_name=session_name, persist_snapshot_artifact=True)
        call("get_page_source", mcpmod.get_page_source, session_name=session_name, persist_snapshot_artifact=True)
        call(
            "decide",
            mcpmod.decide,
            session_name=session_name,
            command_query="Explore freely for 1 actions.",
            mode=args.mode,
            include_screenshot=True,
        )
        call(
            "execute_wait",
            mcpmod.execute,
            session_name=session_name,
            action="wait",
            dry_run=(not args.live),
        )

        step_outcomes = []
        for i in range(1, args.steps + 1):
            step_result = call(
                f"step_{i}",
                mcpmod.step,
                session_name=session_name,
                command_query="Go to discover. Explore for a few actions.",
                mode=args.mode,
                execute_action=True,
                dry_run=(not args.live),
                include_screenshot=True,
            )
            step_outcomes.append(
                {
                    "idx": i,
                    "decision": (step_result.get("decision") or {}).get("action"),
                    "screen_type": ((step_result.get("packet") or {}).get("screen_type")),
                }
            )

        # Low-level physical controls after high-level loop.
        call("press_back", mcpmod.press_keycode, session_name=session_name, keycode=4, metastate=None)
        call("tap_point", mcpmod.tap_point, session_name=session_name, x=100, y=200)
        call(
            "swipe_points",
            mcpmod.swipe_points,
            session_name=session_name,
            x1=100,
            y1=900,
            x2=100,
            y2=300,
            duration_ms=500,
        )

        state = call("dump_state", mcpmod.dump_state, session_name=session_name)
        report["summary"] = {
            "initial_screen_type": ((observed.get("packet") or {}).get("screen_type")),
            "step_outcomes": step_outcomes,
            "final_state": state.get("state"),
        }
        return_code = 0
    except Exception:
        return_code = 2
    finally:
        try:
            call("stop_session", mcpmod.stop_session, session_name=session_name)
        except Exception:
            try:
                call("close_all_sessions", mcpmod.close_all_sessions)
            except Exception:
                pass

        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"report={report_path}")

    if report["errors"]:
        print("errors:")
        for err in report["errors"]:
            print(f"  - {err}")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
