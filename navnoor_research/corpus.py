"""Read-only import of article metadata from the published research corpus.

This module never writes to the corpus and never reads a body field. It opens
exactly one file — the metadata index — and takes only the fields listed in
`ALLOWED_SOURCE_FIELDS`. Body text, member previews and parser observations are
not read at all, so they cannot leak into the new catalogue by accident.
"""

from __future__ import annotations

from pathlib import Path

from . import jsonio, normalize
from .entities import EntityMatcher, TopicClassifier
from .models import Article

CORPUS_INDEX_NAME = "articles_index.json"

ALLOWED_SOURCE_FIELDS = frozenset({
    "source", "source_id", "slug", "title", "subtitle",
    "post_date", "url", "audience", "wordcount", "content_status", "brief",
})

# Present in the corpus and deliberately never read.
PROHIBITED_SOURCE_FIELDS = frozenset({
    "body_text", "member_preview", "parser_observations", "body_html_length",
    "body_source", "position", "return", "recommendation",
})


class CorpusError(Exception):
    """The corpus is missing or does not have the expected shape."""


def index_path(corpus_dir: Path) -> Path:
    return corpus_dir / CORPUS_INDEX_NAME


def load_index(corpus_dir: Path) -> list[dict]:
    path = index_path(corpus_dir)
    if not path.is_file():
        raise CorpusError(
            f"corpus index not found at {path}. Set CORPUS_DIR to the directory "
            f"containing {CORPUS_INDEX_NAME}."
        )
    records = jsonio.load(path)
    if not isinstance(records, list):
        raise CorpusError(f"{path}: expected a list of records")
    return records


def _project(record: dict) -> dict:
    """Keep only reviewed fields, so nothing else can be read downstream."""
    return {k: v for k, v in record.items() if k in ALLOWED_SOURCE_FIELDS}


def build_article(
    record: dict,
    matcher: EntityMatcher,
    classifier: TopicClassifier,
) -> Article | None:
    """Convert one corpus record, or None when it cannot be published safely."""
    safe = _project(record)

    title = normalize.clean_text(safe.get("title"))
    url = (safe.get("url") or "").strip()
    published = normalize.published_date(safe.get("post_date"))
    source = (safe.get("source") or "").strip().lower()

    # A record with no title, no link, or no date cannot be presented honestly.
    if not title or not url.startswith("https://") or not published or not source:
        return None

    access = normalize.access_of(safe.get("audience"))
    summary = normalize.summary_for(safe, access)

    # Entities and topic are read from public-facing text only.
    parts = [title, normalize.clean_text(safe.get("subtitle")), summary]
    haystack = " ".join(p for p in parts if p)
    entity_ids = matcher.find(haystack)
    topic = classifier.classify(haystack, entity_ids)

    return Article(
        id=normalize.article_id(source, safe.get("source_id") or safe.get("slug") or ""),
        title=title,
        url=url,
        source=source,
        published=published,
        access=access,
        topic=topic,
        entities=entity_ids,
        summary=summary,
        reading_minutes=normalize.reading_minutes(
            safe.get("wordcount"), safe.get("content_status")
        ),
    )


def import_articles(corpus_dir: Path) -> tuple[list[Article], dict[str, int]]:
    """Import every publishable article, newest first, with import counters."""
    from .config import load_entities, load_topics

    matcher = EntityMatcher(load_entities())
    classifier = TopicClassifier(load_topics())

    records = load_index(corpus_dir)
    stats: dict[str, int] = {
        "read": len(records), "published": 0, "skipped": 0,
        "with_summary": 0, "with_reading_time": 0, "with_entities": 0, "classified": 0,
    }

    by_id: dict[str, Article] = {}
    for record in records:
        article = build_article(record, matcher, classifier)
        if article is None:
            stats["skipped"] += 1
            continue
        # Cross-source reruns can repeat an id; last write wins deterministically
        # because the input order is fixed.
        by_id[article.id] = article

    articles = sorted(by_id.values(), key=lambda a: (a.published, a.id), reverse=True)
    stats["published"] = len(articles)
    stats["skipped"] = stats["read"] - stats["published"]
    for article in articles:
        stats["with_summary"] += 1 if article.summary else 0
        stats["with_reading_time"] += 1 if article.reading_minutes else 0
        stats["with_entities"] += 1 if article.entities else 0
        stats["classified"] += 1 if article.topic != TopicClassifier.FALLBACK else 0
    return articles, stats
