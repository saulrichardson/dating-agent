#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from automation_service.mobile import live_hinge_agent as lha
from automation_service.mobile.env import ensure_dotenv_loaded
from automation_service.mobile.llm_validation import validate_decision_output


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Validate long-horizon LLM behavior using a simulated state machine of Hinge screens.\n\n"
            "This does NOT connect to Appium. It calls the LLM decision engine on synthetic packets and "
            "verifies multi-step navigation/overlay recovery behavior."
        )
    )
    p.add_argument(
        "--scenarios",
        default="datasets/hinge_rollouts/scenarios.synthetic.v1.json",
        help="Path to a hinge_rollout_scenarios.v1 JSON file.",
    )
    p.add_argument(
        "--scenario-id",
        default="",
        help="Optional scenario id to run (default: run all).",
    )
    p.add_argument("--model", default="gpt-4.1-mini", help="Decision model (default gpt-4.1-mini)")
    p.add_argument("--temperature", type=float, default=0.1, help="Decision temperature (default 0.1)")
    p.add_argument("--timeout-s", type=float, default=30, help="Decision timeout seconds (default 30)")
    p.add_argument("--api-key-env", default="OPENAI_API_KEY", help="API key env var for decision calls")
    p.add_argument("--base-url", default="https://api.openai.com", help="Base URL for decision calls")
    p.add_argument(
        "--include-screenshot",
        action="store_true",
        help="Include screenshots if a state provides them (synthetic scenarios usually do not).",
    )
    p.add_argument(
        "--max-steps",
        type=int,
        default=0,
        help="Override scenario max_steps (0 means use scenario file).",
    )
    p.add_argument(
        "--report-path",
        default="",
        help="Optional report JSON path. Defaults to artifacts/validation/long_horizon_<ts>.json",
    )
    return p


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _resolve_profile_path(*, scenarios_path: Path, profile_ref: str) -> Path:
    p = Path(profile_ref)
    if p.is_absolute():
        return p.resolve()
    return (scenarios_path.parent / p).resolve()


def _expect_any(state: dict[str, Any]) -> set[str]:
    expected = state.get("expected")
    if isinstance(expected, dict):
        xs = expected.get("expect_action_any")
        if isinstance(xs, list):
            return {str(x) for x in xs if isinstance(x, str) and str(x).strip()}
    return set()


def _require_message(state: dict[str, Any]) -> bool:
    expected = state.get("expected")
    if isinstance(expected, dict):
        return bool(expected.get("require_message"))
    return False


