"""Official regulator RSS feeds (Federal Reserve Board, CFTC).

Headline metadata only. No image, seal, attachment or publisher body is read.
The XML is parsed defensively: a document declaring a DTD or an entity is
rejected outright rather than handed to the parser.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Callable

from .http import FetchError, fetch

# Reviewed feeds, keyed by the source id in config/source_rights.json.
FEEDS: dict[str, str] = {
    "federal-reserve-rss": "https://www.federalreserve.gov/feeds/press_all.xml",
    "cftc-rss": "https://www.cftc.gov/RSS/RSSGP/rssgp.xml",
}

MAX_FEED_BYTES = 2_000_000
ALLOWED_FIELDS = frozenset({"guid", "title", "url", "published_at", "summary", "category"})

_DANGEROUS = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")


class FeedError(Exception):
    """The feed could not be parsed safely."""


def parse_xml(payload: bytes) -> ElementTree.Element:
    """Parse XML with external and internal entity expansion refused."""
    if _DANGEROUS.search(payload):
        raise FeedError("feed declares a DTD or entity; refusing to parse")
    parser = ElementTree.XMLParser()
    # Belt and braces: where the pure-Python parser allows it, make entity
    # resolution raise instead of expand. CPython's C parser exposes `entity`
    # read-only, in which case the DTD scan above is the operative defence.
    try:
        class _Refuse(dict):
            def __getitem__(self, key):
                raise FeedError(f"entity {key!r} refused")
        parser.entity = _Refuse()  # type: ignore[attr-defined]
    except AttributeError:
        pass
    try:
        return ElementTree.fromstring(payload, parser=parser)
    except ElementTree.ParseError as exc:
        raise FeedError(f"malformed feed: {exc}") from exc


def _text(node: ElementTree.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    stripped = _TAGS.sub(" ", node.text)
    collapsed = " ".join(stripped.split())
    return collapsed or None


def _published(raw: str | None) -> str | None:
    """RFC 822 feed date to a UTC ISO-8601 instant."""
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_items(payload: bytes) -> list[dict]:
    """Extract allowed fields from every <item> in an RSS document."""
    root = parse_xml(payload)
    items: list[dict] = []
    for item in root.iter("item"):
        url = _text(item.find("link"))
        title = _text(item.find("title"))
        if not title or not url or not url.startswith("https://"):
            continue
        record = {
            "guid": _text(item.find("guid")) or url,
            "title": title,
            "url": url,
            "published_at": _published(_text(item.find("pubDate"))),
            "summary": _text(item.find("description")),
            "category": _text(item.find("category")),
        }
        items.append({k: v for k, v in record.items() if k in ALLOWED_FIELDS and v is not None})
    return items


def collect(source_id: str, allowed_hosts: list[str],
            fetcher: Callable[..., bytes] = fetch) -> list[dict]:
    """Fetch and parse one reviewed feed."""
    url = FEEDS.get(source_id)
    if url is None:
        raise FeedError(f"no reviewed feed configured for source {source_id!r}")
    payload = fetcher(url, allowed_hosts, max_bytes=MAX_FEED_BYTES,
                      accept="application/rss+xml, application/xml;q=0.9, */*;q=0.8")
    if not payload:
        raise FetchError(f"{url}: empty response")
    return parse_items(payload)
