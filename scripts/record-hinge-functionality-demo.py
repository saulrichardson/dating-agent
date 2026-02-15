#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from automation_service.mobile.live_hinge_agent import LiveHingeAgentResult, run_live_hinge_agent


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Record and demonstrate current live Hinge agent functionality (like, pass, comment+like).\n\n"
            "This script interacts with a live signed-in Hinge session on the connected Android device/emulator.\n"
            "It writes all outputs under artifacts/ and does NOT commit or print any credentials.\n"
            "WARNING: raw recordings/screenshots may contain private user data."
        )
    )
    p.add_argument(
        "--base-config",
        default="automation_service/mobile_examples/live_hinge_agent.live_comment_probe.example.json",
        help="Base live_hinge_agent config to clone for each demo run.",
    )
    p.add_argument(
        "--out-dir",
        default="",
        help="Output directory. Defaults to artifacts/demo/hinge_functionality_demo_<ts>/",
    )
    p.add_argument(
        "--record-seconds",
        type=int,
        default=22,
        help="Seconds to record screen for each demo run (default 22).",
    )
    p.add_argument(
        "--redact-top-fraction",
        type=float,
        default=0.62,
        help="Fraction of video height to black out from top (default 0.62).",
    )
    p.add_argument(
        "--skip-redaction",
        action="store_true",
        help="If set, do not generate redacted video copies.",
    )
    p.add_argument(
        "--skip-comment-like",
        action="store_true",
        help="If set, do not run the comment+like (send_message) demo.",
    )
    p.add_argument(
        "--skip-like",
        action="store_true",
        help="If set, do not run the 1-step 'like now' demo.",
    )
    p.add_argument(
        "--skip-pass",
        action="store_true",
        help="If set, do not run the 1-step 'pass now' demo.",
    )
    return p


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _run(cmd: list[str], *, timeout_s: float = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout_s)


def _require_ok(proc: subprocess.CompletedProcess[str], *, context: str) -> None:
    if proc.returncode != 0:
        raise RuntimeError(f"{context} failed: rc={proc.returncode} stderr_tail={(proc.stderr or '').splitlines()[-10:]}")


def _adb(*args: str, timeout_s: float = 30) -> subprocess.CompletedProcess[str]:
    return _run(["adb", *args], timeout_s=timeout_s)


def _launch_hinge() -> None:
    # Best-effort: bring Hinge to foreground.
    _adb("shell", "am", "start", "-n", "co.hinge.app/.ui.AppActivity", timeout_s=20)
    time.sleep(0.8)


def _start_screenrecord(*, seconds: int, remote_path: str) -> subprocess.Popen[bytes]:
    # NOTE: adb screenrecord writes to /sdcard/... and exits when time-limit is reached.
    # We start it as a background process so the live agent can run concurrently.
    cmd = ["adb", "shell", "screenrecord", "--time-limit", str(int(seconds)), remote_path]
    return subprocess.Popen(cmd, cwd=str(REPO_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _pull_recording(*, remote_path: str, local_path: Path) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    proc = _adb("pull", remote_path, str(local_path), timeout_s=90)
    _require_ok(proc, context=f"adb pull {remote_path}")
    _adb("shell", "rm", "-f", remote_path, timeout_s=20)


def _ffmpeg_redact(*, src: Path, dst: Path, redact_top_fraction: float) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    frac = max(0.0, min(float(redact_top_fraction), 1.0))
    # Black out the top portion of the screen to avoid capturing private profile info.
    vf = f"drawbox=x=0:y=0:w=iw:h=ih*{frac}:color=black@1:t=fill"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-crf",
        "23",
        "-preset",
        "veryfast",
        "-an",
        str(dst),
    ]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg redaction failed: {proc.stderr}")


def _sanitize_action_log_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "iteration": row.get("iteration"),
                "ts": row.get("ts"),
                "screen_type": row.get("screen_type"),
                "decision": row.get("decision"),
                "reason": row.get("reason"),
                "dry_run": row.get("dry_run"),
                "validation_status": row.get("validation_status"),
                "validation_reason": row.get("validation_reason"),
                "matched_locator": row.get("matched_locator"),
                "packet_screenshot_path": row.get("packet_screenshot_path"),
                "post_action_screenshot_path": row.get("post_action_screenshot_path"),
                "llm_trace": row.get("llm_trace"),
            }
        )
    return out


def _write_run_config(*, base_config: dict[str, Any], out_path: Path, artifacts_dir: Path, command_query: str) -> None:
    cfg = json.loads(json.dumps(base_config))  # deep copy
    cfg["artifacts_dir"] = str(artifacts_dir.resolve())
    cfg["command_query"] = command_query
    # Make the demo deterministic and bounded.
    cfg["decision_engine"] = {"type": "deterministic"}
    cfg["pause_before_start"] = False
    # Always capture evidence.
    cfg["capture_each_action"] = True
    cfg["persist_packet_log"] = True
    cfg["packet_capture_screenshot"] = True
    cfg["packet_capture_xml"] = True
    out_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return payload


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(x, dict) for x in payload):
        raise ValueError(f"Expected JSON list of objects at {path}")
    return payload


