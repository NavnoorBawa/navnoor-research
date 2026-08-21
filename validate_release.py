#!/usr/bin/env python3
"""Prove a built bundle is exactly what its manifest says.

    python3 validate_release.py --site _site --expected-revision $(git rev-parse HEAD)

Replays the release manifest against the files on disk: every listed file must
be present with the recorded size and digest, and no unlisted file may exist.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from navnoor_research import jsonio, manifest


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True, help="built bundle directory")
    parser.add_argument("--expected-revision", default="", help="revision the bundle must declare")
    args = parser.parse_args(argv)

    site_dir = args.site
    if not site_dir.is_dir():
        print(f"error: {site_dir} is not a directory", file=sys.stderr)
        return 2

    manifest_path = site_dir / manifest.MANIFEST_NAME
    if not manifest_path.is_file():
        print(f"error: {manifest_path} is missing", file=sys.stderr)
        return 2

    release = jsonio.load(manifest_path)
    problems = manifest.verify(site_dir, release, args.expected_revision)

    print(f"site      : {site_dir}")
    print(f"revision  : {release.get('revision')}")
    print(f"files     : {release.get('file_count')}")
    print(f"bytes     : {release.get('total_bytes', 0):,}")

    for problem in problems:
        print(f"error     : {problem}", file=sys.stderr)
    if problems:
        print(f"\nFAILED with {len(problems)} problem(s)", file=sys.stderr)
        return 1

    print("\nexact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
