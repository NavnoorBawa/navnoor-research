"""Validated last-known-good storage for checked headline metadata."""

from __future__ import annotations

import fcntl
import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import jsonio, paths
from .adapters.http import FetchError, check_url
from .config import Source
from .entities import EntityMatcher, TopicClassifier
from .models import NewsItem
from .schema import NEWS_SCHEMA_VERSION

MAX_ITEMS = 300
MAX_SNAPSHOT_BYTES = 750_000
MAX_TITLE_CHARS = 300
MAX_ATTRIBUTION_CHARS = 120
MAX_PUBLISHER_CHARS = 253
FUTURE_SKEW = timedelta(minutes=5)
LOCK_PATH = Path("/tmp/navnoor-research-news.lock")

ITEM_FIELDS = frozenset({
    "attribution", "entities", "id", "published", "publisher", "source_id",
    "title", "topic", "url",
})
STATE_FIELDS = frozenset({
    "attribution", "item_count", "label", "last_attempt_at", "last_success_at", "status",
})
SNAPSHOT_FIELDS = frozenset({"items", "schema_version", "sources"})
STATE_VALUES = frozenset({"error", "never", "ok", "partial"})

_INSTANT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_PROHIBITED_HEADLINE = re.compile(
    r"(?:"
    r"\blive(?:\s+(?:blog|coverage|updates?))?\b|"
    r"\bprice\s+target\b|"
    r"\btarget\s+price\b|"
    r"\b(?:raise|raises|raised|cut|cuts|lower|lowers|lowered|boost|boosts|boosted|"
    r"slash|slashes|slashed)\b.{0,80}\b(?:price\s+)?target\b|"
    r"\b(?:strong\s+)?(?:buy|sell|hold)\s+(?:rating|recommendation)\b|"
    r"\b(?:is|remains?|rates?)\s+(?:an?\s+)?(?:strong\s+)?(?:buy|sell|hold)\b|"
    r"\b(?:upgrade|upgrades|upgraded|downgrade|downgrades|downgraded)\b|"
    r"\b(?:upgrade|downgrade|upgraded|downgraded)\b.{0,80}\bto\s+"
    r"(?:(?:strong\s+)?(?:buy|sell|hold)|(?:out|under)perform|neutral|"
    r"overweight|underweight)\b|"
    r"\bstocks?\s+to\s+(?:buy|sell)\b|"
    r"\b(?:stock|stocks|investment|investments)\s+picks?\b|"
    r"\b(?:should|could)\s+(?:you\s+)?(?:buy|sell)\b|"
    r"\brecommend(?:s|ed|ation|ations)\b"
    r")",
    re.IGNORECASE,
)


class NewsError(ValueError):
    """A headline or snapshot violates the publication contract."""


