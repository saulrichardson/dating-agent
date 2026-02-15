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
    sha256_bytes,
    sha256_text,
    xml_to_root,
)
from .hinge_profile_bundle import (
    HingeProfileBundleError,
    ProfileBundleCaptureConfig,
    capture_profile_bundle,
)
from . import live_hinge_agent as lha


class HingeProfilePackageError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProfilePackageCaptureConfig:
    # Base scroll-sweep capture (screenshots + XML + interaction targets).
    base_bundle: ProfileBundleCaptureConfig

    # Probes attempt to open secondary surfaces without executing irreversible actions.
    probe_more_menu: bool
    probe_comment_composer: bool
    probe_primary_surface: bool

    # Sleep after taps to allow animations to settle.
    settle_sleep_s: float


def _now_iso() -> str:
    return datetime.now().isoformat()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _safe_write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _capture_surface(
    client: AppiumHTTPClient,
    *,
    output_dir: Path,
    surface_id: str,
    view_index: int = 0,
    max_nodes: int = 4500,
    max_accessible_strings: int = 2500,
    max_targets: int = 260,
) -> dict[str, Any]:
    _ensure_dir(output_dir)
    xml = client.get_page_source()
    xml_sha = sha256_text(xml)
    root = xml_to_root(xml)
    package_name = extract_package_name(root)
    strings = extract_accessible_strings(xml, limit=max_accessible_strings)
    screen_type = lha._classify_hinge_screen(strings)
    nodes = extract_ui_nodes(root=root, max_nodes=max_nodes)
    targets = extract_interaction_targets(nodes=nodes, view_index=view_index, max_targets=max_targets)
    profile_snap = extract_profile_snapshot(strings=strings, nodes=nodes, screen_type=screen_type)

    screenshot_bytes = client.get_screenshot_png_bytes()
    screenshot_sha = sha256_bytes(screenshot_bytes)
    screenshot_path = output_dir / "surface.png"
    xml_path = output_dir / "surface.xml"
    screenshot_path.write_bytes(screenshot_bytes)
    xml_path.write_text(xml, encoding="utf-8")

    surface = {
        "surface_id": surface_id,
        "captured_at": _now_iso(),
        "package_name": package_name,
        "screen_type": screen_type,
        "xml_sha256": xml_sha,
        "screenshot_sha256": screenshot_sha,
        "screenshot_path": str(screenshot_path.resolve()),
        "xml_path": str(xml_path.resolve()),
        "accessible_strings": strings,
        "profile_snapshot": profile_snap,
        "interaction_targets": targets,
    }
    _safe_write_json(output_dir / "surface.json", surface)
    return surface


def _wait_for_accessible_strings(
    client: AppiumHTTPClient,
    *,
    needles: list[str],
    timeout_s: float,
    poll_s: float = 0.2,
    max_strings: int = 1200,
) -> tuple[bool, list[str]]:
    """
    Poll page source until any string in `needles` appears in extracted accessibility strings.
    """
    deadline = time.time() + float(timeout_s)
    needles_norm = [n.lower().strip() for n in needles if n and n.strip()]
    last_strings: list[str] = []
    while time.time() < deadline:
        xml = client.get_page_source()
        strings = extract_accessible_strings(xml, limit=max_strings)
        last_strings = strings
        lowered = [s.lower() for s in strings]
        for n in needles_norm:
            if any(n in s for s in lowered):
                return True, strings
        time.sleep(float(poll_s))
    return False, last_strings


