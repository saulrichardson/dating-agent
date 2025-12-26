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
    print("7. Exit")

    choice = input("\nEnter your choice (1-7): ").strip()

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
        print("Exiting...")
        sys.exit(0)
    else:
        print("Invalid choice. Please choose 1-7.")


if __name__ == "__main__":
    main()
