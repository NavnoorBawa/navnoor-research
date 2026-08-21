#!/usr/bin/env python3
"""Validate the stored catalogue before it is allowed into a build.

    python3 validate_data.py [--strict]

Checks shape, referential integrity against the reviewed tables, and the rights
rules that must hold for every published record. --strict also fails on quality
warnings rather than only reporting them.
"""

from __future__ import annotations

import argparse
import re
import sys

from navnoor_research import SCHEMA_VERSION, config, jsonio, normalize, paths
from navnoor_research.entities import TopicClassifier

ARTICLE_FIELDS = {"id", "title", "url", "source", "published", "access", "topic",
                  "entities", "summary", "reading_minutes"}
ARTICLE_REQUIRED = {"id", "title", "url", "source", "published", "access", "topic", "entities"}

NEWS_FIELDS = {"id", "title", "url", "source_id", "attribution", "published", "entities", "topic"}
NEWS_REQUIRED = NEWS_FIELDS

# Fields that must never appear in a published record.
FORBIDDEN_FIELDS = {"body", "body_text", "body_html", "member_preview", "parser_observations",
                    "position", "return", "recommendation", "pnl", "holdings"}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_SUMMARY = 260


def validate_articles(doc: dict, entity_ids: set, topic_ids: set) -> list[str]:
    errors: list[str] = []
    if doc.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"articles: schema_version {doc.get('schema_version')!r} != {SCHEMA_VERSION}")

    seen: dict[str, int] = {}
    for index, record in enumerate(doc.get("articles", [])):
        where = f"articles[{index}] {record.get('id', '?')}"
        extra = set(record) - ARTICLE_FIELDS
        if extra:
            errors.append(f"{where}: unexpected fields {sorted(extra)}")
        forbidden = set(record) & FORBIDDEN_FIELDS
        if forbidden:
            errors.append(f"{where}: forbidden fields {sorted(forbidden)}")
        for field in ARTICLE_REQUIRED - set(record):
            errors.append(f"{where}: missing required field {field!r}")

        if record.get("id") in seen:
            errors.append(f"{where}: duplicate id, first seen at index {seen[record['id']]}")
        elif "id" in record:
            seen[record["id"]] = index

        url = record.get("url", "")
        if not str(url).startswith("https://"):
            errors.append(f"{where}: url must be https, got {url!r}")
        if not DATE_RE.match(str(record.get("published", ""))):
            errors.append(f"{where}: published must be YYYY-MM-DD, got "
                          f"{record.get('published')!r}")
        access = record.get("access")
        if access not in {normalize.ACCESS_FREE, normalize.ACCESS_PAID, normalize.ACCESS_UNKNOWN}:
            errors.append(f"{where}: unknown access {access!r}")
        if record.get("topic") not in topic_ids:
            errors.append(f"{where}: unknown topic {record.get('topic')!r}")
        for entity in record.get("entities", []):
            if entity not in entity_ids:
                errors.append(f"{where}: unknown entity {entity!r}")

        summary = record.get("summary")
        if summary is not None and len(summary) > MAX_SUMMARY:
            errors.append(f"{where}: summary is {len(summary)} chars, ceiling is {MAX_SUMMARY}")
        minutes = record.get("reading_minutes")
        if minutes is not None and (not isinstance(minutes, int) or minutes < 1):
            errors.append(f"{where}: reading_minutes must be a positive integer, got {minutes!r}")
    return errors


def validate_news(doc: dict, entity_ids: set, topic_ids: set, source_ids: set) -> list[str]:
    errors: list[str] = []
    if doc.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"news: schema_version {doc.get('schema_version')!r} != {SCHEMA_VERSION}")

    checked = doc.get("checked_at")
    if checked is not None and not INSTANT_RE.match(str(checked)):
        errors.append(f"news: checked_at must be an ISO-8601 UTC instant, got {checked!r}")

    seen = set()
    for index, record in enumerate(doc.get("items", [])):
        where = f"news[{index}] {record.get('id', '?')}"
        extra = set(record) - NEWS_FIELDS
        if extra:
            errors.append(f"{where}: unexpected fields {sorted(extra)}")
        forbidden = set(record) & FORBIDDEN_FIELDS
        if forbidden:
            errors.append(f"{where}: forbidden fields {sorted(forbidden)}")
        for field in NEWS_REQUIRED - set(record):
            errors.append(f"{where}: missing required field {field!r}")

        if record.get("id") in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(record.get("id"))

        if not str(record.get("url", "")).startswith("https://"):
            errors.append(f"{where}: url must be https, got {record.get('url')!r}")
        if not INSTANT_RE.match(str(record.get("published", ""))):
            errors.append(f"{where}: published must be an ISO-8601 UTC instant, got "
                          f"{record.get('published')!r}")
        if record.get("source_id") not in source_ids:
            errors.append(f"{where}: unknown source {record.get('source_id')!r}")
        if record.get("topic") not in topic_ids:
            errors.append(f"{where}: unknown topic {record.get('topic')!r}")
        for entity in record.get("entities", []):
            if entity not in entity_ids:
                errors.append(f"{where}: unknown entity {entity!r}")
    return errors


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = parser.parse_args(argv)

    entity_ids = {e.id for e in config.load_entities()}
    classifier = TopicClassifier(config.load_topics())
    topic_ids = set(classifier.order())
    source_ids = set(config.load_sources())

    if not paths.ARTICLES_PATH.exists():
        print("error: data/articles.json is missing. Run import_articles.py.", file=sys.stderr)
        return 2

    articles_doc = jsonio.load(paths.ARTICLES_PATH)
    news_doc = jsonio.load(paths.NEWS_PATH) if paths.NEWS_PATH.exists() else {
        "schema_version": SCHEMA_VERSION, "checked_at": None, "items": []
    }

    errors = validate_articles(articles_doc, entity_ids, topic_ids)
    errors += validate_news(news_doc, entity_ids, topic_ids, source_ids)

    articles = articles_doc.get("articles", [])
    total = max(1, len(articles))
    warnings = []
    no_summary = sum(1 for a in articles if not a.get("summary"))
    if no_summary / total > 0.65:
        warnings.append(f"{no_summary}/{len(articles)} articles have no summary")
    unclassified = sum(1 for a in articles if a.get("topic") == TopicClassifier.FALLBACK)
    if unclassified / total > 0.35:
        warnings.append(f"{unclassified}/{len(articles)} articles fall back to the general topic")

    print(f"articles  : {len(articles)}")
    print(f"headlines : {len(news_doc.get('items', []))}")
    for warning in warnings:
        print(f"warning   : {warning}")
    for error in errors:
        print(f"error     : {error}", file=sys.stderr)

    if errors:
        print(f"\nFAILED with {len(errors)} error(s)", file=sys.stderr)
        return 1
    if warnings and args.strict:
        print(f"\nFAILED with {len(warnings)} warning(s) under --strict", file=sys.stderr)
        return 1
    print("\nvalid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
