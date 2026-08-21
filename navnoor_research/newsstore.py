"""The checked-headline store.

Two rules govern this file. A refresh is a transaction: either a complete,
validated snapshot replaces the previous one, or the previous one survives
untouched. And nothing here is called 'live' — every timestamp describes when a
source was last *checked*.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone

from . import SCHEMA_VERSION, jsonio, paths
from .config import Source
from .entities import EntityMatcher, TopicClassifier
from .models import NewsItem

MAX_ITEMS = 400


def news_id(url: str) -> str:
    """Content-addressed identity so the same headline never appears twice."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def build_item(
    raw: dict,
    source: Source,
    matcher: EntityMatcher,
    classifier: TopicClassifier,
) -> NewsItem | None:
    """Turn one adapter record into a publishable headline, or None."""
    title = (raw.get("title") or "").strip()
    url = (raw.get("url") or "").strip()
    published = (raw.get("published_at") or raw.get("seen_at") or "").strip()
    if not title or not url.startswith("https://") or not published:
        return None

    parts = [title, raw.get("summary") or "", raw.get("category") or ""]
    haystack = " ".join(p for p in parts if p)
    entity_ids = matcher.find(haystack)
    return NewsItem(
        id=news_id(url),
        title=title,
        url=url,
        source_id=source.id,
        attribution=source.attribution,
        published=published,
        entities=entity_ids,
        topic=classifier.classify(haystack, entity_ids),
    )


def load(path=None) -> dict:
    """Read the last known good snapshot, or an empty one."""
    target = path or paths.NEWS_PATH
    if not target.exists():
        return {"schema_version": SCHEMA_VERSION, "checked_at": None, "items": []}
    return jsonio.load(target)


def merge(
    previous: Sequence[dict],
    incoming: Iterable[NewsItem],
    retention: dict[str, int],
    now: datetime | None = None,
) -> list[dict]:
    """Combine a fresh sweep with retained history, newest first.

    Incoming records win on id so that a corrected headline replaces the stored
    one, and per-source retention is enforced on the way out.
    """
    moment = now or datetime.now(timezone.utc)
    merged: dict[str, dict] = {item["id"]: item for item in previous if "id" in item}
    for item in incoming:
        merged[item.id] = item.to_json()

    kept: list[dict] = []
    for record in merged.values():
        days = retention.get(record.get("source_id", ""), 0)
        stamp = _parse_iso(record.get("published", ""))
        if days and stamp and stamp < moment - timedelta(days=days):
            continue
        kept.append(record)

    kept.sort(key=lambda r: (r.get("published", ""), r.get("id", "")), reverse=True)
    return kept[:MAX_ITEMS]


def promote(items: Sequence[dict], checked_at: str, path=None) -> dict:
    """Atomically replace the store. A failed write leaves the old file intact."""
    target = path or paths.NEWS_PATH
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "checked_at": checked_at,
        "items": list(items),
    }
    jsonio.write_atomic(target, jsonio.dumps_pretty(snapshot))
    return snapshot
