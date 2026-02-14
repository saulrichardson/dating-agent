#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool
    returncode: int
    report_path: Optional[str]
    stdout_tail: str
    stderr_tail: str


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "System-level validation suite (Appium + MCP + LLM + packaging). "
            "Runs a selected set of scripts and aggregates a single JSON report."
        )
    )
    p.add_argument(
        "--llm-config",
        default="automation_service/mobile_examples/live_hinge_agent.llm.example.json",
        help="LLM live agent config JSON path (used by LLM validations).",
    )
    p.add_argument(
        "--run-live",
        action="store_true",
        help="Run live LLM probe and MCP probe (requires emulator + Appium + Hinge foreground).",
    )
    p.add_argument(
        "--live-steps",
        type=int,
        default=1,
        help="Steps for live LLM probe (default 1).",
    )
    p.add_argument(
        "--run-synthetic",
        action="store_true",
        help="Run synthetic LLM validation suite (no Appium needed).",
    )
    p.add_argument(
        "--run-regression",
        action="store_true",
        help="Run offline LLM regression dataset (no Appium needed, but requires OPENAI_API_KEY).",
    )
    p.add_argument(
        "--regression-dataset",
        default="datasets/hinge_llm_regression/cases.synthetic.v1.jsonl",
        help="Dataset JSONL for regression runs.",
    )
    p.add_argument(
        "--regression-baseline",
        default="",
        help="Optional baseline JSONL for regression drift detection.",
    )
    p.add_argument(
        "--run-long-horizon",
        action="store_true",
        help="Run long-horizon rollout simulation suite (no Appium needed, but requires OPENAI_API_KEY).",
    )
    p.add_argument(
        "--long-horizon-scenarios",
        default="datasets/hinge_rollouts/scenarios.synthetic.v1.json",
        help="Scenario JSON for long-horizon simulation runs.",
    )
    p.add_argument(
        "--run-stress",
        action="store_true",
        help="Run the real-world stress suite (requires emulator + Appium + Hinge foreground).",
    )
    p.add_argument(
        "--stress-base-config",
        default="automation_service/mobile_examples/live_hinge_agent.example.json",
        help="Base config for stress suite.",
    )
    p.add_argument(
        "--stress-suite-config",
        default="automation_service/mobile_examples/live_hinge_stress_suite.realworld.example.json",
        help="Stress suite config.",
    )
    p.add_argument(
        "--session-package",
        default="",
        help="Optional session_package.json to validate (packaging contract).",
    )
    p.add_argument(
        "--report-path",
        default="",
        help="Optional output report path (defaults to artifacts/validation/system_suite_<ts>.json).",
    )
    return p


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _run(cmd: list[str], *, name: str) -> StepResult:
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    stdout_tail = "\n".join((proc.stdout or "").splitlines()[-20:])
    stderr_tail = "\n".join((proc.stderr or "").splitlines()[-20:])

    # Try to find a "report=..." line if present.
    report_path = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("report="):
            report_path = line.split("=", 1)[1].strip()
    ok = proc.returncode == 0
    return StepResult(
        name=name,
        ok=ok,
        returncode=proc.returncode,
        report_path=report_path,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
    )


def main() -> int:
    args = _parser().parse_args()

    ts = _now_tag()
    default_report = (REPO_ROOT / "artifacts" / "validation" / f"system_suite_{ts}.json").resolve()
    report_path = Path(args.report_path).resolve() if args.report_path else default_report
    report_path.parent.mkdir(parents=True, exist_ok=True)

    steps: list[StepResult] = []

    # Always run contract validator (fast, no device required).
    steps.append(
        _run(
            [sys.executable, str((REPO_ROOT / "scripts" / "validate-hinge-control-contract.py").resolve())],
            name="hinge_control_contract",
        )
    )

    if args.run_synthetic:
        steps.append(
            _run(
                [
                    sys.executable,
                    str((REPO_ROOT / "scripts" / "validate-llm-suite.py").resolve()),
                    "--config",
                    str(Path(args.llm_config).resolve()),
                    "--synthetic",
                ],
                name="llm_synthetic_suite",
            )
        )

    if args.run_regression:
        cmd = [
            sys.executable,
            str((REPO_ROOT / "scripts" / "run-llm-regression.py").resolve()),
            "--dataset",
            str(Path(args.regression_dataset).resolve()),
            "--include-screenshot",
            "--temperature",
            "0",
            "--max-cases",
            "25",
        ]
        if args.regression_baseline:
            cmd.extend(["--baseline", str(Path(args.regression_baseline).resolve())])
        steps.append(_run(cmd, name="llm_regression_dataset"))

    if args.run_long_horizon:
        steps.append(
            _run(
                [
                    sys.executable,
                    str((REPO_ROOT / "scripts" / "validate-long-horizon.py").resolve()),
                    "--scenarios",
                    str(Path(args.long_horizon_scenarios).resolve()),
                    "--temperature",
                    "0",
                ],
                name="llm_long_horizon_rollouts",
            )
        )

    if args.run_live:
        steps.append(
            _run(
                [
                    sys.executable,
                    str((REPO_ROOT / "scripts" / "validate-llm-suite.py").resolve()),
                    "--config",
                    str(Path(args.llm_config).resolve()),
                    "--live",
                    "--live-steps",
                    str(int(args.live_steps)),
                    "--mcp-probe",
                ],
                name="llm_live_and_mcp_probe",
            )
        )

    if args.run_stress:
        stress_report = (REPO_ROOT / "artifacts" / "validation" / f"stress_suite_{ts}.json").resolve()
        steps.append(
            _run(
                [
                    sys.executable,
                    str((REPO_ROOT / "scripts" / "stress-test-live-hinge-agent.py").resolve()),
                    "--base-config",
                    str(Path(args.stress_base_config).resolve()),
                    "--suite-config",
                    str(Path(args.stress_suite_config).resolve()),
                    "--report-path",
                    str(stress_report),
                ],
                name="live_stress_suite",
            )
        )

    if args.session_package:
        steps.append(
            _run(
                [
                    sys.executable,
                    str((REPO_ROOT / "scripts" / "validate-llm-suite.py").resolve()),
                    "--config",
                    str(Path(args.llm_config).resolve()),
                    "--session-package",
                    str(Path(args.session_package).resolve()),
                ],
                name="session_package_contract",
            )
        )

    overall_ok = all(s.ok for s in steps)
    payload: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "ok": overall_ok,
        "args": {
            "llm_config": str(Path(args.llm_config).resolve()),
            "run_live": bool(args.run_live),
            "live_steps": int(args.live_steps),
            "run_synthetic": bool(args.run_synthetic),
            "run_regression": bool(args.run_regression),
            "regression_dataset": str(Path(args.regression_dataset).resolve()),
            "regression_baseline": str(Path(args.regression_baseline).resolve()) if args.regression_baseline else None,
            "run_long_horizon": bool(args.run_long_horizon),
            "long_horizon_scenarios": str(Path(args.long_horizon_scenarios).resolve()),
            "run_stress": bool(args.run_stress),
            "stress_base_config": str(Path(args.stress_base_config).resolve()),
            "stress_suite_config": str(Path(args.stress_suite_config).resolve()),
            "session_package": str(Path(args.session_package).resolve()) if args.session_package else None,
        },
        "steps": [
            {
                "name": s.name,
                "ok": s.ok,
                "returncode": s.returncode,
                "report_path": s.report_path,
                "stdout_tail": s.stdout_tail,
                "stderr_tail": s.stderr_tail,
            }
            for s in steps
        ],
    }
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"report={report_path}")
    return 0 if overall_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