def _run_one_demo(
    *,
    base_config: dict[str, Any],
    out_dir: Path,
    name: str,
    command_query: str,
    record_seconds: int,
    redact_top_fraction: float,
    skip_redaction: bool,
) -> dict[str, Any]:
    run_dir = out_dir / name
    run_dir.mkdir(parents=True, exist_ok=True)

    _launch_hinge()
    remote_mp4 = f"/sdcard/hinge_demo_{name}_{_now_tag()}.mp4"
    raw_mp4 = run_dir / "screenrecord_raw.mp4"
    redacted_mp4 = run_dir / "screenrecord_redacted.mp4"

    recorder = _start_screenrecord(seconds=record_seconds, remote_path=remote_mp4)
    time.sleep(0.6)

    cfg_path = run_dir / "live_hinge_agent.demo_config.json"
    _write_run_config(
        base_config=base_config,
        out_path=cfg_path,
        artifacts_dir=run_dir / "artifacts",
        command_query=command_query,
    )

    agent_result: Optional[LiveHingeAgentResult] = None
    agent_error: Optional[str] = None
    try:
        # Ensure all relative paths in configs resolve consistently.
        os.chdir(str(REPO_ROOT))
        agent_result = run_live_hinge_agent(config_json_path=str(cfg_path))
    except Exception as e:
        agent_error = str(e)
    finally:
        # Wait for the recorder to finish (it will exit on time-limit).
        try:
            recorder.wait(timeout=max(5, int(record_seconds) + 5))
        except Exception:
            recorder.kill()

    # Pull the recording even if the agent failed; it can help debug.
    try:
        _pull_recording(remote_path=remote_mp4, local_path=raw_mp4)
    except Exception as e:
        # Not fatal; emulator/device may not support screenrecord in some cases.
        raw_mp4 = None  # type: ignore[assignment]
        agent_error = (agent_error or "") + f" | recording_pull_failed:{e}"

    if raw_mp4 is not None and (not skip_redaction):
        try:
            _ffmpeg_redact(src=raw_mp4, dst=redacted_mp4, redact_top_fraction=redact_top_fraction)
        except Exception as e:
            agent_error = (agent_error or "") + f" | redaction_failed:{e}"

    sanitized_actions_path = None
    summary = {
        "name": name,
        "command_query": command_query,
        "ok": agent_result is not None and agent_error is None,
        "agent_error": agent_error,
        "run_dir": str(run_dir),
        "config_path": str(cfg_path),
        "raw_video_path": None if raw_mp4 is None else str(raw_mp4),
        "redacted_video_path": None if skip_redaction else str(redacted_mp4) if redacted_mp4.exists() else None,
    }

    if agent_result is not None:
        summary["agent_result"] = {
            "session_id": agent_result.session_id,
            "iterations": agent_result.iterations,
            "likes": agent_result.likes,
            "passes": agent_result.passes,
            "messages": agent_result.messages,
            "action_log_path": str(agent_result.action_log_path),
            "packet_log_path": None if agent_result.packet_log_path is None else str(agent_result.packet_log_path),
            "artifacts_count": len(agent_result.artifacts),
        }
        # Write a sanitized action trace that avoids names/prompts/observed_strings.
        rows = _read_json_list(agent_result.action_log_path)
        sanitized = _sanitize_action_log_rows(rows)
        sanitized_actions_path = run_dir / "action_log_sanitized.json"
        sanitized_actions_path.write_text(json.dumps(sanitized, indent=2), encoding="utf-8")
        summary["action_log_sanitized_path"] = str(sanitized_actions_path)

    (run_dir / "demo_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    args = _parser().parse_args()

    base_config_path = Path(args.base_config).expanduser().resolve()
    if not base_config_path.exists():
        raise SystemExit(f"base config not found: {base_config_path}")
    base_config = _load_json(base_config_path)

    out_dir = (
        Path(args.out_dir).expanduser().resolve()
        if args.out_dir
        else (REPO_ROOT / "artifacts" / "demo" / f"hinge_functionality_demo_{_now_tag()}").resolve()
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    # Quick environment sanity checks (best effort).
    _adb("devices", timeout_s=10)
    _adb("shell", "pm", "list", "packages", timeout_s=20)

    demos: list[tuple[str, str, bool]] = [
        (
            "pass_once",
            "Pass now. For 1 actions. Live run. Don't message.",
            bool(args.skip_pass),
        ),
        (
            "like_once",
            "Like now. For 1 actions. Live run. Don't message.",
            bool(args.skip_like),
        ),
        (
            "comment_like_once",
            "Send message now. Max messages 1. For 1 actions. Live run.",
            bool(args.skip_comment_like),
        ),
    ]

    results: list[dict[str, Any]] = []
    for name, query, skip in demos:
        if skip:
            continue
        results.append(
            _run_one_demo(
                base_config=base_config,
                out_dir=out_dir,
                name=name,
                command_query=query,
                record_seconds=int(args.record_seconds),
                redact_top_fraction=float(args.redact_top_fraction),
                skip_redaction=bool(args.skip_redaction),
            )
        )

    index = {
        "timestamp": datetime.now().isoformat(),
        "out_dir": str(out_dir),
        "warning": (
            "Raw videos and screenshots may contain private user data. "
            "Do not commit or share them. Use redacted copies when possible."
        ),
        "runs": results,
    }
    (out_dir / "demo_index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"demo_dir={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