def _pick_first_target(
    targets: list[dict[str, Any]],
    *,
    kind: str,
    label_exact: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    for t in targets:
        if not isinstance(t, dict):
            continue
        if str(t.get("kind") or "") != kind:
            continue
        if label_exact is not None and str(t.get("label") or "") != label_exact:
            continue
        return t
    return None


def _tap_target_or_raise(client: AppiumHTTPClient, *, target: dict[str, Any], context: str) -> None:
    tap = target.get("tap")
    if not isinstance(tap, dict) or ("x" not in tap) or ("y" not in tap):
        raise HingeProfilePackageError(f"{context}: target missing tap coordinates: {target}")
    client.tap(x=int(tap["x"]), y=int(tap["y"]))


def _build_action_space(*, surfaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Convert captured surfaces + interaction targets into an explicit "action space" contract.

    This is intentionally conservative: it lists actions we can *prove* are represented in the
    captured UI model. More actions can be added as we capture additional surfaces (menus, viewers, etc).
    """
    actions: list[dict[str, Any]] = []

    # Helper: union target_ids by kind across surfaces
    by_kind: dict[str, list[str]] = {}
    for s in surfaces:
        for t in (s.get("interaction_targets") or []):
            if not isinstance(t, dict):
                continue
            kind = str(t.get("kind") or "")
            tid = str(t.get("target_id") or "")
            if not kind or not tid:
                continue
            by_kind.setdefault(kind, [])
            if tid not in by_kind[kind]:
                by_kind[kind].append(tid)

    # Profile-scoped, always-possible action.
    actions.append(
        {
            "action_id": "scroll",
            "human_equivalent": "Swipe vertically",
            "description": "Scroll within the current profile surface to reveal additional content.",
            "requires": [],
        }
    )

    if by_kind.get("pass_button"):
        actions.append(
            {
                "action_id": "pass",
                "human_equivalent": "Tap Skip/Pass",
                "description": "Skip the current profile/card.",
                "requires": [],
                "target_kinds": ["pass_button"],
            }
        )

    if by_kind.get("like_button"):
        actions.append(
            {
                "action_id": "like",
                "human_equivalent": "Tap Like on a specific prompt/photo",
                "description": "Like a specific item on the profile. Requires selecting which Like target to use.",
                "requires": ["target_id"],
                "target_kinds": ["like_button"],
            }
        )

    if by_kind.get("comment_input") and by_kind.get("send_like"):
        actions.append(
            {
                "action_id": "comment_like",
                "human_equivalent": "Type comment and tap Send like",
                "description": "Send a Like with a comment from the composer surface.",
                "requires": ["message_text"],
                "target_kinds": ["comment_input", "send_like"],
                "dangerous": True,
            }
        )

    if by_kind.get("send_like"):
        actions.append(
            {
                "action_id": "send_like",
                "human_equivalent": "Tap Send like",
                "description": "Finalize sending a Like from the composer surface.",
                "requires": [],
                "target_kinds": ["send_like"],
                "dangerous": True,
            }
        )

    if by_kind.get("send_rose"):
        actions.append(
            {
                "action_id": "send_rose",
                "human_equivalent": "Tap Send a Rose",
                "description": "Send a Rose from the composer surface (if present).",
                "requires": [],
                "target_kinds": ["send_rose"],
                "dangerous": True,
            }
        )

    if by_kind.get("more_menu"):
        actions.append(
            {
                "action_id": "open_more_menu",
                "human_equivalent": "Tap More",
                "description": "Open the 'More' menu for additional actions (report/block/share/etc.).",
                "requires": [],
                "target_kinds": ["more_menu"],
            }
        )

    if by_kind.get("undo"):
        actions.append(
            {
                "action_id": "undo",
                "human_equivalent": "Tap Undo",
                "description": "Undo the previous pass rating (if present).",
                "requires": [],
                "target_kinds": ["undo"],
            }
        )

    if by_kind.get("media_unmute"):
        actions.append(
            {
                "action_id": "unmute_media",
                "human_equivalent": "Tap Unmute",
                "description": "Unmute a video prompt (if present).",
                "requires": [],
                "target_kinds": ["media_unmute"],
            }
        )

    if by_kind.get("primary_surface"):
        actions.append(
            {
                "action_id": "tap_primary_surface",
                "human_equivalent": "Tap the main photo/video surface",
                "description": "Open the main media viewer surface (best-effort; UI-dependent).",
                "requires": ["target_id"],
                "target_kinds": ["primary_surface"],
            }
        )

    return actions


def capture_profile_package(
    client: AppiumHTTPClient,
    *,
    output_dir: Path,
    expected_package: Optional[str],
    cfg: ProfilePackageCaptureConfig,
) -> dict[str, Any]:
    """
    Capture a *single profile* as a structured on-disk package:

    - Base scroll-sweep bundle (multi-viewport screenshots + XML + interaction targets)
    - Optional probe surfaces (More menu, comment composer, primary media viewer)
    - Explicit action_space derived from captured interaction targets
    """
    _ensure_dir(output_dir)

    # Baseline classification from a single snapshot (used only for sanity + metadata).
    xml0 = client.get_page_source()
    strings0 = extract_accessible_strings(xml0, limit=1200)
    screen_type0 = lha._classify_hinge_screen(strings0)
    if screen_type0 != "hinge_discover_card":
        raise HingeProfilePackageError(
            f"capture_profile_package currently supports hinge_discover_card only (got {screen_type0!r})"
        )

    surfaces: list[dict[str, Any]] = []
    probe_errors: list[str] = []

    base_dir = output_dir / "base_bundle"
    try:
        base_bundle = capture_profile_bundle(
            client,
            output_dir=base_dir,
            expected_package=expected_package,
            screen_type=screen_type0,
            cfg=cfg.base_bundle,
        )
    except HingeProfileBundleError as e:
        raise HingeProfilePackageError(str(e)) from e

    surfaces.append(
        {
            "surface_id": "base_bundle",
            "type": "scroll_sweep",
            "bundle_path": base_bundle.get("bundle_path"),
            "views_captured": len(base_bundle.get("views") or []),
            "like_candidates": base_bundle.get("like_candidates") if isinstance(base_bundle.get("like_candidates"), list) else [],
            # These fields are primarily for convenience. The canonical targets live inside base_bundle.views[*].
            "interaction_targets_sample": (base_bundle.get("views") or [{}])[0].get("interaction_targets") if (base_bundle.get("views") or []) else [],
        }
    )

    # Probe: More menu (if visible in base view 0).
    if cfg.probe_more_menu:
        view0_targets = []
        try:
            views = base_bundle.get("views") or []
            if views and isinstance(views[0], dict):
                view0_targets = views[0].get("interaction_targets") or []
        except Exception:
            view0_targets = []
        more = _pick_first_target([t for t in view0_targets if isinstance(t, dict)], kind="more_menu")
        if more is not None:
            _tap_target_or_raise(client, target=more, context="probe_more_menu")
            if cfg.settle_sleep_s > 0:
                time.sleep(cfg.settle_sleep_s)
            surfaces.append(
                _capture_surface(
                    client,
                    output_dir=output_dir / "surfaces" / "more_menu",
                    surface_id="more_menu",
                )
            )
            client.press_keycode(keycode=4)
            time.sleep(0.2)
        else:
            probe_errors.append("probe_more_menu: no more_menu target found in base view 0")

    # Probe: comment composer (open by tapping a Like target, but do NOT press Send like).
    if cfg.probe_comment_composer:
        like_candidates = base_bundle.get("like_candidates")
        candidates: list[dict[str, Any]] = []
        if isinstance(like_candidates, list):
            for c in like_candidates:
                if isinstance(c, dict) and isinstance(c.get("tap"), dict):
                    candidates.append(c)

        composer_opened = False
        # Try a few candidates: some Like affordances open a composer, others can send immediately.
        for idx, chosen in enumerate(candidates[:3]):
            _tap_target_or_raise(client, target=chosen, context=f"probe_comment_composer[{idx}]")
            ok, _ = _wait_for_accessible_strings(
                client,
                needles=["send like", "edit comment", "add a comment", "send a rose"],
                timeout_s=2.0,
                poll_s=0.2,
            )
            if ok:
                surfaces.append(
                    _capture_surface(
                        client,
                        output_dir=output_dir / "surfaces" / "comment_composer",
                        surface_id="comment_composer",
                    )
                )
                composer_opened = True
                client.press_keycode(keycode=4)
                time.sleep(0.2)
                break

            # Best-effort attempt to unwind if this tap opened something transient.
            client.press_keycode(keycode=4)
            time.sleep(0.2)

        if not candidates:
            probe_errors.append("probe_comment_composer: no like_candidates found in base bundle")
        elif not composer_opened:
            probe_errors.append("probe_comment_composer: failed to open composer after probing like_candidates[0..2]")

    # Probe: primary surface (tap the large unlabeled media region if present in base view 0).
    if cfg.probe_primary_surface:
        view0_targets = []
        try:
            views = base_bundle.get("views") or []
            if views and isinstance(views[0], dict):
                view0_targets = views[0].get("interaction_targets") or []
        except Exception:
            view0_targets = []
        primary = _pick_first_target([t for t in view0_targets if isinstance(t, dict)], kind="primary_surface")
        if primary is not None:
            _tap_target_or_raise(client, target=primary, context="probe_primary_surface")
            if cfg.settle_sleep_s > 0:
                time.sleep(cfg.settle_sleep_s)
            surfaces.append(
                _capture_surface(
                    client,
                    output_dir=output_dir / "surfaces" / "primary_surface",
                    surface_id="primary_surface",
                )
            )
            client.press_keycode(keycode=4)
            time.sleep(0.2)
        else:
            probe_errors.append("probe_primary_surface: no primary_surface target found in base view 0")

    # Derive action space from captured surfaces (only what we can prove is present).
    expanded_surfaces: list[dict[str, Any]] = []
    for s in surfaces:
        # Convert base_bundle surface into a pseudo-surface with interaction_targets for action_space building.
        if s.get("surface_id") == "base_bundle":
            # Collect the union of base bundle view targets into one surface object.
            targets: list[dict[str, Any]] = []
            for v in (base_bundle.get("views") or []):
                if isinstance(v, dict):
                    for t in (v.get("interaction_targets") or []):
                        if isinstance(t, dict):
                            targets.append(t)
            expanded_surfaces.append({"surface_id": "base_bundle", "interaction_targets": targets})
        else:
            expanded_surfaces.append(s)

    action_space = _build_action_space(surfaces=expanded_surfaces)

    manifest = {
        "contract_version": "hinge_profile_package.v1",
        "captured_at": _now_iso(),
        "expected_package": expected_package,
        "screen_type": screen_type0,
        "package_dir": str(output_dir.resolve()),
        "base_bundle_path": base_bundle.get("bundle_path"),
        "profile_fingerprint": base_bundle.get("profile_fingerprint"),
        "surfaces": surfaces,
        "probe_errors": probe_errors,
        "action_space": action_space,
        "notes": [
            "This package stores UI evidence (screenshots + UIAutomator XML) and an interaction map.",
            "It does not claim to reconstruct Hinge's internal profile model.",
            "Probe surfaces intentionally avoid irreversible actions (no Send like / Send rose taps).",
        ],
    }

    _safe_write_json(output_dir / "profile_package.json", manifest)
    return manifest
