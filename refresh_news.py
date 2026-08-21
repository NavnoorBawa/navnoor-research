#!/usr/bin/env python3
"""Check reviewed public sources and promote a new headline snapshot.

    python3 refresh_news.py [--offline]

Runs every enabled news adapter. If every adapter fails the previous snapshot is
kept and the command reports failure, so a bad network day can never empty the
news section.
"""

from __future__ import annotations

import argparse
import sys

from navnoor_research import config, newsstore
from navnoor_research.adapters import gdelt, rss
from navnoor_research.adapters.http import FetchError
from navnoor_research.entities import EntityMatcher, TopicClassifier

RSS_SOURCES = ("federal-reserve-rss", "cftc-rss")
GDELT_SOURCE = "gdelt-doc-v2"


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true",
                        help="validate the stored snapshot without contacting any source")
    args = parser.parse_args(argv)

    sources = config.load_sources()
    matcher = EntityMatcher(config.load_entities())
    classifier = TopicClassifier(config.load_topics())
    previous = newsstore.load()

    if args.offline:
        print(f"offline: keeping {len(previous.get('items', []))} stored headlines")
        return 0

    collected = []
    failures = []

    for source_id in RSS_SOURCES:
        source = sources.get(source_id)
        if source is None or source.status != "enabled":
            continue
        try:
            raw_items = rss.collect(source_id, source.allowed_hosts)
            built = [newsstore.build_item(r, source, matcher, classifier) for r in raw_items]
            kept = [b for b in built if b is not None]
            collected.extend(kept)
            print(f"{source_id:22s} {len(kept):3d} headlines")
        except (FetchError, rss.FeedError) as exc:
            failures.append(f"{source_id}: {exc}")
            print(f"{source_id:22s} FAILED  {exc}", file=sys.stderr)

    source = sources.get(GDELT_SOURCE)
    if source is not None and source.status == "enabled":
        try:
            raw_items = gdelt.collect(source.allowed_hosts)
            built = [newsstore.build_item(r, source, matcher, classifier) for r in raw_items]
            kept = [b for b in built if b is not None]
            collected.extend(kept)
            print(f"{GDELT_SOURCE:22s} {len(kept):3d} headlines")
        except (FetchError, gdelt.GdeltError) as exc:
            failures.append(f"{GDELT_SOURCE}: {exc}")
            print(f"{GDELT_SOURCE:22s} FAILED  {exc}", file=sys.stderr)

    if not collected:
        print("\nno source answered; previous snapshot retained", file=sys.stderr)
        return 1

    retention = {s.id: s.retention_days for s in sources.values()}
    merged = newsstore.merge(previous.get("items", []), collected, retention)
    snapshot = newsstore.promote(merged, newsstore.utc_now_iso())

    print(f"\nchecked_at : {snapshot['checked_at']}")
    print(f"retained   : {len(snapshot['items'])} headlines")
    if failures:
        print(f"partial    : {len(failures)} source(s) failed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
