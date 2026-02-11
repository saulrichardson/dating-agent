#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@dataclass(frozen=True)
class IterationResult:
    iteration: int
    ok: bool
    duration_s: float
    executed_steps: int
    artifact_count: int
    error: str | None
    artifacts: list[str]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a mobile spec repeatedly and emit a JSON stability report. "
            "Useful for comparing deterministic routine reliability over time."
        )
    )
    parser.add_argument(
        "--spec",
        required=True,
        help="Path to a mobile spec JSON file.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="How many times to execute the spec sequentially (default: 3).",
    )
    parser.add_argument(
        "--report-path",
        default="",
        help=(
            "Output path for JSON report. If omitted, writes to "
            "artifacts/mobile_spec_benchmark_<timestamp>.json"
        ),
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    spec_path = Path(args.spec).resolve()
    if not spec_path.exists():
        print(f"ERROR: spec file does not exist: {spec_path}", file=sys.stderr)
        return 1

    if args.iterations <= 0:
        print("ERROR: --iterations must be > 0", file=sys.stderr)
        return 1

    try:
        from automation_service.mobile.spec_runner import run_mobile_spec
    except Exception as e:
        print(f"ERROR: failed to import spec runner: {e}", file=sys.stderr)
        return 1

    started_at = datetime.now()
    results: list[IterationResult] = []

    for i in range(1, args.iterations + 1):
        t0 = time.time()
        try:
            run_result = run_mobile_spec(spec_json_path=str(spec_path))
            duration_s = round(time.time() - t0, 2)
            iter_result = IterationResult(
                iteration=i,
                ok=True,
                duration_s=duration_s,
                executed_steps=run_result.executed_steps,
                artifact_count=len(run_result.artifacts),
                error=None,
                artifacts=[str(p) for p in run_result.artifacts],
            )
        except Exception as e:  # fail-fast per iteration, but keep benchmark running
            duration_s = round(time.time() - t0, 2)
            iter_result = IterationResult(
                iteration=i,
                ok=False,
                duration_s=duration_s,
                executed_steps=0,
                artifact_count=0,
                error=str(e),
                artifacts=[],
            )

        results.append(iter_result)
        print(
            f"iter={iter_result.iteration} ok={iter_result.ok} "
            f"duration={iter_result.duration_s}s steps={iter_result.executed_steps}"
        )

    ended_at = datetime.now()
    passed = sum(1 for r in results if r.ok)
    failed = len(results) - passed
    total_duration_s = round((ended_at - started_at).total_seconds(), 2)

    default_report_path = (
        Path("artifacts")
        / f"mobile_spec_benchmark_{started_at.strftime('%Y%m%d-%H%M%S')}.json"
    ).resolve()
    report_path = Path(args.report_path).resolve() if args.report_path else default_report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report_payload = {
        "timestamp_start": started_at.isoformat(),
        "timestamp_end": ended_at.isoformat(),
        "total_duration_s": total_duration_s,
        "spec_path": str(spec_path),
        "iterations": len(results),
        "passed": passed,
        "failed": failed,
        "pass_rate": round((passed / len(results)) * 100.0, 2) if results else 0.0,
        "results": [asdict(r) for r in results],
    }
    report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    print(f"report={report_path}")
    if failed > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
