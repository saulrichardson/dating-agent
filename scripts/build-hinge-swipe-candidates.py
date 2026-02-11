#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SwipeCandidate:
    source_id: str
    source_path: str
    screenshot_path: str | None
    capture_timestamp: str | None
    screen_type: str
    profile_name_candidate: str | None
    quality_score_v1: int | None
    quality_reasons_v1: list[str]
    decision: str
    decision_reason: str


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Build a deterministic Hinge swipe candidate queue from offline "
            "screen JSONL exports."
        )
    )
    p.add_argument("--screens-jsonl", required=True, help="Path to *_screens_*.jsonl export file.")
    p.add_argument(
        "--output-jsonl",
        default="",
        help="Output path for candidate JSONL. Defaults to artifacts/offline_exports/<auto>.jsonl",
    )
    p.add_argument(
        "--summary-json",
        default="",
        help="Optional path for summary JSON. Defaults next to output JSONL.",
    )
    p.add_argument(
        "--like-threshold",
        type=int,
        default=75,
        help="Score >= this threshold gets decision=like (default: 75).",
    )
    p.add_argument(
        "--review-threshold",
        type=int,
        default=50,
        help="Score >= this threshold gets decision=review (default: 50).",
    )
    p.add_argument(
        "--exclude-skip",
        action="store_true",
        help="Exclude rows with decision=skip from output.",
    )
    return p


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception as e:
                raise ValueError(f"Invalid JSONL at {path}:{idx}: {e}") from e
            if not isinstance(payload, dict):
                raise ValueError(f"Invalid JSONL row at {path}:{idx}: expected object")
            rows.append(payload)
    return rows


def _as_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _build_decision(
    *,
    screen_type: str,
    score: int | None,
    like_threshold: int,
    review_threshold: int,
) -> tuple[str, str]:
    if screen_type != "hinge_discover_card":
        return "skip", "non_discover_surface"
    if score is None:
        return "review", "missing_score"
    if score >= like_threshold:
        return "like", f"score>={like_threshold}"
    if score >= review_threshold:
        return "review", f"score>={review_threshold}"
    return "pass", f"score<{review_threshold}"


def main() -> int:
    args = _parser().parse_args()

    if args.review_threshold > args.like_threshold:
        print(
            "ERROR: --review-threshold cannot be greater than --like-threshold",
            file=sys.stderr,
        )
        return 1

    input_path = Path(args.screens_jsonl).resolve()
    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        return 1

    rows = _read_jsonl(input_path)
    if not rows:
        print("ERROR: input JSONL has no rows", file=sys.stderr)
        return 1

    now = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    default_output = (
        Path("artifacts")
        / "offline_exports"
        / f"hinge_swipe_candidates_{now}.jsonl"
    ).resolve()
    output_jsonl = Path(args.output_jsonl).resolve() if args.output_jsonl else default_output
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)

    default_summary = output_jsonl.with_suffix(".summary.json")
    summary_json = Path(args.summary_json).resolve() if args.summary_json else default_summary
    summary_json.parent.mkdir(parents=True, exist_ok=True)

    # Keep the highest scoring candidate per source_id.
    best_by_source: dict[str, SwipeCandidate] = {}
    filtered_rows = [
        r
        for r in rows
        if r.get("package_name") == "co.hinge.app"
    ]
    for row in filtered_rows:
        source_id = str(row.get("source_id") or "")
        if not source_id:
            continue
        quality_features = row.get("quality_features") if isinstance(row.get("quality_features"), dict) else {}
        profile_name_candidate = quality_features.get("profile_name_candidate")
        if profile_name_candidate is not None:
            profile_name_candidate = str(profile_name_candidate)

        reasons = row.get("quality_reasons_v1")
        if not isinstance(reasons, list):
            reasons = []
        reasons = [str(r) for r in reasons]

        score = _as_int_or_none(row.get("quality_score_v1"))
        screen_type = str(row.get("screen_type") or "unknown")
        decision, decision_reason = _build_decision(
            screen_type=screen_type,
            score=score,
            like_threshold=args.like_threshold,
            review_threshold=args.review_threshold,
        )

        candidate = SwipeCandidate(
            source_id=source_id,
            source_path=str(row.get("source_path") or ""),
            screenshot_path=None if row.get("screenshot_path") is None else str(row.get("screenshot_path")),
            capture_timestamp=None if row.get("capture_timestamp") is None else str(row.get("capture_timestamp")),
            screen_type=screen_type,
            profile_name_candidate=profile_name_candidate,
            quality_score_v1=score,
            quality_reasons_v1=reasons,
            decision=decision,
            decision_reason=decision_reason,
        )

        prev = best_by_source.get(source_id)
        if prev is None:
            best_by_source[source_id] = candidate
            continue

        prev_score = -1 if prev.quality_score_v1 is None else prev.quality_score_v1
        curr_score = -1 if candidate.quality_score_v1 is None else candidate.quality_score_v1
        if curr_score >= prev_score:
            best_by_source[source_id] = candidate

    candidates = sorted(
        best_by_source.values(),
        key=lambda c: (
            c.quality_score_v1 if c.quality_score_v1 is not None else -1,
            c.capture_timestamp or "",
            c.source_id,
        ),
        reverse=True,
    )
    if args.exclude_skip:
        candidates = [c for c in candidates if c.decision != "skip"]

    with output_jsonl.open("w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")

    decision_counts = Counter(c.decision for c in candidates)
    summary = {
        "input_path": str(input_path),
        "output_jsonl": str(output_jsonl),
        "like_threshold": args.like_threshold,
        "review_threshold": args.review_threshold,
        "total_input_rows": len(rows),
        "filtered_hinge_rows": len(filtered_rows),
        "output_candidate_rows": len(candidates),
        "decision_counts": dict(decision_counts),
    }
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"output_jsonl={output_jsonl}")
    print(f"summary_json={summary_json}")
    print(f"candidates={len(candidates)}")
    print(f"decision_counts={dict(decision_counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
