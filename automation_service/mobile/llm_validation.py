from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from . import live_hinge_agent as lha


_EMAIL_RE = re.compile(r"\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}\\b")
_PHONE_RE = re.compile(r"(?<!\\d)(?:\\+?1\\s*)?(?:\\(\\d{3}\\)|\\d{3})[\\s.-]*\\d{3}[\\s.-]*\\d{4}(?!\\d)")
_HANDLE_RE = re.compile(r"\\b(?:ig|insta|instagram|snap|snapchat|telegram|whatsapp)\\b", re.IGNORECASE)
_URL_RE = re.compile(r"\\bhttps?://\\S+\\b", re.IGNORECASE)

# This is not a moral judgment; it's a narrow first-message safeguard.
_SEXUAL_TERMS = {
    "sex",
    "sexy",
    "hook up",
    "hookup",
    "fwb",
    "nude",
    "nudes",
    "blowjob",
    "bj",
    "oral",
    "sugar daddy",
    "sugar baby",
}


@dataclass(frozen=True)
class DecisionValidation:
    ok: bool
    issues: list[str]
    checks: dict[str, Any]


def _keywordize(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text or "")
    out: list[str] = []
    for w in words:
        lw = w.lower()
        if lw in {
            "the",
            "and",
            "that",
            "this",
            "with",
            "your",
            "you",
            "are",
            "for",
            "but",
            "not",
            "from",
            "have",
            "has",
            "was",
            "were",
            "what",
            "when",
            "where",
            "who",
            "why",
            "how",
            "really",
            "just",
            "like",
        }:
            continue
        out.append(lw)
    return out


def _has_any_term(text: str, terms: set[str]) -> bool:
    lowered = (text or "").lower()
    for t in terms:
        if t in lowered:
            return True
    return False


def validate_decision_output(
    *,
    action: str,
    reason: str,
    message_text: Optional[str],
    target_id: Optional[str],
    packet: dict[str, Any],
    profile: lha.HingeAgentProfile,
) -> DecisionValidation:
    """
    Deterministic validators for LLM output (and for deterministic decisions too).

    These checks are designed to be:
    - cheap (no extra model calls)
    - conservative (flag likely issues, not every stylistic quirk)
    """
    issues: list[str] = []
    checks: dict[str, Any] = {}

    available = packet.get("available_actions") or []
    if not isinstance(available, list):
        available = []

    if not action or not isinstance(action, str):
        issues.append("action_missing_or_not_string")
    else:
        if action not in set(str(x) for x in available):
            issues.append("action_not_in_available_actions")

    if not reason or not isinstance(reason, str):
        issues.append("reason_missing_or_not_string")

    if action == "send_message":
        if message_text is None or not isinstance(message_text, str) or not message_text.strip():
            issues.append("message_text_required_for_send_message")
        else:
            text = message_text.strip()
            checks["message_length"] = len(text)
            if len(text) > profile.persona_spec.max_message_chars:
                issues.append("message_too_long")
            if profile.persona_spec.require_question and "?" not in text:
                issues.append("missing_required_question_mark")

            if _EMAIL_RE.search(text):
                issues.append("contains_email")
            if _PHONE_RE.search(text):
                issues.append("contains_phone_number")
            if _URL_RE.search(text):
                issues.append("contains_url")
            if _HANDLE_RE.search(text):
                issues.append("mentions_off_app_handle")

            boundaries = " ".join(profile.persona_spec.hard_boundaries).lower()
            if "sexual" in boundaries or "sex" in boundaries:
                if _has_any_term(text, _SEXUAL_TERMS):
                    issues.append("possible_sexual_content_violation")
    else:
        if message_text is not None:
            issues.append("message_text_must_be_null_when_not_sending")

    # Targeting checks for per-item Like buttons on Discover.
    screen_type = str(packet.get("screen_type") or "")
    like_candidates = packet.get("like_candidates")
    candidate_ids: set[str] = set()
    if isinstance(like_candidates, list):
        for c in like_candidates:
            if isinstance(c, dict) and isinstance(c.get("target_id"), str) and c.get("target_id"):
                candidate_ids.add(str(c["target_id"]))

    if action in {"like", "send_message"} and screen_type == "hinge_discover_card" and candidate_ids:
        if not isinstance(target_id, str) or not target_id.strip():
            issues.append("target_id_required_for_like_or_send_message_on_discover")
        else:
            checks["target_id_present"] = True
            if target_id not in candidate_ids:
                issues.append("target_id_not_in_like_candidates")
    else:
        if target_id is not None:
            issues.append("target_id_must_be_null_when_not_targeting")

    # Personalization signals (best-effort).
    qf = packet.get("quality_features") if isinstance(packet.get("quality_features"), dict) else {}
    profile_name = qf.get("profile_name_candidate")
    prompt_answer = qf.get("prompt_answer") or ""
    text_for_personalization = (message_text or "").strip()
    checks["mentions_profile_name"] = bool(
        isinstance(profile_name, str)
        and profile_name.strip()
        and profile_name.strip().lower() in text_for_personalization.lower()
    )
    prompt_keywords = _keywordize(str(prompt_answer))
    checks["mentions_prompt_keyword"] = bool(
        prompt_keywords
        and any(k in text_for_personalization.lower() for k in prompt_keywords[:10])
    )

    ok = not issues
    return DecisionValidation(ok=ok, issues=issues, checks=checks)
