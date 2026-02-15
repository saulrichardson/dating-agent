from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import time
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .android_accessibility import extract_accessible_strings
from .appium_http_client import AppiumHTTPClient, WebDriverElementRef
from .config import load_json_file, require_key
from . import live_hinge_agent as lha
from .hinge_observation import (
    extract_interaction_targets,
    extract_profile_snapshot,
    extract_ui_nodes,
    sha256_json,
    xml_to_root,
)
from .hinge_profile_bundle import (
    HingeProfileBundleError,
    ProfileBundleCaptureConfig,
    capture_profile_bundle as capture_profile_bundle_artifact,
    parse_profile_bundle_capture_config,
)


@dataclass
class _ManagedSession:
    name: str
    config_json_path: str
    client: AppiumHTTPClient
    session_id: str
    profile: lha.HingeAgentProfile
    decision_engine: lha.DecisionEngineConfig
    locator_map: dict[str, list[lha.Locator]]
    state: lha._RuntimeState
    default_dry_run: bool
    default_command_query: Optional[str]
    artifacts_dir: Path
    profile_bundle_capture_cfg: ProfileBundleCaptureConfig


_SESSIONS: dict[str, _ManagedSession] = {}

_ACTION_TO_LOCATOR_KEY: dict[str, str] = {
    "goto_discover": "discover_tab",
    "goto_matches": "matches_tab",
    "goto_likes_you": "likes_you_tab",
    "goto_standouts": "standouts_tab",
    "goto_profile_hub": "profile_hub_tab",
    "like": "like",
    "pass": "pass",
    "open_thread": "open_thread",
    "dismiss_overlay": "overlay_close",
}

mcp = FastMCP(
    "hinge-agent-control",
    instructions=(
        "Control a live Hinge Appium session with free-form and deterministic tools. "
        "Use start_session first, then observe/decide/execute/step, then stop_session."
    ),
)


def _now() -> str:
    return datetime.now().isoformat()


def _must_get_session(session_name: str) -> _ManagedSession:
    session = _SESSIONS.get(session_name)
    if session is None:
        raise RuntimeError(f"Session {session_name!r} not found. Call start_session first.")
    return session


def _snapshot_artifact_path(*, artifacts_dir: Path, stem: str, ext: str) -> Path:
    safe_stem = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in stem.strip())
    if not safe_stem:
        safe_stem = "artifact"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return artifacts_dir / "mcp_snapshots" / f"{safe_stem}_{ts}.{ext.lstrip('.')}"


def _find_element_or_raise(
    session: _ManagedSession,
    *,
    using: str,
    value: str,
    index: int,
) -> WebDriverElementRef:
    if not isinstance(using, str) or not using.strip():
        raise RuntimeError("'using' must be a non-empty string")
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("'value' must be a non-empty string")
    if not isinstance(index, int) or index < 0:
        raise RuntimeError("'index' must be an integer >= 0")

    elements = session.client.find_elements(using=using.strip(), value=value.strip())
    if not elements:
        raise RuntimeError(f"No elements found for locator using={using!r} value={value!r}")
    if index >= len(elements):
        raise RuntimeError(
            f"Element index out of range: index={index}, available={len(elements)} "
            f"for locator using={using!r} value={value!r}"
        )
    return elements[index]


def _parse_locator_map(config: dict[str, Any], *, context: str) -> dict[str, list[lha.Locator]]:
    locators_raw = require_key(config, "locators", context=context)
    if not isinstance(locators_raw, dict):
        raise RuntimeError(f"{context}: 'locators' must be an object")
    return {
        "discover_tab": lha._parse_locators(
            locators_raw.get("discover_tab"), field="discover_tab", context=context, required=True
        ),
        "matches_tab": lha._parse_locators(
            locators_raw.get("matches_tab"), field="matches_tab", context=context, required=True
        ),
        "likes_you_tab": lha._parse_locators(
            locators_raw.get("likes_you_tab"), field="likes_you_tab", context=context, required=False
        ),
        "standouts_tab": lha._parse_locators(
            locators_raw.get("standouts_tab"), field="standouts_tab", context=context, required=False
        ),
        "profile_hub_tab": lha._parse_locators(
            locators_raw.get("profile_hub_tab"), field="profile_hub_tab", context=context, required=False
        ),
        "like": lha._parse_locators(locators_raw.get("like"), field="like", context=context, required=True),
        "pass": lha._parse_locators(locators_raw.get("pass"), field="pass", context=context, required=True),
        "open_thread": lha._parse_locators(
            locators_raw.get("open_thread"), field="open_thread", context=context, required=True
        ),
        "message_input": lha._parse_locators(
            locators_raw.get("message_input"), field="message_input", context=context, required=True
        ),
        "send": lha._parse_locators(locators_raw.get("send"), field="send", context=context, required=True),
        "overlay_close": lha._parse_locators(
            locators_raw.get("overlay_close"),
            field="overlay_close",
            context=context,
            required=False,
        ),
        "discover_message_input": lha._parse_locators(
            locators_raw.get("discover_message_input"),
            field="discover_message_input",
            context=context,
            required=False,
        ),
        "discover_send": lha._parse_locators(
            locators_raw.get("discover_send"),
            field="discover_send",
            context=context,
            required=False,
        ),
    }


