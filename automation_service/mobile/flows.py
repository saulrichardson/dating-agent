from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .android_accessibility import extract_accessible_strings
from .appium_http_client import AppiumHTTPClient
from .config import load_json_file, require_key


DEFAULT_APPIUM_SERVER_URL = "http://127.0.0.1:4723"


@dataclass(frozen=True)
class MobileSmokeTestResult:
    session_id: str
    screenshot_path: Path
    page_source_path: Path


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _default_artifacts_dir() -> Path:
    return Path(os.environ.get("CONCIERGE_ARTIFACTS_DIR", "artifacts")).resolve()


def run_mobile_smoke_test(
    *,
    appium_server_url: str,
    capabilities_json_path: str,
    artifacts_dir: Optional[str] = None,
    wait_for_enter_before_capture: bool = False,
) -> MobileSmokeTestResult:
    """
    Create a session, save a screenshot and UI XML (/source), then teardown.

    This is the fastest way to validate:
    - Appium connectivity
    - device/emulator availability
    - whether the app's UI exposes text via accessibility/UIAutomator
    """
    capabilities_payload = load_json_file(capabilities_json_path)
    require_key(capabilities_payload, "capabilities", context=capabilities_json_path)

    out_dir = Path(artifacts_dir).resolve() if artifacts_dir else _default_artifacts_dir()
    _ensure_dir(out_dir)

    client = AppiumHTTPClient(appium_server_url)
    session_id = client.create_session(capabilities_payload)
    try:
        if wait_for_enter_before_capture:
            input(
                "\nAppium session started. Use the emulator now (login/navigate), then press Enter to capture..."
            )

        screenshot_bytes = client.get_screenshot_png_bytes()
        page_source_xml = client.get_page_source()

        screenshot_path = out_dir / "mobile_screenshot.png"
        page_source_path = out_dir / "mobile_page_source.xml"

        screenshot_path.write_bytes(screenshot_bytes)
        page_source_path.write_text(page_source_xml, encoding="utf-8")

        return MobileSmokeTestResult(
            session_id=session_id,
            screenshot_path=screenshot_path,
            page_source_path=page_source_path,
        )
    finally:
        client.delete_session()


def run_mobile_accessibility_dump(
    *,
    appium_server_url: str,
    capabilities_json_path: str,
    max_strings: int = 200,
    wait_for_enter_before_capture: bool = False,
) -> list[str]:
    """
    Convenience helper: create a session, grab /source, and return accessible strings.
    """
    capabilities_payload = load_json_file(capabilities_json_path)
    require_key(capabilities_payload, "capabilities", context=capabilities_json_path)

    client = AppiumHTTPClient(appium_server_url)
    client.create_session(capabilities_payload)
    try:
        if wait_for_enter_before_capture:
            input(
                "\nAppium session started. Use the emulator now (login/navigate), then press Enter to dump strings..."
            )

        page_source_xml = client.get_page_source()
        strings = extract_accessible_strings(page_source_xml, limit=2000)
        return strings[:max_strings]
    finally:
        client.delete_session()
