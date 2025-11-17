#!/usr/bin/env python3
"""
Playwright Script for Dating App UI Automation

USAGE:
    Step 1: Save Authentication State
        Run: python test_bumble_playwright.py
        Choose option 1 to save auth state
        - Browser will open to the login page
        - Manually log in to your account
        - Once logged in, press Enter in the terminal
        - Auth state will be saved to 'auth-state.json'

    Step 2: Test Chat Flow
        Run: python test_bumble_playwright.py
        Choose option 2 to test chat flow
        - Browser will open with saved auth state (auto-logged in)
        - Script will navigate to messages page
        - Click first conversation
        - Print last few messages
        - Send a test message

IMPORTANT:
    This script uses actual CSS selectors discovered via Chrome DevTools inspection:
    - Conversation items: .contact
    - Messages: .message
    - Input: .textarea__input
    - Send button: .message-field__send
"""

from playwright.sync_api import sync_playwright
import json
import sys


def save_auth_state():
    """
    Opens the browser, allows manual login, then saves the authenticated state.
    """
    print("\n=== Step 1: Saving Authentication State ===")
    print("Browser will open. Please log in manually.")
    print("After logging in, return here and press Enter to save auth state.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        page = context.new_page()
        page.goto("https://bumble.com/app/connections")

        input("\nPress Enter after you have logged in successfully...")

        context.storage_state(path="auth-state.json")
        print("✓ Authentication state saved to 'auth-state.json'")

        browser.close()


def test_chat_flow():
    """
    Uses saved auth state to automate chat interactions:
    - Opens messages page
    - Clicks first conversation
    - Reads last messages
    - Sends a test message
    """
    print("\n=== Step 2: Testing Chat Flow ===")

    try:
        with open("auth-state.json", "r") as f:
            auth_state = json.load(f)
    except FileNotFoundError:
        print("❌ Error: 'auth-state.json' not found!")
        print("   Please run option 1 first to save your authentication state.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state="auth-state.json")

        page = context.new_page()

        print("Navigating to messages page...")
        page.goto("https://bumble.com/app/connections")
        page.wait_for_load_state("domcontentloaded")
        
        print("Waiting for conversation list...")
        page.wait_for_selector(".contact", timeout=15000)

        try:
            conversation_items = page.query_selector_all(".contact")

            if not conversation_items:
                raise Exception("No conversations found in the list")

            print(f"✓ Found {len(conversation_items)} conversation(s)")
            
            # First, check if there's a "Your move" conversation already visible
            target_contact = page.evaluate("""
                () => {
                    const contacts = document.querySelectorAll('.contact');
                    for (let contact of contacts) {
                        const text = contact.textContent || '';
                        // Skip if already selected
                        if (contact.classList.contains('is-selected')) continue;
                        // Check if it contains "Your move" indicating user needs to reply
                        if (text.includes('Your move')) {
                            return {
                                found: true,
                                index: Array.from(contacts).indexOf(contact)
                            };
                        }
                    }
                    return { found: false };
                }
            """)
            
            # Only scroll if we didn't find a "Your move" conversation
            if not target_contact or not target_contact.get('found'):
                print("No 'Your move' conversation found in visible list, scrolling to load more...")
                search_attempts = 0
                max_search_attempts = 10
                
                while search_attempts < max_search_attempts:
                    # Scroll down to load additional conversations
                    page.evaluate("""
                        () => {
                            const scrollContainer = document.querySelector('.scroll__inner');
                            if (scrollContainer) {
                                scrollContainer.scrollTop = scrollContainer.scrollHeight;
                            }
                        }
                    """)
                    page.wait_for_timeout(1000)
                    
                    # Search again after scrolling
                    target_contact = page.evaluate("""
                        () => {
                            const contacts = document.querySelectorAll('.contact');
                            for (let contact of contacts) {
                                const text = contact.textContent || '';
                                // Skip if already selected
                                if (contact.classList.contains('is-selected')) continue;
                                // Check if it contains "Your move" indicating user needs to reply
                                if (text.includes('Your move')) {
                                    return {
                                        found: true,
                                        index: Array.from(contacts).indexOf(contact)
                                    };
                                }
                            }
                            return { found: false };
                        }
                    """)
                    
                    if target_contact and target_contact.get('found'):
                        break
                    
                    search_attempts += 1
            
            if not target_contact or not target_contact.get('found'):
                raise Exception("No conversations found that need a reply")
            
            contact_index = target_contact.get('index', 0)
            print(f"Opening conversation that needs reply (index {contact_index})...")
            
            # Get the name of the conversation we're about to open
            target_name = page.evaluate(f"""
                () => {{
                    const contacts = document.querySelectorAll('.contact');
                    const contact = contacts[{contact_index}];
                    if (contact) {{
                        const nameElement = contact.querySelector('.contact__name') || 
                                           contact.querySelector('[class*="name"]') ||
                                           contact.firstElementChild;
                        if (nameElement) {{
                            const name = nameElement.textContent?.trim() || nameElement.innerText?.trim() || '';
                            return name.split('\\n')[0]?.split('Your move')[0]?.trim() || '';
                        }}
                        const text = contact.textContent || '';
                        const firstLine = text.split('\\n')[0]?.trim() || '';
                        return firstLine.split('Your move')[0]?.trim() || firstLine;
                    }}
                    return '';
                }}
            """)
            
            try:
                # Try clicking the image in the target contact
                page.click(f".contact:nth-of-type({contact_index + 1}) img", timeout=5000)
            except Exception:
                # Fallback: use JavaScript to click
                page.evaluate(f"""
                    () => {{
                        const contacts = document.querySelectorAll('.contact');
                        const contact = contacts[{contact_index}];
                        if (contact) {{
                            const img = contact.querySelector('img');
                            if (img) img.click();
                            else contact.click();
                        }}
                    }}
                """)
            
            # Wait for the conversation to be marked as selected
            page.wait_for_selector(f".contact:nth-of-type({contact_index + 1}).is-selected", timeout=5000)
            
            # Wait for messages to appear (this ensures the conversation view has loaded)
            page.wait_for_selector(".message", timeout=10000)
            
            # Give a moment for the UI to fully settle
            page.wait_for_timeout(500)

            message_bubbles = page.query_selector_all(".message")
            if not message_bubbles:
                raise Exception("No messages found in the conversation")

            num_messages = min(5, len(message_bubbles))
            last_messages = message_bubbles[-num_messages:]

            print(f"\n=== Last {num_messages} Message(s) ===")
            for i, msg in enumerate(last_messages, 1):
                try:
                    msg_info = msg.evaluate("""
                        (element) => {
                            const hasImg = element.querySelector('img') !== null;
                            const hasVideo = element.querySelector('video') !== null;
                            const innerHTML = element.innerHTML || '';
                            const hasGif = innerHTML.includes('gif') || innerHTML.includes('GIF');
                            const text = element.innerText?.trim() || element.textContent?.trim() || '';
                            
                            let type = 'text';
                            if (hasVideo || hasGif) type = 'gif';
                            else if (hasImg) type = 'image';
                            
                            return { type: type, text: text };
                        }
                    """)
                    
                    msg_type = msg_info['type']
                    msg_text = msg_info['text']
                    
                    if msg_type in ['gif', 'image']:
                        print(f"{i}. [{msg_type.upper()}] {msg_text if msg_text else '(no caption)'}")
                    else:
                        print(f"{i}. {msg_text if msg_text else '(empty message)'}")
                except Exception as e:
                    print(f"{i}. [Unable to read message: {e}]")

            # Get the input field from within the main chat area (not from a stale conversation)
            message_input = page.query_selector("main .textarea__input")
            if not message_input:
                # Fallback to any input if main doesn't have one
                message_input = page.query_selector(".textarea__input")
            if not message_input:
                raise Exception("Message input box not found")

            # Verify the input is visible and enabled
            if not message_input.is_visible():
                raise Exception("Message input box is not visible")

            test_message = "<3"
            print(f"\nSending test message to {target_name}: '{test_message}'")
            message_input.fill(test_message)

            # Get the send button from within the main chat area
            send_button = page.query_selector("main .message-field__send")
            if not send_button:
                send_button = page.query_selector(".message-field__send")
            if not send_button:
                raise Exception("Send button not found")

            page.wait_for_function(
                "document.querySelector('.message-field__send') && "
                "!document.querySelector('.message-field__send').hasAttribute('disabled') && "
                "document.querySelector('.message-field__send').getAttribute('aria-disabled') !== 'true'",
                timeout=5000
            )

            send_button.click(force=True)
            print("✓ Message sent!")

            input("\nPress Enter to close browser...")
            browser.close()

        except Exception as e:
            print(f"\n❌ Error: {e}")
            print("   Possible causes: page structure changed, network issues, or selector updates needed")
            input("\nPress Enter to close browser...")
            browser.close()


def extract_chat_history():
    """Extract all chat history and upload persona."""
    try:
        from persona_service.extract_chat_history import extract_and_upload_chat_history
        user_id = input("Enter user ID (or press Enter for 'default'): ").strip() or "default"
        extract_and_upload_chat_history(user_id)
    except ImportError:
        print("❌ Error: extract_chat_history module not found!")
    except Exception as e:
        print(f"❌ Error: {e}")


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