def _capture_packet(
    session: _ManagedSession,
    *,
    include_screenshot: bool,
    persist_snapshot_artifacts: bool,
) -> tuple[dict[str, Any], Optional[bytes], Optional[Path], Optional[Path]]:
    xml = session.client.get_page_source()
    package_name = lha._extract_package_name(xml)
    strings = extract_accessible_strings(xml, limit=2500)
    screen_type = lha._classify_hinge_screen(strings)
    quality_features = lha._extract_quality_features(strings)
    score = lha._score_quality(screen_type=screen_type, quality_features=quality_features)

    profile_fingerprint: Optional[str] = None
    profile_summary: Optional[dict[str, Any]] = None
    like_candidates: list[dict[str, Any]] = []
    interaction_extraction_error: Optional[str] = None
    try:
        root = xml_to_root(xml)
        nodes = extract_ui_nodes(root=root, max_nodes=2500)
        profile_summary = extract_profile_snapshot(strings=strings, nodes=nodes, screen_type=screen_type)
        if int(profile_summary.get("signal_strength") or 0) > 0:
            profile_fingerprint = sha256_json(profile_summary)
        targets = extract_interaction_targets(nodes=nodes, view_index=0, max_targets=120)
        like_candidates = [
            {
                "target_id": t.get("target_id"),
                "label": t.get("label"),
                "view_index": t.get("view_index"),
                "context_text": t.get("context_text") if isinstance(t.get("context_text"), list) else [],
                "tap": t.get("tap"),
            }
            for t in targets
            if t.get("kind") == "like_button"
        ][:12]
    except Exception as e:
        # Preserve the error so callers know the extraction is incomplete.
        interaction_extraction_error = str(e)
        profile_fingerprint = None
        profile_summary = None
        like_candidates = []

    screenshot_bytes: Optional[bytes] = None
    screenshot_path: Optional[Path] = None
    xml_path: Optional[Path] = None
    snapshot_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")

    if include_screenshot:
        screenshot_bytes = session.client.get_screenshot_png_bytes()
        if persist_snapshot_artifacts:
            snapshot_dir = session.artifacts_dir / "mcp_snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            screenshot_path = snapshot_dir / f"mcp_snapshot_{snapshot_id}.png"
            screenshot_path.write_bytes(screenshot_bytes)

    if persist_snapshot_artifacts:
        snapshot_dir = session.artifacts_dir / "mcp_snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        xml_path = snapshot_dir / f"mcp_snapshot_{snapshot_id}.xml"
        xml_path.write_text(xml, encoding="utf-8")

    available_actions = lha._build_available_actions(
        screen_type=screen_type,
        client=session.client,
        locators=session.locator_map,
        message_enabled=session.profile.message_policy.enabled,
    )

    packet = {
        "ts": _now(),
        "package_name": package_name,
        "screen_type": screen_type,
        "quality_score_v1": score,
        "quality_features": quality_features,
        "profile_fingerprint": profile_fingerprint,
        "profile_summary": profile_summary,
        "like_candidates": like_candidates,
        "profile_bundle_path": None,
        "interaction_extraction_error": interaction_extraction_error,
        "available_actions": available_actions,
        "observed_strings": strings[:120],
        "limits": {
            "likes_remaining": max(session.profile.swipe_policy.max_likes - session.state.likes, 0),
            "passes_remaining": max(session.profile.swipe_policy.max_passes - session.state.passes, 0),
            "messages_remaining": max(session.profile.message_policy.max_messages - session.state.messages, 0),
        },
        "screenshot_path": None if screenshot_path is None else str(screenshot_path),
        "xml_path": None if xml_path is None else str(xml_path),
    }
    return packet, screenshot_bytes, screenshot_path, xml_path


