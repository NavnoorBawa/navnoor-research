#!/usr/bin/env python3
"""Import an exact Git-archive stream into the fixed rights-safe seed files.

Example:

    git -C ../substack-trades archive REV \
      articles_index.json trades_extracted.json snapshot_manifest.json \
      | python3 import_research_seed.py --revision REV --write

The process accepts no filesystem path. It reads one bounded tar stream from
stdin and writes only `seed/publications.json` plus `seed/manifest.json`.
"""

from __future__ import annotations

import argparse
import sys

from navnoor_research import jsonio, paths, seed


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    payload = sys.stdin.buffer.read(seed.MAX_ARCHIVE_BYTES + 1)
    try:
        files = seed.read_git_archive(payload, args.revision)
        publications, provenance = seed.project(files, args.revision)
    except seed.SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    publications_text = jsonio.dumps_pretty(publications)
    provenance_text = jsonio.dumps_pretty(provenance)
    current_publications = paths.PUBLICATIONS_PATH.read_text(encoding="utf-8") \
        if paths.PUBLICATIONS_PATH.exists() else ""
    current_provenance = paths.SEED_MANIFEST_PATH.read_text(encoding="utf-8") \
        if paths.SEED_MANIFEST_PATH.exists() else ""
    changed = current_publications != publications_text or current_provenance != provenance_text

    print(f"revision     : {args.revision}")
    print(f"publications : {len(publications['records'])}")
    print(f"dataset      : {publications['source_dataset_version']}")
    if args.check:
        if changed:
            print("stale: checked seed files do not match the supplied archive", file=sys.stderr)
            return 1
        print("up to date")
        return 0

    if not changed:
        print("unchanged")
        return 0
    jsonio.write_atomic(paths.PUBLICATIONS_PATH, publications_text)
    # The manifest is the transaction marker and is promoted last.
    jsonio.write_atomic(paths.SEED_MANIFEST_PATH, provenance_text)
    print("wrote seed/publications.json and seed/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
