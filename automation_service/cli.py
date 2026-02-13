#!/usr/bin/env python3
"""
Appium-first CLI entry point.
"""

from __future__ import annotations

import sys

from automation_service.mobile.console import run_mobile_interactive_console, run_mobile_script
from automation_service.mobile.flows import (
    DEFAULT_APPIUM_SERVER_URL,
    run_mobile_accessibility_dump,
    run_mobile_smoke_test,
)
from automation_service.mobile.full_fidelity_hinge import run_hinge_full_fidelity_capture
from automation_service.mobile.live_hinge_agent import run_live_hinge_agent
from automation_service.mobile.offline_artifacts import run_offline_artifact_extraction
from automation_service.mobile.spec_runner import run_mobile_spec
from automation_service.mobile.ui_xml_search import search_uiautomator_xml, suggest_locator
from automation_service.mobile.vertical_slices import run_vertical_inbox_probe


def _prompt_server_url() -> str:
    return input(f"Appium server URL [{DEFAULT_APPIUM_SERVER_URL}]: ").strip() or DEFAULT_APPIUM_SERVER_URL


def _prompt_capabilities_path() -> str:
    default_caps_path = "automation_service/mobile_examples/android_capabilities.example.json"
    return input(f"Capabilities JSON path [{default_caps_path}]: ").strip() or default_caps_path


def _prompt_pause(label: str) -> bool:
    response = input(f"Pause before {label} to let you navigate manually? [y/N]: ").strip().lower()
    return response in {"y", "yes"}


def _run_smoke_test() -> None:
    result = run_mobile_smoke_test(
        appium_server_url=_prompt_server_url(),
        capabilities_json_path=_prompt_capabilities_path(),
        wait_for_enter_before_capture=_prompt_pause("capture"),
    )
    print("\n✓ Mobile smoke test completed")
    print(f"  Session: {result.session_id}")
    print(f"  Screenshot: {result.screenshot_path}")
    print(f"  Page source: {result.page_source_path}")


def _run_accessibility_dump() -> None:
    strings = run_mobile_accessibility_dump(
        appium_server_url=_prompt_server_url(),
        capabilities_json_path=_prompt_capabilities_path(),
        max_strings=200,
        wait_for_enter_before_capture=_prompt_pause("dump"),
    )
    print("\n=== Accessible strings (best-effort) ===")
    if not strings:
        print("(none found)")
        return
    for i, s in enumerate(strings, 1):
        print(f"{i:>3}. {s}")


def _run_ui_xml_search() -> None:
    default_xml_path = "artifacts/mobile_page_source.xml"
    xml_path = input(f"UI XML path [{default_xml_path}]: ").strip() or default_xml_path
    query = input("Search query (e.g. 'likes you', 'messages', 'send'): ").strip()
    if not query:
        print("Query is required.")
        return

    try:
        xml = open(xml_path, "r", encoding="utf-8").read()
    except FileNotFoundError:
        print(f"UI XML file not found: {xml_path}")
        return

    matches = search_uiautomator_xml(xml, query=query, limit=30)
    if not matches:
        print("No matches found.")
        return

    print(f"\nFound {len(matches)} match(es):")
    for i, m in enumerate(matches, 1):
        locator = suggest_locator(m)
        locator_str = f"{locator[0]} -> {locator[1]}" if locator else "(no suggestion)"
        bounds_str = f"{m.bounds}" if m.bounds else "(no bounds)"
        print(f"{i:>2}. {locator_str} | {bounds_str}")
        if m.text:
            print(f"    text: {m.text}")
        if m.content_desc:
            print(f"    content-desc: {m.content_desc}")
        if m.resource_id:
            print(f"    resource-id: {m.resource_id}")
        if m.class_name:
            print(f"    class: {m.class_name}")


def _run_interactive_console() -> None:
    artifacts_dir = input("Artifacts dir [artifacts]: ").strip() or "artifacts"
    run_mobile_interactive_console(
        appium_server_url=_prompt_server_url(),
        capabilities_json_path=_prompt_capabilities_path(),
        artifacts_dir=artifacts_dir,
    )


def _run_script_from_json() -> None:
    default_script_path = "automation_service/mobile_examples/mobile_script.example.json"
    script_json_path = input(f"Script JSON path [{default_script_path}]: ").strip() or default_script_path
    run_mobile_script(script_json_path=script_json_path)


def _run_vertical_probe() -> None:
    default_probe_config = "automation_service/mobile_examples/vertical_hinge_inbox_probe.example.json"
    config_json_path = input(f"Vertical probe JSON path [{default_probe_config}]: ").strip() or default_probe_config
    result = run_vertical_inbox_probe(config_json_path=config_json_path)
    print("\n✓ Vertical inbox probe completed")
    print(f"  App: {result.app}")
    print(f"  Session: {result.session_id}")
    print(f"  Report: {result.report_path}")
    print(f"  Initial screenshot: {result.initial_screenshot_path}")
    print(f"  Post-inbox screenshot: {result.post_inbox_screenshot_path}")
    if result.matched_inbox_locator:
        print(
            "  Matched locator: "
            f"{result.matched_inbox_locator.using} -> {result.matched_inbox_locator.value}"
        )
    else:
        print("  Matched locator: none")
    print(f"  Keyword hits (after click): {len(result.keyword_hits)}")


