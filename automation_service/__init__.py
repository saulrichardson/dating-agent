"""
Automation service for dating app UI automation.
"""

from __future__ import annotations

from typing import Any

__all__ = ["save_auth_state", "test_chat_flow", "extract_chat_history"]


def __getattr__(name: str) -> Any:
    """
    Lazy exports.

    We intentionally avoid importing Playwright at package import time so that
    consumers can use `automation_service.mobile.*` without needing the
    Playwright dependency installed.
    """
    if name in __all__:
        from . import browser  # local import to avoid import-time playwright dependency

        return getattr(browser, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
