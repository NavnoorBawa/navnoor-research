#!/usr/bin/env python3
"""Validate every tracked input against independent rights and schema contracts."""

from __future__ import annotations

import re
import sys
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import refresh_companies
from navnoor_research import config, corpus, jsonio, newsstore, paths, seed
from navnoor_research.adapters import gdelt, rss, sec
from navnoor_research.entities import TopicClassifier
from navnoor_research.schema import RESEARCH_SCHEMA_VERSION

RESEARCH_FIELDS = frozenset({
    "access", "entities", "id", "published", "source", "summary", "title", "topic", "url",
})
RESEARCH_REQUIRED = RESEARCH_FIELDS - {"summary"}
RESEARCH_ENVELOPE = frozenset({
    "research", "schema_version", "source_dataset_version", "source_revision",
})
FORBIDDEN_FIELDS = frozenset({
    "article_body", "body", "body_html", "body_text", "brief", "holdings", "member_preview",
    "parser_observations", "pnl", "position", "reading_minutes", "recommendation", "return",
    "wordcount",
})
SOURCE_HOSTS = dict(seed.SOURCE_HOSTS)
ENABLED_SOURCES = {
    "archive": "seed",
    "federal-reserve-rss": "rss",
    "gdelt-doc-v2": "gdelt",
    "sec-edgar": "sec",
}
ALL_SOURCES = set(ENABLED_SOURCES) | {"cftc-rss"}
MAX_RESEARCH_BYTES = 1_000_000
MAX_COMPANIES_BYTES = 4_000_000


class ValidationError(ValueError):
    """A tracked dataset cannot be published."""


def _real_published(value: Any, where: str) -> None:
    if not isinstance(value, str):
        raise ValidationError(f"{where}: publication time is not text")
    try:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            parsed = datetime.combine(date.fromisoformat(value), datetime.min.time(), timezone.utc)
        elif re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z",
            value,
        ):
            parsed = datetime.fromisoformat(value[:-1] + "+00:00")
        else:
            raise ValueError
    except ValueError as exc:
        raise ValidationError(f"{where}: invalid publication date/instant") from exc
    if parsed > datetime.now(timezone.utc) + newsstore.FUTURE_SKEW:
        raise ValidationError(f"{where}: future publication time refused")


def validate_source_matrix(sources: dict[str, config.Source]) -> None:
    if set(sources) != ALL_SOURCES:
        raise ValidationError("source rights table does not match the reviewed source matrix")
    actual_enabled = {
        source.id: source.adapter for source in sources.values() if source.status == "enabled"
    }
    if actual_enabled != ENABLED_SOURCES:
        raise ValidationError("enabled source adapters do not match the launch matrix")
    if sources["cftc-rss"].status != "disabled":
        raise ValidationError("CFTC must remain disabled until verified TLS succeeds")

    allowed = {
        "archive": set(seed.RECORD_KEYS),
        "sec-edgar": set(sec.PUBLIC_FIELDS),
        "gdelt-doc-v2": set(gdelt.ALLOWED_FIELDS),
        "federal-reserve-rss": set(rss.ALLOWED_FIELDS),
        "cftc-rss": set(rss.ALLOWED_FIELDS),
    }
    for source_id, expected_fields in allowed.items():
        source = sources[source_id]
        if set(source.allowed_fields) != expected_fields:
            raise ValidationError(f"{source_id}: rights fields do not match its adapter")
        if set(source.allowed_fields) & set(source.prohibited_fields):
            raise ValidationError(f"{source_id}: a prohibited field is allow-listed")
    if sources["archive"].allowed_hosts:
        raise ValidationError("archive seed import must not declare a network host")
    if set(sources["archive"].link_hosts) != set(seed.SOURCE_HOSTS.values()):
        raise ValidationError("archive publication link hosts drifted")
    if sources["gdelt-doc-v2"].link_hosts:
        raise ValidationError(
            "GDELT publisher hosts are discovery metadata, not pre-approved hosts"
        )
    if tuple(sources["sec-edgar"].allowed_hosts) != sec.ALLOWED_HOSTS:
        raise ValidationError("SEC request hosts drifted")
    for source_id, feed in rss.FEEDS.items():
        expected_host = (urlsplit(feed).hostname or "").lower()
        source = sources[source_id]
        if source.allowed_hosts != [expected_host] or source.link_hosts != [expected_host]:
            raise ValidationError(f"{source_id}: request/link hosts drifted")