def main() -> int:
    args = _parser().parse_args()
    ensure_dotenv_loaded()

    scenarios_path = Path(args.scenarios).expanduser().resolve()
    if not scenarios_path.exists():
        raise SystemExit(f"scenarios file not found: {scenarios_path}")

    payload = json.loads(scenarios_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("contract_version") != "hinge_rollout_scenarios.v1":
        raise SystemExit("scenarios file must be contract_version=hinge_rollout_scenarios.v1")

    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not all(isinstance(x, dict) for x in scenarios):
        raise SystemExit("scenarios file must contain scenarios: list[object]")

    decision_engine_dict = {
        "type": "llm",
        "llm_failure_mode": "fail",
        "llm": {
            "model": str(args.model),
            "temperature": float(args.temperature),
            "timeout_s": float(args.timeout_s),
            "api_key_env": str(args.api_key_env),
            "base_url": str(args.base_url),
            "include_screenshot": bool(args.include_screenshot),
            "image_detail": "low",
            "max_observed_strings": 160,
        },
    }
    decision_engine = lha._parse_decision_engine(decision_engine_dict, context="validate-long-horizon: decision_engine")

    selected = []
    if str(args.scenario_id).strip():
        for s in scenarios:
            if s.get("id") == str(args.scenario_id).strip():
                selected.append(s)
        if not selected:
            raise SystemExit(f"scenario_id not found: {args.scenario_id}")
    else:
        selected = list(scenarios)

    report_ts = _now_tag()
    default_report = (REPO_ROOT / "artifacts" / "validation" / f"long_horizon_{report_ts}.json").resolve()
    report_path = Path(args.report_path).expanduser().resolve() if args.report_path else default_report
    report_path.parent.mkdir(parents=True, exist_ok=True)

    overall_failures: list[str] = []
    scenario_reports: list[dict[str, Any]] = []

    for scenario in selected:
        scenario_id = str(scenario.get("id") or "").strip() or "scenario"
        profile_ref = scenario.get("profile_ref")
        if not isinstance(profile_ref, str) or not profile_ref.strip():
            overall_failures.append(f"{scenario_id}: missing profile_ref")
            continue

        profile_path = _resolve_profile_path(scenarios_path=scenarios_path, profile_ref=profile_ref)
        if not profile_path.exists():
            overall_failures.append(f"{scenario_id}: profile_ref not found: {profile_path}")
            continue
        profile = lha._load_profile(str(profile_path))

        start_state = scenario.get("start_state")
        states = scenario.get("states")
        terminal_states = scenario.get("terminal_states")
        max_steps = int(args.max_steps) if int(args.max_steps) > 0 else int(scenario.get("max_steps") or 12)
        if not isinstance(start_state, str) or not start_state.strip():
            overall_failures.append(f"{scenario_id}: missing start_state")
            continue
        if not isinstance(states, dict):
            overall_failures.append(f"{scenario_id}: missing states map")
            continue
        terminal_set = set()
        if isinstance(terminal_states, list):
            terminal_set = {str(x) for x in terminal_states if isinstance(x, str)}

        cur = start_state
        visited: dict[str, int] = {}
        steps: list[dict[str, Any]] = []
        failures: list[str] = []

        for step_idx in range(1, max_steps + 1):
            visited[cur] = visited.get(cur, 0) + 1
            if visited[cur] > 4:
                failures.append(f"loop_detected: state={cur} visited={visited[cur]}")
                break

            state = states.get(cur)
            if not isinstance(state, dict):
                failures.append(f"missing_state: {cur}")
                break

            is_terminal = bool(state.get("terminal")) or (cur in terminal_set)
            packet = state.get("packet")
            if not isinstance(packet, dict):
                failures.append(f"{cur}: packet missing")
                break
            nl_query = state.get("nl_query")
            if not isinstance(nl_query, str) or not nl_query.strip():
                nl_query = None

            action, reason, message_text, llm_trace = lha._llm_decide_with_trace(
                packet=copy.deepcopy(packet),
                profile=profile,
                decision_engine=decision_engine,
                nl_query=nl_query,
                screenshot_png_bytes=None,
            )
            validation = validate_decision_output(
                action=action,
                reason=reason,
                message_text=message_text,
                packet=packet,
                profile=profile,
            )

            expected_any = _expect_any(state)
            if expected_any and action not in expected_any:
                failures.append(f"{cur}: unexpected_action={action!r} expected_any={sorted(expected_any)}")

            if _require_message(state) and not (isinstance(message_text, str) and message_text.strip()):
                failures.append(f"{cur}: expected message_text but got empty")

            if not validation.ok:
                failures.append(f"{cur}: validation issues={validation.issues}")

            steps.append(
                {
                    "step": step_idx,
                    "state": cur,
                    "is_terminal": is_terminal,
                    "nl_query": nl_query,
                    "decision": {
                        "action": action,
                        "reason": reason,
                        "message_text": message_text,
                        "llm_trace": llm_trace,
                        "validation": asdict(validation),
                    },
                }
            )

            if is_terminal:
                break

            transitions = state.get("transitions")
            if not isinstance(transitions, dict):
                failures.append(f"{cur}: transitions missing")
                break
            next_state = transitions.get(action)
            if not isinstance(next_state, str) or not next_state.strip():
                failures.append(f"{cur}: no transition for action={action!r}")
                break
            cur = next_state

        ok = not failures
        if not ok:
            overall_failures.extend([f"{scenario_id}: {x}" for x in failures])

        scenario_reports.append(
            {
                "id": scenario_id,
                "ok": ok,
                "description": scenario.get("description"),
                "profile_path": str(profile_path),
                "start_state": start_state,
                "max_steps": max_steps,
                "steps": steps,
                "failures": failures,
            }
        )

    overall_ok = not overall_failures
    report = {
        "timestamp": datetime.now().isoformat(),
        "ok": bool(overall_ok),
        "scenarios_path": str(scenarios_path),
        "args": {
            "scenario_id": (str(args.scenario_id).strip() or None),
            "model": str(args.model),
            "temperature": float(args.temperature),
            "include_screenshot": bool(args.include_screenshot),
            "max_steps": int(args.max_steps),
        },
        "failures": overall_failures,
        "scenarios": scenario_reports,
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"report={report_path}")
    return 0 if overall_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

