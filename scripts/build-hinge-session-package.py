#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SessionPaths:
    session_dir: Path
    frames_jsonl: Path
    profiles_jsonl: Path
    messages_jsonl: Path
    nodes_jsonl: Path
    summary_json: Path


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Build a portable, structured package contract from a full-fidelity Hinge session "
            "(frames/profiles/messages/nodes + screenshots/XML artifacts)."
        )
    )
    p.add_argument(
        "--session-dir",
        default="",
        help="Path to full-fidelity session directory containing frames.jsonl etc.",
    )
    p.add_argument(
        "--summary-json",
        default="",
        help="Path to summary.json from a full-fidelity session (alternative to --session-dir).",
    )
    p.add_argument(
        "--output-dir",
        default="",
        help="Output package directory. Defaults to <session-dir>/package_contract_<timestamp>.",
    )
    p.add_argument(
        "--copy-assets",
        action="store_true",
        help="Copy referenced screenshot/XML assets into package assets/ for portability.",
    )
    p.add_argument(
        "--max-snapshots-per-profile",
        type=int,
        default=12,
        help="Max snapshots to retain per profile in package metadata.",
    )
    return p


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


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
                raise ValueError(f"Invalid JSON in {path}:{idx}: {e}") from e
            if not isinstance(payload, dict):
                raise ValueError(f"Expected object row in {path}:{idx}")
            rows.append(payload)
    return rows


def _resolve_session_paths(*, session_dir: str, summary_json: str) -> SessionPaths:
    if bool(session_dir) == bool(summary_json):
        raise ValueError("Provide exactly one of --session-dir or --summary-json")

    if summary_json:
        summary_path = Path(summary_json).resolve()
        if not summary_path.exists():
            raise FileNotFoundError(f"summary.json not found: {summary_path}")
        s = _load_json(summary_path)
        files = s.get("files") if isinstance(s.get("files"), dict) else {}
        required = ["frames_jsonl_path", "profiles_jsonl_path", "messages_jsonl_path", "nodes_jsonl_path"]
        for k in required:
            if not isinstance(files.get(k), str) or not files.get(k):
                raise ValueError(f"summary missing files.{k}: {summary_path}")
        return SessionPaths(
            session_dir=summary_path.parent.resolve(),
            frames_jsonl=Path(files["frames_jsonl_path"]).resolve(),
            profiles_jsonl=Path(files["profiles_jsonl_path"]).resolve(),
            messages_jsonl=Path(files["messages_jsonl_path"]).resolve(),
            nodes_jsonl=Path(files["nodes_jsonl_path"]).resolve(),
            summary_json=summary_path,
        )

    base = Path(session_dir).resolve()
    if not base.exists():
        raise FileNotFoundError(f"session dir not found: {base}")
    return SessionPaths(
        session_dir=base,
        frames_jsonl=base / "frames.jsonl",
        profiles_jsonl=base / "profiles.jsonl",
        messages_jsonl=base / "messages.jsonl",
        nodes_jsonl=base / "nodes.jsonl",
        summary_json=base / "summary.json",
    )


def _copy_asset(path: str | None, *, assets_dir: Path, copied: dict[str, str]) -> str | None:
    if path is None:
        return None
    src = Path(path).resolve()
    if not src.exists():
        return None
    src_key = str(src)
    if src_key in copied:
        return copied[src_key]
    assets_dir.mkdir(parents=True, exist_ok=True)
    dest = assets_dir / src.name
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        i = 1
        while True:
            candidate = assets_dir / f"{stem}_{i}{suffix}"
            if not candidate.exists():
                dest = candidate
                break
            i += 1
    shutil.copy2(src, dest)
    rel = str(dest)
    copied[src_key] = rel
    return rel