def _execute_action(
    session: _ManagedSession,
    *,
    action: str,
    message_text: Optional[str],
    dry_run: bool,
    screen_type: str,
    quality_features: dict[str, Any],
    target_id: Optional[str],
    like_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    def _pick_like_candidate() -> Optional[dict[str, Any]]:
        candidates = [x for x in like_candidates if isinstance(x, dict)]
        if not candidates:
            return None
        if target_id:
            for c in candidates:
                if str(c.get("target_id") or "") == target_id:
                    return c
            return None
        for c in candidates:
            if "prompt" in str(c.get("label") or "").lower():
                return c
        return candidates[0]

    if action == "wait":
        session.state.last_action = "wait"
        return {"executed": "wait", "dry_run": dry_run}

    if action == "back":
        if not dry_run:
            session.client.press_keycode(keycode=4)
        session.state.last_action = "back"
        return {"executed": "back", "dry_run": dry_run}

    if action == "send_message":
        if session.state.messages >= session.profile.message_policy.max_messages:
            raise RuntimeError("message limit reached")
        # On Discover, sending a message is a "comment + like" and must count against like quotas.
        if screen_type == "hinge_discover_card" and session.state.likes >= session.profile.swipe_policy.max_likes:
            raise RuntimeError("like limit reached (discover send_message)")
        outbound = lha._normalize_message_text(
            raw_text=message_text,
            profile=session.profile,
            quality_features=quality_features,
        )
        if not dry_run:
            if screen_type == "hinge_discover_card":
                discover_input_locators = session.locator_map.get("discover_message_input") or session.locator_map["message_input"]
                discover_send_locators = session.locator_map.get("discover_send") or session.locator_map["send"]
                chosen = _pick_like_candidate()
                if target_id and chosen is None:
                    raise RuntimeError(f"Unknown like target_id for send_message: {target_id}")
                if chosen is not None:
                    tap = chosen.get("tap")
                    if not isinstance(tap, dict) or ("x" not in tap) or ("y" not in tap):
                        raise RuntimeError(f"Like candidate missing tap coords: {chosen}")
                    session.client.tap(x=int(tap["x"]), y=int(tap["y"]))
                    time.sleep(0.35)
                    # Fail fast if the composer does not appear. We do not fall back to a different Like.
                    lha._find_first_any(session.client, locators=discover_input_locators)
                like_locator, input_locator, send_locator = lha._send_discover_message(
                    session.client,
                    like_locators=session.locator_map["like"],
                    input_locators=discover_input_locators,
                    send_locators=discover_send_locators,
                    text=outbound,
                )
                locator = {"discover_like": {"using": like_locator.using, "value": like_locator.value}}
                locator["input"] = {"using": input_locator.using, "value": input_locator.value}
                locator["send"] = {"using": send_locator.using, "value": send_locator.value}
            else:
                input_locator, send_locator = lha._send_message(
                    session.client,
                    input_locators=session.locator_map["message_input"],
                    send_locators=session.locator_map["send"],
                    text=outbound,
                )
                locator = {"input": {"using": input_locator.using, "value": input_locator.value}}
                locator["send"] = {"using": send_locator.using, "value": send_locator.value}
        else:
            locator = None
        session.state.messages += 1
        if screen_type == "hinge_discover_card":
            session.state.likes += 1
        session.state.last_action = "send_message"
        return {
            "executed": "send_message",
            "dry_run": dry_run,
            "message_text": outbound,
            "locator": locator,
        }

    if action == "like":
        if session.state.likes >= session.profile.swipe_policy.max_likes:
            raise RuntimeError("like limit reached")
        matched = None
        if not dry_run:
            if screen_type == "hinge_discover_card":
                discover_send_locators = session.locator_map.get("discover_send") or session.locator_map["send"]
                chosen = _pick_like_candidate()
                if target_id and chosen is None:
                    raise RuntimeError(f"Unknown like target_id: {target_id}")
                if chosen is not None:
                    tap = chosen.get("tap")
                    if not isinstance(tap, dict) or ("x" not in tap) or ("y" not in tap):
                        raise RuntimeError(f"Like candidate missing tap coords: {chosen}")
                    session.client.tap(x=int(tap["x"]), y=int(tap["y"]))
                    time.sleep(0.35)
                    # Like only counts once "Send like" is clicked.
                    matched = lha._click_discover_send_like(session.client, send_locators=discover_send_locators)
                else:
                    _, send_locator = lha._send_discover_like(
                        session.client,
                        like_locators=session.locator_map["like"],
                        send_locators=discover_send_locators,
                    )
                    matched = send_locator
            else:
                matched = lha._click_any(session.client, locators=session.locator_map["like"])
        session.state.likes += 1
        session.state.last_action = "like"
        return {
            "executed": "like",
            "dry_run": dry_run,
            "locator": None if matched is None else {"using": matched.using, "value": matched.value},
        }

    if action == "pass":
        if session.state.passes >= session.profile.swipe_policy.max_passes:
            raise RuntimeError("pass limit reached")
        matched = None
        if not dry_run:
            matched = lha._click_any(session.client, locators=session.locator_map["pass"])
        session.state.passes += 1
        session.state.last_action = "pass"
        return {
            "executed": "pass",
            "dry_run": dry_run,
            "locator": None if matched is None else {"using": matched.using, "value": matched.value},
        }

    if action in _ACTION_TO_LOCATOR_KEY:
        key = _ACTION_TO_LOCATOR_KEY[action]
        matched = None
        if not dry_run:
            matched = lha._click_any(session.client, locators=session.locator_map[key])
        session.state.last_action = action
        return {
            "executed": action,
            "dry_run": dry_run,
            "locator": None if matched is None else {"using": matched.using, "value": matched.value},
        }

    raise RuntimeError(f"Unsupported action {action!r}")


@mcp.tool()
def start_session(config_json_path: str, session_name: str = "default") -> dict[str, Any]:
    """
    Start a live Appium-backed Hinge session from a live_hinge_agent config JSON.
    """
    if session_name in _SESSIONS:
        raise RuntimeError(f"Session {session_name!r} already exists. Stop it first or choose another name.")

    config = load_json_file(config_json_path)
    context = config_json_path
    appium_server_url = lha._as_non_empty_str(
        require_key(config, "appium_server_url", context=context),
        field="appium_server_url",
        context=context,
    )
    capabilities_json_path = lha._as_non_empty_str(
        require_key(config, "capabilities_json_path", context=context),
        field="capabilities_json_path",
        context=context,
    )
    profile_json_path = lha._as_non_empty_str(
        require_key(config, "profile_json_path", context=context),
        field="profile_json_path",
        context=context,
    )
    locator_map = _parse_locator_map(config, context=context)
    decision_engine = lha._parse_decision_engine(config.get("decision_engine"), context=f"{context}: decision_engine")
    profile_bundle_capture_cfg = parse_profile_bundle_capture_config(
        config.get("profile_bundle_capture"),
        context=context,
    )
    profile = lha._load_profile(profile_json_path)
    default_dry_run = bool(config.get("dry_run", True))
    default_query = config.get("command_query")
    if default_query is not None and (not isinstance(default_query, str) or not default_query.strip()):
        raise RuntimeError(f"{context}: command_query must be a non-empty string when provided")

    capabilities_payload = load_json_file(capabilities_json_path)
    require_key(capabilities_payload, "capabilities", context=capabilities_json_path)

    artifacts_dir = Path(str(config.get("artifacts_dir") or "artifacts/live_hinge_mcp")).resolve()
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    client = AppiumHTTPClient(appium_server_url)
    session_id = client.create_session(capabilities_payload)
    managed = _ManagedSession(
        name=session_name,
        config_json_path=str(Path(config_json_path).resolve()),
        client=client,
        session_id=session_id,
        profile=profile,
        decision_engine=decision_engine,
        locator_map=locator_map,
        state=lha._RuntimeState(),
        default_dry_run=default_dry_run,
        default_command_query=default_query,
        artifacts_dir=artifacts_dir,
        profile_bundle_capture_cfg=profile_bundle_capture_cfg,
    )
    _SESSIONS[session_name] = managed
    return {
        "session_name": session_name,
        "session_id": session_id,
        "profile": profile.name,
        "decision_engine_type": decision_engine.type,
        "default_dry_run": default_dry_run,
        "config_json_path": managed.config_json_path,
        "artifacts_dir": str(artifacts_dir),
    }


@mcp.tool()
def list_sessions() -> dict[str, Any]:
    """
    List active in-memory sessions managed by this MCP server.
    """
    sessions = []
    for name, s in sorted(_SESSIONS.items()):
        sessions.append(
            {
                "session_name": name,
                "session_id": s.session_id,
                "profile": s.profile.name,
                "iterations": s.state.iterations,
                "likes": s.state.likes,
                "passes": s.state.passes,
                "messages": s.state.messages,
            }
        )
    return {"sessions": sessions}


@mcp.tool()
def observe(session_name: str = "default", include_screenshot: bool = True) -> dict[str, Any]:
    """
    Capture and return the current Hinge observation packet (screen type, quality signals, available actions).
    """
    session = _must_get_session(session_name)
    packet, _, _, _ = _capture_packet(
        session,
        include_screenshot=include_screenshot,
        persist_snapshot_artifacts=True,
    )
    return {
        "session_name": session_name,
        "packet": packet,
    }


@mcp.tool()
def capture_profile_bundle(session_name: str = "default", tag: Optional[str] = None) -> dict[str, Any]:
    """
    Capture a full Discover profile bundle (multi-viewport screenshots + XML + interaction targets).

    This is explicit and can be expensive: it performs multiple screenshots/source dumps and scroll swipes,
    then returns the app to the starting scroll position.
    """
    session = _must_get_session(session_name)
    cfg = session.profile_bundle_capture_cfg
    if not cfg.enabled:
        raise RuntimeError(
            "profile_bundle_capture is disabled for this session config. "
            "Enable it in the config JSON under profile_bundle_capture.enabled=true."
        )

    packet, _, _, _ = _capture_packet(
        session,
        include_screenshot=False,
        persist_snapshot_artifacts=False,
    )
    if str(packet.get("screen_type") or "") != "hinge_discover_card":
        raise RuntimeError(
            f"capture_profile_bundle only supports hinge_discover_card (got screen_type={packet.get('screen_type')!r})"
        )

    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    safe_tag = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in (tag or "").strip())
    if not safe_tag:
        safe_tag = f"mcp_{ts}"
    output_dir = (session.artifacts_dir / "profile_bundles" / safe_tag).resolve()

    try:
        bundle = capture_profile_bundle_artifact(
            session.client,
            output_dir=output_dir,
            expected_package=str(packet.get("package_name") or "") or None,
            screen_type=str(packet.get("screen_type") or ""),
            cfg=cfg,
        )
    except HingeProfileBundleError as e:
        raise RuntimeError(str(e)) from e

    like_candidates = bundle.get("like_candidates")
    if not isinstance(like_candidates, list):
        like_candidates = []

    return {
        "captured": True,
        "contract_version": bundle.get("contract_version"),
        "bundle_path": bundle.get("bundle_path"),
        "bundle_dir": bundle.get("bundle_dir"),
        "profile_fingerprint": bundle.get("profile_fingerprint"),
        "views_captured": len(bundle.get("views") or []),
        "like_candidates": like_candidates[:12],
    }


