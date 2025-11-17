#!/usr/bin/env python3
"""
CLI entry point for automation service.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from automation_service.browser import save_auth_state, test_chat_flow, extract_chat_history


def main():
    """
    Main function that provides a menu to choose between saving auth state or testing chat flow.
    """
    print("=" * 60)
    print("Playwright Dating App Automation Script")
    print("=" * 60)
    print("\nOptions:")
    print("1. Save authentication state (run this first)")
    print("2. Test chat flow (requires saved auth state)")
    print("3. Extract chat history & upload persona")
    print("4. Exit")

    choice = input("\nEnter your choice (1-4): ").strip()

    if choice == "1":
        save_auth_state()
    elif choice == "2":
        test_chat_flow()
    elif choice == "3":
        extract_chat_history()
    elif choice == "4":
        print("Exiting...")
        sys.exit(0)
    else:
        print("Invalid choice. Please choose 1, 2, 3, or 4.")


if __name__ == "__main__":
    main()

