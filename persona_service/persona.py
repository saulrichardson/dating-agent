"""
Persona extraction from chat logs.

Extracts messaging style from past chats to provide context to Automation Service.
"""

import json
import re
from typing import List, Dict, Any
from collections import Counter


def extract_persona(chat_logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract persona profile from chat logs.
    
    Args:
        chat_logs: List of message dicts with at least 'text' and optionally 'timestamp', 'sender'
                  Format: [{"text": "message text", "sender": "me", "timestamp": ...}, ...]
    
    Returns:
        Compact persona JSON dict
    """
    if not chat_logs:
        return _empty_persona()
    
    my_messages = [msg for msg in chat_logs if msg.get("sender") == "me"]
    if not my_messages:
        my_messages = chat_logs
    
    texts = [msg["text"] for msg in my_messages if msg.get("text")]
    if not texts:
        return _empty_persona()
    
    persona = {}
    
    persona["caps"] = _analyze_capitalization(texts)
    persona["punct"] = _analyze_punctuation(texts)
    persona["emoji_style"] = _analyze_emoji(texts)
    persona["message_length"] = _analyze_message_length(texts)
    persona["chunking"] = _analyze_chunking(my_messages)
    persona["typos"] = _analyze_typos_slang(texts)
    persona["question_freq"] = _analyze_question_frequency(texts)
    persona["tone"] = _analyze_tone(texts)
    persona["interests"] = _analyze_interests(texts)
    persona["other"] = _analyze_other_patterns(texts, my_messages)
    
    return persona


def generate_reply(persona: Dict[str, Any], recent_messages: List[Dict[str, Any]]) -> str:
    """
    Generate a reply based on persona profile and recent conversation context.
    
    This is a STUB that returns a template. Replace with actual LLM call later.
    
    Args:
        persona: Persona profile dict from extract_persona()
        recent_messages: Last few messages in conversation [{"text": "...", "sender": "..."}, ...]
    
    Returns:
        Generated reply string
    """
    prompt = _build_prompt(persona, recent_messages)
    
    return f"[STUB: Would call LLM with this prompt]\n\n{prompt}"


def _empty_persona() -> Dict[str, Any]:
    """Return empty persona structure."""
    return {
        "caps": "standard",
        "punct": "standard",
        "emoji_style": "none",
        "message_length": "medium",
        "chunking": "single messages",
        "typos": "none",
        "question_freq": "medium",
        "tone": "neutral",
        "interests": [],
        "other": ""
    }


def _analyze_capitalization(texts: List[str]) -> str:
    """Analyze capitalization habits."""
    if not texts:
        return "standard"
    
    lowercase_i_count = sum(1 for text in texts if re.search(r'\bi\b', text))
    total_i_count = sum(1 for text in texts if re.search(r'\b[iI]\b', text))
    
    all_lowercase = sum(1 for text in texts if text.lower() == text and text.strip())
    has_caps = sum(1 for text in texts if any(c.isupper() for c in text))
    
    patterns = []
    
    if total_i_count > 0 and lowercase_i_count / total_i_count > 0.5:
        patterns.append("uses 'i' instead of 'I'")
    
    if len(texts) > 0 and all_lowercase / len(texts) > 0.7:
        patterns.append("mostly lowercase")
    elif has_caps / len(texts) < 0.3:
        patterns.append("rarely capitalizes")
    
    return "; ".join(patterns) if patterns else "standard"


def _analyze_punctuation(texts: List[str]) -> str:
    """Analyze punctuation habits."""
    if not texts:
        return "standard"
    
    punct_patterns = {
        "??": sum(text.count("??") for text in texts),
        "...": sum(text.count("...") for text in texts),
        "!": sum(text.count("!") for text in texts),
        "?": sum(text.count("?") for text in texts),
        ".": sum(text.count(".") for text in texts),
    }
    
    total_chars = sum(len(text) for text in texts)
    if total_chars == 0:
        return "standard"
    
    patterns = []
    
    if punct_patterns["??"] > len(texts) * 0.2:
        patterns.append("uses ?? often")
    if punct_patterns["..."] > len(texts) * 0.2:
        patterns.append("uses ... often")
    if punct_patterns["!"] / total_chars > 0.01:
        patterns.append("frequent !")
    if punct_patterns["?"] / total_chars > 0.01:
        patterns.append("frequent ?")
    if punct_patterns["."] / total_chars < 0.005:
        patterns.append("rare periods")
    
    return "; ".join(patterns) if patterns else "standard"


def _analyze_emoji(texts: List[str]) -> str:
    """Analyze emoji usage."""
    if not texts:
        return "none"
    
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"  # dingbats
        "\U000024C2-\U0001F251"  # enclosed characters
        "]+",
        flags=re.UNICODE
    )
    
    emoji_counts = Counter()
    messages_with_emoji = 0
    
    for text in texts:
        emojis = emoji_pattern.findall(text)
        if emojis:
            messages_with_emoji += 1
            for emoji_str in emojis:
                for char in emoji_str:
                    emoji_counts[char] += 1
    
    if messages_with_emoji == 0:
        return "none"
    
    emoji_freq = messages_with_emoji / len(texts)
    top_emojis = [e for e, _ in emoji_counts.most_common(3)]
    
    if emoji_freq < 0.1:
        style = "sparingly"
    elif emoji_freq < 0.5:
        style = "occasionally"
    else:
        style = "frequently"
    
    if top_emojis:
        return f"{style}; mostly {', '.join(top_emojis)}"
    return style


def _analyze_message_length(texts: List[str]) -> str:
    """Analyze typical message length."""
    if not texts:
        return "medium"
    
    lengths = [len(text) for text in texts]
    avg_len = sum(lengths) / len(lengths)
    
    if avg_len < 20:
        return "short"
    elif avg_len < 100:
        return "medium"
    else:
        return "long"


def _analyze_chunking(messages: List[Dict[str, Any]]) -> str:
    """Analyze message chunking patterns."""
    if len(messages) < 2:
        return "single messages"
    
    if "timestamp" not in messages[0]:
        return "unknown"
    
    short_gaps = 0
    total_gaps = 0
    
    for i in range(1, len(messages)):
        if "timestamp" in messages[i] and "timestamp" in messages[i-1]:
            gap = messages[i]["timestamp"] - messages[i-1]["timestamp"]
            if gap < 60:
                short_gaps += 1
            total_gaps += 1
    
    if total_gaps == 0:
        return "single messages"
    
    if short_gaps / total_gaps > 0.5:
        return "frequent short back-to-back messages"
    else:
        return "single messages"


def _analyze_typos_slang(texts: List[str]) -> str:
    """Analyze typos and slang patterns."""
    if not texts:
        return "none"
    
    common_slang = ["lol", "omg", "wtf", "tbh", "imo", "idk", "ngl", "fr", "lowkey", "highkey"]
    common_abbrev = ["u", "ur", "r", "y", "cuz", "bc", "bcuz"]
    
    slang_count = sum(1 for text in texts if any(word in text.lower() for word in common_slang))
    abbrev_count = sum(1 for text in texts if any(word in text.lower() for word in common_abbrev))
    
    patterns = []
    if slang_count / len(texts) > 0.2:
        patterns.append("casual slang")
    if abbrev_count / len(texts) > 0.2:
        patterns.append("abbreviations")
    
    return "; ".join(patterns) if patterns else "none"


def _analyze_question_frequency(texts: List[str]) -> str:
    """Analyze how often questions are asked."""
    if not texts:
        return "medium"
    
    question_count = sum(1 for text in texts if "?" in text)
    freq = question_count / len(texts)
    
    if freq > 0.5:
        return "high"
    elif freq > 0.2:
        return "medium"
    else:
        return "low"


def _analyze_tone(texts: List[str]) -> str:
    """Analyze overall tone."""
    if not texts:
        return "neutral"
    
    playful_words = ["haha", "lol", "lmao", "😄", "😆", "😂"]
    sarcastic_indicators = ["sure", "totally", "obviously", "of course"]
    flirty_words = ["😉", "😘", "😍", "🔥", "💕"]
    direct_indicators = ["yes", "no", "sure", "ok", "okay"]
    
    playful_count = sum(1 for text in texts if any(word in text.lower() for word in playful_words))
    sarcastic_count = sum(1 for text in texts if any(word in text.lower() for word in sarcastic_indicators))
    flirty_count = sum(1 for text in texts if any(word in text for word in flirty_words))
    direct_count = sum(1 for text in texts if any(word in text.lower() for word in direct_indicators))
    
    tones = []
    if playful_count / len(texts) > 0.2:
        tones.append("playful")
    if sarcastic_count / len(texts) > 0.1:
        tones.append("sarcastic at times")
    if flirty_count / len(texts) > 0.15:
        tones.append("flirty")
    if direct_count / len(texts) > 0.3:
        tones.append("direct")
    
    return ", ".join(tones) if tones else "neutral"


def _analyze_interests(texts: List[str]) -> List[str]:
    """Extract recurring interests/topics."""
    if not texts:
        return []
    
    common_interests = {
        "fitness": ["gym", "workout", "exercise", "running", "fitness"],
        "travel": ["travel", "trip", "vacation", "flight", "hotel"],
        "food": ["restaurant", "food", "cooking", "recipe", "dinner", "lunch"],
        "music": ["music", "song", "concert", "album", "spotify"],
        "tech": ["code", "programming", "tech", "computer", "software"],
        "sports": ["game", "match", "team", "sport", "football", "basketball"],
    }
    
    interest_counts = Counter()
    all_text = " ".join(texts).lower()
    
    for interest, keywords in common_interests.items():
        count = sum(1 for keyword in keywords if keyword in all_text)
        if count > 0:
            interest_counts[interest] = count
    
    return [interest for interest, _ in interest_counts.most_common(3)]


def _analyze_other_patterns(texts: List[str], messages: List[Dict[str, Any]]) -> str:
    """Catch other obvious patterns."""
    patterns = []
    
    exclamation_ratio = sum(text.count("!") for text in texts) / max(sum(len(text) for text in texts), 1)
    if exclamation_ratio > 0.015:
        patterns.append("high energy")
    
    if len(texts) > 0:
        avg_words = sum(len(text.split()) for text in texts) / len(texts)
        if avg_words < 5:
            patterns.append("very concise")
        elif avg_words > 20:
            patterns.append("verbose")
    
    return "; ".join(patterns) if patterns else ""


def _build_prompt(persona: Dict[str, Any], recent_messages: List[Dict[str, Any]]) -> str:
    """Build prompt for LLM reply generation."""
    context = "\n".join([f"{msg.get('sender', 'other')}: {msg.get('text', '')}" for msg in recent_messages[-5:]])
    
    prompt = f"""Generate a reply in this exact style:

PERSONA:
- Capitalization: {persona.get('caps', 'standard')}
- Punctuation: {persona.get('punct', 'standard')}
- Emoji: {persona.get('emoji_style', 'none')}
- Message length: {persona.get('message_length', 'medium')}
- Chunking: {persona.get('chunking', 'single')}
- Question frequency: {persona.get('question_freq', 'medium')}
- Tone: {persona.get('tone', 'neutral')}
- Interests: {', '.join(persona.get('interests', []))}
- Other: {persona.get('other', '')}

RECENT MESSAGES:
{context}

Generate ONE reply that matches this persona exactly. Keep it token-efficient."""
    
    return prompt