@mcp.tool()
def get_page_source(
    session_name: str = "default",
    persist_snapshot_artifact: bool = True,
) -> dict[str, Any]:
    """
    Return current raw UI XML source for the active session.
    """
    session = _must_get_session(session_name)
    xml = session.client.get_page_source()
    xml_path: Optional[Path] = None
    if persist_snapshot_artifact:
        snapshot_dir = session.artifacts_dir / "mcp_snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        xml_path = _snapshot_artifact_path(artifacts_dir=session.artifacts_dir, stem="mcp_source", ext="xml")
        xml_path.write_text(xml, encoding="utf-8")
    return {
        "session_name": session_name,
        "xml": xml,
        "xml_path": None if xml_path is None else str(xml_path),
    }


@mcp.tool()
def capture_screenshot(
    session_name: str = "default",
    persist_snapshot_artifact: bool = True,
) -> dict[str, Any]:
    """
    Capture a PNG screenshot for the active session.
    """
    session = _must_get_session(session_name)
    png = session.client.get_screenshot_png_bytes()
    screenshot_path: Optional[Path] = None
    if persist_snapshot_artifact:
        snapshot_dir = session.artifacts_dir / "mcp_snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = _snapshot_artifact_path(
            artifacts_dir=session.artifacts_dir,
            stem="mcp_screenshot",
            ext="png",
        )
        screenshot_path.write_bytes(png)
    return {
        "session_name": session_name,
        "bytes": len(png),
        "screenshot_path": None if screenshot_path is None else str(screenshot_path),
    }


