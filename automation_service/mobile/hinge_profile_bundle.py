from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .android_accessibility import extract_accessible_strings
from .appium_http_client import AppiumHTTPClient
from .hinge_observation import (
    HingeObservationError,
    extract_interaction_targets,
    extract_package_name,
    extract_profile_snapshot,
    extract_ui_nodes,
    merge_profile_snapshots,
    sha256_bytes,
    sha256_json,
    sha256_text,
    xml_to_root,
)


class HingeProfileBundleError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProfileBundleCaptureConfig:
    enabled: bool
    max_views: int
    stop_after_unchanged: int
    swipe_duration_ms: int
    swipe_margin_pct: float
    settle_sleep_s: float
    max_nodes_per_view: int
    max_accessible_strings: int
    max_targets_per_view: int


def _as_positive_int(value: Any, *, field: str, context: str) -> int:
    try:
        parsed = int(value)
    except Exception as e:
        raise HingeProfileBundleError(f"{context}: '{field}' must be an integer") from e
    if parsed <= 0:
        raise HingeProfileBundleError(f"{context}: '{field}' must be > 0")
    return parsed


def _as_non_negative_float(value: Any, *, field: str, context: str) -> float:
    try:
        parsed = float(value)
    except Exception as e:
        raise HingeProfileBundleError(f"{context}: '{field}' must be numeric") from e
    if parsed < 0:
        raise HingeProfileBundleError(f"{context}: '{field}' must be >= 0")
    return parsed


def parse_profile_bundle_capture_config(raw: Any, *, context: str) -> ProfileBundleCaptureConfig:
    if raw is None:
        # Explicit by default: full profile capture is expensive and can change UI scroll state.
        raw = {}
    if not isinstance(raw, dict):
        raise HingeProfileBundleError(f"{context}: profile_bundle_capture must be an object when provided")

    enabled = bool(raw.get("enabled", False))
    max_views = _as_positive_int(raw.get("max_views", 6), field="max_views", context=f"{context}: profile_bundle_capture")
    stop_after_unchanged = _as_positive_int(
        raw.get("stop_after_unchanged", 2),
        field="stop_after_unchanged",
        context=f"{context}: profile_bundle_capture",
    )
    swipe_duration_ms = _as_positive_int(
        raw.get("swipe_duration_ms", 650),
        field="swipe_duration_ms",
        context=f"{context}: profile_bundle_capture",
    )
    swipe_margin_pct = _as_non_negative_float(
        raw.get("swipe_margin_pct", 0.12),
        field="swipe_margin_pct",
        context=f"{context}: profile_bundle_capture",
    )
    if swipe_margin_pct >= 0.45:
        raise HingeProfileBundleError(
            f"{context}: profile_bundle_capture.swipe_margin_pct must be < 0.45 (got {swipe_margin_pct})"
        )
    settle_sleep_s = _as_non_negative_float(
        raw.get("settle_sleep_s", 0.35),
        field="settle_sleep_s",
        context=f"{context}: profile_bundle_capture",
    )
    max_nodes_per_view = _as_positive_int(
        raw.get("max_nodes_per_view", 3500),
        field="max_nodes_per_view",
        context=f"{context}: profile_bundle_capture",
    )
    max_accessible_strings = _as_positive_int(
        raw.get("max_accessible_strings", 2500),
        field="max_accessible_strings",
        context=f"{context}: profile_bundle_capture",
    )
    max_targets_per_view = _as_positive_int(
        raw.get("max_targets_per_view", 160),
        field="max_targets_per_view",
        context=f"{context}: profile_bundle_capture",
    )

    return ProfileBundleCaptureConfig(
        enabled=enabled,
        max_views=max_views,
        stop_after_unchanged=stop_after_unchanged,
        swipe_duration_ms=swipe_duration_ms,
        swipe_margin_pct=swipe_margin_pct,
        settle_sleep_s=settle_sleep_s,
        max_nodes_per_view=max_nodes_per_view,
        max_accessible_strings=max_accessible_strings,
        max_targets_per_view=max_targets_per_view,
    )


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now().isoformat()


def _swipe_up(
    client: AppiumHTTPClient,
    *,
    window_rect: dict[str, int],
    margin_pct: float,
    duration_ms: int,
) -> None:
    x_mid = int(window_rect["width"] / 2)
    y1 = int(window_rect["height"] * (1.0 - margin_pct))
    y2 = int(window_rect["height"] * margin_pct)
    client.swipe(x1=x_mid, y1=y1, x2=x_mid, y2=y2, duration_ms=duration_ms)


def _swipe_down(
    client: AppiumHTTPClient,
    *,
    window_rect: dict[str, int],
    margin_pct: float,
    duration_ms: int,
) -> None:
    x_mid = int(window_rect["width"] / 2)
    y1 = int(window_rect["height"] * margin_pct)
    y2 = int(window_rect["height"] * (1.0 - margin_pct))
    client.swipe(x1=x_mid, y1=y1, x2=x_mid, y2=y2, duration_ms=duration_ms)


