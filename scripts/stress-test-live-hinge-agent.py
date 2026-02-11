#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    ok: bool
    execution_ok: bool
    error: str | None
    session_id: str | None
    iterations: int
    likes: int
    passes: int
    messages: int
    action_log_path: str | None
    decision_counts: dict[str, int]
    screen_type_counts: dict[str, int]
    validation_failed: int
    max_consecutive_validation_failures: int
    unique_actions: int
    repeat_action_max_streak: int
    covered_actions: list[str]
    missing_actions: list[str]
    coverage_ratio: float
    available_actions_seen: list[str]
    unavailable_actions: list[str]
    available_coverage_ratio: float
    assertion_failures: list[str]


def _load_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected top-level JSON object in {path}")
    return payload


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _compute_log_metrics(action_log_path: Path) -> dict[str, Any]:
    payload = json.loads(action_log_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Action log must be a list: {action_log_path}")

    decision_counts = Counter()
    screen_type_counts = Counter()
    validation_failed = 0
    max_validation_failures = 0
    actions: list[str] = []
    available_actions_seen: set[str] = set()

    for row in payload:
        if not isinstance(row, dict):
            continue
        decision = str(row.get("decision") or "")
        screen_type = str(row.get("screen_type") or "")
        if decision:
            decision_counts[decision] += 1
            actions.append(decision)
        if screen_type:
            screen_type_counts[screen_type] += 1

        if str(row.get("validation_status") or "") == "failed":
            validation_failed += 1

        available_actions_raw = row.get("available_actions")
        if isinstance(available_actions_raw, list):
            for action_name in available_actions_raw:
                if isinstance(action_name, str) and action_name:
                    available_actions_seen.add(action_name)

        try:
            c = int(row.get("consecutive_validation_failures") or 0)
            if c > max_validation_failures:
                max_validation_failures = c
        except Exception:
            pass

    repeat_action_max_streak = 0
    current_streak = 0
    last_action = None
    for action in actions:
        if action == last_action:
            current_streak += 1
        else:
            current_streak = 1
            last_action = action
        if current_streak > repeat_action_max_streak:
            repeat_action_max_streak = current_streak

    return {
        "decision_counts": dict(decision_counts),
        "screen_type_counts": dict(screen_type_counts),
        "validation_failed": validation_failed,
        "max_consecutive_validation_failures": max_validation_failures,
        "unique_actions": len(set(actions)),
        "repeat_action_max_streak": repeat_action_max_streak,
        "available_actions_seen": sorted(available_actions_seen),
    }


def _assert_int(
    assertions: dict[str, Any],
    *,
    key: str,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    raw = assertions.get(key)
    if raw is None:
        return None
    try:
        value = int(raw)
    except Exception as e:
        raise ValueError(f"assertions.{key} must be an integer") from e
    if minimum is not None and value < minimum:
        raise ValueError(f"assertions.{key} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"assertions.{key} must be <= {maximum}")
    return value


def _assert_str_list(assertions: dict[str, Any], *, key: str) -> list[str] | None:
    raw = assertions.get(key)
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(x, str) and x.strip() for x in raw):
        raise ValueError(f"assertions.{key} must be a list of non-empty strings")
    return [x.strip() for x in raw]


def _evaluate_assertions(
    *,
    metrics: dict[str, Any],
    assertions: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    if not assertions:
        return failures

    max_validation_failed = _assert_int(assertions, key="max_validation_failed", minimum=0)
    min_unique_actions = _assert_int(assertions, key="min_unique_actions", minimum=1)
    max_repeat_action_streak = _assert_int(assertions, key="max_repeat_action_streak", minimum=1)
    expect_actions_any = _assert_str_list(assertions, key="expect_actions_any")
    expect_actions_all = _assert_str_list(assertions, key="expect_actions_all")
    expect_screens_any = _assert_str_list(assertions, key="expect_screens_any")
    expect_screens_all = _assert_str_list(assertions, key="expect_screens_all")

    decision_counts = metrics["decision_counts"]
    screen_type_counts = metrics["screen_type_counts"]
    seen_actions = {str(k) for k in decision_counts.keys() if str(k)}
    seen_screens = {str(k) for k in screen_type_counts.keys() if str(k)}

    if max_validation_failed is not None and int(metrics["validation_failed"]) > max_validation_failed:
        failures.append(
            f"validation_failed={metrics['validation_failed']} > max_validation_failed={max_validation_failed}"
        )
    if min_unique_actions is not None and int(metrics["unique_actions"]) < min_unique_actions:
        failures.append(f"unique_actions={metrics['unique_actions']} < min_unique_actions={min_unique_actions}")
    if max_repeat_action_streak is not None and int(metrics["repeat_action_max_streak"]) > max_repeat_action_streak:
        failures.append(
            "repeat_action_max_streak="
            f"{metrics['repeat_action_max_streak']} > max_repeat_action_streak={max_repeat_action_streak}"
        )
    if expect_actions_any is not None and not any(x in seen_actions for x in expect_actions_any):
        failures.append(f"expected at least one action in {expect_actions_any}, saw {sorted(seen_actions)}")
    if expect_actions_all is not None:
        missing = [x for x in expect_actions_all if x not in seen_actions]
        if missing:
            failures.append(f"missing expected actions {missing}, saw {sorted(seen_actions)}")
    if expect_screens_any is not None and not any(x in seen_screens for x in expect_screens_any):
        failures.append(f"expected at least one screen in {expect_screens_any}, saw {sorted(seen_screens)}")
    if expect_screens_all is not None:
        missing = [x for x in expect_screens_all if x not in seen_screens]
        if missing:
            failures.append(f"missing expected screens {missing}, saw {sorted(seen_screens)}")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a stress suite of live Hinge agent scenarios and summarize robustness metrics."
    )
    parser.add_argument(
        "--base-config",
        required=True,
        help="Base live hinge config JSON path.",
    )
    parser.add_argument(
        "--suite-config",
        required=True,
        help=(
            "Suite config JSON path with schema: "
            "{\"scenarios\":[{\"name\":\"...\",\"overrides\":{...}}, ...]}"
        ),
    )
    parser.add_argument(
        "--report-path",
        default="",
        help="Optional output report JSON path.",
    )
    args = parser.parse_args()

    base_path = Path(args.base_config).resolve()
    suite_path = Path(args.suite_config).resolve()
    if not base_path.exists():
        raise SystemExit(f"Base config not found: {base_path}")
    if not suite_path.exists():
        raise SystemExit(f"Suite config not found: {suite_path}")

    base_cfg = _load_json(base_path)
    suite_cfg = _load_json(suite_path)
    scenarios_raw = suite_cfg.get("scenarios")
    if not isinstance(scenarios_raw, list) or not scenarios_raw:
        raise SystemExit(f"{suite_path}: 'scenarios' must be a non-empty list")

    from automation_service.mobile.live_hinge_agent import get_hinge_action_catalog, run_live_hinge_agent

    action_catalog = sorted({str(item.get("action")) for item in get_hinge_action_catalog() if item.get("action")})
    if not action_catalog:
        raise SystemExit("Action catalog is empty; cannot compute coverage")

    scenario_results: list[ScenarioResult] = []
    temp_dir = Path("artifacts/live_hinge_stress").resolve()
    temp_dir.mkdir(parents=True, exist_ok=True)

    for idx, scenario in enumerate(scenarios_raw, 1):
        if not isinstance(scenario, dict):
            raise SystemExit(f"{suite_path}: scenarios[{idx}] must be an object")
        name_raw = scenario.get("name")
        if not isinstance(name_raw, str) or not name_raw.strip():
            raise SystemExit(f"{suite_path}: scenarios[{idx}].name must be a non-empty string")
        name = name_raw.strip()
        overrides = scenario.get("overrides", {})
        if not isinstance(overrides, dict):
            raise SystemExit(f"{suite_path}: scenarios[{idx}].overrides must be an object when provided")
        assertions = scenario.get("assertions", {})
        if assertions is None:
            assertions = {}
        if not isinstance(assertions, dict):
            raise SystemExit(f"{suite_path}: scenarios[{idx}].assertions must be an object when provided")

        merged = _deep_merge(base_cfg, overrides)
        merged_path = temp_dir / f"scenario_{idx:02d}_{name.replace(' ', '_').lower()}.json"
        merged_path.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")

        print(f"\n=== Stress Scenario {idx}/{len(scenarios_raw)}: {name} ===")
        print(f"Config: {merged_path}")

        try:
            result = run_live_hinge_agent(config_json_path=str(merged_path))
            metrics = _compute_log_metrics(result.action_log_path)
            covered_actions = sorted({k for k in metrics["decision_counts"].keys() if k in action_catalog})
            missing_actions = sorted(set(action_catalog) - set(covered_actions))
            coverage_ratio = 0.0
            if action_catalog:
                coverage_ratio = round(len(covered_actions) / len(action_catalog), 4)
            available_actions_seen = sorted({k for k in metrics["available_actions_seen"] if k in action_catalog})
            unavailable_actions = sorted(set(action_catalog) - set(available_actions_seen))
            available_coverage_ratio = 0.0
            if action_catalog:
                available_coverage_ratio = round(len(available_actions_seen) / len(action_catalog), 4)
            assertion_failures = _evaluate_assertions(metrics=metrics, assertions=assertions)
            scenario_ok = len(assertion_failures) == 0
            scenario_results.append(
                ScenarioResult(
                    name=name,
                    ok=scenario_ok,
                    execution_ok=True,
                    error=None,
                    session_id=result.session_id,
                    iterations=result.iterations,
                    likes=result.likes,
                    passes=result.passes,
                    messages=result.messages,
                    action_log_path=str(result.action_log_path),
                    decision_counts=metrics["decision_counts"],
                    screen_type_counts=metrics["screen_type_counts"],
                    validation_failed=metrics["validation_failed"],
                    max_consecutive_validation_failures=metrics["max_consecutive_validation_failures"],
                    unique_actions=metrics["unique_actions"],
                    repeat_action_max_streak=metrics["repeat_action_max_streak"],
                    covered_actions=covered_actions,
                    missing_actions=missing_actions,
                    coverage_ratio=coverage_ratio,
                    available_actions_seen=available_actions_seen,
                    unavailable_actions=unavailable_actions,
                    available_coverage_ratio=available_coverage_ratio,
                    assertion_failures=assertion_failures,
                )
            )
            print(
                "coverage="
                f"{len(covered_actions)}/{len(action_catalog)} ({coverage_ratio:.2%}) "
                f"availability={len(available_actions_seen)}/{len(action_catalog)} ({available_coverage_ratio:.2%}) "
                f"assertions_failed={len(assertion_failures)}"
            )
        except Exception as e:
            scenario_results.append(
                ScenarioResult(
                    name=name,
                    ok=False,
                    execution_ok=False,
                    error=str(e),
                    session_id=None,
                    iterations=0,
                    likes=0,
                    passes=0,
                    messages=0,
                    action_log_path=None,
                    decision_counts={},
                    screen_type_counts={},
                    validation_failed=0,
                    max_consecutive_validation_failures=0,
                    unique_actions=0,
                    repeat_action_max_streak=0,
                    covered_actions=[],
                    missing_actions=list(action_catalog),
                    coverage_ratio=0.0,
                    available_actions_seen=[],
                    unavailable_actions=list(action_catalog),
                    available_coverage_ratio=0.0,
                    assertion_failures=["scenario_execution_failed"],
                )
            )

    started = datetime.now().strftime("%Y%m%d-%H%M%S")
    default_report = Path("artifacts/live_hinge_stress") / f"stress_report_{started}.json"
    report_path = Path(args.report_path).resolve() if args.report_path else default_report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)

    passed = sum(1 for s in scenario_results if s.ok)
    failed = len(scenario_results) - passed
    execution_failed = sum(1 for s in scenario_results if not s.execution_ok)
    assertion_failed = sum(1 for s in scenario_results if s.execution_ok and not s.ok)
    aggregate_decisions = Counter()
    aggregate_screens = Counter()
    total_validation_failed = 0
    worst_repeat_streak = 0
    aggregate_covered_actions: set[str] = set()
    aggregate_available_actions: set[str] = set()
    for s in scenario_results:
        aggregate_decisions.update(s.decision_counts)
        aggregate_screens.update(s.screen_type_counts)
        total_validation_failed += s.validation_failed
        worst_repeat_streak = max(worst_repeat_streak, s.repeat_action_max_streak)
        aggregate_covered_actions.update(s.covered_actions)
        aggregate_available_actions.update(s.available_actions_seen)

    aggregate_missing_actions = sorted(set(action_catalog) - aggregate_covered_actions)
    aggregate_unavailable_actions = sorted(set(action_catalog) - aggregate_available_actions)
    aggregate_coverage_ratio = 0.0
    if action_catalog:
        aggregate_coverage_ratio = round(len(aggregate_covered_actions) / len(action_catalog), 4)
    aggregate_available_coverage_ratio = 0.0
    if action_catalog:
        aggregate_available_coverage_ratio = round(len(aggregate_available_actions) / len(action_catalog), 4)

    report_payload = {
        "base_config": str(base_path),
        "suite_config": str(suite_path),
        "action_catalog": action_catalog,
        "scenario_count": len(scenario_results),
        "passed": passed,
        "failed": failed,
        "execution_failed": execution_failed,
        "assertion_failed": assertion_failed,
        "aggregate_decision_counts": dict(aggregate_decisions),
        "aggregate_screen_type_counts": dict(aggregate_screens),
        "aggregate_covered_actions": sorted(aggregate_covered_actions),
        "aggregate_missing_actions": aggregate_missing_actions,
        "aggregate_action_coverage_ratio": aggregate_coverage_ratio,
        "aggregate_available_actions": sorted(aggregate_available_actions),
        "aggregate_unavailable_actions": aggregate_unavailable_actions,
        "aggregate_available_coverage_ratio": aggregate_available_coverage_ratio,
        "total_validation_failed": total_validation_failed,
        "worst_repeat_action_streak": worst_repeat_streak,
        "results": [asdict(r) for r in scenario_results],
    }
    report_path.write_text(json.dumps(report_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nreport={report_path}")
    print(f"passed={passed} failed={failed}")
    print(
        "aggregate_coverage="
        f"{len(aggregate_covered_actions)}/{len(action_catalog)} "
        f"({aggregate_coverage_ratio:.2%})"
    )
    print(
        "aggregate_availability="
        f"{len(aggregate_available_actions)}/{len(action_catalog)} "
        f"({aggregate_available_coverage_ratio:.2%})"
    )
    print(f"aggregate_missing_actions={aggregate_missing_actions}")
    print(f"aggregate_unavailable_actions={aggregate_unavailable_actions}")
    print(f"aggregate_decision_counts={dict(aggregate_decisions)}")
    if failed > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