@mcp.tool()
def find_elements(
    session_name: str = "default",
    using: str = "xpath",
    value: str = "",
    limit: int = 10,
    include_text: bool = True,
    include_rect: bool = True,
) -> dict[str, Any]:
    """
    Find elements by raw locator and optionally return text/rect for each match.
    """
    session = _must_get_session(session_name)
    if not isinstance(limit, int) or limit <= 0:
        raise RuntimeError("'limit' must be an integer > 0")

    locator_using = using.strip()
    locator_value = value.strip()
    if not locator_using or not locator_value:
        raise RuntimeError("'using' and 'value' must be non-empty")

    elements = session.client.find_elements(using=locator_using, value=locator_value)
    payload: list[dict[str, Any]] = []
    for idx, element in enumerate(elements[:limit]):
        row: dict[str, Any] = {
            "index": idx,
            "element_id": element.element_id,
        }
        if include_text:
            try:
                row["text"] = session.client.get_element_text(element)
            except Exception as e:
                row["text_error"] = str(e)
        if include_rect:
            try:
                row["rect"] = session.client.get_element_rect(element)
            except Exception as e:
                row["rect_error"] = str(e)
        payload.append(row)

    return {
        "session_name": session_name,
        "using": locator_using,
        "value": locator_value,
        "total_found": len(elements),
        "returned": len(payload),
        "elements": payload,
    }


