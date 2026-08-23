#!/usr/bin/env python3
"""Build the fixed deterministic GitHub Pages bundle without network access."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import validate_data
from navnoor_research import config, jsonio, manifest, normalize, paths, render
from navnoor_research.entities import TopicClassifier
from navnoor_research.fingerprint import fingerprint_name, sha256_hex
from navnoor_research.schema import COMPANY_SCHEMA_VERSION, TAXONOMY_SCHEMA_VERSION

STAGING_DIR = paths.ROOT / ".site-build"
REVISION_RE = re.compile(r"(?:[0-9a-f]{40}|local-[a-z0-9-]{1,40})")
PUBLIC_COMPANY_FIELDS = ("cik", "ticker", "exchange", "name")
SOCIAL_CARD_SHA256 = "241f3fd6b20312e7b4f91b95bccd265009c825c2049d90c620d412e2e2a74151"


def checked_social_card() -> bytes:
    """Return the reviewed social card.

    The card states no release counts. Counts change on every scheduled refresh,
    and social platforms cache a scraped card for days, so a number burned into
    these pixels could only ever be stale. The exact live counts are published in
    the regenerated og:description instead, next to this card.
    """
    path = paths.ASSETS_DIR / "og.png"
    if not path.is_file():
        raise ValueError("reviewed social card is missing")
    payload = path.read_bytes()
    if sha256_hex(payload) != SOCIAL_CARD_SHA256:
        raise ValueError("social card bytes do not match the reviewed factual asset")
    return payload


def public_companies(document: dict[str, Any]) -> dict[str, Any]:
    """Remove derived IDs/URLs and column-pack the SEC registry for browsers."""
    return {
        "checked_at": document["checked_at"],
        "companies": [
            [record[field] for field in PUBLIC_COMPANY_FIELDS] for record in document["items"]
        ],
        "fields": list(PUBLIC_COMPANY_FIELDS),
        "schema_version": COMPANY_SCHEMA_VERSION,
        "source_id": document["source_id"],
    }


def build_taxonomy() -> dict[str, Any]:
    entities = config.load_entities()
    classifier = TopicClassifier(config.load_topics())
    source_labels = dict(normalize.SOURCE_LABELS)
    for source in config.load_sources().values():
        source_labels[source.id] = source.label
    return {
        "entities": {
            entity.id: {
                "aliases": entity.aliases,
                "kind": entity.kind,
                "label": entity.label,
            }
            for entity in entities
        },
        "schema_version": TAXONOMY_SCHEMA_VERSION,
        "sources": dict(sorted(source_labels.items())),
        "topics": classifier.labels(),
    }


def build_into(out_dir: Path, revision: str) -> dict[str, Any]:
    """Assemble one validated bundle. Tests may supply an isolated directory."""
    research, companies, news = validate_data.load_and_validate()
    taxonomy = build_taxonomy()
    companies_public = public_companies(companies)

    if out_dir.exists():
        if out_dir.is_symlink():
            raise ValueError("site output cannot be a symbolic link")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    written: dict[str, str] = {}

    def emit(logical: str, name: str, payload: bytes) -> None:
        final = fingerprint_name(name, payload)
        (out_dir / final).write_bytes(payload)
        written[logical] = final

    emit("research", "research.json", jsonio.dumps(research).encode("utf-8"))
    emit("companies", "companies.json", jsonio.dumps(companies_public).encode("utf-8"))
    emit("news", "news.json", jsonio.dumps(news).encode("utf-8"))
    emit("taxonomy", "taxonomy.json", jsonio.dumps(taxonomy).encode("utf-8"))
    emit("css", "app.css", (paths.ASSETS_DIR / "app.css").read_bytes())
    emit("js", "app.js", (paths.ASSETS_DIR / "app.js").read_bytes())
    emit("og", "og.png", checked_social_card())

    html = render.render(
        written,
        revision,
        len(research["research"]),
        len(companies_public["companies"]),
        len(news["items"]),
        len(news["sources"]),
        sum(source["status"] != "ok" for source in news["sources"].values()),
    )
    with (out_dir / "index.html").open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(html)
    (out_dir / ".nojekyll").write_bytes(b"")

    counts = {
        "companies": len(companies_public["companies"]),
        "entities": len(taxonomy["entities"]),
        "headlines": len(news["items"]),
        "research": len(research["research"]),
        "topics": len(taxonomy["topics"]),
    }
    release = manifest.build(out_dir, revision, counts)
    jsonio.write_atomic(out_dir / manifest.MANIFEST_NAME, jsonio.dumps_pretty(release))
    return release


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="full Git SHA or local-* audit label")
    args = parser.parse_args(argv)
    if not REVISION_RE.fullmatch(args.revision):
        print(
            "error: revision must be a full lowercase SHA or bounded local-* label",
            file=sys.stderr,
        )
        return 2
    if paths.DEFAULT_SITE_DIR.is_symlink() or STAGING_DIR.is_symlink():
        print("error: fixed build directories must not be symbolic links", file=sys.stderr)
        return 2
    try:
        release = build_into(STAGING_DIR, args.revision)
        if paths.DEFAULT_SITE_DIR.exists():
            shutil.rmtree(paths.DEFAULT_SITE_DIR)
        STAGING_DIR.replace(paths.DEFAULT_SITE_DIR)
    except (OSError, ValueError, config.ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"output     : {paths.DEFAULT_SITE_DIR}")
    print(f"revision   : {args.revision}")
    for key, value in sorted(release["counts"].items()):
        print(f"{key:10s} : {value:,}")
    print(f"files      : {release['file_count']}")
    print(f"bytes      : {release['total_bytes']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
