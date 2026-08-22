"""Small deterministic text/date helpers for public metadata."""

from __future__ import annotations

import re

ACCESS_PUBLIC = "public"
ACCESS_RESTRICTED = "restricted"
ACCESS_UNKNOWN = "unknown"

SOURCE_LABELS = {
    "substack": "Substack",
    "medium": "Medium",
    "patreon": "Patreon",
    "fxempire": "FXEmpire",
}

_WHITESPACE = re.compile(r"\s+")

# Syndication platforms append a call to action to the excerpt they expose.
# It is the platform's furniture, not the author's sentence, so it is removed.
_BOILERPLATE = re.compile(
    r"(?:\s*[.\u2026]*\s*)?Continue reading on [^\u00bb\n]*\u00bb\s*$",
    re.IGNORECASE,
)


def clean_text(value: str | None) -> str | None:
    if not value:
        return None
    stripped = _BOILERPLATE.sub("", value)
    collapsed = _WHITESPACE.sub(" ", stripped).strip()
    collapsed = collapsed.rstrip("\u2026 ").rstrip()
    return collapsed or None


def truncate(value: str, limit: int = 240) -> str:
    """Cut on a word boundary and mark the cut with an ellipsis."""
    if len(value) <= limit:
        return value
    cut = value[:limit].rsplit(" ", 1)[0].rstrip(",;:.—- ")
    return cut + "…"


def published_date(raw: str | None) -> str | None:
    """Normalise a timestamp to a plain YYYY-MM-DD date."""
    if not raw:
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw.strip())
    if not match:
        return None
    return match.group(0)
