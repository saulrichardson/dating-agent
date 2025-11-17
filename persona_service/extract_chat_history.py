#!/usr/bin/env python3
"""
Extract all chat history from Bumble and upload to persona service.
"""

from playwright.sync_api import sync_playwright
import json
import sys
import os
import requests
from typing import List, Dict, Any

# Allow running as script
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from persona_service.persona import extract_persona
else:
    from .persona import extract_persona

CONTEXT_SERVICE_URL = "http://localhost:5000"
CHUNK_SIZE = 50


def extract_all_chat_history(page) -> List[Dict[str, Any]]:
    """Extract all messages from all conversations."""
    all_messages = []
    
    page.wait_for_selector(".contact", timeout=15000)
    
    print("Loading all conversations by scrolling...")
    last_count = 0
    scroll_attempts = 0
    max_scroll_attempts = 50
    
    while scroll_attempts < max_scroll_attempts:
        conversation_items = page.query_selector_all(".contact")
        current_count = len(conversation_items)
        
        if current_count == last_count:
            break
        
        last_count = current_count
        page.evaluate("""
            () => {
                const scrollContainer = document.querySelector('.scroll__inner');
                if (scrollContainer) {
                    scrollContainer.scrollTop = scrollContainer.scrollHeight;
                }
            }
        """)
        page.wait_for_timeout(500)
        scroll_attempts += 1
    
    conversation_items = page.query_selector_all(".contact")
    print(f"Found {len(conversation_items)} conversations")
    
    for idx in range(len(conversation_items)):
        try:
            page.wait_for_selector(".contact", timeout=5000)
            contacts = page.query_selector_all(".contact")
            if idx >= len(contacts):
                continue
            
            page.evaluate(f"""
                () => {{
                    const contacts = document.querySelectorAll('.contact');
                    const contact = contacts[{idx}];
                    if (contact) {{
                        const img = contact.querySelector('img');
                        if (img) {{
                            img.click();
                        }} else {{
                            contact.click();
                        }}
                    }}
                }}
            """)
            
            page.wait_for_selector(".message", timeout=5000)
            page.wait_for_timeout(1000)
            
            # Scroll up to load older messages
            print(f"    Loading all messages for conversation {idx + 1}...")
            last_message_count = 0
            scroll_attempts = 0
            max_scroll_attempts = 20
            
            while scroll_attempts < max_scroll_attempts:
                current_messages = page.query_selector_all(".message")
                current_count = len(current_messages)
                
                if current_count == last_message_count:
                    break
                
                last_message_count = current_count
                
                # Scroll to top to load older messages
                # Find the scroll container in the main chat area
                page.evaluate("""
                    () => {
                        const mainArea = document.querySelector('main');
                        if (mainArea) {
                            const scrollContainer = mainArea.querySelector('.scroll__inner') ||
                                                   mainArea.querySelector('[class*="scroll"]') ||
                                                   mainArea.querySelector('[class*="messages"]');
                            if (scrollContainer && scrollContainer.scrollHeight > scrollContainer.clientHeight) {
                                scrollContainer.scrollTop = 0;
                            }
                        }
                    }
                """)
                page.wait_for_timeout(1500)
                scroll_attempts += 1
            
            messages_data = page.evaluate("""
                () => {
                    const messages = document.querySelectorAll('.message');
                    const result = [];
                    for (const msg of messages) {
                        const text = msg.innerText?.trim() || msg.textContent?.trim() || '';
                        if (!text) continue;
                        
                        const classes = msg.className || '';
                        const isMe = classes.includes('message--out') || 
                                    classes.includes('message--sent') ||
                                    classes.includes('is-sent');
                        
                        result.push({
                            text: text,
                            isMe: isMe
                        });
                    }
                    return result;
                }
            """)
            
            my_count = sum(1 for m in messages_data if m["isMe"])
            for msg_data in messages_data:
                all_messages.append({
                    "text": msg_data["text"],
                    "sender": "me" if msg_data["isMe"] else "other",
                    "conversation_idx": idx
                })
            
            print(f"  Conversation {idx + 1}: {len(messages_data)} messages ({my_count} from you)")
            
        except Exception as e:
            print(f"  Error processing conversation {idx + 1}: {e}")
            continue
    
    return all_messages


def chunk_messages(messages: List[Dict[str, Any]], chunk_size: int = CHUNK_SIZE) -> List[List[Dict[str, Any]]]:
    """Split messages into chunks."""
    chunks = []
    for i in range(0, len(messages), chunk_size):
        chunks.append(messages[i:i + chunk_size])
    return chunks


def upload_persona(user_id: str, persona: Dict[str, Any]) -> bool:
    """Upload persona to context service."""
    try:
        response = requests.post(
            f"{CONTEXT_SERVICE_URL}/persona/{user_id}",
            json={"persona": persona},
            timeout=10
        )
        return response.status_code in [200, 201]
    except Exception as e:
        print(f"Error uploading persona: {e}")
        return False


def extract_and_upload_chat_history(user_id: str = "default"):
    """Main function to extract chat history and upload persona."""
    print("\n=== Extracting Chat History ===")
    
    try:
        with open("auth-state.json", "r") as f:
            auth_state = json.load(f)
    except FileNotFoundError:
        print("❌ Error: 'auth-state.json' not found!")
        print("   Please run test_bumble_playwright.py option 1 first.")
        return
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(storage_state="auth-state.json")
        page = context.new_page()
        
        print("Navigating to messages page...")
        page.goto("https://bumble.com/app/connections")
        page.wait_for_load_state("domcontentloaded")
        
        print("Extracting all chat history...")
        all_messages = extract_all_chat_history(page)
        
        print(f"\n✓ Extracted {len(all_messages)} total messages")
        
        my_messages = [msg for msg in all_messages if msg.get("sender") == "me"]
        print(f"  - {len(my_messages)} from you")
        print(f"  - {len(all_messages) - len(my_messages)} from others")
        
        if not my_messages:
            print("❌ No messages from you found!")
            browser.close()
            return
        
        print("\n=== Generating Persona Profile ===")
        persona = extract_persona(my_messages)
        
        print("\nExtracted Persona:")
        print(json.dumps(persona, indent=2))
        
        print("\n=== Uploading to Persona Service ===")
        if upload_persona(user_id, persona):
            print("✓ Persona uploaded successfully!")
        else:
            print("⚠ Failed to upload persona (service may not be running)")
            print("  Saving locally to persona_profile.json...")
            with open("persona_profile.json", "w") as f:
                json.dump(persona, f, indent=2)
        
        input("\nPress Enter to close browser...")
        browser.close()


if __name__ == "__main__":
    user_id = sys.argv[1] if len(sys.argv) > 1 else "default"
    extract_and_upload_chat_history(user_id)