def validate_research(
    document: Any,
    entity_ids: set[str],
    topic_ids: set[str],
) -> None:
    if not isinstance(document, dict) or set(document) != RESEARCH_ENVELOPE:
        raise ValidationError("research envelope has unexpected fields")
    if document.get("schema_version") != RESEARCH_SCHEMA_VERSION:
        raise ValidationError("research schema is unsupported")
    version = document.get("source_dataset_version")
    revision = document.get("source_revision")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9a-f]{64}", version):
        raise ValidationError("research source dataset version is invalid")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValidationError("research source revision is invalid")
    records = document.get("research")
    if not isinstance(records, list) or not records or len(records) > 2_000:
        raise ValidationError("research records must be a bounded non-empty array")
    seen = set()
    for index, record in enumerate(records):
        where = f"research[{index}]"
        if not isinstance(record, dict):
            raise ValidationError(f"{where}: expected an object")
        if not RESEARCH_REQUIRED.issubset(record) or not set(record).issubset(RESEARCH_FIELDS):
            raise ValidationError(f"{where}: fields do not match the research schema")
        if set(record) & FORBIDDEN_FIELDS:
            raise ValidationError(f"{where}: prohibited source material reached research data")
        identifier = record.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"r_[0-9a-f]{64}", identifier):
            raise ValidationError(f"{where}: invalid identity")
        if identifier in seen:
            raise ValidationError(f"{where}: duplicate identity")
        seen.add(identifier)
        title = record.get("title")
        summary = record.get("summary")
        if not isinstance(title, str) or not title or len(title) > 500:
            raise ValidationError(f"{where}: invalid title")
        if summary is not None and (not isinstance(summary, str) or len(summary) > 240):
            raise ValidationError(f"{where}: invalid summary")
        source = record.get("source")
        if source not in SOURCE_HOSTS:
            raise ValidationError(f"{where}: unknown publication source")
        url = record.get("url")
        host = (urlsplit(url).hostname or "").lower() if isinstance(url, str) else ""
        if host != SOURCE_HOSTS[source]:
            raise ValidationError(f"{where}: publication host does not match its source")
        _real_published(record.get("published"), f"{where}.published")
        if record.get("access") not in {"public", "restricted", "unknown"}:
            raise ValidationError(f"{where}: invalid access state")
        if record.get("topic") not in topic_ids:
            raise ValidationError(f"{where}: unknown topic")
        entities = record.get("entities")
        if (
            not isinstance(entities, list) or len(entities) != len(set(entities))
            or any(entity not in entity_ids for entity in entities)
        ):
            raise ValidationError(f"{where}: invalid entity references")

    expected, stats = corpus.import_articles()
    if [article.to_json() for article in expected] != records:
        raise ValidationError("research data is not the exact deterministic seed projection")
    if version != stats["source_dataset_version"] or revision != stats["source_revision"]:
        raise ValidationError("research data provenance does not match the seed transaction")


def load_and_validate() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    sources = config.load_sources()
    validate_source_matrix(sources)
    entities = config.load_entities()
    classifier = TopicClassifier(config.load_topics())
    entity_ids = {entity.id for entity in entities}
    topic_ids = set(classifier.order())

    for path, ceiling in (
        (paths.RESEARCH_PATH, MAX_RESEARCH_BYTES),
        (paths.COMPANIES_PATH, MAX_COMPANIES_BYTES),
        (paths.NEWS_PATH, newsstore.MAX_SNAPSHOT_BYTES),
    ):
        if not path.is_file():
            raise ValidationError(f"required tracked data is missing: {path.name}")
        if path.stat().st_size > ceiling:
            raise ValidationError(f"{path.name} exceeds its tracked byte ceiling")

    research = jsonio.load(paths.RESEARCH_PATH)
    companies = jsonio.load(paths.COMPANIES_PATH)
    news = jsonio.load(paths.NEWS_PATH)
    validate_research(research, entity_ids, topic_ids)
    refresh_companies.validate_snapshot(companies)
    newsstore.validate_snapshot(news, sources, entity_ids, topic_ids)
    return research, companies, news


def main(argv: list[str]) -> int:
    if argv:
        print("error: validate_data.py accepts no arguments", file=sys.stderr)
        return 2
    try:
        research, companies, news = load_and_validate()
    except (
        ValidationError,
        config.ConfigError,
        corpus.CorpusError,
        jsonio.JsonError,
        newsstore.NewsError,
        OSError,
        refresh_companies.CompanyStoreError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"research   : {len(research['research'])}")
    print(f"companies  : {len(companies['items'])}")
    print(f"headlines  : {len(news['items'])}")
    print(f"seed       : {research['source_revision']}")
    print("\nvalid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
