#!/usr/bin/env python3
"""
CLI entry point for automation service.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    """
    Main function that provides a menu to choose between saving auth state or testing chat flow.
    """
    print("=" * 60)
    print("Concierge Automation CLI (Playwright + Appium)")
    print("=" * 60)
    print("\nOptions:")
    print("1. Save authentication state (run this first)")
    print("2. Test chat flow (requires saved auth state)")
    print("3. Extract chat history & upload persona")
    print("4. Mobile (Android/Appium) smoke test (screenshot + UI XML)")
    print("5. Mobile (Android/Appium) dump accessible strings")
    print("6. Mobile: search last captured UI XML (locator discovery)")
    print("7. Mobile: interactive console (live Appium session)")
    print("8. Mobile: run script from JSON (repeatable automation)")
    print("9. Mobile: app-specific vertical inbox probe (Hinge/Tinder)")
    print("10. Mobile: run declarative spec from JSON (app-agnostic)")
    print("11. Mobile: offline artifact extraction (XML/screenshot -> JSONL)")
    print("12. Mobile: live Hinge agent (single session, NL + profile policy)")
    print("13. Mobile: full-fidelity Hinge capture (profiles + messages + raw artifacts)")
    print("14. Exit")

    choice = input("\nEnter your choice (1-14): ").strip()

    if choice == "1":
        from automation_service.browser import save_auth_state

        save_auth_state()
    elif choice == "2":
        from automation_service.browser import test_chat_flow

        test_chat_flow()
    elif choice == "3":
        from automation_service.browser import extract_chat_history

        extract_chat_history()
    elif choice == "4":
        from automation_service.mobile.flows import DEFAULT_APPIUM_SERVER_URL, run_mobile_smoke_test

        appium_server_url = (
            input(f"Appium server URL [{DEFAULT_APPIUM_SERVER_URL}]: ").strip()
            or DEFAULT_APPIUM_SERVER_URL
        )
        default_caps_path = "automation_service/mobile_examples/android_capabilities.example.json"
        capabilities_json_path = (
            input(f"Capabilities JSON path [{default_caps_path}]: ").strip() or default_caps_path
        )

        pause = input("Pause before capture to let you login/navigate? [y/N]: ").strip().lower() in {
            "y",
            "yes",
        }

        result = run_mobile_smoke_test(
            appium_server_url=appium_server_url,
            capabilities_json_path=capabilities_json_path,
            wait_for_enter_before_capture=pause,
        )
        print("\n✓ Mobile smoke test completed")
        print(f"  Session: {result.session_id}")
        print(f"  Screenshot: {result.screenshot_path}")
        print(f"  Page source: {result.page_source_path}")
    elif choice == "5":
        from automation_service.mobile.flows import DEFAULT_APPIUM_SERVER_URL, run_mobile_accessibility_dump

        appium_server_url = (
            input(f"Appium server URL [{DEFAULT_APPIUM_SERVER_URL}]: ").strip()
            or DEFAULT_APPIUM_SERVER_URL
        )
        default_caps_path = "automation_service/mobile_examples/android_capabilities.example.json"
        capabilities_json_path = (
            input(f"Capabilities JSON path [{default_caps_path}]: ").strip() or default_caps_path
        )

        pause = input("Pause before dump to let you login/navigate? [y/N]: ").strip().lower() in {
            "y",
            "yes",
        }

        strings = run_mobile_accessibility_dump(
            appium_server_url=appium_server_url,
            capabilities_json_path=capabilities_json_path,
            max_strings=200,
            wait_for_enter_before_capture=pause,
        )

        print("\n=== Accessible strings (best-effort) ===")
        if not strings:
            print("(none found)")
        for i, s in enumerate(strings, 1):
            print(f"{i:>3}. {s}")
    elif choice == "6":
        from automation_service.mobile.ui_xml_search import search_uiautomator_xml, suggest_locator

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
    elif choice == "7":
        from automation_service.mobile.console import run_mobile_interactive_console
        from automation_service.mobile.flows import DEFAULT_APPIUM_SERVER_URL

        appium_server_url = (
            input(f"Appium server URL [{DEFAULT_APPIUM_SERVER_URL}]: ").strip()
            or DEFAULT_APPIUM_SERVER_URL
        )
        default_caps_path = "automation_service/mobile_examples/android_capabilities.example.json"
        capabilities_json_path = (
            input(f"Capabilities JSON path [{default_caps_path}]: ").strip() or default_caps_path
        )
        artifacts_dir = input("Artifacts dir [artifacts]: ").strip() or "artifacts"

        run_mobile_interactive_console(
            appium_server_url=appium_server_url,
            capabilities_json_path=capabilities_json_path,
            artifacts_dir=artifacts_dir,
        )
    elif choice == "8":
        from automation_service.mobile.console import run_mobile_script

        default_script_path = "automation_service/mobile_examples/mobile_script.example.json"
        script_json_path = input(f"Script JSON path [{default_script_path}]: ").strip() or default_script_path
        run_mobile_script(script_json_path=script_json_path)
    elif choice == "9":
        from automation_service.mobile.vertical_slices import run_vertical_inbox_probe

        default_probe_config = "automation_service/mobile_examples/vertical_hinge_inbox_probe.example.json"
        config_json_path = (
            input(f"Vertical probe JSON path [{default_probe_config}]: ").strip() or default_probe_config
        )
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
    elif choice == "10":
        from automation_service.mobile.spec_runner import run_mobile_spec

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
    elif choice == "11":
        from automation_service.mobile.offline_artifacts import run_offline_artifact_extraction

        default_config_path = "automation_service/mobile_examples/offline_artifact_extract.hinge.example.json"
        config_json_path = (
            input(f"Offline extraction config JSON path [{default_config_path}]: ").strip()
            or default_config_path
        )
        result = run_offline_artifact_extraction(config_json_path=config_json_path)
        print("\n✓ Offline artifact extraction completed")
        print(f"  Processed XML files: {result.processed_xml_files}")
        print(f"  Failed XML files: {result.failed_xml_files}")
        print(f"  Screens JSONL: {result.screens_jsonl_path}")
        print(f"  Summary JSON: {result.summary_json_path}")
        if result.nodes_jsonl_path is not None:
            print(f"  Nodes JSONL: {result.nodes_jsonl_path}")
    elif choice == "12":
        from automation_service.mobile.live_hinge_agent import run_live_hinge_agent

        default_config_path = "automation_service/mobile_examples/live_hinge_agent.example.json"
        config_json_path = (
            input(f"Live Hinge agent config JSON path [{default_config_path}]: ").strip()
            or default_config_path
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
    elif choice == "13":
        from automation_service.mobile.full_fidelity_hinge import run_hinge_full_fidelity_capture

        default_config_path = "automation_service/mobile_examples/hinge_full_fidelity_capture.example.json"
        config_json_path = (
            input(f"Full-fidelity config JSON path [{default_config_path}]: ").strip()
            or default_config_path
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
    elif choice == "14":
        print("Exiting...")
        sys.exit(0)
    else:
        print("Invalid choice. Please choose 1-14.")


if __name__ == "__main__":
    main()
