#!/usr/bin/env python3
"""Derive the fixed searchable research payload from the rights-safe seed."""

from __future__ import annotations

import sys

from navnoor_research import corpus, jsonio, paths
from navnoor_research.schema import RESEARCH_SCHEMA_VERSION


def main(argv: list[str]) -> int:
    if argv:
        print("error: build_research.py accepts no arguments", file=sys.stderr)
        return 2
    try:
        articles, stats = corpus.import_articles()
    except (corpus.CorpusError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload = {
        "schema_version": RESEARCH_SCHEMA_VERSION,
        "source_dataset_version": stats["source_dataset_version"],
        "source_revision": stats["source_revision"],
        "research": [article.to_json() for article in articles],
    }
    text = jsonio.dumps_pretty(payload)
    jsonio.write_atomic(paths.RESEARCH_PATH, text)
    total = max(1, int(stats["published"]))
    print(f"research     : {stats['published']}")
    print(f"summaries    : {stats['with_summary']} ({stats['with_summary'] / total:.0%})")
    print(f"entities     : {stats['with_entities']} ({stats['with_entities'] / total:.0%})")
    print(f"classified   : {stats['classified']} ({stats['classified'] / total:.0%})")
    print(f"source       : {stats['source_revision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
