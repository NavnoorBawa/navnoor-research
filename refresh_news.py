#!/usr/bin/env python3
"""Check fixed public sources and atomically promote checked headline metadata."""

from __future__ import annotations

import argparse
import copy
import sys
from datetime import datetime, timezone
from typing import Any

from navnoor_research import config, jsonio, newsstore, paths
from navnoor_research.adapters import gdelt, rss
from navnoor_research.adapters.http import FetchError
from navnoor_research.entities import EntityMatcher, TopicClassifier

RSS_SOURCES = ("federal-reserve-rss", "cftc-rss")
GDELT_SOURCE = "gdelt-doc-v2"


def _legacy_snapshot() -> bool:
    """Recognise only the repository's superseded global-schema snapshot."""
    try:
        document = jsonio.load(paths.NEWS_PATH)
    except (OSError, jsonio.JsonError):
        return False
    return (
        isinstance(document, dict)
        and set(document) == {"checked_at", "items", "schema_version"}
        and document.get("schema_version") == 2
        and isinstance(document.get("items"), list)
    )


def _without_retired_sources(
    sources: dict[str, config.Source],
    entity_ids: set[str],
    topic_ids: set[str],
) -> dict[str, Any] | None:
    """Drop only zero-item state for an explicitly disabled news adapter."""
    try:
        document = jsonio.load(paths.NEWS_PATH)
    except (OSError, jsonio.JsonError):
        return None
    if not isinstance(document, dict) or document.get("schema_version") != 3:
        return None
    candidate = copy.deepcopy(document)
    states = candidate.get("sources")
    items = candidate.get("items")
    if not isinstance(states, dict) or not isinstance(items, list):
        return None
    expected = set(newsstore.empty_snapshot(sources)["sources"])
    retired = set(states) - expected
    if not retired:
        return None
    if any(
        not isinstance(states[source_id], dict)
        or states[source_id].get("item_count") != 0
        or any(item.get("source_id") == source_id for item in items if isinstance(item, dict))
        for source_id in retired
    ):
        return None
    for source_id in retired:
        del states[source_id]
    try:
        return newsstore.validate_snapshot(candidate, sources, entity_ids, topic_ids)
    except newsstore.NewsError:
        return None


def _state(
    previous: dict[str, Any],
    source: config.Source,
    attempted_at: str,
    status: str,
) -> dict[str, Any]:
    state = dict(previous)
    state.update({
        "attribution": source.attribution,
        "label": source.label,
        "last_attempt_at": attempted_at,
        "status": status,
    })
    if status == "ok":
        state["last_success_at"] = attempted_at
    return state


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline", action="store_true",
        help="validate the committed last-known-good snapshot without network access",
    )
    args = parser.parse_args(argv)

    sources = config.load_sources()
    entities = config.load_entities()
    matcher = EntityMatcher(entities)
    classifier = TopicClassifier(config.load_topics())
    entity_ids = {entity.id for entity in entities}
    topic_ids = set(classifier.order())

    with newsstore.refresh_lock():
        try:
            previous = newsstore.load(sources, entity_ids, topic_ids)
        except newsstore.NewsError as exc:
            if args.offline:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            retired = _without_retired_sources(sources, entity_ids, topic_ids)
            if retired is not None:
                previous = retired
                print("removing state for a disabled headline source")
            elif not _legacy_snapshot():
                print(f"error: {exc}", file=sys.stderr)
                return 2
            else:
                # The old envelope contains headlines that no longer meet the
                # launch policy. It stays on disk unless at least one fresh source
                # answers and a complete new-schema snapshot validates.
                previous = newsstore.empty_snapshot(sources)
                print("migrating the superseded headline envelope from fresh source checks")

        if args.offline:
            print(f"offline valid: {len(previous['items'])} checked headlines")
            return 0

        attempted_at = newsstore.utc_now_iso()
        moment = datetime.strptime(attempted_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        collected = []
        answered = 0
        failures = []
        states = copy.deepcopy(previous["sources"])

        for source_id in RSS_SOURCES:
            source = sources.get(source_id)
            if source is None or source.status != "enabled":
                continue
            try:
                raw_items = rss.collect(source_id, source.allowed_hosts, source.link_hosts)
                built = [
                    newsstore.build_item(row, source, matcher, classifier, now=moment)
                    for row in raw_items
                ]
                kept = [item for item in built if item is not None]
                collected.extend(kept)
                answered += 1
                states[source_id] = _state(states[source_id], source, attempted_at, "ok")
                print(f"{source_id:22s} {len(kept):3d} accepted headlines")
            except (FetchError, rss.FeedError, newsstore.NewsError) as exc:
                failures.append(source_id)
                states[source_id] = _state(states[source_id], source, attempted_at, "error")
                print(f"{source_id:22s} FAILED  {exc}", file=sys.stderr)

        source = sources.get(GDELT_SOURCE)
        if source is not None and source.status == "enabled":
            try:
                raw_items, query_failures = gdelt.collect(source.allowed_hosts)
                built = [
                    newsstore.build_item(row, source, matcher, classifier, now=moment)
                    for row in raw_items
                ]
                kept = [item for item in built if item is not None]
                collected.extend(kept)
                answered += 1
                status = "partial" if query_failures else "ok"
                states[source.id] = _state(states[source.id], source, attempted_at, status)
                if query_failures:
                    failures.append(source.id)
                print(f"{source.id:22s} {len(kept):3d} accepted headlines ({status})")
            except (FetchError, gdelt.GdeltError, newsstore.NewsError) as exc:
                failures.append(source.id)
                states[source.id] = _state(states[source.id], source, attempted_at, "error")
                print(f"{source.id:22s} FAILED  {exc}", file=sys.stderr)

        if not answered:
            snapshot = newsstore.with_item_counts({
                "items": previous["items"],
                "schema_version": newsstore.NEWS_SCHEMA_VERSION,
                "sources": states,
            })
            newsstore.promote(snapshot, sources, entity_ids, topic_ids, now=moment)
            print(
                "\nno source answered; previous items retained and failed attempts recorded",
                file=sys.stderr,
            )
            return 1

        retention = {source.id: source.retention_days for source in sources.values()}
        merged = newsstore.merge(previous["items"], collected, retention, moment)
        snapshot = newsstore.with_item_counts({
            "items": merged,
            "schema_version": newsstore.NEWS_SCHEMA_VERSION,
            "sources": states,
        })
        newsstore.promote(snapshot, sources, entity_ids, topic_ids, now=moment)

        print(f"\nretained : {len(merged)} checked headlines")
        if failures:
            print(f"partial  : {len(set(failures))} source(s) incomplete", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
