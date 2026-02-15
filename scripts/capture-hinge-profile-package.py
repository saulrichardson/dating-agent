#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from automation_service.mobile.appium_http_client import AppiumHTTPClient
from automation_service.mobile.config import load_json_file
from automation_service.mobile.android_accessibility import extract_accessible_strings
from automation_service.mobile import live_hinge_agent as lha
from automation_service.mobile.hinge_profile_bundle import parse_profile_bundle_capture_config
from automation_service.mobile.hinge_profile_package import (
    ProfilePackageCaptureConfig,
    capture_profile_package,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a full Hinge profile package (UI evidence + action map).")
    parser.add_argument(
        "--appium-url",
        default="http://127.0.0.1:4723",
        help="Appium server URL (default: http://127.0.0.1:4723)",
    )
    parser.add_argument(
        "--capabilities",
        default="automation_service/mobile_examples/android_capabilities.example.json",
        help="Path to capabilities JSON",
    )
    parser.add_argument(
        "--out",
        default="artifacts/proofs",
        help="Output directory root (default: artifacts/proofs)",
    )
    parser.add_argument(
        "--expected-package",
        default="co.hinge.app",
        help="Expected Android package for Hinge (default: co.hinge.app)",
    )
    parser.add_argument(
        "--activity",
        default=".ui.AppActivity",
        help="Android activity to foreground (default: .ui.AppActivity)",
    )
    parser.add_argument("--tag", default=None, help="Optional tag appended to output folder name")
    parser.add_argument("--no-probe-more", action="store_true", help="Disable probing the More menu surface")
    parser.add_argument("--no-probe-composer", action="store_true", help="Disable probing the comment composer surface")
    parser.add_argument(
        "--no-probe-primary",
        action="store_true",
        help="Disable probing the primary media surface (photo/video viewer)",
    )
    args = parser.parse_args()

    appium_url = str(args.appium_url)
    caps = load_json_file(str(args.capabilities))
    out_root = Path(str(args.out)).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    tag = str(args.tag or "").strip()
    suffix = f"_{tag}" if tag else ""
    out_dir = out_root / f"hinge_profile_package_{ts}{suffix}"

    base_bundle_cfg = parse_profile_bundle_capture_config(
        {
            "enabled": True,
            "max_views": 10,
            "stop_after_unchanged": 2,
            "swipe_duration_ms": 650,
            "swipe_margin_pct": 0.12,
            "settle_sleep_s": 0.35,
            "max_nodes_per_view": 4500,
            "max_accessible_strings": 2500,
            "max_targets_per_view": 260,
        },
        context="capture-hinge-profile-package",
    )

    cfg = ProfilePackageCaptureConfig(
        base_bundle=base_bundle_cfg,
        probe_more_menu=not bool(args.no_probe_more),
        probe_comment_composer=not bool(args.no_probe_composer),
        probe_primary_surface=not bool(args.no_probe_primary),
        settle_sleep_s=0.35,
    )

    client = AppiumHTTPClient(appium_url)
    session_id = client.create_session(caps)
    try:
        # Foreground Hinge via adb first. Appium sessions do not guarantee app foreground.
        pkg = str(args.expected_package).strip()
        activity = str(args.activity).strip()
        if pkg and activity:
            component = activity if "/" in activity else f"{pkg}/{activity}"
            try:
                subprocess.run(
                    ["adb", "shell", "am", "start", "-n", component],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

        # Best-effort routing: try to land on a Discover profile card before capture.
        for _ in range(4):
            xml = client.get_page_source()
            strings = extract_accessible_strings(xml, limit=1200)
            st = lha._classify_hinge_screen(strings)
            if st == "hinge_discover_card":
                break
            # Dismiss transient overlays / recover to a stable surface.
            try:
                client.press_keycode(keycode=4)
            except Exception:
                pass
            # Tap Discover tab if present.
            try:
                els = client.find_elements(using="accessibility id", value="Discover")
                if els:
                    client.click(els[0])
            except Exception:
                pass
        else:
            raise RuntimeError(
                "Failed to reach hinge_discover_card after routing attempts. "
                "Open Hinge and navigate to Discover before running this capture."
            )

        manifest = capture_profile_package(
            client,
            output_dir=out_dir,
            expected_package=str(args.expected_package) or None,
            cfg=cfg,
        )
        print(manifest.get("package_dir"))
    finally:
        client.delete_session()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
