from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree

import requests

from .android_accessibility import extract_accessible_strings
from .appium_http_client import AppiumHTTPClient, AppiumHTTPError, WebDriverElementRef
from .config import load_json_file, require_key
from .env import ensure_dotenv_loaded


class LiveHingeAgentError(RuntimeError):
    pass


@dataclass(frozen=True)
class Locator:
    using: str
    value: str


@dataclass(frozen=True)
class HingeSwipePolicy:
    min_quality_score_like: int
    require_flags_all: set[str]
    block_prompt_keywords: list[str]
    max_likes: int
    max_passes: int


@dataclass(frozen=True)
class HingeMessagePolicy:
    enabled: bool
    min_quality_score_to_message: int
    max_messages: int
    template: str


@dataclass(frozen=True)
class HingePersonaSpec:
    archetype: str
    intent: str
    tone_traits: list[str]
    hard_boundaries: list[str]
    preferred_signals: list[str]
    avoid_signals: list[str]
    opener_strategy: str
    examples: list[str]
    max_message_chars: int
    require_question: bool


@dataclass(frozen=True)
class HingeAgentProfile:
    name: str
    persona_spec: HingePersonaSpec
    swipe_policy: HingeSwipePolicy
    message_policy: HingeMessagePolicy
    llm_criteria: dict[str, Any]


@dataclass(frozen=True)
class DecisionEngineConfig:
    type: str
    llm_model: Optional[str]
    llm_temperature: float
    llm_timeout_s: float
    llm_api_key_env: str
    llm_base_url: str
    llm_include_screenshot: bool
    llm_image_detail: str
    llm_max_observed_strings: int
    llm_failure_mode: str


@dataclass(frozen=True)
class NLDirective:
    query: Optional[str]
    goal: str
    force_action_once: Optional[str]
    overrides: dict[str, Any]


@dataclass(frozen=True)
class LiveHingeAgentResult:
    session_id: str
    iterations: int
    likes: int
    passes: int
    messages: int
    action_log_path: Path
    packet_log_path: Optional[Path]
    artifacts: list[Path]


@dataclass
class _RuntimeState:
    likes: int = 0
    passes: int = 0
    messages: int = 0
    iterations: int = 0
    action_log: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[Path] = field(default_factory=list)
    force_action_consumed: bool = False
    last_action: Optional[str] = None
    consecutive_validation_failures: int = 0
    explore_nav_index: int = 0


_HINGE_ACTION_CATALOG: list[dict[str, str]] = [
    {
        "action": "goto_discover",
        "human_action": "Tap Discover tab",
        "description": "Navigate to Discover where swiping cards is possible.",
    },
    {
        "action": "goto_matches",
        "human_action": "Tap Matches tab",
        "description": "Navigate to Matches to review conversations.",
    },
    {
        "action": "goto_likes_you",
        "human_action": "Tap Likes You tab",
        "description": "Navigate to Likes You surface.",
    },
    {
        "action": "goto_standouts",
        "human_action": "Tap Standouts tab",
        "description": "Navigate to Standouts surface.",
    },
    {
        "action": "goto_profile_hub",
        "human_action": "Tap Profile tab",
        "description": "Navigate to profile/settings tab.",
    },
    {
        "action": "open_thread",
        "human_action": "Tap a match thread",
        "description": "Open a conversation thread in Matches.",
    },
    {
        "action": "like",
        "human_action": "Tap Like on current card item",
        "description": "Like the current profile card/prompt/photo/voice item.",
    },
    {
        "action": "pass",
        "human_action": "Tap Skip/Pass",
        "description": "Skip the current profile card.",
    },
    {
        "action": "send_message",
        "human_action": "Type and send a message",
        "description": "Send a chat message in an open thread.",
    },
    {
        "action": "back",
        "human_action": "Tap Android back",
        "description": "Dismiss overlays/modals or navigate one level back.",
    },
    {
        "action": "dismiss_overlay",
        "human_action": "Tap overlay close affordance",
        "description": "Close visible Hinge overlays (for example Rose/paywall sheets) without Android back.",
    },
    {
        "action": "wait",
        "human_action": "Observe",
        "description": "Take no action this iteration.",
    },
]


def get_hinge_action_catalog() -> list[dict[str, str]]:
    return list(_HINGE_ACTION_CATALOG)


