#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from automation_service.mobile.android_accessibility import extract_accessible_strings
from automation_service.mobile.appium_http_client import AppiumHTTPClient
from automation_service.mobile.config import load_json_file
from automation_service.mobile import live_hinge_agent as lha


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Record a single continuous video demonstrating: like, discover comment+like (send_message), and pass.\n\n"
            "WARNING: the resulting video/screenshots may contain private user data."
        )
    )
    p.add_argument(
        "--base-config",
        default="automation_service/mobile_examples/live_hinge_agent.live_comment_probe.example.json",
        help="Base live_hinge_agent config for capabilities + locators.",
    )
    p.add_argument(
        "--out-dir",
        default="",
        help="Output directory. Defaults to artifacts/demo/hinge_combo_demo_<ts>/",
    )
    p.add_argument(
        "--record-seconds",
        type=int,
        default=45,
        help="Screenrecord time limit seconds (default 45).",
    )
    p.add_argument(
        "--message-text",
        default="",
        help=(
            "Optional comment text for the discover comment-like step. "
            "If omitted, uses the profile's message_policy.template."
        ),
    )
    p.add_argument(
        "--sleep-after-action-s",
        type=float,
        default=1.0,
        help="Seconds to wait after each action before capturing post-state (default 1.0).",
    )
    p.add_argument(
        "--redact",
        action="store_true",
        help="If set, also generate a redacted video copy (top portion blacked out).",
    )
    p.add_argument(
        "--redact-top-fraction",
        type=float,
        default=0.0,
        help="If --redact, fraction of video height to black out from top (default 0.0; you should set ~0.65).",
    )
    return p


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _run(cmd: list[str], *, timeout_s: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout_s)


def _adb(*args: str, timeout_s: float = 60) -> subprocess.CompletedProcess[str]:
    return _run(["adb", *args], timeout_s=timeout_s)


def _require_ok(proc: subprocess.CompletedProcess[str], *, context: str) -> None:
    if proc.returncode != 0:
        stderr_tail = "\n".join((proc.stderr or "").splitlines()[-20:])
        raise RuntimeError(f"{context} failed: rc={proc.returncode}\n{stderr_tail}")


def _launch_hinge() -> None:
    _adb("shell", "am", "start", "-n", "co.hinge.app/.ui.AppActivity", timeout_s=30)
    time.sleep(0.8)