def news_id(url: str) -> str:
    """Full content-addressed identity for one canonical publisher URL."""
    return "n_" + hashlib.sha256(url.encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_instant(value: Any, where: str, now: datetime | None = None) -> datetime:
    text = value if isinstance(value, str) else ""
    if not _INSTANT.fullmatch(text):
        raise NewsError(f"{where}: expected a whole-second UTC instant")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise NewsError(f"{where}: invalid calendar instant") from exc
    if parsed > (now or datetime.now(timezone.utc)) + FUTURE_SKEW:
        raise NewsError(f"{where}: future timestamp refused")
    return parsed


def headline_allowed(title: str) -> bool:
    """Return False for live-blog, target, rating, or recommendation language."""
    return _PROHIBITED_HEADLINE.search(title) is None


def _publisher_url(url: str, source: Source) -> str:
    host = (urlsplit(url).hostname or "").lower()
    allowed = source.link_hosts if source.adapter == "rss" else ([host] if host else [])
    try:
        return check_url(url, allowed)
    except FetchError as exc:
        raise NewsError(f"{source.id}: publisher URL is invalid: {exc}") from exc


def build_item(
    raw: dict[str, Any],
    source: Source,
    matcher: EntityMatcher,
    classifier: TopicClassifier,
    *,
    now: datetime | None = None,
) -> NewsItem | None:
    """Project one adapter row, filtering prohibited editorial claim formats."""
    if not isinstance(raw, dict):
        raise NewsError(f"{source.id}: adapter row is not an object")
    unknown = set(raw) - set(source.allowed_fields)
    forbidden = set(raw) & set(source.prohibited_fields)
    if unknown or forbidden:
        raise NewsError(
            f"{source.id}: adapter row fields violate the rights profile "
            f"(unknown={sorted(unknown)}, prohibited={sorted(forbidden)})"
        )
    title = " ".join(str(raw.get("title") or "").split())
    url = str(raw.get("url") or "").strip()
    published = str(raw.get("published_at") or raw.get("seen_at") or "").strip()
    if not title or not url or not published:
        raise NewsError(f"{source.id}: adapter row is missing title, URL, or publication time")
    if len(title) > MAX_TITLE_CHARS or len(title.encode("utf-8")) > 1_200:
        raise NewsError(f"{source.id}: title exceeds the publication ceiling")
    if not headline_allowed(title):
        return None
    parse_instant(published, f"{source.id}.published", now)
    publisher = _publisher_url(url, source)
    raw_domain = str(raw.get("domain") or "").strip().lower()
    if raw_domain and raw_domain != publisher:
        raise NewsError(f"{source.id}: declared domain does not match publisher URL")

    parts = [title, str(raw.get("summary") or ""), str(raw.get("category") or "")]
    haystack = " ".join(part for part in parts if part)
    entity_ids = matcher.find(haystack)
    return NewsItem(
        id=news_id(url),
        title=title,
        url=url,
        source_id=source.id,
        attribution=source.attribution,
        publisher=publisher,
        published=published,
        entities=entity_ids,
        topic=classifier.classify(haystack, entity_ids),
    )


def empty_snapshot(sources: dict[str, Source]) -> dict[str, Any]:
    states = {}
    for source in sorted(sources.values(), key=lambda item: item.id):
        if source.status == "enabled" and source.adapter in {"gdelt", "rss"}:
            states[source.id] = {
                "attribution": source.attribution,
                "item_count": 0,
                "label": source.label,
                "last_attempt_at": None,
                "last_success_at": None,
                "status": "never",
            }
    return {"items": [], "schema_version": NEWS_SCHEMA_VERSION, "sources": states}


def _canonical_item(
    record: Any,
    sources: dict[str, Source],
    entity_ids: set[str],
    topic_ids: set[str],
    now: datetime,
    where: str,
) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != ITEM_FIELDS:
        raise NewsError(f"{where}: item fields do not match the fixed schema")
    source_id = record.get("source_id")
    source = sources.get(source_id) if isinstance(source_id, str) else None
    if source is None or source.status != "enabled" or source.adapter not in {"gdelt", "rss"}:
        raise NewsError(f"{where}: source is not an enabled news adapter")
    title = record.get("title")
    if not isinstance(title, str) or not title or len(title) > MAX_TITLE_CHARS:
        raise NewsError(f"{where}: invalid title")
    if not headline_allowed(title):
        raise NewsError(f"{where}: prohibited live/target/rating/recommendation headline")
    url = record.get("url")
    if not isinstance(url, str):
        raise NewsError(f"{where}: URL is not text")
    publisher = _publisher_url(url, source)
    if record.get("publisher") != publisher:
        raise NewsError(f"{where}: publisher does not match the canonical URL host")
    if record.get("id") != news_id(url):
        raise NewsError(f"{where}: content identity does not match URL")
    if record.get("attribution") != source.attribution:
        raise NewsError(f"{where}: source attribution drifted")
    parse_instant(record.get("published"), f"{where}.published", now)
    entities = record.get("entities")
    if (
        not isinstance(entities, list) or len(entities) > 50
        or any(not isinstance(entity, str) or entity not in entity_ids for entity in entities)
        or len(entities) != len(set(entities))
    ):
        raise NewsError(f"{where}: entity references are invalid")
    if record.get("topic") not in topic_ids:
        raise NewsError(f"{where}: topic reference is invalid")
    attribution = record.get("attribution")
    if not isinstance(attribution, str) or len(attribution) > MAX_ATTRIBUTION_CHARS:
        raise NewsError(f"{where}: attribution is invalid")
    if len(publisher) > MAX_PUBLISHER_CHARS:
        raise NewsError(f"{where}: publisher host is invalid")
    return dict(record)


def validate_snapshot(
    document: Any,
    sources: dict[str, Source],
    entity_ids: set[str],
    topic_ids: set[str],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate and return a complete immutable-shaped headline snapshot."""
    moment = now or datetime.now(timezone.utc)
    if not isinstance(document, dict) or set(document) != SNAPSHOT_FIELDS:
        raise NewsError("news snapshot envelope has unexpected fields")
    if document.get("schema_version") != NEWS_SCHEMA_VERSION:
        raise NewsError("news snapshot schema is unsupported")
    items = document.get("items")
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise NewsError(f"news snapshot exceeds the {MAX_ITEMS} item ceiling")
    canonical = [
        _canonical_item(record, sources, entity_ids, topic_ids, moment, f"news[{index}]")
        for index, record in enumerate(items)
    ]
    ids = [record["id"] for record in canonical]
    if len(ids) != len(set(ids)):
        raise NewsError("news snapshot contains duplicate identities")
    expected_order = sorted(
        canonical, key=lambda record: (record["published"], record["id"]), reverse=True
    )
    if canonical != expected_order:
        raise NewsError("news items are not in deterministic newest-first order")

    states = document.get("sources")
    expected_source_ids = set(empty_snapshot(sources)["sources"])
    if not isinstance(states, dict) or set(states) != expected_source_ids:
        raise NewsError("news source-state coverage does not match enabled adapters")
    counts = Counter(record["source_id"] for record in canonical)
    for source_id, state in states.items():
        source = sources[source_id]
        if not isinstance(state, dict) or set(state) != STATE_FIELDS:
            raise NewsError(f"news source state {source_id!r} has unexpected fields")
        if state.get("label") != source.label or state.get("attribution") != source.attribution:
            raise NewsError(f"news source state {source_id!r} attribution drifted")
        if state.get("status") not in STATE_VALUES:
            raise NewsError(f"news source state {source_id!r} status is invalid")
        if state.get("item_count") != counts[source_id]:
            raise NewsError(f"news source state {source_id!r} item count is inconsistent")
        attempt = state.get("last_attempt_at")
        success = state.get("last_success_at")
        if attempt is not None:
            attempt_time = parse_instant(
                attempt, f"news source {source_id}.last_attempt_at", moment
            )
        else:
            attempt_time = None
        if success is not None:
            success_time = parse_instant(
                success, f"news source {source_id}.last_success_at", moment
            )
        else:
            success_time = None
        if success_time and attempt_time and success_time > attempt_time:
            raise NewsError(f"news source state {source_id!r} succeeds after its latest attempt")
        if state["status"] == "never" and (attempt is not None or success is not None):
            raise NewsError(f"news source state {source_id!r} never-state has timestamps")
        if state["status"] == "ok" and (attempt is None or success != attempt):
            raise NewsError(f"news source state {source_id!r} success timestamps are inconsistent")

    encoded = jsonio.dumps(document).encode("utf-8")
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise NewsError(f"news snapshot exceeds {MAX_SNAPSHOT_BYTES} bytes")
    return document


def load(
    sources: dict[str, Source],
    entity_ids: set[str],
    topic_ids: set[str],
    path: Path | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    target = path or paths.NEWS_PATH
    if not target.exists():
        return empty_snapshot(sources)
    try:
        document = jsonio.load(target)
    except (OSError, jsonio.JsonError) as exc:
        raise NewsError(f"stored news snapshot is invalid: {exc}") from exc
    return validate_snapshot(document, sources, entity_ids, topic_ids, now=now)


def merge(
    previous: Sequence[dict[str, Any]],
    incoming: Iterable[NewsItem],
    retention: dict[str, int],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Merge already-validated records with fresh projected items."""
    moment = now or datetime.now(timezone.utc)
    merged: dict[str, dict[str, Any]] = {record["id"]: dict(record) for record in previous}
    for item in incoming:
        merged[item.id] = item.to_json()
    kept = []
    for record in merged.values():
        days = retention.get(record["source_id"], 0)
        stamp = parse_instant(record["published"], "retained news item", moment)
        if days and stamp < moment - timedelta(days=days):
            continue
        kept.append(record)
    kept.sort(key=lambda record: (record["published"], record["id"]), reverse=True)
    return kept[:MAX_ITEMS]


def with_item_counts(snapshot: dict[str, Any]) -> dict[str, Any]:
    counts = Counter(record["source_id"] for record in snapshot["items"])
    for source_id, state in snapshot["sources"].items():
        state["item_count"] = counts[source_id]
    return snapshot


def promote(
    snapshot: dict[str, Any],
    sources: dict[str, Source],
    entity_ids: set[str],
    topic_ids: set[str],
    path: Path | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate before atomically replacing the last-known-good snapshot."""
    target = path or paths.NEWS_PATH
    validate_snapshot(snapshot, sources, entity_ids, topic_ids, now=now)
    jsonio.write_atomic(target, jsonio.dumps_pretty(snapshot))
    return snapshot


@contextmanager
def refresh_lock() -> Iterator[None]:
    """Serialize scheduled refreshes so freshness can never regress."""
    with LOCK_PATH.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
