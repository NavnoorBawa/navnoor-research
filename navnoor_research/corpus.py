"""Build the searchable research catalogue from the fixed metadata-only seed."""

from __future__ import annotations

from typing import Any

from . import normalize, paths, seed
from .entities import EntityMatcher, TopicClassifier
from .models import Article

ALLOWED_SOURCE_FIELDS = frozenset(seed.RECORD_KEYS)
PROHIBITED_SOURCE_FIELDS = frozenset({
    "brief", "body", "body_text", "body_html", "member_preview",
    "parser_observations", "reading_minutes", "wordcount", "position",
    "return", "recommendation", "pnl", "holdings",
})


class CorpusError(ValueError):
    """The seed is missing or violates the published projection contract."""


def load_index() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Load only the fixed seed transaction and verify its commit marker."""
    if not paths.PUBLICATIONS_PATH.is_file() or not paths.SEED_MANIFEST_PATH.is_file():
        raise CorpusError("the committed research seed transaction is incomplete")
    try:
        document, provenance = seed.validate_stored(
            paths.PUBLICATIONS_PATH.read_bytes(),
            paths.SEED_MANIFEST_PATH.read_bytes(),
        )
    except (OSError, seed.SeedError) as exc:
        raise CorpusError(str(exc)) from exc
    records = document["records"]
    return records, document, provenance


def build_article(
    record: dict[str, Any],
    matcher: EntityMatcher,
    classifier: TopicClassifier,
) -> Article:
    if set(record) != ALLOWED_SOURCE_FIELDS:
        raise CorpusError("research seed record keys do not match the fixed rights profile")
    if set(record) & PROHIBITED_SOURCE_FIELDS:
        raise CorpusError("research seed contains a prohibited field")
    title = str(record.get("title") or "")
    subtitle = normalize.clean_text(str(record.get("subtitle") or ""))
    url = str(record.get("canonical_url") or "")
    published = str(record.get("published_at") or "")
    access = str(record.get("access") or "")
    if not title or not url.startswith("https://") or not published:
        raise CorpusError("research seed record is missing title, HTTPS URL, or publication time")
    if access not in {
        normalize.ACCESS_PUBLIC, normalize.ACCESS_RESTRICTED, normalize.ACCESS_UNKNOWN
    }:
        raise CorpusError(f"research seed record has unknown access {access!r}")
    haystack = " ".join(part for part in (title, subtitle) if part)
    entity_ids = matcher.find(haystack)
    topic = classifier.classify(haystack, entity_ids)
    return Article(
        id=str(record["id"]),
        title=title,
        url=url,
        source=str(record["source"]),
        published=published,
        access=access,
        topic=topic,
        entities=entity_ids,
        summary=normalize.truncate(subtitle) if subtitle else None,
    )


def import_articles() -> tuple[list[Article], dict[str, Any]]:
    """Derive searchable records in deterministic newest-first order."""
    from .config import load_entities, load_topics

    matcher = EntityMatcher(load_entities())
    classifier = TopicClassifier(load_topics())
    records, document, provenance = load_index()
    articles = [build_article(record, matcher, classifier) for record in records]
    ids = [article.id for article in articles]
    if len(set(ids)) != len(ids):
        raise CorpusError("research seed produces duplicate publication IDs")
    articles.sort(key=lambda article: (article.published, article.id), reverse=True)
    stats: dict[str, Any] = {
        "read": len(records),
        "published": len(articles),
        "with_summary": sum(bool(article.summary) for article in articles),
        "with_entities": sum(bool(article.entities) for article in articles),
        "classified": sum(article.topic != TopicClassifier.FALLBACK for article in articles),
        "source_dataset_version": str(document.get("source_dataset_version") or ""),
        "source_revision": str(provenance["source_snapshot"]["revision"]),
    }
    return articles, stats
