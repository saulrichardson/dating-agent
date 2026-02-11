from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .android_accessibility import extract_accessible_strings
from .appium_http_client import AppiumHTTPClient
from .config import load_json_file, require_key


class VerticalSliceError(RuntimeError):
    pass


@dataclass(frozen=True)
class LocatorCandidate:
    using: str
    value: str
    purpose: str


@dataclass(frozen=True)
class VerticalSliceResult:
    app: str
    session_id: str
    report_path: Path
    initial_screenshot_path: Path
    initial_source_path: Path
    post_inbox_screenshot_path: Path
    post_inbox_source_path: Path
    matched_inbox_locator: Optional[LocatorCandidate]
    keyword_hits: list[str]


_APP_KEYWORDS: dict[str, list[str]] = {
    "hinge": [
        "message",
        "messages",
        "match",
        "matches",
        "likes",
        "send",
        "chat",
    ],
    "tinder": [
        "message",
        "messages",
        "match",
        "matches",
        "likes",
        "send",
        "chat",
    ],
}


_INBOX_LOCATORS: dict[str, list[LocatorCandidate]] = {
    "hinge": [
        LocatorCandidate(
            using="accessibility id",
            value="Messages",
            purpose="Messages tab by accessibility id",
        ),
        LocatorCandidate(
            using="-android uiautomator",
            value='new UiSelector().textContains("Matches")',
            purpose="Matches tab by visible text",
        ),
        LocatorCandidate(
            using="-android uiautomator",
            value='new UiSelector().descriptionContains("Matches")',
            purpose="Matches tab by content-desc",
        ),
        LocatorCandidate(
            using="-android uiautomator",
            value='new UiSelector().textContains("Messages")',
            purpose="Messages tab by visible text",
        ),
        LocatorCandidate(
            using="-android uiautomator",
            value='new UiSelector().textContains("Chats")',
            purpose="Chats tab by visible text",
        ),
        LocatorCandidate(
            using="-android uiautomator",
            value='new UiSelector().descriptionContains("Messages")',
            purpose="Messages tab by content-desc",
        ),
    ],
    "tinder": [
        LocatorCandidate(
            using="accessibility id",
            value="Messages",
            purpose="Messages tab by accessibility id",
        ),
        LocatorCandidate(
            using="-android uiautomator",
            value='new UiSelector().textContains("Messages")',
            purpose="Messages tab by visible text",
        ),
        LocatorCandidate(
            using="-android uiautomator",
            value='new UiSelector().textContains("Matches")',
            purpose="Matches tab by visible text",
        ),
        LocatorCandidate(
            using="-android uiautomator",
            value='new UiSelector().descriptionContains("Messages")',
            purpose="Messages tab by content-desc",
        ),
    ],
}


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _artifact_path(*, artifacts_dir: Path, stem: str, ext: str) -> Path:
    safe_stem = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in stem.strip())
    if not safe_stem:
        safe_stem = "artifact"
    filename = f"{safe_stem}_{_timestamp()}.{ext.lstrip('.')}"
    return artifacts_dir / filename