def _start_screenrecord(*, seconds: int, remote_path: str) -> subprocess.Popen[bytes]:
    cmd = ["adb", "shell", "screenrecord", "--time-limit", str(int(seconds)), remote_path]
    return subprocess.Popen(cmd, cwd=str(REPO_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _pull_recording(*, remote_path: str, local_path: Path) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    proc = _adb("pull", remote_path, str(local_path), timeout_s=120)
    _require_ok(proc, context=f"adb pull {remote_path}")
    _adb("shell", "rm", "-f", remote_path, timeout_s=30)


def _ffmpeg_redact(*, src: Path, dst: Path, redact_top_fraction: float) -> None:
    frac = max(0.0, min(float(redact_top_fraction), 1.0))
    if frac <= 0:
        raise RuntimeError("--redact-top-fraction must be > 0 when --redact is set")
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
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg redaction failed: {proc.stderr}")


def _capture_state(client: AppiumHTTPClient) -> tuple[str, list[str], str, dict[str, Any], int]:
    xml = client.get_page_source()
    strings = extract_accessible_strings(xml, limit=2500)
    screen_type = lha._classify_hinge_screen(strings)
    quality_features = lha._extract_quality_features(strings)
    score = lha._score_quality(screen_type=screen_type, quality_features=quality_features)
    return xml, strings, screen_type, quality_features, score


def _ensure_discover_surface(
    client: AppiumHTTPClient,
    *,
    locator_map: dict[str, list[lha.Locator]],
    max_attempts: int = 4,
) -> tuple[str, list[str], str, dict[str, Any], int]:
    for _ in range(max_attempts):
        xml, strings, screen_type, qf, score = _capture_state(client)
        if screen_type == "hinge_discover_card":
            return xml, strings, screen_type, qf, score

        # Prefer closing overlays if possible.
        if screen_type in {"hinge_overlay_rose_sheet", "hinge_like_paywall"} and locator_map.get("overlay_close"):
            try:
                lha._click_any(client, locators=locator_map["overlay_close"])
                time.sleep(0.6)
                continue
            except Exception:
                pass

        # Try to go to Discover tab.
        if locator_map.get("discover_tab"):
            try:
                lha._click_any(client, locators=locator_map["discover_tab"])
                time.sleep(0.6)
                continue
            except Exception:
                pass

        # Last resort: Android back.
        try:
            client.press_keycode(keycode=4)
        except Exception:
            pass
        time.sleep(0.6)

    xml, strings, screen_type, qf, score = _capture_state(client)
    raise RuntimeError(f"Could not reach hinge_discover_card. screen_type={screen_type} score={score}")


def main() -> int:
    args = _parser().parse_args()

    base_config_path = Path(args.base_config).expanduser().resolve()
    if not base_config_path.exists():
        raise SystemExit(f"base config not found: {base_config_path}")
    base = load_json_file(str(base_config_path))

    out_dir = (
        Path(args.out_dir).expanduser().resolve()
        if args.out_dir
        else (REPO_ROOT / "artifacts" / "demo" / f"hinge_combo_demo_{_now_tag()}").resolve()
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = out_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Load capabilities + locators + profile to reuse the exact same runtime config as the agent.
    capabilities_json_path = str(base.get("capabilities_json_path") or "").strip()
    if not capabilities_json_path:
        raise SystemExit("base config missing capabilities_json_path")
    capabilities_payload = load_json_file(capabilities_json_path)

    locators_raw = base.get("locators")
    if not isinstance(locators_raw, dict):
        raise SystemExit("base config missing locators object")

    locator_map: dict[str, list[lha.Locator]] = {
        "discover_tab": lha._parse_locators(locators_raw.get("discover_tab"), field="discover_tab", context=str(base_config_path), required=True),
        "matches_tab": lha._parse_locators(locators_raw.get("matches_tab"), field="matches_tab", context=str(base_config_path), required=True),
        "likes_you_tab": lha._parse_locators(locators_raw.get("likes_you_tab"), field="likes_you_tab", context=str(base_config_path), required=False),
        "standouts_tab": lha._parse_locators(locators_raw.get("standouts_tab"), field="standouts_tab", context=str(base_config_path), required=False),
        "profile_hub_tab": lha._parse_locators(locators_raw.get("profile_hub_tab"), field="profile_hub_tab", context=str(base_config_path), required=False),
        "like": lha._parse_locators(locators_raw.get("like"), field="like", context=str(base_config_path), required=True),
        "pass": lha._parse_locators(locators_raw.get("pass"), field="pass", context=str(base_config_path), required=True),
        "message_input": lha._parse_locators(locators_raw.get("message_input"), field="message_input", context=str(base_config_path), required=True),
        "send": lha._parse_locators(locators_raw.get("send"), field="send", context=str(base_config_path), required=True),
        "overlay_close": lha._parse_locators(locators_raw.get("overlay_close"), field="overlay_close", context=str(base_config_path), required=False),
        "discover_message_input": lha._parse_locators(locators_raw.get("discover_message_input"), field="discover_message_input", context=str(base_config_path), required=False),
        "discover_send": lha._parse_locators(locators_raw.get("discover_send"), field="discover_send", context=str(base_config_path), required=False),
    }

    profile_json_path = str(base.get("profile_json_path") or "").strip()
    if not profile_json_path:
        raise SystemExit("base config missing profile_json_path")
    profile = lha._load_profile(profile_json_path)

    message_text = str(args.message_text).strip() if str(args.message_text).strip() else lha._render_template(
        profile.message_policy.template,
        name=None,
    )

    # Bring Hinge to foreground first so the video starts on the app.
    _launch_hinge()

    remote_mp4 = f"/sdcard/hinge_combo_demo_{_now_tag()}.mp4"
    raw_mp4 = out_dir / "screenrecord_raw.mp4"
    redacted_mp4 = out_dir / "screenrecord_redacted.mp4"
    recorder = _start_screenrecord(seconds=int(args.record_seconds), remote_path=remote_mp4)
    time.sleep(0.6)

    client = AppiumHTTPClient(str(base.get("appium_server_url") or "http://127.0.0.1:4723"))
    session_id = client.create_session(capabilities_payload)

    actions_log: list[dict[str, Any]] = []
    combo_plan = [
        {"action": "like", "label": "like"},
        {"action": "send_message", "label": "comment_like"},
        {"action": "pass", "label": "pass"},
    ]

    try:
        for idx, step in enumerate(combo_plan, 1):
            pre_xml, pre_strings, screen_type, qf, score = _ensure_discover_surface(client, locator_map=locator_map)

            pre_png_path = artifacts_dir / f"step_{idx:02d}_pre.png"
            pre_xml_path = artifacts_dir / f"step_{idx:02d}_pre.xml"
            pre_png_path.write_bytes(client.get_screenshot_png_bytes())
            pre_xml_path.write_text(pre_xml, encoding="utf-8")

            matched_locator = None
            action = step["action"]
            reason = "combo_demo_plan"
            error = None
            try:
                if action == "like":
                    matched_locator = lha._click_any(client, locators=locator_map["like"])
                elif action == "pass":
                    matched_locator = lha._click_any(client, locators=locator_map["pass"])
                elif action == "send_message":
                    discover_input = locator_map.get("discover_message_input") or locator_map["message_input"]
                    discover_send = locator_map.get("discover_send") or locator_map["send"]
                    like_locator, input_locator, send_locator = lha._send_discover_message(
                        client,
                        like_locators=locator_map["like"],
                        input_locators=discover_input,
                        send_locators=discover_send,
                        text=lha._normalize_message_text(
                            raw_text=message_text,
                            profile=profile,
                            quality_features=qf,
                        ),
                    )
                    matched_locator = send_locator
                    reason = (
                        f"{reason}; discover_like={like_locator.using}:{like_locator.value}; "
                        f"input={input_locator.using}:{input_locator.value}"
                    )
                else:
                    raise RuntimeError(f"unsupported action in combo plan: {action}")
            except Exception as e:
                error = str(e)

            time.sleep(max(0.0, float(args.sleep_after_action_s)))
            post_xml, post_strings, post_screen_type, post_qf, post_score = _capture_state(client)

            post_png_path = artifacts_dir / f"step_{idx:02d}_post.png"
            post_xml_path = artifacts_dir / f"step_{idx:02d}_post.xml"
            post_png_path.write_bytes(client.get_screenshot_png_bytes())
            post_xml_path.write_text(post_xml, encoding="utf-8")

            changed = (post_xml != pre_xml) or (post_screen_type != screen_type)
            actions_log.append(
                {
                    "step": idx,
                    "label": step["label"],
                    "action": action,
                    "reason": reason,
                    "error": error,
                    "pre": {
                        "screen_type": screen_type,
                        "quality_score_v1": score,
                        "available_actions": lha._build_available_actions(
                            screen_type=screen_type,
                            client=client,
                            locators=locator_map,
                            message_enabled=True,
                        ),
                        "screenshot_path": str(pre_png_path),
                        "xml_path": str(pre_xml_path),
                    },
                    "post": {
                        "screen_type": post_screen_type,
                        "quality_score_v1": post_score,
                        "screenshot_path": str(post_png_path),
                        "xml_path": str(post_xml_path),
                    },
                    "changed": bool(changed),
                    "matched_locator": None
                    if matched_locator is None
                    else {"using": matched_locator.using, "value": matched_locator.value},
                }
            )

    finally:
        try:
            client.delete_session()
        except Exception:
            pass

        try:
            recorder.wait(timeout=max(10, int(args.record_seconds) + 10))
        except Exception:
            recorder.kill()

        # Pull recording to out_dir.
        _pull_recording(remote_path=remote_mp4, local_path=raw_mp4)
        if args.redact:
            _ffmpeg_redact(src=raw_mp4, dst=redacted_mp4, redact_top_fraction=float(args.redact_top_fraction))

    summary = {
        "timestamp": datetime.now().isoformat(),
        "out_dir": str(out_dir),
        "screenrecord_raw_mp4": str(raw_mp4),
        "screenrecord_redacted_mp4": str(redacted_mp4) if args.redact else None,
        "actions_log_path": str((out_dir / "actions_log.json").resolve()),
        "warning": "Videos and screenshots may contain private user data. Do not commit or share.",
    }
    (out_dir / "actions_log.json").write_text(json.dumps(actions_log, indent=2), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"demo_dir={out_dir}")
    print(f"video={raw_mp4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