def _as_non_empty_str(value: Any, *, field: str, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiveHingeAgentError(f"{context}: '{field}' must be a non-empty string")
    return value.strip()


def _as_positive_int(value: Any, *, field: str, context: str) -> int:
    try:
        parsed = int(value)
    except Exception as e:
        raise LiveHingeAgentError(f"{context}: '{field}' must be an integer") from e
    if parsed <= 0:
        raise LiveHingeAgentError(f"{context}: '{field}' must be > 0")
    return parsed


def _as_non_negative_float(value: Any, *, field: str, context: str) -> float:
    try:
        parsed = float(value)
    except Exception as e:
        raise LiveHingeAgentError(f"{context}: '{field}' must be numeric") from e
    if parsed < 0:
        raise LiveHingeAgentError(f"{context}: '{field}' must be >= 0")
    return parsed


def _as_list_of_non_empty_str(
    value: Any,
    *,
    field: str,
    context: str,
    default: Optional[list[str]] = None,
) -> list[str]:
    if value is None:
        return list(default or [])
    if not isinstance(value, list):
        raise LiveHingeAgentError(f"{context}: '{field}' must be a list of non-empty strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise LiveHingeAgentError(f"{context}: '{field}' must be a list of non-empty strings")
        out.append(item.strip())
    return out


def _as_dict_or_empty(value: Any, *, field: str, context: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise LiveHingeAgentError(f"{context}: '{field}' must be an object when provided")
    return {str(k): v for k, v in value.items()}


def _parse_locator(raw: Any, *, context: str) -> Locator:
    if not isinstance(raw, dict):
        raise LiveHingeAgentError(f"{context}: locator must be an object")
    using = _as_non_empty_str(raw.get("using"), field="using", context=context)
    value = _as_non_empty_str(raw.get("value"), field="value", context=context)
    return Locator(using=using, value=value)


def _parse_locators(raw: Any, *, field: str, context: str, required: bool) -> list[Locator]:
    if raw is None:
        if required:
            raise LiveHingeAgentError(f"{context}: '{field}' is required and must be a non-empty list")
        return []
    if not isinstance(raw, list) or not raw:
        raise LiveHingeAgentError(f"{context}: '{field}' must be a non-empty list")
    out: list[Locator] = []
    for idx, item in enumerate(raw, 1):
        out.append(_parse_locator(item, context=f"{context}: {field}[{idx}]"))
    return out


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _artifact_path(*, artifacts_dir: Path, stem: str, ext: str) -> Path:
    safe_stem = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in stem.strip())
    if not safe_stem:
        safe_stem = "artifact"
    return artifacts_dir / f"{safe_stem}_{_timestamp()}.{ext.lstrip('.')}"


def _extract_package_name(xml: str) -> Optional[str]:
    try:
        root = ElementTree.fromstring(xml)
    except Exception:
        return None
    for node in root.iter():
        package = (node.attrib or {}).get("package")
        if package:
            return package
    return None


def _classify_hinge_screen(strings: list[str]) -> str:
    lowered = [s.lower() for s in strings]
    if any("out of free likes" in s for s in lowered):
        return "hinge_like_paywall"
    if (
        (any("close sheet" in s for s in lowered) and any("rose" in s for s in lowered))
        or any("catch their eye by sending a rose" in s for s in lowered)
    ):
        return "hinge_overlay_rose_sheet"
    if any("no matches yet" in s for s in lowered):
        return "hinge_matches_empty"
    if any("when a like is mutual" in s for s in lowered):
        return "hinge_matches_empty"
    discover_like_signal = any(s.startswith("like ") for s in lowered) or any(
        "send like with message" in s for s in lowered
    )
    discover_pass_signal = any(s.startswith("skip ") or s == "skip" for s in lowered) or any(
        "undo the previous pass rating" in s for s in lowered
    )
    discover_composer_signal = any(
        ("edit comment" in s) or ("add a comment" in s) or ("send like with message" in s) for s in lowered
    )
    if (discover_like_signal and discover_pass_signal) or discover_composer_signal:
        return "hinge_discover_card"
    if any("type a message" in s for s in lowered) or ("send" in lowered):
        return "hinge_chat"
    if "matches" in lowered and "discover" in lowered:
        return "hinge_tab_shell"
    return "hinge_unknown"


def _extract_quality_features(strings: list[str]) -> dict[str, Any]:
    profile_name = None
    prompt_answer = None
    like_targets: list[str] = []
    flags: set[str] = set()

    for s in strings:
        lowered = s.lower().strip()
        if (lowered.endswith("'s photo") or lowered.endswith("’s photo")) and profile_name is None:
            profile_name = s.split("'s photo")[0].split("’s photo")[0].strip()
        if lowered.startswith("prompt:") and "answer:" in lowered and prompt_answer is None:
            answer = s.split("Answer:", 1)[-1].strip()
            prompt_answer = answer or None
        if lowered.startswith("like "):
            like_targets.append(s)
        if "selfie verified" in lowered:
            flags.add("selfie_verified")
        if "active today" in lowered:
            flags.add("active_today")
        if "voice prompt" in lowered:
            flags.add("has_voice_prompt")

    return {
        "profile_name_candidate": profile_name,
        "prompt_answer": prompt_answer,
        "like_targets": like_targets,
        "quality_flags": sorted(flags),
    }


def _score_quality(*, screen_type: str, quality_features: dict[str, Any]) -> int:
    if screen_type == "hinge_matches_empty":
        return 0

    score = 0
    flags = set(quality_features.get("quality_flags") or [])
    if screen_type == "hinge_discover_card":
        score += 20
    if "selfie_verified" in flags:
        score += 20
    if "active_today" in flags:
        score += 15
    if "has_voice_prompt" in flags:
        score += 10
    if quality_features.get("prompt_answer"):
        score += 15
    like_targets = quality_features.get("like_targets") or []
    if isinstance(like_targets, list) and like_targets:
        score += min(len(like_targets), 3) * 8
    if quality_features.get("profile_name_candidate"):
        score += 8
    return max(0, min(score, 100))


def _find_first_any(client: AppiumHTTPClient, *, locators: list[Locator]) -> tuple[Locator, WebDriverElementRef]:
    for locator in locators:
        elements = client.find_elements(using=locator.using, value=locator.value)
        if elements:
            return locator, elements[0]
    locator_debug = "; ".join(f"{l.using}:{l.value}" for l in locators)
    raise LiveHingeAgentError(f"No elements found for locator candidates: {locator_debug}")


def _has_any(client: AppiumHTTPClient, *, locators: list[Locator]) -> bool:
    if not locators:
        return False
    for locator in locators:
        try:
            elements = client.find_elements(using=locator.using, value=locator.value)
        except Exception:
            continue
        if elements:
            return True
    return False


def _click_any(client: AppiumHTTPClient, *, locators: list[Locator]) -> Locator:
    matched, element = _find_first_any(client, locators=locators)
    client.click(element)
    return matched


def _send_message(
    client: AppiumHTTPClient,
    *,
    input_locators: list[Locator],
    send_locators: list[Locator],
    send_fallback_locators: Optional[list[Locator]] = None,
    text: str,
) -> tuple[Locator, Locator]:
    input_locator, input_el = _find_first_any(client, locators=input_locators)
    client.send_keys(input_el, text=text)
    try:
        send_locator = _click_any(client, locators=send_locators)
    except Exception:
        if send_fallback_locators:
            send_locator = _click_any(client, locators=send_fallback_locators)
        else:
            raise
    return input_locator, send_locator


def _adb_input_text(text: str) -> None:
    """
    Type text into the currently focused Android input via adb.

    This is used as a fallback when the visible composer is not exposed as an
    editable element for WebDriver send_keys (common on custom React Native views).
    """
    cleaned = " ".join((text or "").split())
    if not cleaned:
        raise LiveHingeAgentError("Cannot input empty text via adb")
    # Keep characters that typically survive adb input and normalize the rest.
    cleaned = re.sub(r"[^A-Za-z0-9 @._,!?'-]", " ", cleaned)
    cleaned = " ".join(cleaned.split())
    adb_text = cleaned.replace(" ", "%s")
    try:
        subprocess.run(
            ["adb", "shell", "input", "text", adb_text],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        raise LiveHingeAgentError(f"Failed adb text input fallback: {e}") from e


def _resolve_activity_component(*, package_name: str, activity_name: str) -> str:
    activity = activity_name.strip()
    if not activity:
        raise LiveHingeAgentError("target_activity must be non-empty when foreground recovery is enabled")
    if "/" in activity:
        return activity
    if activity.startswith("."):
        return f"{package_name}/{activity}"
    return f"{package_name}/{activity}"


def _adb_start_activity(*, package_name: str, activity_name: str) -> str:
    """
    Bring the target app to foreground via adb am start.
    Returns the component string that was launched.
    """
    component = _resolve_activity_component(package_name=package_name, activity_name=activity_name)
    try:
        subprocess.run(
            ["adb", "shell", "am", "start", "-n", component],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        raise LiveHingeAgentError(f"Failed to foreground app via adb start ({component}): {e}") from e
    return component


def _send_discover_message(
    client: AppiumHTTPClient,
    *,
    like_locators: list[Locator],
    input_locators: list[Locator],
    send_locators: list[Locator],
    text: str,
) -> tuple[Locator, Locator, Locator]:
    """
    Send a Discover-card comment flow:
    1) tap Like (opens comment composer), 2) type comment, 3) tap Send like.
    """
    like_locator: Optional[Locator] = None
    try:
        input_locator, input_el = _find_first_any(client, locators=input_locators)
    except Exception:
        like_locator = _click_any(client, locators=like_locators)
        time.sleep(0.35)
        try:
            input_locator, input_el = _find_first_any(client, locators=input_locators)
        except Exception:
            xml_after_like = client.get_page_source()
            strings_after_like = extract_accessible_strings(xml_after_like, limit=800)
            lowered = [s.lower() for s in strings_after_like]
            if any("out of free likes" in s for s in lowered):
                raise LiveHingeAgentError("Discover message send blocked: out of free likes")
            raise

    # Some UIs return a non-editable view for the comment area. Click to focus.
    try:
        client.click(input_el)
    except Exception:
        # Refind once in case of stale references after animation.
        input_locator, input_el = _find_first_any(client, locators=input_locators)
        client.click(input_el)

    typed = False
    try:
        client.send_keys(input_el, text=text)
        typed = True
    except AppiumHTTPError:
        typed = False
    except Exception:
        typed = False

    if not typed:
        _adb_input_text(text)

    send_locator = _click_any(client, locators=send_locators)
    try:
        post_xml = client.get_page_source()
        post_strings = extract_accessible_strings(post_xml, limit=800)
        lowered = [s.lower() for s in post_strings]
        if any("out of free likes" in s for s in lowered):
            raise LiveHingeAgentError("Discover message send blocked: out of free likes")
    except LiveHingeAgentError:
        raise
    except Exception:
        # Post-send inspection is best-effort only.
        pass
    if like_locator is None:
        # Composer was already open; annotate with a synthetic locator to keep logs explicit.
        like_locator = Locator(using="synthetic", value="discover_composer_already_open")
    return like_locator, input_locator, send_locator


def _render_template(template: str, *, name: Optional[str]) -> str:
    rendered = template.replace("{{name}}", (name or "there"))
    if "{{name}}" in rendered:
        rendered = rendered.replace("{{name}}", (name or "there"))
    return rendered


def _normalize_message_text(
    *,
    raw_text: Optional[str],
    profile: HingeAgentProfile,
    quality_features: dict[str, Any],
) -> str:
    fallback = _render_template(
        profile.message_policy.template,
        name=quality_features.get("profile_name_candidate"),
    )
    text = (raw_text or "").strip()
    if not text:
        text = fallback

    # Normalize whitespace and guard length so outbound messages remain concise.
    text = " ".join(text.split())
    max_chars = profile.persona_spec.max_message_chars
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"

    if profile.persona_spec.require_question and "?" not in text:
        suffix = " What's been your highlight this week?"
        candidate = text + suffix
        if len(candidate) <= max_chars:
            text = candidate
        else:
            # Keep question requirement while respecting max length.
            head = text[: max(0, max_chars - len(suffix) - 1)].rstrip()
            text = (head + suffix).strip()

    return text


def _screen_fingerprint(*, screen_type: str, quality_features: dict[str, Any], strings: list[str]) -> str:
    key_parts = [
        screen_type,
        str(quality_features.get("profile_name_candidate") or ""),
        str(quality_features.get("prompt_answer") or ""),
        "|".join((quality_features.get("quality_flags") or [])[:6]),
        "|".join(strings[:12]),
    ]
    return "||".join(key_parts)


def _load_profile(profile_json_path: str) -> HingeAgentProfile:
    raw = load_json_file(profile_json_path)
    context = profile_json_path

    name = _as_non_empty_str(raw.get("name") or "hinge_profile", field="name", context=context)
    persona_raw = _as_dict_or_empty(raw.get("persona_spec"), field="persona_spec", context=context)
    swipe_raw = require_key(raw, "swipe_policy", context=context)
    message_raw = require_key(raw, "message_policy", context=context)
    llm_criteria_raw = _as_dict_or_empty(raw.get("llm_criteria"), field="llm_criteria", context=context)

    if not isinstance(swipe_raw, dict):
        raise LiveHingeAgentError(f"{context}: 'swipe_policy' must be an object")
    if not isinstance(message_raw, dict):
        raise LiveHingeAgentError(f"{context}: 'message_policy' must be an object")

    require_flags_all_raw = swipe_raw.get("require_flags_all", [])
    if not isinstance(require_flags_all_raw, list) or not all(
        isinstance(x, str) and x.strip() for x in require_flags_all_raw
    ):
        raise LiveHingeAgentError(f"{context}: swipe_policy.require_flags_all must be a list of non-empty strings")

    block_prompt_keywords_raw = swipe_raw.get("block_prompt_keywords", [])
    if not isinstance(block_prompt_keywords_raw, list) or not all(
        isinstance(x, str) and x.strip() for x in block_prompt_keywords_raw
    ):
        raise LiveHingeAgentError(
            f"{context}: swipe_policy.block_prompt_keywords must be a list of non-empty strings"
        )

    swipe_policy = HingeSwipePolicy(
        min_quality_score_like=_as_positive_int(
            swipe_raw.get("min_quality_score_like", 70),
            field="min_quality_score_like",
            context=f"{context}: swipe_policy",
        ),
        require_flags_all={x.strip() for x in require_flags_all_raw},
        block_prompt_keywords=[x.strip().lower() for x in block_prompt_keywords_raw],
        max_likes=_as_positive_int(
            swipe_raw.get("max_likes", 20),
            field="max_likes",
            context=f"{context}: swipe_policy",
        ),
        max_passes=_as_positive_int(
            swipe_raw.get("max_passes", 120),
            field="max_passes",
            context=f"{context}: swipe_policy",
        ),
    )

    message_policy = HingeMessagePolicy(
        enabled=bool(message_raw.get("enabled", False)),
        min_quality_score_to_message=_as_positive_int(
            message_raw.get("min_quality_score_to_message", 85),
            field="min_quality_score_to_message",
            context=f"{context}: message_policy",
        ),
        max_messages=_as_positive_int(
            message_raw.get("max_messages", 5),
            field="max_messages",
            context=f"{context}: message_policy",
        ),
        template=_as_non_empty_str(
            message_raw.get("template") or "Hey {{name}}, how's your week going?",
            field="template",
            context=f"{context}: message_policy",
        ),
    )

    persona_spec = HingePersonaSpec(
        archetype=_as_non_empty_str(
            persona_raw.get("archetype") or "intentional_warm_connector",
            field="archetype",
            context=f"{context}: persona_spec",
        ),
        intent=_as_non_empty_str(
            persona_raw.get("intent") or "Find emotionally available, high-intent matches for meaningful dating.",
            field="intent",
            context=f"{context}: persona_spec",
        ),
        tone_traits=_as_list_of_non_empty_str(
            persona_raw.get("tone_traits"),
            field="tone_traits",
            context=f"{context}: persona_spec",
            default=["warm", "curious", "grounded", "playful"],
        ),
        hard_boundaries=_as_list_of_non_empty_str(
            persona_raw.get("hard_boundaries"),
            field="hard_boundaries",
            context=f"{context}: persona_spec",
            default=[
                "No sexual content in first message",
                "No manipulative or negging language",
                "No pressure to move off-app immediately",
            ],
        ),
        preferred_signals=_as_list_of_non_empty_str(
            persona_raw.get("preferred_signals"),
            field="preferred_signals",
            context=f"{context}: persona_spec",
            default=[
                "Specific prompt answers with personality",
                "Evidence of emotional maturity",
                "Signs of an active lifestyle",
            ],
        ),
        avoid_signals=_as_list_of_non_empty_str(
            persona_raw.get("avoid_signals"),
            field="avoid_signals",
            context=f"{context}: persona_spec",
            default=[
                "Profile hostility",
                "Heavy cynicism",
                "Low-effort one-word prompts",
            ],
        ),
        opener_strategy=_as_non_empty_str(
            persona_raw.get("opener_strategy")
            or "Reference one concrete profile detail and end with one easy-to-answer question.",
            field="opener_strategy",
            context=f"{context}: persona_spec",
        ),
        examples=_as_list_of_non_empty_str(
            persona_raw.get("examples"),
            field="examples",
            context=f"{context}: persona_spec",
            default=[
                "You mentioned learning salsa. What's been the hardest move to get right so far?",
                "Your travel prompt made me laugh. What's your most controversial airport opinion?",
            ],
        ),
        max_message_chars=_as_positive_int(
            persona_raw.get("max_message_chars", 180),
            field="max_message_chars",
            context=f"{context}: persona_spec",
        ),
        require_question=bool(persona_raw.get("require_question", True)),
    )
    if persona_spec.max_message_chars > 500:
        raise LiveHingeAgentError(
            f"{context}: persona_spec.max_message_chars must be <= 500 for first-message safety"
        )

    llm_criteria = dict(llm_criteria_raw)
    return HingeAgentProfile(
        name=name,
        persona_spec=persona_spec,
        swipe_policy=swipe_policy,
        message_policy=message_policy,
        llm_criteria=llm_criteria,
    )


def _parse_decision_engine(raw: Any, *, context: str) -> DecisionEngineConfig:
    if raw is None:
        return DecisionEngineConfig(
            type="deterministic",
            llm_model=None,
            llm_temperature=0.1,
            llm_timeout_s=30.0,
            llm_api_key_env="OPENAI_API_KEY",
            llm_base_url="https://api.openai.com",
            llm_include_screenshot=True,
            llm_image_detail="auto",
            llm_max_observed_strings=120,
            llm_failure_mode="fail",
        )
    if not isinstance(raw, dict):
        raise LiveHingeAgentError(f"{context}: decision_engine must be an object")

    engine_type = _as_non_empty_str(raw.get("type") or "deterministic", field="type", context=context).lower()
    if engine_type not in {"deterministic", "llm"}:
        raise LiveHingeAgentError(f"{context}: decision_engine.type must be 'deterministic' or 'llm'")

    llm_raw = raw.get("llm", {})
    if llm_raw is None:
        llm_raw = {}
    if not isinstance(llm_raw, dict):
        raise LiveHingeAgentError(f"{context}: decision_engine.llm must be an object when provided")

    llm_failure_mode = str(raw.get("llm_failure_mode") or "fail").strip().lower()
    if llm_failure_mode not in {"fail", "fallback_deterministic"}:
        raise LiveHingeAgentError(
            f"{context}: decision_engine.llm_failure_mode must be 'fail' or 'fallback_deterministic'"
        )

    llm_model = llm_raw.get("model")
    if llm_model is not None:
        llm_model = _as_non_empty_str(llm_model, field="model", context=f"{context}: decision_engine.llm")

    llm_image_detail = str(llm_raw.get("image_detail") or "auto").strip().lower()
    if llm_image_detail not in {"low", "high", "auto"}:
        raise LiveHingeAgentError(f"{context}: decision_engine.llm.image_detail must be 'low', 'high', or 'auto'")

    return DecisionEngineConfig(
        type=engine_type,
        llm_model=llm_model,
        llm_temperature=float(llm_raw.get("temperature", 0.1)),
        llm_timeout_s=float(llm_raw.get("timeout_s", 30.0)),
        llm_api_key_env=str(llm_raw.get("api_key_env") or "OPENAI_API_KEY").strip(),
        llm_base_url=str(llm_raw.get("base_url") or "https://api.openai.com").strip().rstrip("/"),
        llm_include_screenshot=bool(llm_raw.get("include_screenshot", True)),
        llm_image_detail=llm_image_detail,
        llm_max_observed_strings=_as_positive_int(
            llm_raw.get("max_observed_strings", 120),
            field="max_observed_strings",
            context=f"{context}: decision_engine.llm",
        ),
        llm_failure_mode=llm_failure_mode,
    )


def _parse_natural_language_query(query: Optional[str]) -> NLDirective:
    if not query or not query.strip():
        return NLDirective(query=None, goal="swipe", force_action_once=None, overrides={})

    q = query.strip()
    lowered = q.lower()
    overrides: dict[str, Any] = {}
    force_action_once: Optional[str] = None
    goal = "swipe"

    if "explore" in lowered or "free form" in lowered or "freely navigate" in lowered:
        goal = "explore"

    # One-shot navigation directives.
    if "go to matches" in lowered:
        force_action_once = "goto_matches"
    elif "go to discover" in lowered:
        force_action_once = "goto_discover"
    elif "go to likes" in lowered or "go to likes you" in lowered:
        force_action_once = "goto_likes_you"
    elif "go to standouts" in lowered:
        force_action_once = "goto_standouts"
    elif "go to profile" in lowered:
        force_action_once = "goto_profile_hub"
    elif "go back" in lowered or "press back" in lowered:
        force_action_once = "back"
    elif "dismiss overlay" in lowered or "close overlay" in lowered:
        force_action_once = "dismiss_overlay"
    elif "open thread now" in lowered or "force open thread" in lowered:
        force_action_once = "open_thread"
    elif "send message now" in lowered or "force send message" in lowered:
        force_action_once = "send_message"
    elif "like now" in lowered or "force like" in lowered:
        force_action_once = "like"
    elif "pass now" in lowered or "force pass" in lowered:
        force_action_once = "pass"
    elif "wait now" in lowered or "force wait" in lowered or "do nothing now" in lowered:
        force_action_once = "wait"

    if "message" in lowered and "don't message" not in lowered and "do not message" not in lowered:
        goal = "message"
    if "swipe" in lowered:
        goal = "swipe"

    # Runtime/action limits.
    m_actions = re.search(r"(?:for\s+)?(\d+)\s+actions", lowered)
    if m_actions:
        overrides["max_actions"] = int(m_actions.group(1))

    m_likes = re.search(r"max\s+likes?\s+(\d+)", lowered)
    if m_likes:
        overrides["max_likes"] = int(m_likes.group(1))

    m_passes = re.search(r"max\s+passes?\s+(\d+)", lowered)
    if m_passes:
        overrides["max_passes"] = int(m_passes.group(1))

    m_messages = re.search(r"max\s+messages?\s+(\d+)", lowered)
    if m_messages:
        overrides["max_messages"] = int(m_messages.group(1))

    m_score = re.search(r"(?:score|quality)\s*(?:>=|above|over)?\s*(\d{1,3})", lowered)
    if m_score:
        overrides["min_quality_score_like"] = int(m_score.group(1))

    m_minutes = re.search(r"for\s+(\d+)\s+minutes?", lowered)
    if m_minutes:
        overrides["max_runtime_s"] = int(m_minutes.group(1)) * 60

    m_seconds = re.search(r"for\s+(\d+)\s+seconds?", lowered)
    if m_seconds:
        overrides["max_runtime_s"] = int(m_seconds.group(1))

    if "dry run" in lowered:
        overrides["dry_run"] = True
    if "live run" in lowered or "execute" in lowered:
        overrides["dry_run"] = False

    if "don't message" in lowered or "do not message" in lowered:
        overrides["message_enabled"] = False
    elif "message" in lowered:
        overrides["message_enabled"] = True

    return NLDirective(
        query=q,
        goal=goal,
        force_action_once=force_action_once,
        overrides=overrides,
    )


def _apply_directive_overrides(
    *,
    directive: NLDirective,
    profile: HingeAgentProfile,
    max_runtime_s: int,
    max_actions: int,
    dry_run: bool,
) -> tuple[HingeAgentProfile, int, int, bool]:
    swipe = profile.swipe_policy
    message = profile.message_policy

    if "min_quality_score_like" in directive.overrides:
        swipe = HingeSwipePolicy(
            min_quality_score_like=int(directive.overrides["min_quality_score_like"]),
            require_flags_all=set(swipe.require_flags_all),
            block_prompt_keywords=list(swipe.block_prompt_keywords),
            max_likes=swipe.max_likes,
            max_passes=swipe.max_passes,
        )

    if "max_likes" in directive.overrides:
        swipe = HingeSwipePolicy(
            min_quality_score_like=swipe.min_quality_score_like,
            require_flags_all=set(swipe.require_flags_all),
            block_prompt_keywords=list(swipe.block_prompt_keywords),
            max_likes=int(directive.overrides["max_likes"]),
            max_passes=swipe.max_passes,
        )

    if "max_passes" in directive.overrides:
        swipe = HingeSwipePolicy(
            min_quality_score_like=swipe.min_quality_score_like,
            require_flags_all=set(swipe.require_flags_all),
            block_prompt_keywords=list(swipe.block_prompt_keywords),
            max_likes=swipe.max_likes,
            max_passes=int(directive.overrides["max_passes"]),
        )

    if "message_enabled" in directive.overrides:
        message = HingeMessagePolicy(
            enabled=bool(directive.overrides["message_enabled"]),
            min_quality_score_to_message=message.min_quality_score_to_message,
            max_messages=message.max_messages,
            template=message.template,
        )

    if "max_messages" in directive.overrides:
        message = HingeMessagePolicy(
            enabled=message.enabled,
            min_quality_score_to_message=message.min_quality_score_to_message,
            max_messages=int(directive.overrides["max_messages"]),
            template=message.template,
        )

    profile = HingeAgentProfile(
        name=profile.name,
        persona_spec=profile.persona_spec,
        swipe_policy=swipe,
        message_policy=message,
        llm_criteria=dict(profile.llm_criteria),
    )

    if "max_runtime_s" in directive.overrides:
        max_runtime_s = int(directive.overrides["max_runtime_s"])
    if "max_actions" in directive.overrides:
        max_actions = int(directive.overrides["max_actions"])
    if "dry_run" in directive.overrides:
        dry_run = bool(directive.overrides["dry_run"])

    return profile, max_runtime_s, max_actions, dry_run


def _build_available_actions(
    *,
    screen_type: str,
    client: AppiumHTTPClient,
    locators: dict[str, list[Locator]],
    message_enabled: bool,
) -> list[str]:
    available: set[str] = {"wait"}
    available.add("back")
    has_like = _has_any(client, locators=locators.get("like", []))
    has_pass = _has_any(client, locators=locators.get("pass", []))
    has_message_input = _has_any(client, locators=locators.get("message_input", []))
    has_send = _has_any(client, locators=locators.get("send", []))
    discover_message_input_locators = locators.get("discover_message_input", [])
    discover_send_locators = locators.get("discover_send", [])
    discover_message_configured = bool(discover_message_input_locators) and bool(discover_send_locators)
    has_discover_message_input = _has_any(client, locators=discover_message_input_locators)
    has_discover_send = _has_any(client, locators=discover_send_locators)
    discover_surface_signals = has_like or has_pass or has_discover_message_input or has_discover_send
    has_overlay_close = _has_any(client, locators=locators.get("overlay_close", []))

    if _has_any(client, locators=locators.get("discover_tab", [])):
        available.add("goto_discover")
    if _has_any(client, locators=locators.get("matches_tab", [])):
        available.add("goto_matches")
    if _has_any(client, locators=locators.get("likes_you_tab", [])):
        available.add("goto_likes_you")
    if _has_any(client, locators=locators.get("standouts_tab", [])):
        available.add("goto_standouts")
    if _has_any(client, locators=locators.get("profile_hub_tab", [])):
        available.add("goto_profile_hub")

    if screen_type == "hinge_discover_card":
        if has_like:
            available.add("like")
        if has_pass:
            available.add("pass")
        # Discover can support comment+like messaging on some UI variants.
        if message_enabled and has_like and (discover_message_configured or (has_message_input and has_send)):
            available.add("send_message")

    if screen_type in {"hinge_tab_shell", "hinge_matches_empty"} and not discover_surface_signals:
        if _has_any(client, locators=locators.get("open_thread", [])):
            available.add("open_thread")

    if screen_type == "hinge_chat" and message_enabled:
        if has_message_input and has_send:
            available.add("send_message")
    if screen_type in {"hinge_overlay_rose_sheet", "hinge_like_paywall"} and has_overlay_close:
        available.add("dismiss_overlay")

    return sorted(available)


def _deterministic_decide(
    *,
    packet: dict[str, Any],
    profile: HingeAgentProfile,
    state: _RuntimeState,
    directive: NLDirective,
) -> tuple[str, str, Optional[str]]:
    available = set(packet["available_actions"])
    screen_type = str(packet["screen_type"])
    score = int(packet["quality_score_v1"])
    quality_features = packet["quality_features"]
    flags = set(quality_features.get("quality_flags") or [])
    prompt_answer = str(quality_features.get("prompt_answer") or "").lower()

    if directive.force_action_once and not state.force_action_consumed:
        forced = directive.force_action_once
        if forced in available:
            state.force_action_consumed = True
            return forced, "natural_language_forced_action", None

        # Route toward prerequisite surfaces when the requested force action
        # is not immediately available.
        if forced == "send_message":
            if screen_type in {"hinge_overlay_rose_sheet", "hinge_like_paywall"}:
                if "dismiss_overlay" in available:
                    return "dismiss_overlay", "forced_send_message_overlay_recovery_dismiss", None
                if "back" in available:
                    return "back", "forced_send_message_overlay_recovery_back", None
            if "goto_discover" in available:
                return "goto_discover", "forced_send_message_route_discover", None
            if "open_thread" in available:
                return "open_thread", "forced_send_message_route_open_thread", None
            if "goto_matches" in available:
                return "goto_matches", "forced_send_message_route_matches", None
        if forced == "open_thread":
            if "goto_matches" in available:
                return "goto_matches", "forced_open_thread_route_matches", None
        if forced in {"like", "pass"}:
            if "goto_discover" in available:
                return "goto_discover", f"forced_{forced}_route_discover", None

    if directive.goal == "explore":
        if screen_type == "hinge_overlay_rose_sheet":
            if "dismiss_overlay" in available:
                return "dismiss_overlay", "explore_overlay_recovery_dismiss", None
            if "back" in available:
                return "back", "explore_overlay_recovery_back", None
        if screen_type == "hinge_discover_card":
            blocked = any(k in prompt_answer for k in profile.swipe_policy.block_prompt_keywords if k)
            has_required_flags = profile.swipe_policy.require_flags_all.issubset(flags)
            if (
                profile.message_policy.enabled
                and state.messages < profile.message_policy.max_messages
                and "send_message" in available
                and score >= profile.message_policy.min_quality_score_to_message
                and has_required_flags
                and not blocked
            ):
                text = _normalize_message_text(
                    raw_text=_render_template(
                        profile.message_policy.template,
                        name=quality_features.get("profile_name_candidate"),
                    ),
                    profile=profile,
                    quality_features=quality_features,
                )
                return "send_message", "explore_discover_message_opportunity", text
            if (
                score >= profile.swipe_policy.min_quality_score_like
                and has_required_flags
                and not blocked
                and "like" in available
                and state.likes < profile.swipe_policy.max_likes
            ):
                return "like", "explore_scored_like", None
            if "pass" in available and state.passes < profile.swipe_policy.max_passes:
                return "pass", "explore_fallback_pass", None

        if (
            profile.message_policy.enabled
            and state.messages < profile.message_policy.max_messages
            and screen_type != "hinge_discover_card"
        ):
            if "send_message" in available:
                text = _normalize_message_text(
                    raw_text=_render_template(
                        profile.message_policy.template,
                        name=quality_features.get("profile_name_candidate"),
                    ),
                    profile=profile,
                    quality_features=quality_features,
                )
                return "send_message", "explore_message_opportunity", text
            if "open_thread" in available:
                return "open_thread", "explore_open_thread", None

        nav_cycle = ["goto_matches", "goto_likes_you", "goto_standouts", "goto_profile_hub", "goto_discover"]
        for offset in range(len(nav_cycle)):
            idx = (state.explore_nav_index + offset) % len(nav_cycle)
            candidate = nav_cycle[idx]
            if candidate in available and candidate != state.last_action:
                state.explore_nav_index = (idx + 1) % len(nav_cycle)
                return candidate, "explore_nav_cycle", None

        for candidate in sorted(available):
            if candidate != "wait" and candidate != state.last_action:
                return candidate, "explore_any_available", None
        return "wait", "explore_wait", None

    if directive.goal == "message":
        if state.consecutive_validation_failures >= 2:
            if screen_type == "hinge_discover_card" and "back" in available:
                return "back", "message_goal_validation_recovery_back", None
            if "goto_discover" in available:
                return "goto_discover", "message_goal_validation_recovery_discover", None
        if screen_type == "hinge_overlay_rose_sheet":
            if "dismiss_overlay" in available:
                return "dismiss_overlay", "message_goal_overlay_recovery_dismiss", None
            if "back" in available:
                return "back", "message_goal_overlay_recovery_back", None
        if screen_type == "hinge_like_paywall":
            if "dismiss_overlay" in available:
                return "dismiss_overlay", "message_goal_like_paywall_recovery_dismiss", None
            if "back" in available:
                return "back", "message_goal_like_paywall_recovery_back", None
        if screen_type == "hinge_discover_card":
            if state.consecutive_validation_failures >= 2 and "back" in available:
                return "back", "message_goal_discover_validation_recovery_back", None
            if "send_message" in available and state.messages < profile.message_policy.max_messages:
                text = _normalize_message_text(
                    raw_text=_render_template(
                        profile.message_policy.template,
                        name=quality_features.get("profile_name_candidate"),
                    ),
                    profile=profile,
                    quality_features=quality_features,
                )
                return "send_message", "message_goal_discover_message_surface", text
            if "goto_matches" in available:
                return "goto_matches", "message_goal_route_matches", None
        if screen_type == "hinge_matches_empty":
            if "goto_discover" in available:
                return "goto_discover", "message_goal_no_matches_route_discover", None
            return "wait", "message_goal_no_matches_available", None
        if screen_type == "hinge_tab_shell" and "goto_discover" in available:
            return "goto_discover", "message_goal_tab_shell_route_discover", None
        if "send_message" in available and state.messages < profile.message_policy.max_messages:
            text = _normalize_message_text(
                raw_text=_render_template(
                    profile.message_policy.template,
                    name=quality_features.get("profile_name_candidate"),
                ),
                profile=profile,
                quality_features=quality_features,
            )
            return "send_message", "message_goal_chat_surface", text
        if "open_thread" in available:
            return "open_thread", "message_goal_open_thread", None
        if "goto_matches" in available:
            return "goto_matches", "message_goal_navigate_matches", None
        if "goto_discover" in available:
            return "goto_discover", "message_goal_fallback_discover", None
        if "back" in available:
            return "back", "message_goal_back_recovery", None
        return "wait", "message_goal_no_action_available", None

    if screen_type == "hinge_discover_card":
        blocked = any(k in prompt_answer for k in profile.swipe_policy.block_prompt_keywords if k)
        has_required_flags = profile.swipe_policy.require_flags_all.issubset(flags)

        if state.likes >= profile.swipe_policy.max_likes:
            if "pass" in available and state.passes < profile.swipe_policy.max_passes:
                return "pass", "like_quota_exhausted", None
            return "wait", "like_quota_exhausted_no_pass", None

        if blocked:
            if "pass" in available and state.passes < profile.swipe_policy.max_passes:
                return "pass", "blocked_prompt_keyword", None
            return "wait", "blocked_prompt_keyword_no_pass", None

        if not has_required_flags:
            if "pass" in available and state.passes < profile.swipe_policy.max_passes:
                return "pass", "required_flags_missing", None
            return "wait", "required_flags_missing_no_pass", None

        if (
            profile.message_policy.enabled
            and state.messages < profile.message_policy.max_messages
            and "send_message" in available
            and score >= profile.message_policy.min_quality_score_to_message
        ):
            text = _normalize_message_text(
                raw_text=_render_template(
                    profile.message_policy.template,
                    name=quality_features.get("profile_name_candidate"),
                ),
                profile=profile,
                quality_features=quality_features,
            )
            return "send_message", "discover_profile_message_policy", text

        if score >= profile.swipe_policy.min_quality_score_like and "like" in available:
            return "like", f"score>={profile.swipe_policy.min_quality_score_like}", None

        if "pass" in available and state.passes < profile.swipe_policy.max_passes:
            return "pass", f"score<{profile.swipe_policy.min_quality_score_like}", None

        if "back" in available:
            return "back", "discover_no_pass_recovery_back", None

        return "wait", "no_like_or_pass_available", None

    if screen_type == "hinge_overlay_rose_sheet":
        if "dismiss_overlay" in available:
            return "dismiss_overlay", "swipe_goal_overlay_recovery_dismiss", None
        if "back" in available:
            return "back", "swipe_goal_overlay_recovery_back", None
    if screen_type == "hinge_like_paywall":
        if "dismiss_overlay" in available:
            return "dismiss_overlay", "swipe_goal_like_paywall_recovery_dismiss", None
        if "back" in available:
            return "back", "swipe_goal_like_paywall_recovery_back", None

    if screen_type == "hinge_chat":
        if (
            profile.message_policy.enabled
            and state.messages < profile.message_policy.max_messages
            and "send_message" in available
            and score >= profile.message_policy.min_quality_score_to_message
        ):
            text = _normalize_message_text(
                raw_text=_render_template(
                    profile.message_policy.template,
                    name=quality_features.get("profile_name_candidate"),
                ),
                profile=profile,
                quality_features=quality_features,
            )
            return "send_message", "chat_surface_profile_message_policy", text
        if "goto_discover" in available:
            return "goto_discover", "chat_surface_return_discover", None
        if "back" in available:
            return "back", "chat_surface_back", None
        return "wait", "chat_surface_no_available_navigation", None

    if "goto_discover" in available:
        return "goto_discover", "default_route_discover", None
    if screen_type == "hinge_unknown" and "back" in available:
        return "back", "unknown_surface_recovery_back", None

    return "wait", "default_wait", None


def _extract_first_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise LiveHingeAgentError("LLM response was empty")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise LiveHingeAgentError("Could not find JSON object in LLM response")
    segment = text[start : end + 1]
    try:
        parsed = json.loads(segment)
    except Exception as e:
        raise LiveHingeAgentError(f"Failed to parse JSON decision from LLM: {e}") from e
    if not isinstance(parsed, dict):
        raise LiveHingeAgentError("LLM decision JSON must be an object")
    return parsed


def _llm_decide(
    *,
    packet: dict[str, Any],
    profile: HingeAgentProfile,
    decision_engine: DecisionEngineConfig,
    nl_query: Optional[str],
    screenshot_png_bytes: Optional[bytes],
) -> tuple[str, str, Optional[str]]:
    if not decision_engine.llm_model:
        raise LiveHingeAgentError("decision_engine.llm.model is required when type='llm'")

    # Prefer explicit exported env vars, but support local `.env` for developer experience.
    ensure_dotenv_loaded()
    api_key = os.environ.get(decision_engine.llm_api_key_env, "").strip()
    if not api_key:
        raise LiveHingeAgentError(
            f"Missing API key env var {decision_engine.llm_api_key_env!r} required for llm decision engine"
        )

    available_actions = packet["available_actions"]
    packet_for_llm = dict(packet)
    observed_strings = packet_for_llm.get("observed_strings", [])
    if isinstance(observed_strings, list):
        packet_for_llm["observed_strings"] = observed_strings[: decision_engine.llm_max_observed_strings]

    user_payload = {
        "available_actions": available_actions,
        "action_catalog": get_hinge_action_catalog(),
        "command_query": nl_query,
        "profile": {
            "name": profile.name,
            "persona_spec": {
                "archetype": profile.persona_spec.archetype,
                "intent": profile.persona_spec.intent,
                "tone_traits": profile.persona_spec.tone_traits,
                "hard_boundaries": profile.persona_spec.hard_boundaries,
                "preferred_signals": profile.persona_spec.preferred_signals,
                "avoid_signals": profile.persona_spec.avoid_signals,
                "opener_strategy": profile.persona_spec.opener_strategy,
                "examples": profile.persona_spec.examples,
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
            "llm_criteria": profile.llm_criteria,
        },
        "packet": packet_for_llm,
    }

    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": json.dumps(user_payload, ensure_ascii=False),
        }
    ]
    if screenshot_png_bytes is not None and decision_engine.llm_include_screenshot:
        data_url = "data:image/png;base64," + base64.b64encode(screenshot_png_bytes).decode("ascii")
        user_content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": data_url,
                    "detail": decision_engine.llm_image_detail,
                },
            }
        )

    payload = {
        "model": decision_engine.llm_model,
        "temperature": float(decision_engine.llm_temperature),
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an autonomous Hinge action selector and first-message writer. "
                    "Decide the safest next action for the current screen. "
                    "Return strict JSON with keys: action (string), reason (string), message_text (string|null). "
                    "Action must be exactly one of available_actions. "
                    "Respect profile persona_spec and hard_boundaries. "
                    "If action is send_message, provide concise message_text that follows opener_strategy "
                    "and max_message_chars. If action is not send_message, message_text must be null. "
                    "Do not include any additional keys."
                ),
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
    }

    url = f"{decision_engine.llm_base_url}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=float(decision_engine.llm_timeout_s),
        )
    except Exception as e:
        raise LiveHingeAgentError(f"LLM API request failed: {e}") from e

    body: dict[str, Any]
    try:
        body = response.json()
    except Exception as e:
        raise LiveHingeAgentError(f"LLM API returned non-JSON response: {e}") from e

    if response.status_code >= 400:
        raise LiveHingeAgentError(f"LLM API error {response.status_code}: {body}")

    try:
        content = body["choices"][0]["message"]["content"]
    except Exception as e:
        raise LiveHingeAgentError(f"Unexpected LLM response shape: {body}") from e

    parsed = _extract_first_json_object(str(content))
    action = _as_non_empty_str(parsed.get("action"), field="action", context="llm_decision")
    reason = _as_non_empty_str(parsed.get("reason") or "llm_selected_action", field="reason", context="llm_decision")
    message_text_raw = parsed.get("message_text")
    message_text = None
    if message_text_raw is not None:
        message_text = _as_non_empty_str(message_text_raw, field="message_text", context="llm_decision")

    if action not in available_actions:
        raise LiveHingeAgentError(
            f"LLM selected unavailable action {action!r}. available_actions={available_actions}"
        )

    if action == "send_message":
        message_text = _normalize_message_text(
            raw_text=message_text,
            profile=profile,
            quality_features=packet.get("quality_features") or {},
        )
    elif message_text is not None:
        # Keep the log shape deterministic for non-message actions.
        message_text = None

    return action, reason, message_text