def _run_spec_from_json() -> None:
    default_spec_path = "automation_service/mobile_examples/mobile_spec.example.json"
    spec_json_path = input(f"Spec JSON path [{default_spec_path}]: ").strip() or default_spec_path
    result = run_mobile_spec(spec_json_path=spec_json_path)
    print("\n✓ Mobile spec run completed")
    print(f"  Session: {result.session_id}")
    print(f"  Executed steps: {result.executed_steps}")
    print(f"  Artifacts written: {len(result.artifacts)}")
    for artifact in result.artifacts:
        print(f"    - {artifact}")
    if result.vars:
        print("  Final vars:")
        for k, v in sorted(result.vars.items()):
            print(f"    {k}={v}")


def _run_offline_extraction() -> None:
    default_config_path = "automation_service/mobile_examples/offline_artifact_extract.hinge.example.json"
    config_json_path = (
        input(f"Offline extraction config JSON path [{default_config_path}]: ").strip() or default_config_path
    )
    result = run_offline_artifact_extraction(config_json_path=config_json_path)
    print("\n✓ Offline artifact extraction completed")
    print(f"  Processed XML files: {result.processed_xml_files}")
    print(f"  Failed XML files: {result.failed_xml_files}")
    print(f"  Screens JSONL: {result.screens_jsonl_path}")
    print(f"  Summary JSON: {result.summary_json_path}")
    if result.nodes_jsonl_path is not None:
        print(f"  Nodes JSONL: {result.nodes_jsonl_path}")


def _run_live_agent() -> None:
    default_config_path = "automation_service/mobile_examples/live_hinge_agent.example.json"
    config_json_path = (
        input(f"Live Hinge agent config JSON path [{default_config_path}]: ").strip() or default_config_path
    )
    result = run_live_hinge_agent(config_json_path=config_json_path)
    print("\n✓ Live Hinge agent run completed")
    print(f"  Session: {result.session_id}")
    print(f"  Iterations: {result.iterations}")
    print(f"  Likes: {result.likes}")
    print(f"  Passes: {result.passes}")
    print(f"  Messages: {result.messages}")
    print(f"  Action log: {result.action_log_path}")
    if result.packet_log_path is not None:
        print(f"  Packet log: {result.packet_log_path}")
    print(f"  Artifacts: {len(result.artifacts)}")
    for artifact in result.artifacts:
        print(f"    - {artifact}")


def _run_full_fidelity_capture() -> None:
    default_config_path = "automation_service/mobile_examples/hinge_full_fidelity_capture.example.json"
    config_json_path = (
        input(f"Full-fidelity config JSON path [{default_config_path}]: ").strip() or default_config_path
    )
    result = run_hinge_full_fidelity_capture(config_json_path=config_json_path)
    print("\n✓ Full-fidelity Hinge capture completed")
    print(f"  Session: {result.session_id}")
    print(f"  Iterations: {result.iterations}")
    print(f"  Session dir: {result.session_dir}")
    print(f"  Frames JSONL: {result.frames_jsonl_path}")
    print(f"  Profiles JSONL: {result.profiles_jsonl_path}")
    print(f"  Messages JSONL: {result.messages_jsonl_path}")
    print(f"  Nodes JSONL: {result.nodes_jsonl_path}")
    print(f"  Summary JSON: {result.summary_json_path}")


def main() -> None:
    handlers = {
        "1": _run_smoke_test,
        "2": _run_accessibility_dump,
        "3": _run_ui_xml_search,
        "4": _run_interactive_console,
        "5": _run_script_from_json,
        "6": _run_vertical_probe,
        "7": _run_spec_from_json,
        "8": _run_offline_extraction,
        "9": _run_live_agent,
        "10": _run_full_fidelity_capture,
    }

    while True:
        print("=" * 60)
        print("Concierge Mobile CLI (Appium Only)")
        print("=" * 60)
        print("\nOptions:")
        print("1. Mobile smoke test (screenshot + UI XML)")
        print("2. Mobile dump accessible strings")
        print("3. Search captured UI XML (locator discovery)")
        print("4. Interactive console (live Appium session)")
        print("5. Run script from JSON")
        print("6. Run app-specific vertical inbox probe")
        print("7. Run declarative spec from JSON")
        print("8. Offline artifact extraction (XML/screenshot -> JSONL)")
        print("9. Live Hinge agent (single session, NL + profile policy)")
        print("10. Full-fidelity Hinge capture")
        print("11. Exit")

        choice = input("\nEnter your choice (1-11): ").strip()
        if choice == "11":
            print("Exiting...")
            raise SystemExit(0)
        handler = handlers.get(choice)
        if handler is None:
            print("Invalid choice. Please choose 1-11.\n")
            continue
        handler()
        print("")


if __name__ == "__main__":
    main()