def _as_non_empty_str(value: Any, *, field: str, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VerticalSliceError(f"{context}: '{field}' must be a non-empty string")
    return value.strip()


def _capture(
    *,
    client: AppiumHTTPClient,
    artifacts_dir: Path,
    stem: str,
) -> tuple[Path, Path, str]:
    screenshot_path = _artifact_path(artifacts_dir=artifacts_dir, stem=f"{stem}_screenshot", ext="png")
    source_path = _artifact_path(artifacts_dir=artifacts_dir, stem=f"{stem}_source", ext="xml")
    screenshot_path.write_bytes(client.get_screenshot_png_bytes())
    xml = client.get_page_source()
    source_path.write_text(xml, encoding="utf-8")
    return screenshot_path, source_path, xml


def _click_first_inbox_candidate(
    *,
    client: AppiumHTTPClient,
    candidates: list[LocatorCandidate],
) -> Optional[LocatorCandidate]:
    for candidate in candidates:
        elements = client.find_elements(using=candidate.using, value=candidate.value)
        if not elements:
            continue
        client.click(elements[0])
        return candidate
    return None


def _keyword_hits(*, strings: list[str], keywords: list[str], max_hits: int) -> list[str]:
    out: list[str] = []
    lowered_keywords = [k.lower() for k in keywords]
    for s in strings:
        lowered = s.lower()
        if any(k in lowered for k in lowered_keywords):
            out.append(s)
        if len(out) >= max_hits:
            break
    return out


def run_vertical_inbox_probe(
    *,
    config_json_path: str,
) -> VerticalSliceResult:
    """
    Run an app-specific inbox probe for Hinge or Tinder.

    This intentionally does not send messages. It focuses on proving:
    - can we find and open inbox-like navigation affordances for a target app?
    - do we get useful accessible strings after landing there?

    Config schema (fail-fast):
      {
        "appium_server_url": "http://127.0.0.1:4723",
        "capabilities_json_path": "automation_service/mobile_examples/android_capabilities.example.json",
        "app": "hinge",
        "artifacts_dir": "artifacts",
        "pause_before_start": true,
        "post_click_sleep_s": 1.0,
        "max_keyword_hits": 50
      }
    """
    config = load_json_file(config_json_path)
    appium_server_url = _as_non_empty_str(
        require_key(config, "appium_server_url", context=config_json_path),
        field="appium_server_url",
        context=config_json_path,
    )
    capabilities_json_path = _as_non_empty_str(
        require_key(config, "capabilities_json_path", context=config_json_path),
        field="capabilities_json_path",
        context=config_json_path,
    )
    app = _as_non_empty_str(require_key(config, "app", context=config_json_path), field="app", context=config_json_path).lower()
    if app not in {"hinge", "tinder"}:
        raise VerticalSliceError(f"{config_json_path}: app must be 'hinge' or 'tinder'")

    pause_before_start = bool(config.get("pause_before_start") or False)
    post_click_sleep_s = float(config.get("post_click_sleep_s", 1.0))
    if post_click_sleep_s < 0:
        raise VerticalSliceError(f"{config_json_path}: post_click_sleep_s must be >= 0")
    max_keyword_hits = int(config.get("max_keyword_hits", 50))
    if max_keyword_hits <= 0:
        raise VerticalSliceError(f"{config_json_path}: max_keyword_hits must be > 0")

    artifacts_dir = Path(str(config.get("artifacts_dir") or "artifacts")).resolve()
    _ensure_dir(artifacts_dir)

    capabilities_payload = load_json_file(capabilities_json_path)
    require_key(capabilities_payload, "capabilities", context=capabilities_json_path)

    client = AppiumHTTPClient(appium_server_url)
    session_id = client.create_session(capabilities_payload)
    try:
        print("\n=== Vertical Inbox Probe ===")
        print(f"Config: {Path(config_json_path).resolve()}")
        print(f"App: {app}")
        print(f"Session started: {session_id}")
        if pause_before_start:
            input(
                "Session started. Navigate/login in the emulator and open the target app, "
                "then press Enter to continue..."
            )

        initial_screenshot_path, initial_source_path, initial_xml = _capture(
            client=client,
            artifacts_dir=artifacts_dir,
            stem=f"{app}_before_inbox_probe",
        )

        matched_inbox_locator = _click_first_inbox_candidate(
            client=client,
            candidates=_INBOX_LOCATORS[app],
        )

        if post_click_sleep_s > 0:
            import time

            time.sleep(post_click_sleep_s)

        post_inbox_screenshot_path, post_inbox_source_path, post_xml = _capture(
            client=client,
            artifacts_dir=artifacts_dir,
            stem=f"{app}_after_inbox_probe",
        )

        before_strings = extract_accessible_strings(initial_xml, limit=5000)
        after_strings = extract_accessible_strings(post_xml, limit=5000)
        keywords = _APP_KEYWORDS[app]
        keyword_hits_before = _keyword_hits(strings=before_strings, keywords=keywords, max_hits=max_keyword_hits)
        keyword_hits_after = _keyword_hits(strings=after_strings, keywords=keywords, max_hits=max_keyword_hits)

        report = {
            "app": app,
            "session_id": session_id,
            "matched_inbox_locator": None
            if matched_inbox_locator is None
            else {
                "using": matched_inbox_locator.using,
                "value": matched_inbox_locator.value,
                "purpose": matched_inbox_locator.purpose,
            },
            "artifacts": {
                "initial_screenshot_path": str(initial_screenshot_path),
                "initial_source_path": str(initial_source_path),
                "post_inbox_screenshot_path": str(post_inbox_screenshot_path),
                "post_inbox_source_path": str(post_inbox_source_path),
            },
            "keyword_hits_before": keyword_hits_before,
            "keyword_hits_after": keyword_hits_after,
            "all_candidate_locators": [
                {
                    "using": c.using,
                    "value": c.value,
                    "purpose": c.purpose,
                }
                for c in _INBOX_LOCATORS[app]
            ],
        }

        report_path = _artifact_path(artifacts_dir=artifacts_dir, stem=f"{app}_vertical_probe_report", ext="json")
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote probe report: {report_path}")

        return VerticalSliceResult(
            app=app,
            session_id=session_id,
            report_path=report_path,
            initial_screenshot_path=initial_screenshot_path,
            initial_source_path=initial_source_path,
            post_inbox_screenshot_path=post_inbox_screenshot_path,
            post_inbox_source_path=post_inbox_source_path,
            matched_inbox_locator=matched_inbox_locator,
            keyword_hits=keyword_hits_after,
        )
    finally:
        client.delete_session()
