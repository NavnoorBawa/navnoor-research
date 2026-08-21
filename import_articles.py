#!/usr/bin/env python3
"""Import article metadata from the research corpus into data/articles.json.

Reads the corpus read-only. Run this after publishing new articles.

    python3 import_articles.py [--corpus DIR] [--check]

--check reports what would change and exits non-zero if the stored catalogue is
stale, which is what CI should run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from navnoor_research import SCHEMA_VERSION, corpus, jsonio, paths


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=None,
                        help="corpus directory (default: $CORPUS_DIR)")
    parser.add_argument("--check", action="store_true",
                        help="do not write; fail if data/articles.json is stale")
    args = parser.parse_args(argv)

    corpus_dir = args.corpus or paths.corpus_dir()
    try:
        articles, stats = corpus.import_articles(corpus_dir)
    except corpus.CorpusError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    payload = {
        "schema_version": SCHEMA_VERSION,
        "articles": [a.to_json() for a in articles],
    }
    text = jsonio.dumps_pretty(payload)

    total = max(1, stats["published"])
    print(f"corpus       : {corpus.index_path(corpus_dir)}")
    print(f"read         : {stats['read']}")
    print(f"published    : {stats['published']}")
    print(f"skipped      : {stats['skipped']} (no title, link, date or source)")
    print(f"summary      : {stats['with_summary']} ({stats['with_summary'] / total:.0%})")
    print(f"reading time : {stats['with_reading_time']} ({stats['with_reading_time'] / total:.0%})")
    print(f"entities     : {stats['with_entities']} ({stats['with_entities'] / total:.0%})")
    print(f"topic        : {stats['classified']} ({stats['classified'] / total:.0%})")

    if args.check:
        current = paths.ARTICLES_PATH.read_text(encoding="utf-8") \
            if paths.ARTICLES_PATH.exists() else ""
        if current != text:
            print("\nstale: data/articles.json does not match the corpus", file=sys.stderr)
            return 1
        print("\nup to date")
        return 0

    jsonio.write_atomic(paths.ARTICLES_PATH, text)
    print(f"\nwrote {paths.ARTICLES_PATH} ({len(text):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
