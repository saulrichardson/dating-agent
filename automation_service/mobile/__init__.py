"""
Native mobile automation helpers (Android/iOS) built around Appium.

This package is intentionally small and "fail-fast":
- Capabilities are provided explicitly via JSON (no hidden defaults).
- App-specific locators are expected to be supplied by the user.

The existing Playwright web automation remains in automation_service/browser.py.
"""

from .appium_http_client import AppiumHTTPClient, AppiumHTTPError, WebDriverElementRef
from .flows import (
    run_mobile_smoke_test,
    run_mobile_accessibility_dump,
)

__all__ = [
    "AppiumHTTPClient",
    "AppiumHTTPError",
    "WebDriverElementRef",
    "run_mobile_smoke_test",
    "run_mobile_accessibility_dump",
]

