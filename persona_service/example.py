"""
Example usage of persona extraction and reply generation.
"""

import json
import sys
import os

# Allow running as script from persona_service directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from persona_service.persona import extract_persona, generate_reply


def example_chat_logs():
    """Sample chat logs for testing."""
    return [
        {"text": "hey how are you??", "sender": "me", "timestamp": 1000},
        {"text": "i'm good! what about you", "sender": "me", "timestamp": 1005},
        {"text": "just finished a workout 🔥", "sender": "me", "timestamp": 1010},
        {"text": "thinking about traveling next month", "sender": "me", "timestamp": 1015},
        {"text": "lol that sounds fun", "sender": "me", "timestamp": 1020},
        {"text": "tbh i'm not sure yet", "sender": "me", "timestamp": 1025},
        {"text": "want to grab food later?", "sender": "me", "timestamp": 1030},
        {"text": "sure totally", "sender": "me", "timestamp": 1035},
    ]


def example_recent_messages():
    """Sample recent conversation context."""
    return [
        {"text": "Hey, how's your day going?", "sender": "other"},
        {"text": "pretty good! just got back from the gym", "sender": "me"},
        {"text": "Nice! What did you do?", "sender": "other"},
    ]


def main():
    print("=" * 60)
    print("Persona Extraction Example")
    print("=" * 60)
    
    chat_logs = example_chat_logs()
    print(f"\nAnalyzing {len(chat_logs)} messages...\n")
    
    persona = extract_persona(chat_logs)
    
    print("EXTRACTED PERSONA:")
    print(json.dumps(persona, indent=2))
    
    print("\n" + "=" * 60)
    print("Reply Generation Example")
    print("=" * 60)
    
    recent_messages = example_recent_messages()
    print("\nRecent conversation:")
    for msg in recent_messages:
        print(f"  {msg['sender']}: {msg['text']}")
    
    print("\nGenerated reply (STUB):")
    reply = generate_reply(persona, recent_messages)
    print(reply)


if __name__ == "__main__":
    main()


