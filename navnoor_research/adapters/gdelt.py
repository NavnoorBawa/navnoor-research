"""GDELT DOC 2.0 discovery metadata.

Discovery only: headline, publisher URL and domain, seen time, language and
source country. The publisher body, GDELT's snippet, its tone score and the
social image are never retained. Queries come from the fixed reviewed list
below; a reader's search terms are never transmitted anywhere.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Callable
from urllib.parse import urlencode

from .http import FetchError, fetch

ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"

# Fixed, reviewed queries. Not user input, and not derived from user input.
REVIEWED_QUERIES: dict[str, str] = {
    "markets": '("stock market" OR "equity markets" OR "financial markets")',
    "rates": '("interest rates" OR "central bank" OR "treasury yields")',
    "hedge-funds": '("hedge fund" OR "asset manager" OR "institutional investor")',
    "volatility": '("market volatility" OR "options market")',
    "commodities": '("oil prices" OR "gold prices" OR "commodity markets")',
    "regulation": '("securities regulator" OR "market manipulation" OR "SEC enforcement")',
}

MAX_RECORDS = 60
TIMESPAN = "3d"
MAX_BYTES = 3_000_000
QUERY_TIMEOUT_SECONDS = 25.0
ALLOWED_FIELDS = frozenset({"title", "url", "domain", "seen_at", "language", "source_country"})

# Retained for readability of the reader-facing list.
ACCEPTED_LANGUAGES = frozenset({"English"})


class GdeltError(Exception):
    """GDELT returned something that cannot be used."""


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
    text = (raw or "").strip()
    if len(text) == 16 and text[8] == "T" and text.endswith("Z"):
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}T{text[9:11]}:{text[11:13]}:{text[13:15]}Z"
    return text


def parse_articles(payload: bytes) -> list[dict]:
    """Project a GDELT response onto the allowed field list."""
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GdeltError(f"malformed GDELT response: {exc}") from exc
    if not isinstance(document, dict):
        raise GdeltError("GDELT response was not an object")

    out: list[dict] = []
    for item in document.get("articles") or []:
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or "").strip()
        title = " ".join((item.get("title") or "").split())
        language = (item.get("language") or "").strip()
        if not title or not url.startswith("https://"):
            continue
        if ACCEPTED_LANGUAGES and language not in ACCEPTED_LANGUAGES:
            continue
        record = {
            "title": title,
            "url": url,
            "domain": (item.get("domain") or "").strip(),
            "seen_at": _seen_at(item.get("seendate") or ""),
            "language": language,
            "source_country": (item.get("sourcecountry") or "").strip(),
        }
        out.append({k: v for k, v in record.items() if k in ALLOWED_FIELDS and v})
    return out


def collect(allowed_hosts: Sequence[str], queries: Sequence[str] = (),
            fetcher: Callable[..., bytes] = fetch) -> list[dict]:
    """Run the reviewed queries and return de-duplicated discovery records."""
    selected = list(queries) or list(REVIEWED_QUERIES)
    by_url: dict[str, dict] = {}
    errors: list[str] = []
    for key in selected:
        query = REVIEWED_QUERIES.get(key)
        if query is None:
            continue
        try:
            # GDELT answers slowly and a retry only compounds it; one bounded
            # attempt per query keeps the scheduled job's worst case predictable.
            payload = fetcher(query_url(query), allowed_hosts, max_bytes=MAX_BYTES,
                              timeout=QUERY_TIMEOUT_SECONDS, retries=0,
                              accept="application/json")
            for record in parse_articles(payload):
                by_url.setdefault(record["url"], record)
        except (FetchError, GdeltError) as exc:
            # One failing query must not lose the others.
            errors.append(f"{key}: {exc}")
    if not by_url and errors:
        raise GdeltError("; ".join(errors))
    return [by_url[u] for u in sorted(by_url)]
