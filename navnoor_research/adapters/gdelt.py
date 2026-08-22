"""GDELT DOC 2.0 discovery metadata.

Discovery only: headline, publisher URL and domain, seen time, language and
source country. The publisher body, GDELT's snippet, its tone score and the
social image are never retained. Queries come from the fixed reviewed list
below; a reader's search terms are never transmitted anywhere.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Callable
from urllib.parse import urlencode, urlsplit

from .. import jsonio
from .http import FetchError, check_url, fetch

ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"

# Fixed, reviewed queries. Not user input, and not derived from user input.
REVIEWED_QUERIES: dict[str, str] = {
    "market-news": (
        '("financial markets" OR "stock market" OR "interest rates" OR "treasury yields" '
        'OR "hedge fund" OR "institutional investor" OR "market volatility" '
        'OR "commodity markets" OR "securities regulator" OR "SEC enforcement")'
    ),
}

MAX_RECORDS = 100
TIMESPAN = "3d"
MAX_BYTES = 3_000_000
MAX_TITLE_CHARS = 300
QUERY_TIMEOUT_SECONDS = 25.0
ALLOWED_FIELDS = frozenset({"title", "url", "domain", "seen_at", "language", "source_country"})

# Retained for readability of the reader-facing list.
ACCEPTED_LANGUAGES = frozenset({"English"})


class GdeltError(Exception):
    """GDELT returned something that cannot be used."""


def _text(item: dict, key: str) -> str:
    value = item.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise GdeltError(f"GDELT article field {key!r} was not text")
    return value.strip()


def query_url(query: str) -> str:
    params = urlencode({
        "query": f"{query} sourcelang:english",
        "mode": "artlist",
        "format": "json",
        "maxrecords": str(MAX_RECORDS),
        "sort": "datedesc",
        "timespan": TIMESPAN,
    })
    return f"{ENDPOINT}?{params}"


def _seen_at(raw: str) -> str:
    """GDELT stamps look like 20260821T083000Z; widen to ISO-8601."""
    text = str(raw or "").strip()
    if len(text) == 16 and text[8] == "T" and text.endswith("Z"):
        widened = f"{text[0:4]}-{text[4:6]}-{text[6:8]}T{text[9:11]}:{text[11:13]}:{text[13:15]}Z"
        try:
            datetime.strptime(widened, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return ""
        return widened
    return ""


def parse_articles(payload: bytes) -> list[dict]:
    """Project a GDELT response onto the allowed field list."""
    try:
        document = jsonio.loads_strict(payload)
    except jsonio.JsonError as exc:
        raise GdeltError(f"malformed GDELT response: {exc}") from exc
    if not isinstance(document, dict):
        raise GdeltError("GDELT response was not an object")

    articles = document.get("articles")
    if not isinstance(articles, list):
        raise GdeltError("GDELT articles field was not an array")
    if len(articles) > MAX_RECORDS:
        raise GdeltError(f"GDELT returned more than the {MAX_RECORDS} requested records")

    out: list[dict] = []
    for item in articles:
        if not isinstance(item, dict):
            raise GdeltError("GDELT article entry was not an object")
        url = _text(item, "url")
        title = " ".join(_text(item, "title").split())
        language = _text(item, "language")
        if not title or not url:
            continue
        if ACCEPTED_LANGUAGES and language not in ACCEPTED_LANGUAGES:
            continue
        if len(title) > MAX_TITLE_CHARS:
            raise GdeltError("GDELT title exceeds the character ceiling")
        host = (urlsplit(url).hostname or "").lower()
        try:
            check_url(url, [host] if host else [])
        except FetchError as exc:
            raise GdeltError(f"GDELT publisher URL is not canonical HTTPS: {exc}") from exc
        seen_at = _seen_at(_text(item, "seendate"))
        if not seen_at:
            continue
        record = {
            "title": title,
            "url": url,
            "domain": host,
            "seen_at": seen_at,
            "language": language,
            "source_country": _text(item, "sourcecountry")[:80],
        }
        out.append({k: v for k, v in record.items() if k in ALLOWED_FIELDS and v})
    return out


def collect(allowed_hosts: Sequence[str], queries: Sequence[str] = (),
            fetcher: Callable[..., bytes] = fetch) -> tuple[list[dict], list[str]]:
    """Run the reviewed queries and return de-duplicated discovery records."""
    selected = list(queries) or list(REVIEWED_QUERIES)
    by_url: dict[str, dict] = {}
    errors: list[str] = []
    for key in selected:
        query = REVIEWED_QUERIES.get(key)
        if query is None:
            raise GdeltError(f"query key {key!r} is not reviewed")
        try:
            # GDELT answers slowly and a retry only compounds it; one bounded
            # attempt per query keeps the scheduled job's worst case predictable.
            payload = fetcher(query_url(query), allowed_hosts, max_bytes=MAX_BYTES,
                              timeout=QUERY_TIMEOUT_SECONDS, retries=0,
                              accept="application/json",
                              content_types=("application/json",))
            for record in parse_articles(payload):
                by_url.setdefault(record["url"], record)
        except (FetchError, GdeltError) as exc:
            # One failing query must not lose the others.
            errors.append(f"{key}: {exc}")
    if not by_url and errors:
        raise GdeltError("; ".join(errors))
    return [by_url[u] for u in sorted(by_url)], errors
