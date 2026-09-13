"""Shared tables used by every OS resolver."""
import re

# Popular sites spoken by name -> direct URL (fast path, works on every OS)
URL_APPS = {
    "youtube": "https://www.youtube.com",
    "browser": "https://www.google.com",
    "google": "https://www.google.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "gmail": "https://mail.google.com",
    "twitter": "https://twitter.com",
    "x": "https://twitter.com",
    "linkedin": "https://www.linkedin.com",
    "whatsapp web": "https://web.whatsapp.com",
    "whatsapp": "https://web.whatsapp.com",
    "asep": "https://web.whatsapp.com",
    "asap": "https://web.whatsapp.com",
    "wasap": "https://web.whatsapp.com",
    "chatgpt": "https://chat.openai.com",
    "github": "https://github.com",
}

# Spoken words that are clearly TASKS, not apps — refuse them early so
# "message bhejo" never tries to launch something called "message".
NOT_AN_APP = (
    "message", "messages", "text", "call", "search", "news", "weather",
    "screenshot", "screen shot", "recording", "screen recording",
)

_DOMAIN_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$", re.IGNORECASE)


def looks_like_domain(key: str) -> bool:
    """True for inputs like 'example.com' (no spaces, has a dot + TLD-ish tail)."""
    return " " not in key and bool(_DOMAIN_RE.match(key))
