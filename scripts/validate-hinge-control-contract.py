#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from automation_service.mobile.appium_http_client import WebDriverElementRef
from automation_service.mobile import hinge_agent_mcp as mcpmod
from automation_service.mobile import live_hinge_agent as lha


DISCOVER_XML = """
<hierarchy>
  <node package="co.hinge.app" text="Discover" />
  <node package="co.hinge.app" text="Skip" />
  <node package="co.hinge.app" text="Like photo" />
  <node package="co.hinge.app" text="Alex's photo" />
  <node package="co.hinge.app" text="Prompt: Ideal Sunday Answer: farmers market then a hike" />
  <node package="co.hinge.app" text="Active today" />
</hierarchy>
""".strip()


class FakeAppiumClient:
    def __init__(self) -> None:
        self.composer_open = False
        self.tapped: list[tuple[int, int]] = []
        self.swipes: list[tuple[int, int, int, int, int]] = []
        self.keys: list[tuple[int, int | None]] = []
        self.clicked_ids: list[str] = []
        self.sent_text: list[tuple[str, str]] = []

    def get_page_source(self) -> str:
        return DISCOVER_XML

    def get_screenshot_png_bytes(self) -> bytes:
        return b"fakepng"

    def find_elements(self, *, using: str, value: str) -> list[WebDriverElementRef]:
        key = (using, value)
        if key == ("accessibility id", "Like photo"):
            return [WebDriverElementRef(element_id="el-like")]
        if key == ("accessibility id", "Skip"):
            return [WebDriverElementRef(element_id="el-pass")]
        if key == ("accessibility id", "Edit comment"):
            if self.composer_open:
                return [WebDriverElementRef(element_id="el-comment")]
            return []
        if key == ("accessibility id", "Send like"):
            if self.composer_open:
                return [WebDriverElementRef(element_id="el-send")]
            return []
        if key == ("accessibility id", "Matches"):
            return [WebDriverElementRef(element_id="el-matches")]
        if key == ("accessibility id", "Discover"):
            return [WebDriverElementRef(element_id="el-discover")]
        if key == ("xpath", "//*[@content-desc='Add a comment']"):
            if self.composer_open:
                return [WebDriverElementRef(element_id="el-comment")]
            return []
        if key == ("xpath", "//*[@text='manual_target']"):
            return [
                WebDriverElementRef(element_id="el-manual-1"),
                WebDriverElementRef(element_id="el-manual-2"),
            ]
        return []

    def click(self, element: WebDriverElementRef) -> None:
        self.clicked_ids.append(element.element_id)
        if element.element_id == "el-like":
            self.composer_open = True

    def send_keys(self, element: WebDriverElementRef, *, text: str) -> None:
        self.sent_text.append((element.element_id, text))

    def tap(self, *, x: int, y: int) -> None:
        self.tapped.append((x, y))

    def swipe(self, *, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 600) -> None:
        self.swipes.append((x1, y1, x2, y2, duration_ms))

    def press_keycode(self, *, keycode: int, metastate: int | None = None) -> None:
        self.keys.append((keycode, metastate))

    def get_element_text(self, element: WebDriverElementRef) -> str:
        return f"text:{element.element_id}"

    def get_element_rect(self, element: WebDriverElementRef) -> dict[str, int]:
        return {"x": 1, "y": 2, "width": 3, "height": 4}

    def delete_session(self) -> None:
        return None


def _profile() -> lha.HingeAgentProfile:
    persona = lha.HingePersonaSpec(
        archetype="intentional_warm_connector",
        intent="Find aligned matches",
        tone_traits=["warm", "direct"],
        hard_boundaries=["No sexual content in first message"],
        preferred_signals=["Specific prompts"],
        avoid_signals=["Hostile tone"],
        opener_strategy="Reference one detail and ask one question.",
        examples=["Farmers market + hike is elite. Any local trail recs?"],
        max_message_chars=180,
        require_question=True,
    )
    swipe = lha.HingeSwipePolicy(
        min_quality_score_like=70,
        require_flags_all=set(),
        block_prompt_keywords=[],
        max_likes=20,
        max_passes=100,
    )
    message = lha.HingeMessagePolicy(
        enabled=True,
        min_quality_score_to_message=80,
        max_messages=10,
        template="Hey {{name}}, your Sunday sounds great. Favorite local spot?",
    )
    return lha.HingeAgentProfile(
        name="validation_profile",
        persona_spec=persona,
        swipe_policy=swipe,
        message_policy=message,
        llm_criteria={},
    )