def main() -> int:
    args = _parser().parse_args()
    if args.max_snapshots_per_profile <= 0:
        raise SystemExit("ERROR: --max-snapshots-per-profile must be > 0")

    paths = _resolve_session_paths(session_dir=args.session_dir, summary_json=args.summary_json)
    for p in [paths.frames_jsonl, paths.profiles_jsonl, paths.messages_jsonl, paths.nodes_jsonl]:
        if not p.exists():
            raise FileNotFoundError(f"Required session file missing: {p}")

    frames = _read_jsonl(paths.frames_jsonl)
    profiles = _read_jsonl(paths.profiles_jsonl)
    messages = _read_jsonl(paths.messages_jsonl)

    now = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else (paths.session_dir / f"package_contract_{now}").resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / "assets"
    copied_assets: dict[str, str] = {}

    profile_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in profiles:
        fp = str(row.get("profile_fingerprint") or "")
        if fp:
            profile_groups[fp].append(row)

    packaged_profiles: list[dict[str, Any]] = []
    for fingerprint, rows in profile_groups.items():
        rows = sorted(rows, key=lambda r: int(r.get("iteration") or 0))
        representative = rows[0]
        snapshot_rows = rows[: args.max_snapshots_per_profile]
        snapshots: list[dict[str, Any]] = []
        screenshot_assets: list[str] = []
        source_assets: list[str] = []
        for r in snapshot_rows:
            screenshot_path = r.get("screenshot_path")
            source_path = r.get("source_path")
            if args.copy_assets:
                screenshot_path = _copy_asset(screenshot_path, assets_dir=assets_dir, copied=copied_assets)
                source_path = _copy_asset(source_path, assets_dir=assets_dir, copied=copied_assets)
            snapshots.append(
                {
                    "frame_id": r.get("frame_id"),
                    "iteration": r.get("iteration"),
                    "ts": r.get("ts"),
                    "screen_type": r.get("screen_type"),
                    "screenshot_path": screenshot_path,
                    "source_path": source_path,
                }
            )
            if screenshot_path:
                screenshot_assets.append(str(screenshot_path))
            if source_path:
                source_assets.append(str(source_path))

        packaged_profiles.append(
            {
                "profile_fingerprint": fingerprint,
                "first_seen_iteration": rows[0].get("iteration"),
                "last_seen_iteration": rows[-1].get("iteration"),
                "observations": len(rows),
                "profile_snapshot_latest": rows[-1].get("profile_snapshot"),
                "profile_snapshot_first": representative.get("profile_snapshot"),
                "assets": {
                    "screenshots": sorted(set(screenshot_assets)),
                    "sources": sorted(set(source_assets)),
                },
                "snapshots": snapshots,
            }
        )

    thread_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in messages:
        key = str(row.get("thread_key") or "__unknown__")
        thread_groups[key].append(row)

    packaged_threads: list[dict[str, Any]] = []
    for thread_key, rows in sorted(thread_groups.items()):
        rows = sorted(rows, key=lambda r: int(r.get("iteration") or 0))
        events = []
        screenshot_assets: list[str] = []
        source_assets: list[str] = []
        for r in rows:
            screenshot_path = r.get("screenshot_path")
            source_path = r.get("source_path")
            if args.copy_assets:
                screenshot_path = _copy_asset(screenshot_path, assets_dir=assets_dir, copied=copied_assets)
                source_path = _copy_asset(source_path, assets_dir=assets_dir, copied=copied_assets)
            events.append(
                {
                    "ts": r.get("ts"),
                    "iteration": r.get("iteration"),
                    "event_type": r.get("event_type"),
                    "messages_count": r.get("messages_count"),
                    "new_messages": r.get("new_messages"),
                    "messages": r.get("messages"),
                    "screenshot_path": screenshot_path,
                    "source_path": source_path,
                }
            )
            if screenshot_path:
                screenshot_assets.append(str(screenshot_path))
            if source_path:
                source_assets.append(str(source_path))
        packaged_threads.append(
            {
                "thread_key": thread_key,
                "events_count": len(rows),
                "last_event_type": rows[-1].get("event_type"),
                "assets": {
                    "screenshots": sorted(set(screenshot_assets)),
                    "sources": sorted(set(source_assets)),
                },
                "events": events,
            }
        )

    screen_type_counts: dict[str, int] = {}
    for row in frames:
        screen = str(row.get("screen_type") or "unknown")
        screen_type_counts[screen] = screen_type_counts.get(screen, 0) + 1

    messages_tab_state = "no_threads_observed"
    if packaged_threads:
        if any(t["thread_key"] != "__inbox__" for t in packaged_threads):
            messages_tab_state = "threads_observed"
        else:
            messages_tab_state = "inbox_empty_observed"

    package_payload = {
        "contract_version": "hinge_session_package.v1",
        "generated_at": datetime.now().isoformat(),
        "source_session_dir": str(paths.session_dir),
        "source_files": {
            "summary_json": str(paths.summary_json) if paths.summary_json.exists() else None,
            "frames_jsonl": str(paths.frames_jsonl),
            "profiles_jsonl": str(paths.profiles_jsonl),
            "messages_jsonl": str(paths.messages_jsonl),
            "nodes_jsonl": str(paths.nodes_jsonl),
        },
        "stats": {
            "frames": len(frames),
            "profiles": len(profiles),
            "messages": len(messages),
            "unique_profile_fingerprints": len(packaged_profiles),
            "unique_threads": len(packaged_threads),
            "screen_type_counts": screen_type_counts,
            "messages_tab_state": messages_tab_state,
        },
        "profiles": sorted(
            packaged_profiles,
            key=lambda r: int(r.get("first_seen_iteration") or 0),
        ),
        "threads": packaged_threads,
    }

    package_json = output_dir / "session_package.json"
    package_json.write_text(json.dumps(package_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    profiles_index_jsonl = output_dir / "profiles_index.jsonl"
    with profiles_index_jsonl.open("w", encoding="utf-8") as f:
        for row in package_payload["profiles"]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    threads_index_jsonl = output_dir / "threads_index.jsonl"
    with threads_index_jsonl.open("w", encoding="utf-8") as f:
        for row in package_payload["threads"]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    manifest = {
        "output_dir": str(output_dir),
        "package_json": str(package_json),
        "profiles_index_jsonl": str(profiles_index_jsonl),
        "threads_index_jsonl": str(threads_index_jsonl),
        "assets_copied": len(copied_assets),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"manifest={manifest_path}")
    print(f"package_json={package_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
