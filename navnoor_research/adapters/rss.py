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

from .http import FetchError, check_url, fetch

# Reviewed feeds, keyed by the source id in config/source_rights.json.
FEEDS: dict[str, str] = {
    "federal-reserve-rss": "https://www.federalreserve.gov/feeds/press_all.xml",
    "cftc-rss": "https://www.cftc.gov/RSS/RSSGP/rssgp.xml",
}

MAX_FEED_BYTES = 2_000_000
MAX_ITEMS_PER_FEED = 150
MAX_TITLE_CHARS = 300
MAX_SUMMARY_CHARS = 500
ALLOWED_FIELDS = frozenset({"guid", "title", "url", "published_at", "summary", "category"})

_DANGEROUS = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_DECLARED_ENCODING = re.compile(r"^\s*<\?xml[^>]*\bencoding\s*=\s*['\"]([^'\"]+)", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")


class FeedError(Exception):
    """The feed could not be parsed safely."""


def parse_xml(payload: bytes) -> ElementTree.Element:
    """Parse XML with external and internal entity expansion refused."""
    if b"\x00" in payload:
        raise FeedError("feed contains NUL bytes or a non-UTF-8 encoding")
    try:
        text = payload.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise FeedError(f"feed is not strict UTF-8: {exc}") from exc
    encoding = _DECLARED_ENCODING.search(text)
    if encoding and encoding.group(1).lower().replace("_", "-") not in {
        "utf-8", "utf8", "us-ascii",
    }:
        raise FeedError(f"feed declares unsupported encoding {encoding.group(1)!r}")
    if _DANGEROUS.search(text):
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
        return ElementTree.fromstring(text, parser=parser)
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


def parse_items(payload: bytes, link_hosts: list[str]) -> list[dict]:
    """Extract allowed fields from every <item> in an RSS document."""
    root = parse_xml(payload)
    items: list[dict] = []
    for index, item in enumerate(root.iter("item")):
        if index >= MAX_ITEMS_PER_FEED:
            raise FeedError(f"feed exceeds {MAX_ITEMS_PER_FEED} item ceiling")
        url = _text(item.find("link"))
        title = _text(item.find("title"))
        if not title or not url:
            continue
        try:
            check_url(url, link_hosts)
        except FetchError as exc:
            raise FeedError(f"feed item link is outside reviewed hosts: {exc}") from exc
        summary = _text(item.find("description"))
        category = _text(item.find("category"))
        if len(title) > MAX_TITLE_CHARS:
            raise FeedError("feed item title exceeds the character ceiling")
        if summary is not None and len(summary) > MAX_SUMMARY_CHARS:
            raise FeedError("feed item summary exceeds the character ceiling")
        if category is not None and len(category) > 120:
            raise FeedError("feed item category exceeds the character ceiling")
        record = {
            "guid": (_text(item.find("guid")) or url)[:2_048],
            "title": title,
            "url": url,
            "published_at": _published(_text(item.find("pubDate"))),
            "summary": summary,
            "category": category,
        }
        items.append({k: v for k, v in record.items() if k in ALLOWED_FIELDS and v is not None})
    return items


def collect(source_id: str, allowed_hosts: list[str], link_hosts: list[str],
            fetcher: Callable[..., bytes] = fetch) -> list[dict]:
    """Fetch and parse one reviewed feed."""
    url = FEEDS.get(source_id)
    if url is None:
        raise FeedError(f"no reviewed feed configured for source {source_id!r}")
    payload = fetcher(url, allowed_hosts, max_bytes=MAX_FEED_BYTES,
                      accept="application/rss+xml, application/xml;q=0.9, text/xml;q=0.8",
                      content_types=("application/rss+xml", "application/xml", "text/xml"))
    if not payload:
        raise FetchError(f"{url}: empty response")
    return parse_items(payload, link_hosts)