def run_live_hinge_agent(*, config_json_path: str) -> LiveHingeAgentResult:
    """
    Single-session live Hinge controller driven by profile policy and optional LLM decisions.

    Config schema:
      {
        "appium_server_url": "http://127.0.0.1:4723",
        "capabilities_json_path": "automation_service/mobile_examples/android_capabilities.example.json",
        "profile_json_path": "automation_service/mobile_examples/hinge_agent_profile.example.json",
        "command_query": "swipe for 20 actions and message high quality matches",
        "decision_engine": {
          "type": "deterministic",
          "llm_failure_mode": "fail",
          "llm": {
            "model": "gpt-4.1-mini",
            "temperature": 0.1,
            "timeout_s": 30,
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com",
            "include_screenshot": true,
            "image_detail": "auto",
            "max_observed_strings": 120
          }
        },
        "artifacts_dir": "artifacts/live_hinge",
        "target_package": "co.hinge.app",
        "target_activity": ".ui.AppActivity",
        "foreground_recovery": {
          "enabled": true,
          "max_attempts": 3,
          "cooldown_s": 1.0
        },
        "pause_before_start": true,
        "dry_run": true,
        "max_runtime_s": 300,
        "max_actions": 30,
        "loop_sleep_s": 1.0,
        "capture_each_action": true,
        "persist_packet_log": true,
        "packet_capture_screenshot": true,
        "packet_capture_xml": false,
        "validation": {
          "enabled": true,
          "post_action_sleep_s": 0.8,
          "require_screen_change_for": ["like", "pass", "open_thread", "send_message", "back", "dismiss_overlay"],
          "max_consecutive_failures": 4
        },
        "locators": {
          "discover_tab": [...],
          "matches_tab": [...],
          "likes_you_tab": [...],
          "standouts_tab": [...],
          "profile_hub_tab": [...],
          "like": [...],
          "pass": [...],
          "open_thread": [...],
          "message_input": [...],
          "send": [...],
          "overlay_close": [...],
          "discover_message_input": [...],
          "discover_send": [...]
        }
      }
    """
    config = load_json_file(config_json_path)
    context = config_json_path

    appium_server_url = _as_non_empty_str(
        require_key(config, "appium_server_url", context=context),
        field="appium_server_url",
        context=context,
    )
    capabilities_json_path = _as_non_empty_str(
        require_key(config, "capabilities_json_path", context=context),
        field="capabilities_json_path",
        context=context,
    )
    profile_json_path = _as_non_empty_str(
        require_key(config, "profile_json_path", context=context),
        field="profile_json_path",
        context=context,
    )

    decision_engine = _parse_decision_engine(config.get("decision_engine"), context=f"{context}: decision_engine")
    directive = _parse_natural_language_query(config.get("command_query"))

    locators_raw = require_key(config, "locators", context=context)
    if not isinstance(locators_raw, dict):
        raise LiveHingeAgentError(f"{context}: 'locators' must be an object")

    locator_map: dict[str, list[Locator]] = {
        "discover_tab": _parse_locators(locators_raw.get("discover_tab"), field="discover_tab", context=context, required=True),
        "matches_tab": _parse_locators(locators_raw.get("matches_tab"), field="matches_tab", context=context, required=True),
        "likes_you_tab": _parse_locators(locators_raw.get("likes_you_tab"), field="likes_you_tab", context=context, required=False),
        "standouts_tab": _parse_locators(locators_raw.get("standouts_tab"), field="standouts_tab", context=context, required=False),
        "profile_hub_tab": _parse_locators(locators_raw.get("profile_hub_tab"), field="profile_hub_tab", context=context, required=False),
        "like": _parse_locators(locators_raw.get("like"), field="like", context=context, required=True),
        "pass": _parse_locators(locators_raw.get("pass"), field="pass", context=context, required=True),
        "open_thread": _parse_locators(locators_raw.get("open_thread"), field="open_thread", context=context, required=True),
        "message_input": _parse_locators(locators_raw.get("message_input"), field="message_input", context=context, required=True),
        "send": _parse_locators(locators_raw.get("send"), field="send", context=context, required=True),
        "overlay_close": _parse_locators(
            locators_raw.get("overlay_close"),
            field="overlay_close",
            context=context,
            required=False,
        ),
        "discover_message_input": _parse_locators(
            locators_raw.get("discover_message_input"),
            field="discover_message_input",
            context=context,
            required=False,
        ),
        "discover_send": _parse_locators(
            locators_raw.get("discover_send"),
            field="discover_send",
            context=context,
            required=False,
        ),
    }

    artifacts_dir = Path(str(config.get("artifacts_dir") or "artifacts/live_hinge")).resolve()
    _ensure_dir(artifacts_dir)
    target_package = _as_non_empty_str(
        config.get("target_package") or "co.hinge.app",
        field="target_package",
        context=context,
    )
    target_activity = _as_non_empty_str(
        config.get("target_activity") or ".ui.AppActivity",
        field="target_activity",
        context=context,
    )
    foreground_recovery_raw = config.get("foreground_recovery", {})
    if foreground_recovery_raw is None:
        foreground_recovery_raw = {}
    if not isinstance(foreground_recovery_raw, dict):
        raise LiveHingeAgentError(f"{context}: foreground_recovery must be an object when provided")
    foreground_recovery_enabled = bool(foreground_recovery_raw.get("enabled", True))
    foreground_recovery_max_attempts = _as_positive_int(
        foreground_recovery_raw.get("max_attempts", 3),
        field="max_attempts",
        context=f"{context}: foreground_recovery",
    )
    foreground_recovery_cooldown_s = _as_non_negative_float(
        foreground_recovery_raw.get("cooldown_s", 1.0),
        field="cooldown_s",
        context=f"{context}: foreground_recovery",
    )

    dry_run = bool(config.get("dry_run", True))
    pause_before_start = bool(config.get("pause_before_start", False))
    max_runtime_s = _as_positive_int(config.get("max_runtime_s", 300), field="max_runtime_s", context=context)
    max_actions = _as_positive_int(config.get("max_actions", 30), field="max_actions", context=context)
    loop_sleep_s = _as_non_negative_float(config.get("loop_sleep_s", 1.0), field="loop_sleep_s", context=context)
    capture_each_action = bool(config.get("capture_each_action", True))
    persist_packet_log = bool(config.get("persist_packet_log", True))
    packet_capture_screenshot = bool(
        config.get(
            "packet_capture_screenshot",
            decision_engine.type == "llm" and decision_engine.llm_include_screenshot,
        )
    )
    packet_capture_xml = bool(config.get("packet_capture_xml", False))
    validation_raw = config.get("validation", {})
    if validation_raw is None:
        validation_raw = {}
    if not isinstance(validation_raw, dict):
        raise LiveHingeAgentError(f"{context}: validation must be an object when provided")
    validation_enabled = bool(validation_raw.get("enabled", True))
    validation_post_action_sleep_s = _as_non_negative_float(
        validation_raw.get("post_action_sleep_s", 0.8),
        field="post_action_sleep_s",
        context=f"{context}: validation",
    )
    require_screen_change_for_raw = validation_raw.get(
        "require_screen_change_for",
        ["like", "pass", "open_thread", "send_message", "back", "dismiss_overlay"],
    )
    if (
        not isinstance(require_screen_change_for_raw, list)
        or not all(isinstance(x, str) and x.strip() for x in require_screen_change_for_raw)
    ):
        raise LiveHingeAgentError(
            f"{context}: validation.require_screen_change_for must be a list of non-empty strings"
        )
    require_screen_change_for = {x.strip() for x in require_screen_change_for_raw}
    max_consecutive_validation_failures = _as_positive_int(
        validation_raw.get("max_consecutive_failures", 4),
        field="max_consecutive_failures",
        context=f"{context}: validation",
    )

    capabilities_payload = load_json_file(capabilities_json_path)
    require_key(capabilities_payload, "capabilities", context=capabilities_json_path)

    profile = _load_profile(profile_json_path)
    profile, max_runtime_s, max_actions, dry_run = _apply_directive_overrides(
        directive=directive,
        profile=profile,
        max_runtime_s=max_runtime_s,
        max_actions=max_actions,
        dry_run=dry_run,
    )

    client = AppiumHTTPClient(appium_server_url)
    session_id = client.create_session(capabilities_payload)
    started = time.time()
    state = _RuntimeState()
    packet_log_path: Optional[Path] = None
    packet_log_fh = None
    # Keep decision packet artifacts per-run so repeated runs don't overwrite evidence.
    run_artifact_tag = f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}_{session_id[:8]}"
    packet_artifacts_dir = artifacts_dir / "decision_packets" / run_artifact_tag
    outside_target_package_streak = 0
    if packet_capture_screenshot or packet_capture_xml or persist_packet_log:
        _ensure_dir(packet_artifacts_dir)

    action_to_locator_key: dict[str, str] = {
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

    try:
        print("\n=== Live Hinge Agent ===")
        print(f"Config: {Path(config_json_path).resolve()}")
        print(f"Profile: {profile.name}")
        print(f"Decision engine: {decision_engine.type}")
        if directive.query:
            print(f"Command query: {directive.query}")
            print(f"Directive goal: {directive.goal}")
            print(f"Directive overrides: {directive.overrides}")
        print(f"Session started: {session_id}")
        print(f"Dry run: {dry_run}")
        if pause_before_start:
            input("Session started. Open Hinge in emulator and press Enter to start live loop...")
        if persist_packet_log:
            packet_log_path = _artifact_path(artifacts_dir=artifacts_dir, stem="hinge_live_packet_log", ext="jsonl")
            packet_log_fh = packet_log_path.open("w", encoding="utf-8")

        while state.iterations < max_actions and (time.time() - started) <= max_runtime_s:
            state.iterations += 1
            iteration_idx = state.iterations
            step_ts = datetime.now().isoformat()

            xml = client.get_page_source()
            packet_xml_path: Optional[Path] = None
            if packet_capture_xml:
                packet_xml_path = packet_artifacts_dir / f"packet_{iteration_idx:04d}.xml"
                packet_xml_path.write_text(xml, encoding="utf-8")
                state.artifacts.append(packet_xml_path)

            llm_screenshot_png_bytes: Optional[bytes] = None
            packet_screenshot_path: Optional[Path] = None
            if packet_capture_screenshot or (decision_engine.type == "llm" and decision_engine.llm_include_screenshot):
                llm_screenshot_png_bytes = client.get_screenshot_png_bytes()
                if packet_capture_screenshot:
                    packet_screenshot_path = packet_artifacts_dir / f"packet_{iteration_idx:04d}.png"
                    packet_screenshot_path.write_bytes(llm_screenshot_png_bytes)
                    state.artifacts.append(packet_screenshot_path)

            package_name = _extract_package_name(xml)
            strings = extract_accessible_strings(xml, limit=2500)
            screen_type = _classify_hinge_screen(strings)
            quality_features = _extract_quality_features(strings)
            score = _score_quality(screen_type=screen_type, quality_features=quality_features)
            pre_fingerprint = _screen_fingerprint(
                screen_type=screen_type,
                quality_features=quality_features,
                strings=strings,
            )

            if package_name != target_package:
                outside_target_package_streak += 1
                recovery_attempted = False
                recovery_status = "disabled"
                recovery_component = None
                if foreground_recovery_enabled and outside_target_package_streak <= foreground_recovery_max_attempts:
                    recovery_attempted = True
                    try:
                        recovery_component = _adb_start_activity(
                            package_name=target_package,
                            activity_name=target_activity,
                        )
                        recovery_status = "launched"
                    except Exception as e:
                        recovery_status = f"launch_failed:{e}"
                    if foreground_recovery_cooldown_s > 0:
                        time.sleep(foreground_recovery_cooldown_s)
                elif foreground_recovery_enabled:
                    recovery_status = "max_attempts_exceeded"

                event = {
                    "ts": step_ts,
                    "iteration": iteration_idx,
                    "package_name": package_name,
                    "target_package": target_package,
                    "screen_type": screen_type,
                    "decision": "wait",
                    "reason": "not_in_target_package",
                    "foreground_recovery": {
                        "enabled": foreground_recovery_enabled,
                        "attempted": recovery_attempted,
                        "status": recovery_status,
                        "component": recovery_component,
                        "outside_target_package_streak": outside_target_package_streak,
                    },
                    "packet_screenshot_path": None if packet_screenshot_path is None else str(packet_screenshot_path),
                    "packet_xml_path": None if packet_xml_path is None else str(packet_xml_path),
                }
                state.action_log.append(event)
                if packet_log_fh is not None:
                    packet_log_fh.write(json.dumps(event, ensure_ascii=False) + "\n")
                print(
                    f"[{iteration_idx}] wait: package={package_name!r} "
                    f"(expect {target_package!r}) recovery={recovery_status}"
                )
                time.sleep(loop_sleep_s)
                continue
            outside_target_package_streak = 0

            available_actions = _build_available_actions(
                screen_type=screen_type,
                client=client,
                locators=locator_map,
                message_enabled=profile.message_policy.enabled,
            )

            packet = {
                "ts": step_ts,
                "screen_type": screen_type,
                "package_name": package_name,
                "quality_score_v1": score,
                "quality_features": quality_features,
                "available_actions": available_actions,
                "observed_strings": strings[:120],
                "packet_screenshot_path": None if packet_screenshot_path is None else str(packet_screenshot_path),
                "packet_xml_path": None if packet_xml_path is None else str(packet_xml_path),
                "limits": {
                    "likes_remaining": max(profile.swipe_policy.max_likes - state.likes, 0),
                    "passes_remaining": max(profile.swipe_policy.max_passes - state.passes, 0),
                    "messages_remaining": max(profile.message_policy.max_messages - state.messages, 0),
                },
            }

            action = "wait"
            reason = "no_action"
            message_text: Optional[str] = None

            if decision_engine.type == "deterministic":
                action, reason, message_text = _deterministic_decide(
                    packet=packet,
                    profile=profile,
                    state=state,
                    directive=directive,
                )
            else:
                try:
                    action, reason, message_text = _llm_decide(
                        packet=packet,
                        profile=profile,
                        decision_engine=decision_engine,
                        nl_query=directive.query,
                        screenshot_png_bytes=llm_screenshot_png_bytes,
                    )
                except Exception as e:
                    if decision_engine.llm_failure_mode == "fallback_deterministic":
                        action, reason, message_text = _deterministic_decide(
                            packet=packet,
                            profile=profile,
                            state=state,
                            directive=directive,
                        )
                        reason = f"llm_failed_fallback: {e}; {reason}"
                    else:
                        raise

            matched_locator: Optional[Locator] = None
            validation_status = "skipped"
            validation_reason = "not_run"
            post_screen_type: Optional[str] = None
            post_fingerprint: Optional[str] = None
            try:
                if action == "like":
                    if state.likes >= profile.swipe_policy.max_likes:
                        raise LiveHingeAgentError("like limit reached")
                    if not dry_run:
                        matched_locator = _click_any(client, locators=locator_map["like"])
                    state.likes += 1
                elif action == "pass":
                    if state.passes >= profile.swipe_policy.max_passes:
                        raise LiveHingeAgentError("pass limit reached")
                    if not dry_run:
                        matched_locator = _click_any(client, locators=locator_map["pass"])
                    state.passes += 1
                elif action == "send_message":
                    if state.messages >= profile.message_policy.max_messages:
                        raise LiveHingeAgentError("message limit reached")
                    message_text = _normalize_message_text(
                        raw_text=message_text,
                        profile=profile,
                        quality_features=quality_features,
                    )
                    if not dry_run:
                        if screen_type == "hinge_discover_card":
                            discover_input_locators = locator_map.get("discover_message_input") or locator_map["message_input"]
                            discover_send_locators = locator_map.get("discover_send") or locator_map["send"]
                            like_locator, input_locator, send_locator = _send_discover_message(
                                client,
                                like_locators=locator_map["like"],
                                input_locators=discover_input_locators,
                                send_locators=discover_send_locators,
                                text=message_text,
                            )
                            matched_locator = send_locator
                            reason = (
                                f"{reason}; discover_like={like_locator.using}:{like_locator.value}; "
                                f"input={input_locator.using}:{input_locator.value}"
                            )
                        else:
                            input_locator, send_locator = _send_message(
                                client,
                                input_locators=locator_map["message_input"],
                                send_locators=locator_map["send"],
                                text=message_text,
                            )
                            matched_locator = send_locator
                            reason = f"{reason}; input={input_locator.using}:{input_locator.value}"
                    state.messages += 1
                elif action == "back":
                    if not dry_run:
                        client.press_keycode(keycode=4)
                elif action in action_to_locator_key:
                    key = action_to_locator_key[action]
                    if not dry_run:
                        matched_locator = _click_any(client, locators=locator_map[key])
                elif action == "wait":
                    pass
                else:
                    raise LiveHingeAgentError(f"Unsupported action selected: {action}")
            except Exception as e:
                action = "error"
                reason = str(e)

            if (
                validation_enabled
                and not dry_run
                and action in require_screen_change_for
                and action != "error"
            ):
                if validation_post_action_sleep_s > 0:
                    time.sleep(validation_post_action_sleep_s)
                try:
                    post_xml = client.get_page_source()
                    post_strings = extract_accessible_strings(post_xml, limit=2500)
                    post_screen_type = _classify_hinge_screen(post_strings)
                    post_quality_features = _extract_quality_features(post_strings)
                    post_fingerprint = _screen_fingerprint(
                        screen_type=post_screen_type,
                        quality_features=post_quality_features,
                        strings=post_strings,
                    )
                    # Fingerprint uses a limited string subset; XML comparison catches UI changes
                    # that don't alter accessible strings (for example composer open/close).
                    changed = (
                        (post_xml != xml)
                        or (post_fingerprint != pre_fingerprint)
                        or (post_screen_type != screen_type)
                    )
                    if changed:
                        validation_status = "passed"
                        validation_reason = "screen_changed"
                        state.consecutive_validation_failures = 0
                    else:
                        validation_status = "failed"
                        validation_reason = "screen_unchanged"
                        state.consecutive_validation_failures += 1
                except Exception as e:
                    validation_status = "failed"
                    validation_reason = f"validation_exception:{e}"
                    state.consecutive_validation_failures += 1
            elif validation_enabled and dry_run and action in require_screen_change_for:
                validation_status = "skipped_dry_run"
                validation_reason = "dry_run"
            else:
                validation_status = "skipped"
                validation_reason = "action_not_validated"

            post_action_screenshot_path: Optional[Path] = None
            if capture_each_action:
                post_action_screenshot_path = _artifact_path(
                    artifacts_dir=artifacts_dir,
                    stem=f"hinge_live_{iteration_idx}",
                    ext="png",
                )
                post_action_screenshot_path.write_bytes(client.get_screenshot_png_bytes())
                state.artifacts.append(post_action_screenshot_path)

            event = {
                "ts": step_ts,
                "iteration": iteration_idx,
                "package_name": package_name,
                "screen_type": screen_type,
                "quality_score_v1": score,
                # Keep both the compact fields and the full feature object so downstream
                # evaluation can reproduce packet context without re-parsing XML.
                "quality_flags": quality_features.get("quality_flags") or [],
                "profile_name_candidate": quality_features.get("profile_name_candidate"),
                "quality_features": quality_features,
                "observed_strings": strings[: min(250, len(strings))],
                "decision": action,
                "reason": reason,
                "dry_run": dry_run,
                "available_actions": available_actions,
                "matched_locator": None
                if matched_locator is None
                else {"using": matched_locator.using, "value": matched_locator.value},
                "message_text": message_text,
                "packet_screenshot_path": None if packet_screenshot_path is None else str(packet_screenshot_path),
                "packet_xml_path": None if packet_xml_path is None else str(packet_xml_path),
                "post_action_screenshot_path": None
                if post_action_screenshot_path is None
                else str(post_action_screenshot_path),
                "validation_status": validation_status,
                "validation_reason": validation_reason,
                "pre_fingerprint": pre_fingerprint,
                "post_fingerprint": post_fingerprint,
                "post_screen_type": post_screen_type,
                "consecutive_validation_failures": state.consecutive_validation_failures,
            }
            state.action_log.append(event)
            if packet_log_fh is not None:
                packet_log_fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            state.last_action = action
            print(
                f"[{iteration_idx}] {action} | screen={screen_type} score={score} "
                f"likes={state.likes} passes={state.passes} messages={state.messages}"
            )

            if (
                validation_enabled
                and state.consecutive_validation_failures >= max_consecutive_validation_failures
            ):
                print(
                    f"[{iteration_idx}] stopping: validation failures reached "
                    f"{state.consecutive_validation_failures}/{max_consecutive_validation_failures}"
                )
                break

            time.sleep(loop_sleep_s)

        log_path = _artifact_path(artifacts_dir=artifacts_dir, stem="hinge_live_action_log", ext="json")
        log_path.write_text(json.dumps(state.action_log, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote action log: {log_path}")
        if packet_log_fh is not None:
            packet_log_fh.flush()
            packet_log_fh.close()
            packet_log_fh = None
        if packet_log_path is not None:
            print(f"Wrote packet log: {packet_log_path}")

        return LiveHingeAgentResult(
            session_id=session_id,
            iterations=state.iterations,
            likes=state.likes,
            passes=state.passes,
            messages=state.messages,
            action_log_path=log_path,
            packet_log_path=packet_log_path,
            artifacts=state.artifacts,
        )
    finally:
        if packet_log_fh is not None:
            packet_log_fh.close()
        client.delete_session()