@mcp.tool()
def click_element(
    session_name: str = "default",
    using: str = "xpath",
    value: str = "",
    index: int = 0,
) -> dict[str, Any]:
    """
    Click a specific element selected by locator + index.
    """
    session = _must_get_session(session_name)
    element = _find_element_or_raise(session, using=using, value=value, index=index)
    session.client.click(element)
    return {
        "session_name": session_name,
        "clicked": True,
        "using": using.strip(),
        "value": value.strip(),
        "index": index,
        "element_id": element.element_id,
    }


@mcp.tool()
def type_into_element(
    session_name: str = "default",
    using: str = "xpath",
    value: str = "",
    text: str = "",
    index: int = 0,
) -> dict[str, Any]:
    """
    Type text into a specific element selected by locator + index.
    """
    session = _must_get_session(session_name)
    if not isinstance(text, str) or not text:
        raise RuntimeError("'text' must be a non-empty string")
    element = _find_element_or_raise(session, using=using, value=value, index=index)
    session.client.send_keys(element, text=text)
    return {
        "session_name": session_name,
        "typed": True,
        "using": using.strip(),
        "value": value.strip(),
        "index": index,
        "text_length": len(text),
        "element_id": element.element_id,
    }


@mcp.tool()
def tap_point(session_name: str = "default", x: int = 0, y: int = 0) -> dict[str, Any]:
    """
    Tap absolute viewport coordinates.
    """
    session = _must_get_session(session_name)
    session.client.tap(x=int(x), y=int(y))
    return {
        "session_name": session_name,
        "tapped": True,
        "x": int(x),
        "y": int(y),
    }


@mcp.tool()
def swipe_points(
    session_name: str = "default",
    x1: int = 0,
    y1: int = 0,
    x2: int = 0,
    y2: int = 0,
    duration_ms: int = 600,
) -> dict[str, Any]:
    """
    Swipe between two absolute viewport points.
    """
    session = _must_get_session(session_name)
    session.client.swipe(
        x1=int(x1),
        y1=int(y1),
        x2=int(x2),
        y2=int(y2),
        duration_ms=int(duration_ms),
    )
    return {
        "session_name": session_name,
        "swiped": True,
        "from": {"x": int(x1), "y": int(y1)},
        "to": {"x": int(x2), "y": int(y2)},
        "duration_ms": int(duration_ms),
    }


@mcp.tool()
def press_keycode(
    session_name: str = "default",
    keycode: int = 4,
    metastate: Optional[int] = None,
) -> dict[str, Any]:
    """
    Press an Android keycode (e.g. Back=4, Home=3, Enter=66).
    """
    session = _must_get_session(session_name)
    metastate_int = None if metastate is None else int(metastate)
    session.client.press_keycode(keycode=int(keycode), metastate=metastate_int)
    return {
        "session_name": session_name,
        "pressed": True,
        "keycode": int(keycode),
        "metastate": metastate_int,
    }


