#!/usr/bin/env python3
"""Check fixed tracked-data timestamps and report every freshness finding."""

from __future__ import annotations

import sys

from navnoor_research import freshness, jsonio, paths


def main(argv: list[str]) -> int:
    if argv:
        print("error: check_freshness.py accepts no arguments", file=sys.stderr)
        return 2
    try:
        seed = jsonio.load(paths.SEED_MANIFEST_PATH)
        companies = jsonio.load(paths.COMPANIES_PATH)
        news = jsonio.load(paths.NEWS_PATH)
        errors, warnings = freshness.evaluate(seed, companies, news)
    except (OSError, jsonio.JsonError, freshness.FreshnessError) as exc:
        errors = [str(exc)]
        warnings = []

    for message in warnings:
        print(f"::warning title=Checked source degraded::{message}")
    for message in errors:
        print(f"::error title=Published data freshness::{message}", file=sys.stderr)
    if errors:
        return 1
    print("freshness: scheduled archive, SEC, and headline checks are within policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
