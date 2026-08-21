#!/usr/bin/env python3
"""Build the static bundle.

    SITE_OUTPUT_DIR=_site SITE_REVISION=$(git rev-parse HEAD) python3 build_site.py

The build is deterministic: the same inputs and revision produce byte-identical
output, which is what lets `validate_release.py` prove a deployed bundle is the
one this commit describes. Nothing here reaches the network.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

from navnoor_research import SCHEMA_VERSION, config, jsonio, manifest, normalize, paths, render
from navnoor_research.entities import TopicClassifier
from navnoor_research.fingerprint import fingerprint_name


def build_taxonomy() -> dict[str, Any]:
    """The lookup tables the page needs to label and resolve records."""
    entities = config.load_entities()
    classifier = TopicClassifier(config.load_topics())

    source_labels = dict(normalize.SOURCE_LABELS)
    for source in config.load_sources().values():
        source_labels[source.id] = source.label

    return {
        "schema_version": SCHEMA_VERSION,
        "entities": {
            e.id: {"label": e.label, "kind": e.kind, "aliases": e.aliases} for e in entities
        },
        "topics": classifier.labels(),
        "sources": source_labels,
    }


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="output directory")
    parser.add_argument("--revision", default=None, help="git revision to bind the release to")
    args = parser.parse_args(argv)

    out_dir = args.out or paths.site_output_dir()
    revision = args.revision or paths.site_revision()

    if not paths.ARTICLES_PATH.exists():
        print("error: data/articles.json is missing. Run import_articles.py first.",
              file=sys.stderr)
        return 2

    articles_doc = jsonio.load(paths.ARTICLES_PATH)
    news_doc = jsonio.load(paths.NEWS_PATH) if paths.NEWS_PATH.exists() else {
        "schema_version": SCHEMA_VERSION, "checked_at": None, "items": []
    }
    taxonomy_doc = build_taxonomy()

    articles = articles_doc.get("articles", [])
    headlines = news_doc.get("items", [])

    # A rebuild replaces the bundle completely; stale fingerprinted files from a
    # previous release must never survive into the manifest.
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    written: dict[str, str] = {}

    def emit(logical: str, name: str, payload: bytes) -> None:
        final = fingerprint_name(name, payload)
        (out_dir / final).write_bytes(payload)
        written[logical] = final

    emit("articles", "articles.json", jsonio.dumps(articles_doc).encode("utf-8"))
    emit("news", "news.json", jsonio.dumps(news_doc).encode("utf-8"))
    emit("taxonomy", "taxonomy.json", jsonio.dumps(taxonomy_doc).encode("utf-8"))
    emit("css", "app.css", (paths.ASSETS_DIR / "app.css").read_bytes())
    emit("js", "app.js", (paths.ASSETS_DIR / "app.js").read_bytes())

    html = render.render(written, revision, len(articles), len(headlines))
    (out_dir / "index.html").write_text(html, encoding="utf-8")

    # GitHub Pages serves this repository's output as-is; Jekyll must not touch it.
    (out_dir / ".nojekyll").write_bytes(b"")

    counts = {
        "articles": len(articles),
        "headlines": len(headlines),
        "entities": len(taxonomy_doc["entities"]),
        "topics": len(taxonomy_doc["topics"]),
    }
    release = manifest.build(out_dir, revision, counts)
    jsonio.write_atomic(out_dir / manifest.MANIFEST_NAME, jsonio.dumps_pretty(release))

    print(f"output    : {out_dir}")
    print(f"revision  : {revision}")
    print(f"articles  : {counts['articles']}")
    print(f"headlines : {counts['headlines']}")
    print(f"files     : {release['file_count']}")
    print(f"bytes     : {release['total_bytes']:,}")
    for entry in release["files"]:
        print(f"  {entry['bytes']:>9,}  {entry['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