def capture_profile_bundle(
    client: AppiumHTTPClient,
    *,
    output_dir: Path,
    expected_package: Optional[str],
    screen_type: str,
    cfg: ProfileBundleCaptureConfig,
) -> dict[str, Any]:
    """
    Capture a scroll-swept multi-viewport profile bundle intended to represent a full Discover profile.

    This is a best-effort technique: it captures the *UI representation* of a profile, not Hinge's internal
    model. The contract is designed so downstream pipelines can reconstruct context via screenshots/XML,
    and action selection can target specific Like affordances.
    """
    if not cfg.enabled:
        raise HingeProfileBundleError("capture_profile_bundle called but cfg.enabled is false")

    _ensure_dir(output_dir)
    window_rect = client.get_window_rect()

    views: list[dict[str, Any]] = []
    profile_snaps: list[dict[str, Any]] = []
    all_targets: list[dict[str, Any]] = []

    unchanged = 0
    prev_xml_sha = None
    swipes_executed = 0

    for view_index in range(cfg.max_views):
        xml = client.get_page_source()
        xml_sha = sha256_text(xml)
        root = xml_to_root(xml)
        package_name = extract_package_name(root)
        strings = extract_accessible_strings(xml, limit=cfg.max_accessible_strings)
        nodes = extract_ui_nodes(root=root, max_nodes=cfg.max_nodes_per_view)
        targets = extract_interaction_targets(nodes=nodes, view_index=view_index, max_targets=cfg.max_targets_per_view)
        snap = extract_profile_snapshot(strings=strings, nodes=nodes, screen_type=screen_type)

        screenshot_bytes = client.get_screenshot_png_bytes()
        screenshot_sha = sha256_bytes(screenshot_bytes)
        screenshot_relpath = f"view_{view_index:02d}.png"
        xml_relpath = f"view_{view_index:02d}.xml"
        screenshot_path = output_dir / screenshot_relpath
        xml_path = output_dir / xml_relpath
        screenshot_path.write_bytes(screenshot_bytes)
        xml_path.write_text(xml, encoding="utf-8")

        view = {
            "view_index": view_index,
            "ts": _now_iso(),
            "package_name": package_name,
            "screen_type": screen_type,
            "xml_sha256": xml_sha,
            "screenshot_sha256": screenshot_sha,
            "screenshot_relpath": screenshot_relpath,
            "xml_relpath": xml_relpath,
            "screenshot_path": str(screenshot_path.resolve()),
            "xml_path": str(xml_path.resolve()),
            "accessible_strings": strings,
            "profile_snapshot": snap,
            "interaction_targets": targets,
        }
        views.append(view)
        profile_snaps.append(snap)
        all_targets.extend(targets)

        if expected_package and package_name and package_name != expected_package:
            # Still store the bundle, but flag that capture drifted out-of-app. This is useful for QA.
            # Do not try to recover here; let the live agent handle foreground recovery consistently.
            break

        if prev_xml_sha is not None and xml_sha == prev_xml_sha:
            unchanged += 1
        else:
            unchanged = 0
        prev_xml_sha = xml_sha

        if unchanged >= cfg.stop_after_unchanged:
            break
        if view_index == cfg.max_views - 1:
            break

        _swipe_up(
            client,
            window_rect=window_rect,
            margin_pct=cfg.swipe_margin_pct,
            duration_ms=cfg.swipe_duration_ms,
        )
        swipes_executed += 1
        if cfg.settle_sleep_s > 0:
            time.sleep(cfg.settle_sleep_s)

    # Return to the starting scroll position so downstream actions don't depend on capture side effects.
    for _ in range(swipes_executed):
        _swipe_down(
            client,
            window_rect=window_rect,
            margin_pct=cfg.swipe_margin_pct,
            duration_ms=cfg.swipe_duration_ms,
        )
        if cfg.settle_sleep_s > 0:
            time.sleep(cfg.settle_sleep_s)

    profile_summary = merge_profile_snapshots(profile_snaps)
    profile_fingerprint = sha256_json(profile_summary)

    # Target subset the decision engine will care about most.
    like_candidates = [
        {
            "target_id": t.get("target_id"),
            "label": t.get("label"),
            "view_index": t.get("view_index"),
            "context_text": t.get("context_text") if isinstance(t.get("context_text"), list) else [],
            "tap": t.get("tap"),
        }
        for t in all_targets
        if t.get("kind") == "like_button"
    ]

    bundle = {
        "contract_version": "hinge_profile_bundle.v1",
        "captured_at": _now_iso(),
        "screen_type": screen_type,
        "expected_package": expected_package,
        "bundle_dir": str(output_dir.resolve()),
        "window_rect": window_rect,
        "capture_cfg": {
            "max_views": cfg.max_views,
            "stop_after_unchanged": cfg.stop_after_unchanged,
            "swipe_duration_ms": cfg.swipe_duration_ms,
            "swipe_margin_pct": cfg.swipe_margin_pct,
            "settle_sleep_s": cfg.settle_sleep_s,
            "max_nodes_per_view": cfg.max_nodes_per_view,
            "max_accessible_strings": cfg.max_accessible_strings,
            "max_targets_per_view": cfg.max_targets_per_view,
        },
        "swipes_executed": swipes_executed,
        "profile_fingerprint": profile_fingerprint,
        "profile_summary": profile_summary,
        "like_candidates": like_candidates[:40],
        "views": views,
    }

    bundle_path = output_dir / "profile_bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
    bundle["bundle_path"] = str(bundle_path.resolve())

    return bundle