@mcp.tool()
def decide(
    session_name: str = "default",
    command_query: Optional[str] = None,
    mode: str = "llm",
    include_screenshot: bool = True,
) -> dict[str, Any]:
    """
    Observe the current screen and decide the next action (without executing it).
    """
    session = _must_get_session(session_name)
    packet, screenshot_png_bytes, _, _ = _capture_packet(
        session,
        include_screenshot=include_screenshot,
        persist_snapshot_artifacts=True,
    )
    directive = lha._parse_natural_language_query(command_query or session.default_command_query)
    mode_norm = mode.strip().lower()
    if mode_norm not in {"llm", "deterministic"}:
        raise RuntimeError("mode must be 'llm' or 'deterministic'")

    if mode_norm == "deterministic":
        action, reason, message_text, target_id = lha._deterministic_decide(
            packet=packet,
            profile=session.profile,
            state=session.state,
            directive=directive,
        )
    else:
        try:
            action, reason, message_text, target_id, llm_trace = lha._llm_decide_with_trace(
                packet=packet,
                profile=session.profile,
                decision_engine=session.decision_engine,
                nl_query=directive.query,
                screenshot_png_bytes=screenshot_png_bytes,
            )
        except Exception as e:
            if session.decision_engine.llm_failure_mode == "fallback_deterministic":
                action, reason, message_text, target_id = lha._deterministic_decide(
                    packet=packet,
                    profile=session.profile,
                    state=session.state,
                    directive=directive,
                )
                reason = f"llm_failed_fallback: {e}; {reason}"
                llm_trace = {"ok": False, "error": str(e)}
            else:
                raise

    return {
        "session_name": session_name,
        "mode": mode_norm,
        "packet": packet,
        "decision": {
            "action": action,
            "reason": reason,
            "message_text": message_text,
            "target_id": target_id,
            "llm_trace": llm_trace if mode_norm == "llm" else None,
        },
    }


@mcp.tool()
def execute(
    session_name: str = "default",
    action: str = "wait",
    message_text: Optional[str] = None,
    target_id: Optional[str] = None,
    dry_run: Optional[bool] = None,
) -> dict[str, Any]:
    """
    Execute a specific action on the live session.
    """
    session = _must_get_session(session_name)
    use_dry_run = session.default_dry_run if dry_run is None else bool(dry_run)
    packet, _, _, _ = _capture_packet(
        session,
        include_screenshot=False,
        persist_snapshot_artifacts=False,
    )
    result = _execute_action(
        session,
        action=action.strip(),
        message_text=message_text,
        dry_run=use_dry_run,
        screen_type=str(packet.get("screen_type") or "hinge_unknown"),
        quality_features=packet.get("quality_features") or {},
        target_id=target_id,
        like_candidates=packet.get("like_candidates") if isinstance(packet.get("like_candidates"), list) else [],
    )
    session.state.iterations += 1
    result["counters"] = {
        "iterations": session.state.iterations,
        "likes": session.state.likes,
        "passes": session.state.passes,
        "messages": session.state.messages,
    }
    return {
        "session_name": session_name,
        "packet": packet,
        "execution": result,
    }


@mcp.tool()
def step(
    session_name: str = "default",
    command_query: Optional[str] = None,
    mode: str = "llm",
    execute_action: bool = True,
    dry_run: Optional[bool] = None,
    include_screenshot: bool = True,
) -> dict[str, Any]:
    """
    Single autonomous loop tick: observe -> decide -> optional execute.
    """
    session = _must_get_session(session_name)
    packet, screenshot_png_bytes, _, _ = _capture_packet(
        session,
        include_screenshot=include_screenshot,
        persist_snapshot_artifacts=True,
    )
    directive = lha._parse_natural_language_query(command_query or session.default_command_query)
    mode_norm = mode.strip().lower()
    if mode_norm not in {"llm", "deterministic"}:
        raise RuntimeError("mode must be 'llm' or 'deterministic'")

    if mode_norm == "deterministic":
        action, reason, message_text, target_id = lha._deterministic_decide(
            packet=packet,
            profile=session.profile,
            state=session.state,
            directive=directive,
        )
    else:
        try:
            action, reason, message_text, target_id, llm_trace = lha._llm_decide_with_trace(
                packet=packet,
                profile=session.profile,
                decision_engine=session.decision_engine,
                nl_query=directive.query,
                screenshot_png_bytes=screenshot_png_bytes,
            )
        except Exception as e:
            if session.decision_engine.llm_failure_mode == "fallback_deterministic":
                action, reason, message_text, target_id = lha._deterministic_decide(
                    packet=packet,
                    profile=session.profile,
                    state=session.state,
                    directive=directive,
                )
                reason = f"llm_failed_fallback: {e}; {reason}"
                llm_trace = {"ok": False, "error": str(e)}
            else:
                raise

    execution = None
    if execute_action:
        use_dry_run = session.default_dry_run if dry_run is None else bool(dry_run)
        execution = _execute_action(
            session,
            action=action,
            message_text=message_text,
            dry_run=use_dry_run,
            screen_type=str(packet.get("screen_type") or "hinge_unknown"),
            quality_features=packet.get("quality_features") or {},
            target_id=target_id,
            like_candidates=packet.get("like_candidates") if isinstance(packet.get("like_candidates"), list) else [],
        )
        session.state.iterations += 1

    return {
        "session_name": session_name,
        "mode": mode_norm,
        "packet": packet,
        "decision": {
            "action": action,
            "reason": reason,
            "message_text": message_text,
            "target_id": target_id,
            "llm_trace": llm_trace if mode_norm == "llm" else None,
        },
        "execution": execution,
        "counters": {
            "iterations": session.state.iterations,
            "likes": session.state.likes,
            "passes": session.state.passes,
            "messages": session.state.messages,
        },
    }