def _decision_engine() -> lha.DecisionEngineConfig:
    return lha.DecisionEngineConfig(
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


def _locator_map() -> dict[str, list[lha.Locator]]:
    return {
        "discover_tab": [lha.Locator(using="accessibility id", value="Discover")],
        "matches_tab": [lha.Locator(using="accessibility id", value="Matches")],
        "likes_you_tab": [],
        "standouts_tab": [],
        "profile_hub_tab": [],
        "like": [lha.Locator(using="accessibility id", value="Like photo")],
        "pass": [lha.Locator(using="accessibility id", value="Skip")],
        "open_thread": [lha.Locator(using="accessibility id", value="Open chat")],
        "message_input": [lha.Locator(using="accessibility id", value="Edit comment")],
        "send": [lha.Locator(using="accessibility id", value="Send like")],
        "discover_message_input": [lha.Locator(using="accessibility id", value="Edit comment")],
        "discover_send": [lha.Locator(using="accessibility id", value="Send like")],
    }


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_validation() -> None:
    with tempfile.TemporaryDirectory(prefix="hinge-control-contract-") as td:
        artifacts_dir = Path(td)
        client = FakeAppiumClient()
        session_name = "validation"
        mcpmod._SESSIONS.clear()
        mcpmod._SESSIONS[session_name] = mcpmod._ManagedSession(
            name=session_name,
            config_json_path="in-memory",
            client=client,  # type: ignore[arg-type]
            session_id="fake-session",
            profile=_profile(),
            decision_engine=_decision_engine(),
            locator_map=_locator_map(),
            state=lha._RuntimeState(),
            default_dry_run=False,
            default_command_query=None,
            artifacts_dir=artifacts_dir,
        )

        try:
            actions = {row["action"] for row in lha.get_hinge_action_catalog()}
            required_actions = {
                "goto_discover",
                "goto_matches",
                "like",
                "pass",
                "send_message",
                "back",
                "wait",
            }
            _assert(required_actions.issubset(actions), "Missing required high-level actions in action catalog")

            packet, _, _, _ = mcpmod._capture_packet(
                mcpmod._SESSIONS[session_name],
                include_screenshot=False,
                persist_snapshot_artifacts=False,
            )
            _assert(packet["screen_type"] == "hinge_discover_card", "Expected discover card screen classification")
            _assert("send_message" in packet["available_actions"], "Expected discover send_message to be available")

            execution = mcpmod._execute_action(
                mcpmod._SESSIONS[session_name],
                action="send_message",
                message_text="Loved your prompt. Favorite trail lately?",
                dry_run=False,
                screen_type=str(packet["screen_type"]),
                quality_features=packet["quality_features"],
            )
            _assert(execution["executed"] == "send_message", "Expected send_message execution")
            _assert("el-like" in client.clicked_ids, "Expected Discover flow to click Like before composing")
            _assert(any(el == "el-comment" for el, _ in client.sent_text), "Expected message typed into comment field")
            _assert("el-send" in client.clicked_ids, "Expected Discover flow to click Send like")

            find_result = mcpmod.find_elements(
                session_name=session_name,
                using="xpath",
                value="//*[@text='manual_target']",
                limit=2,
                include_text=True,
                include_rect=True,
            )
            _assert(find_result["total_found"] == 2, "Expected two manual target elements")

            click_result = mcpmod.click_element(
                session_name=session_name,
                using="xpath",
                value="//*[@text='manual_target']",
                index=1,
            )
            _assert(click_result["clicked"] is True, "Expected click_element success")
            _assert(client.clicked_ids[-1] == "el-manual-2", "Expected click_element to use selected index")

            type_result = mcpmod.type_into_element(
                session_name=session_name,
                using="xpath",
                value="//*[@text='manual_target']",
                text="hello",
                index=0,
            )
            _assert(type_result["typed"] is True, "Expected type_into_element success")
            _assert(client.sent_text[-1] == ("el-manual-1", "hello"), "Expected typed payload to be recorded")

            tap_result = mcpmod.tap_point(session_name=session_name, x=120, y=340)
            _assert(tap_result["tapped"] is True, "Expected tap_point success")
            _assert(client.tapped[-1] == (120, 340), "Expected tap coordinates to be recorded")

            swipe_result = mcpmod.swipe_points(
                session_name=session_name,
                x1=100,
                y1=900,
                x2=100,
                y2=200,
                duration_ms=500,
            )
            _assert(swipe_result["swiped"] is True, "Expected swipe_points success")
            _assert(client.swipes[-1] == (100, 900, 100, 200, 500), "Expected swipe parameters to be recorded")

            key_result = mcpmod.press_keycode(session_name=session_name, keycode=4)
            _assert(key_result["pressed"] is True, "Expected press_keycode success")
            _assert(client.keys[-1] == (4, None), "Expected Back keycode record")

            source_result = mcpmod.get_page_source(session_name=session_name, persist_snapshot_artifact=True)
            _assert("co.hinge.app" in source_result["xml"], "Expected raw XML payload from get_page_source")
            _assert(source_result["xml_path"] is not None, "Expected persisted source artifact path")
            _assert(Path(source_result["xml_path"]).exists(), "Expected persisted source artifact file to exist")

            screenshot_result = mcpmod.capture_screenshot(
                session_name=session_name,
                persist_snapshot_artifact=True,
            )
            _assert(screenshot_result["bytes"] > 0, "Expected screenshot byte payload")
            _assert(
                screenshot_result["screenshot_path"] is not None,
                "Expected persisted screenshot artifact path",
            )
            _assert(
                Path(screenshot_result["screenshot_path"]).exists(),
                "Expected persisted screenshot artifact file to exist",
            )

            print("PASS: hinge control contract validated")
        finally:
            mcpmod._SESSIONS.clear()


if __name__ == "__main__":
    run_validation()
