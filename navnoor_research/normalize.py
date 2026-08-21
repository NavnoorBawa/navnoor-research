"""Turning raw corpus records into the product's own vocabulary.

The corpus carries six different audience strings and a `family` field that is
'other' for 78% of records. Neither is usable in a reader-facing filter, so both
are normalised here rather than at render time.
"""

from __future__ import annotations

import math
import re

# Words per minute for the reading-time estimate. Deliberately conservative for
# dense financial prose.
WORDS_PER_MINUTE = 230

_FREE_AUDIENCES = {"everyone", "public"}
_PAID_AUDIENCES = {"only_paid", "paid", "locked"}

ACCESS_FREE = "free"
ACCESS_PAID = "paid"
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


def access_of(audience: str | None) -> str:
    """Collapse the corpus's six audience strings into free / paid / unknown."""
    key = (audience or "").strip().lower()
    if key in _FREE_AUDIENCES:
        return ACCESS_FREE
    if key in _PAID_AUDIENCES:
        return ACCESS_PAID
    return ACCESS_UNKNOWN


# The corpus counts words in whatever text it holds. For an excerpt that is the
# length of the excerpt, not of the article, so it must not become a reading
# time: a 3,000-word piece stored as a 200-word teaser would advertise "1 min".
COMPLETE_BODY_STATUS = "full"


def reading_minutes(wordcount: int | None, content_status: str | None = None) -> int | None:
    """Minutes to read, or None when the corpus cannot support an honest figure.

    Returning None is deliberate and common. Only records holding a complete
    body carry a trustworthy wordcount, so the UI omits the field for the rest
    rather than printing a number that is confidently wrong.
    """
    if content_status is not None and content_status != COMPLETE_BODY_STATUS:
        return None
    if not wordcount or wordcount <= 0:
        return None
    return max(1, math.ceil(wordcount / WORDS_PER_MINUTE))


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


def summary_for(record: dict, access: str) -> str | None:
    """Choose a rights-safe summary.

    A body-derived lead passage is used only for articles that are publicly
    readable. For paid or locked articles the subtitle is the only text the
    publisher shows without a subscription, so it is the only text used. Member
    previews are never read. This is what keeps the new catalogue clear of the
    member-source span problem recorded as LAUNCH-058 in the original project.
    """
    subtitle = clean_text(record.get("subtitle"))
    if access != ACCESS_FREE:
        return truncate(subtitle) if subtitle else None

    brief = record.get("brief")
    if isinstance(brief, dict):
        lead = brief.get("lead")
        if isinstance(lead, dict):
            text = clean_text(lead.get("text"))
            if text:
                return truncate(text)
    return truncate(subtitle) if subtitle else None


def published_date(raw: str | None) -> str | None:
    """Normalise a timestamp to a plain YYYY-MM-DD date."""
    if not raw:
        return None
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw.strip())
    if not match:
        return None
    return match.group(0)


def article_id(source: str, source_id: str) -> str:
    """Stable identity: publisher plus that publisher's own immutable id."""
    slug = re.sub(r"[^a-z0-9]+", "-", (source_id or "").lower()).strip("-")
    return f"{source}:{slug}" if slug else source
