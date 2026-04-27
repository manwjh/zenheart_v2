"""
Validate public wall message text: length, no links, optional banned substrings.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings

# Substrings that usually indicate a URL or link (ASCII / common punycode entry points).
_LINK_HINT_RE = re.compile(
    r"(?:https?://|www\.)|(?<![\w.])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+"
    r"(?:com|net|org|io|cn|dev|ai|app|me|cc|co|tv|gg)(?:/|\b)",
    re.IGNORECASE,
)

# Tight check for "http" / "https" as substrings (catches obfuscated "hxxp").
_HTTPISH_RE = re.compile(r"https?|hxxps?", re.IGNORECASE)


def _banned_list(settings: "Settings") -> list[str]:
    raw = (settings.public_wall_banned_substrings or "").strip()
    if not raw:
        return []
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def validate_wall_body(text: str, settings: "Settings") -> str:
    """
    Return normalized body or raise ValueError with a short machine key as message[0] word.
    """
    s = (text or "").strip()
    if not s:
        raise ValueError("empty")
    max_c = int(settings.public_wall_max_chars)
    if max_c < 1:
        raise ValueError("config_public_wall_max_chars")
    if len(s) > max_c:
        raise ValueError("too_long")
    if "://" in s or _HTTPISH_RE.search(s) is not None:
        raise ValueError("link_forbidden")
    if _LINK_HINT_RE.search(s) is not None:
        raise ValueError("link_forbidden")
    low = s.lower()
    for part in _banned_list(settings):
        if part and part in low:
            raise ValueError("banned_phrase")
    return s
