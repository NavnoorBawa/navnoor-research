#!/usr/bin/env python3
"""Refresh the fixed SEC company registry or validate it offline.

    python3 refresh_companies.py [--offline]

The online path makes one request to the reviewed SEC association file.  A
failed request or invalid response leaves the previously validated snapshot
byte-for-byte unchanged.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from navnoor_research import config, jsonio, paths
from navnoor_research.adapters import sec
from navnoor_research.adapters.http import FetchError
from navnoor_research.models import Company
from navnoor_research.schema import COMPANY_SCHEMA_VERSION

SNAPSHOT_FIELDS = ("schema_version", "source_id", "checked_at", "items")


class CompanyStoreError(ValueError):
    """The rights screen or stored company snapshot is invalid."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _checked_at(value: Any) -> str:
    if type(value) is not str:
        raise CompanyStoreError("checked_at must be a string")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise CompanyStoreError("checked_at must be a real UTC second") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise CompanyStoreError("checked_at must use canonical UTC-second syntax")
    if parsed.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise CompanyStoreError("checked_at cannot be in the future")
    return value


def validate_snapshot(value: Any) -> dict[str, Any]:
    """Validate the entire stored envelope and its canonical item order."""
    if type(value) is not dict or set(value) != set(SNAPSHOT_FIELDS):
        raise CompanyStoreError(f"snapshot must contain exactly {list(SNAPSHOT_FIELDS)!r}")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != COMPANY_SCHEMA_VERSION
    ):
        raise CompanyStoreError("unsupported companies schema version")
    if value["source_id"] != sec.SOURCE_ID:
        raise CompanyStoreError(f"source_id must be {sec.SOURCE_ID!r}")
    _checked_at(value["checked_at"])

    items = value["items"]
    if type(items) is not list or not items:
        raise CompanyStoreError("items must be a non-empty array")
    if len(items) > sec.MAX_RECORDS:
        raise CompanyStoreError(f"items exceeds {sec.MAX_RECORDS} record ceiling")
    try:
        companies = [sec.validate_company(item) for item in items]
    except sec.SecError as exc:
        raise CompanyStoreError(str(exc)) from exc
    ids = [company.id for company in companies]
    if len(ids) != len(set(ids)):
        raise CompanyStoreError("items contains a duplicate company association")
    if companies != sorted(companies, key=sec.sort_key):
        raise CompanyStoreError("items must be in canonical ticker order")
    return value


def load_stored() -> dict[str, Any] | None:
    """Load and validate the fixed last-known-good path, if it exists."""
    if not paths.COMPANIES_PATH.exists():
        return None
    try:
        return validate_snapshot(jsonio.load(paths.COMPANIES_PATH))
    except (OSError, jsonio.JsonError) as exc:
        raise CompanyStoreError(f"stored companies snapshot is invalid: {exc}") from exc


def make_snapshot(companies: Sequence[Company], checked_at: str) -> dict[str, Any]:
    snapshot = {
        "schema_version": COMPANY_SCHEMA_VERSION,
        "source_id": sec.SOURCE_ID,
        "checked_at": checked_at,
        "items": [company.to_json() for company in sorted(companies, key=sec.sort_key)],
    }
    return validate_snapshot(snapshot)


def promote(companies: Sequence[Company], checked_at: str) -> dict[str, Any]:
    """Validate completely, then atomically replace the fixed output."""
    snapshot = make_snapshot(companies, checked_at)
    text = jsonio.dumps_pretty(snapshot)
    # Validate the exact serialized bytes before they are eligible for rename.
    validate_snapshot(jsonio.loads_strict(text.encode("utf-8")))
    jsonio.write_atomic(paths.COMPANIES_PATH, text)
    return snapshot


def _reviewed_source() -> config.Source:
    source = config.load_sources().get(sec.SOURCE_ID)
    if source is None:
        raise CompanyStoreError(f"rights screen is missing {sec.SOURCE_ID!r}")
    if source.status != "enabled":
        raise CompanyStoreError(f"{sec.SOURCE_ID!r} is not enabled")
    if source.adapter != "sec":
        raise CompanyStoreError("SEC rights screen has an unexpected adapter")
    if tuple(source.allowed_hosts) != sec.ALLOWED_HOSTS:
        raise CompanyStoreError("SEC rights screen has an unexpected host allowlist")
    if tuple(source.link_hosts) != sec.ALLOWED_HOSTS:
        raise CompanyStoreError("SEC rights screen has an unexpected link-host allowlist")
    if tuple(source.allowed_fields) != sec.PUBLIC_FIELDS:
        raise CompanyStoreError("SEC rights screen has an unexpected public field allowlist")
    if set(source.allowed_fields) & set(source.prohibited_fields):
        raise CompanyStoreError("SEC rights screen allows a prohibited field")
    return source


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="validate the stored snapshot without contacting the SEC",
    )
    args = parser.parse_args(argv)

    previous: dict[str, Any] | None = None
    try:
        previous = load_stored()
        if args.offline:
            if previous is None:
                raise CompanyStoreError("no stored companies snapshot")
            print(f"offline: validated {len(previous['items'])} stored company associations")
            return 0

        source = _reviewed_source()
        companies = sec.collect(source.allowed_hosts)
        snapshot = promote(companies, utc_now_iso())
    except (
        CompanyStoreError,
        FetchError,
        OSError,
        config.ConfigError,
        sec.SecError,
        jsonio.JsonError,
    ) as exc:
        retained = "no previous snapshot exists"
        if previous is not None:
            retained = f"retained {len(previous['items'])} previous associations"
        print(f"SEC company refresh failed; {retained}: {exc}", file=sys.stderr)
        return 1

    print(f"checked_at : {snapshot['checked_at']}")
    print(f"companies  : {len(snapshot['items'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