@mcp.tool()
def stop_session(session_name: str = "default") -> dict[str, Any]:
    """
    Stop and remove an active live session.
    """
    session = _must_get_session(session_name)
    try:
        session.client.delete_session()
    finally:
        _SESSIONS.pop(session_name, None)
    return {"session_name": session_name, "stopped": True}


@mcp.tool()
def action_catalog() -> dict[str, Any]:
    """
    Return supported high-level Hinge actions.
    """
    return {"actions": lha.get_hinge_action_catalog()}


@mcp.tool()
def profile_summary(profile_json_path: str) -> dict[str, Any]:
    """
    Validate a profile spec JSON and return a normalized summary.
    """
    profile = lha._load_profile(profile_json_path)
    return {
        "name": profile.name,
        "persona_spec": {
            "archetype": profile.persona_spec.archetype,
            "intent": profile.persona_spec.intent,
            "tone_traits": profile.persona_spec.tone_traits,
            "hard_boundaries": profile.persona_spec.hard_boundaries,
            "preferred_signals": profile.persona_spec.preferred_signals,
            "avoid_signals": profile.persona_spec.avoid_signals,
            "opener_strategy": profile.persona_spec.opener_strategy,
            "max_message_chars": profile.persona_spec.max_message_chars,
            "require_question": profile.persona_spec.require_question,
        },
        "swipe_policy": {
            "min_quality_score_like": profile.swipe_policy.min_quality_score_like,
            "require_flags_all": sorted(profile.swipe_policy.require_flags_all),
            "block_prompt_keywords": profile.swipe_policy.block_prompt_keywords,
            "max_likes": profile.swipe_policy.max_likes,
            "max_passes": profile.swipe_policy.max_passes,
        },
        "message_policy": {
            "enabled": profile.message_policy.enabled,
            "min_quality_score_to_message": profile.message_policy.min_quality_score_to_message,
            "max_messages": profile.message_policy.max_messages,
            "template": profile.message_policy.template,
        },
    }


@mcp.tool()
def dump_state(session_name: str = "default") -> dict[str, Any]:
    """
    Return counters and the most recent runtime fields for debugging external agents.
    """
    session = _must_get_session(session_name)
    return {
        "session_name": session_name,
        "session_id": session.session_id,
        "config_json_path": session.config_json_path,
        "profile": session.profile.name,
        "decision_engine_type": session.decision_engine.type,
        "state": {
            "iterations": session.state.iterations,
            "likes": session.state.likes,
            "passes": session.state.passes,
            "messages": session.state.messages,
            "last_action": session.state.last_action,
            "consecutive_validation_failures": session.state.consecutive_validation_failures,
        },
    }


@mcp.tool()
def close_all_sessions() -> dict[str, Any]:
    """
    Best-effort shutdown for all sessions (useful for cleanup and CI).
    """
    closed: list[str] = []
    errors: dict[str, str] = {}
    for name, session in list(_SESSIONS.items()):
        try:
            session.client.delete_session()
            closed.append(name)
        except Exception as e:
            errors[name] = str(e)
        finally:
            _SESSIONS.pop(name, None)
    return {"closed_sessions": closed, "errors": errors}


if __name__ == "__main__":
    mcp.run(transport="stdio")
