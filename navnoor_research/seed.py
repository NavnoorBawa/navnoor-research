"""Strict, rights-bounded import of one exact Navnoor Research Archive snapshot."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from . import jsonio
from .schema import SEED_SCHEMA_VERSION

ARCHIVE_REPOSITORY = "https://github.com/navnoorthapar/substack-trades"
RIGHTS_PROFILE = "public-metadata-only-v1"
DATASET = "navnoor-research-publications"
INPUT_NAMES = ("articles_index.json", "trades_extracted.json", "snapshot_manifest.json")
MAX_ARCHIVE_BYTES = 20_000_000
MAX_MEMBER_BYTES = 10_000_000
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
INSTANT_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)

RECORD_KEYS = {
    "access", "alternate_urls", "canonical_url", "id", "published_at",
    "slug", "source", "source_id", "subtitle", "title",
}

ACCESS = {
    ("substack", "everyone"): "public",
    ("substack", "only_paid"): "restricted",
    ("medium", "public"): "public",
    ("medium", "locked"): "restricted",
    ("medium", "unknown"): "unknown",
    ("patreon", "public"): "public",
    ("patreon", "paid"): "restricted",
    ("fxempire", "public"): "public",
}

ARCHIVE_SOURCE_STATUSES = {"ok", "degraded"}

SOURCE_HOSTS = {
    "substack": "navnoorbawa.substack.com",
    "medium": "medium.com",
    "patreon": "www.patreon.com",
    "fxempire": "www.fxempire.com",
}

SELECTED_ARTICLE_KEYS = {
    "source", "source_id", "slug", "title", "subtitle", "post_date",
    "url", "alternate_urls", "audience", "access",
}


class SeedError(ValueError):
    """The archive input or projected seed violates the fixed contract."""


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def publication_id(source: str, source_id: str) -> str:
    raw = f"{source}\0{source_id}".encode()
    return "r_" + hashlib.sha256(raw).hexdigest()


def _safe_https(value: Any, where: str, expected_host: str | None = None) -> str:
    text = str(value or "")
    parts = urlsplit(text)
    try:
        port = parts.port
    except ValueError as exc:
        raise SeedError(f"{where}: URL contains an invalid port") from exc
    if any(ord(char) < 33 or ord(char) == 127 for char in text):
        raise SeedError(f"{where}: URL contains whitespace or a control character")
    if (
        parts.scheme != "https" or not parts.hostname or parts.username or parts.password
        or parts.fragment or port not in (None, 443)
    ):
        raise SeedError(f"{where}: expected a credential-free HTTPS URL")
    if expected_host is not None and parts.hostname.lower() != expected_host:
        raise SeedError(f"{where}: host is not the reviewed {expected_host!r}")
    if len(text) > 2048:
        raise SeedError(f"{where}: URL exceeds 2,048 characters")
    return text


def read_git_archive(payload: bytes, revision: str) -> dict[str, bytes]:
    """Read exactly the three trusted Git blobs without extracting paths."""
    if not REVISION_RE.fullmatch(revision):
        raise SeedError("archive revision must be a full lowercase 40-hex commit")
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise SeedError("Git archive exceeds the bounded input ceiling")
    try:
        archive = tarfile.open(fileobj=io.BytesIO(payload), mode="r:")
    except tarfile.TarError as exc:
        raise SeedError(f"invalid Git archive: {exc}") from exc
    with archive:
        pax_headers = archive.pax_headers or {}
        comment = str(pax_headers.get("comment") or "")
        if comment != revision:
            raise SeedError(f"Git archive comment {comment!r} does not match revision")
        files: dict[str, bytes] = {}
        for member in archive.getmembers():
            if member.name not in INPUT_NAMES:
                raise SeedError(f"unexpected Git archive member {member.name!r}")
            if not member.isfile() or member.size < 1 or member.size > MAX_MEMBER_BYTES:
                raise SeedError(f"{member.name}: invalid member type or size")
            if member.name in files:
                raise SeedError(f"duplicate Git archive member {member.name!r}")
            handle = archive.extractfile(member)
            if handle is None:
                raise SeedError(f"{member.name}: could not read member")
            files[member.name] = handle.read(MAX_MEMBER_BYTES + 1)
        if set(files) != set(INPUT_NAMES):
            raise SeedError(f"Git archive must contain exactly {list(INPUT_NAMES)}")
        return files


def _skip_ws(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def _scan_string(text: str, index: int) -> int:
    if index >= len(text) or text[index] != '"':
        raise SeedError("expected JSON string")
    index += 1
    while index < len(text):
        char = text[index]
        if char == '"':
            return index + 1
        if ord(char) < 32:
            raise SeedError("JSON string contains an unescaped control character")
        if char == "\\":
            index += 1
            if index >= len(text) or text[index] not in '"\\/bfnrtu':
                raise SeedError("invalid JSON string escape")
            if text[index] == "u":
                digits = text[index + 1:index + 5]
                if index + 4 >= len(text) or not re.fullmatch(r"[0-9a-fA-F]{4}", digits):
                    raise SeedError("invalid JSON unicode escape")
                index += 4
        index += 1
    raise SeedError("unterminated JSON string")


NUMBER_RE = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")


def _skip_value(text: str, index: int) -> int:
    """Validate and skip one JSON value without materialising its contents."""
    index = _skip_ws(text, index)
    if index >= len(text):
        raise SeedError("unexpected end of JSON value")
    if text[index] == '"':
        return _scan_string(text, index)
    if text[index] == "[":
        index = _skip_ws(text, index + 1)
        if index < len(text) and text[index] == "]":
            return index + 1
        while True:
            index = _skip_ws(text, _skip_value(text, index))
            if index >= len(text):
                raise SeedError("unterminated JSON array")
            if text[index] == "]":
                return index + 1
            if text[index] != ",":
                raise SeedError("expected comma in JSON array")
            index += 1
    if text[index] == "{":
        index = _skip_ws(text, index + 1)
        if index < len(text) and text[index] == "}":
            return index + 1
        seen: set[str] = set()
        decoder = json.JSONDecoder()
        while True:
            start = _skip_ws(text, index)
            end = _scan_string(text, start)
            key = decoder.decode(text[start:end])
            if key in seen:
                raise SeedError(f"duplicate JSON object key {key!r}")
            seen.add(key)
            index = _skip_ws(text, end)
            if index >= len(text) or text[index] != ":":
                raise SeedError("expected colon in JSON object")
            index = _skip_ws(text, _skip_value(text, index + 1))
            if index >= len(text):
                raise SeedError("unterminated JSON object")
            if text[index] == "}":
                return index + 1
            if text[index] != ",":
                raise SeedError("expected comma in JSON object")
            index += 1
    for literal in ("true", "false", "null"):
        if text.startswith(literal, index):
            return index + len(literal)
    number = NUMBER_RE.match(text, index)
    if number:
        return number.end()
    raise SeedError("invalid JSON value")


def _strict_decoder() -> json.JSONDecoder:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SeedError(f"duplicate JSON object key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise SeedError(f"non-finite JSON value {value!r}")

    return json.JSONDecoder(object_pairs_hook=unique, parse_constant=reject_constant)


def select_article_fields(payload: bytes) -> list[dict[str, Any]]:
    """Parse only reviewed top-level article fields; skip every other value."""
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SeedError(f"articles_index.json is not UTF-8: {exc}") from exc
    decoder = _strict_decoder()
    index = _skip_ws(text, 0)
    if index >= len(text) or text[index] != "[":
        raise SeedError("articles_index.json must be a JSON array")
    index = _skip_ws(text, index + 1)
    records: list[dict[str, Any]] = []
    if index < len(text) and text[index] == "]":
        return records
    while True:
        if index >= len(text) or text[index] != "{":
            raise SeedError("article entry must be a JSON object")
        index = _skip_ws(text, index + 1)
        selected: dict[str, Any] = {}
        seen: set[str] = set()
        if index < len(text) and text[index] == "}":
            index += 1
        else:
            while True:
                key_start = _skip_ws(text, index)
                key_end = _scan_string(text, key_start)
                key = decoder.decode(text[key_start:key_end])
                if key in seen:
                    raise SeedError(f"duplicate article key {key!r}")
                seen.add(key)
                index = _skip_ws(text, key_end)
                if index >= len(text) or text[index] != ":":
                    raise SeedError("expected colon after article key")
                value_start = _skip_ws(text, index + 1)
                if key in SELECTED_ARTICLE_KEYS:
                    try:
                        value, value_end = decoder.raw_decode(text, value_start)
                    except json.JSONDecodeError as exc:
                        raise SeedError(f"invalid selected article field {key!r}: {exc}") from exc
                    selected[key] = value
                    index = value_end
                else:
                    index = _skip_value(text, value_start)
                index = _skip_ws(text, index)
                if index >= len(text):
                    raise SeedError("unterminated article object")
                if text[index] == "}":
                    index += 1
                    break
                if text[index] != ",":
                    raise SeedError("expected comma in article object")
                index = _skip_ws(text, index + 1)
        records.append(selected)
        index = _skip_ws(text, index)
        if index >= len(text):
            raise SeedError("unterminated articles array")
        if text[index] == "]":
            index = _skip_ws(text, index + 1)
            if index != len(text):
                raise SeedError("trailing content after articles array")
            return records
        if text[index] != ",":
            raise SeedError("expected comma in articles array")
        index = _skip_ws(text, index + 1)


def count_array_items(payload: bytes, where: str) -> int:
    """Validate a JSON array and count items without materialising their values."""
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SeedError(f"{where} is not UTF-8: {exc}") from exc
    index = _skip_ws(text, 0)
    if index >= len(text) or text[index] != "[":
        raise SeedError(f"{where} must be a JSON array")
    index = _skip_ws(text, index + 1)
    if index < len(text) and text[index] == "]":
        return 0
    count = 0
    while True:
        index = _skip_ws(text, _skip_value(text, index))
        count += 1
        if index >= len(text):
            raise SeedError(f"unterminated {where} array")
        if text[index] == "]":
            if _skip_ws(text, index + 1) != len(text):
                raise SeedError(f"trailing content after {where}")
            return count
        if text[index] != ",":
            raise SeedError(f"expected comma in {where}")
        index = _skip_ws(text, index + 1)


def _published(value: Any, where: str) -> str:
    text = str(value or "")
    try:
        if DATE_RE.fullmatch(text):
            date.fromisoformat(text)
        elif INSTANT_RE.fullmatch(text):
            datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            raise ValueError
    except ValueError as exc:
        raise SeedError(f"{where}: invalid publication date/instant {text!r}") from exc
    return text


def _publication_instant(value: Any, where: str) -> datetime:
    """Return the archive's ordering instant for a validated publication value."""
    text = _published(value, where)
    if DATE_RE.fullmatch(text):
        return datetime.combine(
            date.fromisoformat(text), datetime.min.time(), tzinfo=timezone.utc
        )
    return datetime.fromisoformat(text[:-1] + "+00:00")


def _project_article(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SeedError(f"articles_index.json[{index}]: expected object")
    source = str(raw.get("source") or "").strip().lower()
    source_id = str(raw.get("source_id") or "")
    slug = str(raw.get("slug") or "")
    title = str(raw.get("title") or "")
    subtitle = str(raw.get("subtitle") or "")
    published = _published(raw.get("post_date"), f"articles_index.json[{index}].post_date")
    audience = str(raw.get("audience") or raw.get("access") or "")
    where = f"articles_index.json[{index}]"

    if not source or not source_id or len(source_id) > 128:
        raise SeedError(f"{where}: missing or oversized source identity")
    if not slug or len(slug) > 240:
        raise SeedError(f"{where}: missing or oversized slug")
    if not title or len(title) > 500 or len(subtitle) > 500:
        raise SeedError(f"{where}: invalid title/subtitle length")
    access = ACCESS.get((source, audience))
    if access is None:
        raise SeedError(f"{where}: unreviewed source/audience pair {(source, audience)!r}")

    alternate_raw = raw.get("alternate_urls") or {}
    if not isinstance(alternate_raw, dict) or len(alternate_raw) > 3:
        raise SeedError(f"{where}: alternate_urls must be an object with at most three entries")
    alternate: dict[str, str] = {}
    expected_host = SOURCE_HOSTS.get(source)
    if expected_host is None:
        raise SeedError(f"{where}: source {source!r} has no reviewed host")
    canonical = _safe_https(raw.get("url"), f"{where}.url", expected_host)
    canonical_path = urlsplit(canonical).path.rstrip("/")
    if source == "substack" and not canonical_path.endswith(f"/p/{source_id}"):
        raise SeedError(f"{where}: Substack URL does not carry source_id")
    if source in {"medium", "patreon", "fxempire"} and not canonical_path.endswith(source_id):
        raise SeedError(f"{where}: canonical URL does not carry source_id")
    for key, value in sorted(alternate_raw.items()):
        label = str(key)
        alternate_host = SOURCE_HOSTS.get(label)
        if alternate_host is None:
            raise SeedError(f"{where}: alternate URL label {label!r} is not reviewed")
        url = _safe_https(value, f"{where}.alternate_urls[{label!r}]", alternate_host)
        if url == canonical:
            raise SeedError(f"{where}: alternate URL repeats the canonical URL")
        alternate[label] = url

    record = {
        "access": access,
        "alternate_urls": alternate,
        "canonical_url": canonical,
        "id": publication_id(source, source_id),
        "published_at": published,
        "slug": slug,
        "source": source,
        "source_id": source_id,
        "subtitle": subtitle,
        "title": title,
    }
    if set(record) != RECORD_KEYS:
        raise AssertionError("publication projection keys drifted")
    return record


def project(files: dict[str, bytes], revision: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate exact source bytes and return seed publications + provenance."""
    try:
        articles = select_article_fields(files["articles_index.json"])
        snapshot = jsonio.loads_strict(files["snapshot_manifest.json"])
    except jsonio.JsonError as exc:
        raise SeedError(f"strict JSON validation failed: {exc}") from exc
    trades_count = count_array_items(files["trades_extracted.json"], "trades_extracted.json")
    if not isinstance(snapshot, dict):
        raise SeedError("archive inputs have unexpected top-level shapes")
    checksum = _digest(files["articles_index.json"] + b"\0" + files["trades_extracted.json"])
    if snapshot.get("data_checksum") != checksum:
        raise SeedError("snapshot data_checksum does not bind the exact article/trade bytes")
    if snapshot.get("schema_version") != 2:
        raise SeedError("unsupported archive manifest schema")
    if snapshot.get("catalog_count") != len(articles):
        raise SeedError("archive catalogue count does not match articles_index.json")
    if snapshot.get("observation_count") != trades_count:
        raise SeedError("archive observation count does not match trades_extracted.json")

    records = [_project_article(record, index) for index, record in enumerate(articles)]
    ids = [record["id"] for record in records]
    urls = [record["canonical_url"] for record in records]
    if len(set(ids)) != len(ids) or len(set(urls)) != len(urls):
        raise SeedError("projected publication identities and canonical URLs must be unique")

    publications = {
        "dataset": DATASET,
        "records": records,
        "rights_profile": RIGHTS_PROFILE,
        "schema_version": SEED_SCHEMA_VERSION,
        "source_dataset_version": checksum,
    }
    publication_bytes = jsonio.dumps_pretty(publications).encode("utf-8")
    by_source = Counter(record["source"] for record in records)
    by_access = Counter(record["access"] for record in records)
    sources: dict[str, Any] = {}
    for source, status in sorted((snapshot.get("sources") or {}).items()):
        if not isinstance(status, dict):
            raise SeedError(f"archive source status {source!r} is not an object")
        sources[source] = {
            "checked_at": status.get("checked_at"),
            "included_count": status.get("included_count"),
            "newest": status.get("newest"),
            "status": status.get("status"),
        }
    manifest = {
        "artifacts": [{
            "bytes": len(publication_bytes),
            "path": "seed/publications.json",
            "record_count": len(records),
            "sha256": _digest(publication_bytes),
        }],
        "counts": {
            "by_access": dict(sorted(by_access.items())),
            "by_source": dict(sorted(by_source.items())),
            "records": len(records),
        },
        "dataset": DATASET,
        "inputs": [{
            "bytes": len(files[name]),
            "path": name,
            "role": "projected" if name == "articles_index.json" else (
                "checksum-companion-only" if name == "trades_extracted.json" else "provenance"
            ),
            "sha256": _digest(files[name]),
        } for name in INPUT_NAMES],
        "rights_profile": RIGHTS_PROFILE,
        "schema_version": SEED_SCHEMA_VERSION,
        "source_checks": sources,
        "source_snapshot": {
            "article_count": snapshot.get("article_count"),
            "catalog_count": snapshot.get("catalog_count"),
            "catalog_latest_publication": snapshot.get("catalog_latest_publication"),
            "checked_at": snapshot.get("checked_at"),
            "data_checksum": checksum,
            "manifest_schema_version": snapshot.get("schema_version"),
            "observation_count_verified_but_omitted": trades_count,
            "registry_count": snapshot.get("registry_count"),
            "repository": ARCHIVE_REPOSITORY,
            "revision": revision,
        },
    }
    validate_stored(publication_bytes, jsonio.dumps_pretty(manifest).encode("utf-8"))
    return publications, manifest


def validate_stored(
    publications_payload: bytes,
    manifest_payload: bytes,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the two-file transaction; the manifest is the commit marker."""
    try:
        publications = jsonio.loads_strict(publications_payload)
        provenance = jsonio.loads_strict(manifest_payload)
    except jsonio.JsonError as exc:
        raise SeedError(f"stored seed JSON is invalid: {exc}") from exc
    if not isinstance(publications, dict) or not isinstance(provenance, dict):
        raise SeedError("stored seed envelopes must be objects")
    if set(publications) != {
        "dataset", "records", "rights_profile", "schema_version", "source_dataset_version"
    }:
        raise SeedError("stored publication envelope has unexpected keys")
    if set(provenance) != {
        "artifacts", "counts", "dataset", "inputs", "rights_profile", "schema_version",
        "source_checks", "source_snapshot",
    }:
        raise SeedError("stored seed manifest has unexpected keys")
    if (
        publications.get("schema_version") != SEED_SCHEMA_VERSION
        or provenance.get("schema_version") != SEED_SCHEMA_VERSION
    ):
        raise SeedError("stored seed schema is unsupported")
    if publications.get("dataset") != DATASET or provenance.get("dataset") != DATASET:
        raise SeedError("stored seed dataset name is invalid")
    if (
        publications.get("rights_profile") != RIGHTS_PROFILE
        or provenance.get("rights_profile") != RIGHTS_PROFILE
    ):
        raise SeedError("stored seed rights profile is invalid")
    artifacts = provenance.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 1 or not isinstance(artifacts[0], dict):
        raise SeedError("seed manifest must bind exactly one publication artifact")
    artifact = artifacts[0]
    if set(artifact) != {"bytes", "path", "record_count", "sha256"}:
        raise SeedError("seed publication artifact has unexpected keys")
    if artifact.get("path") != "seed/publications.json":
        raise SeedError("seed manifest publication path is invalid")
    if (
        artifact.get("bytes") != len(publications_payload)
        or artifact.get("sha256") != _digest(publications_payload)
    ):
        raise SeedError("seed manifest does not bind exact publication bytes")
    records = publications.get("records")
    if not isinstance(records, list) or artifact.get("record_count") != len(records):
        raise SeedError("seed record count does not match its manifest")
    projected: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != RECORD_KEYS:
            raise SeedError(f"seed record {index} does not match the fixed projection")
        source = record.get("source")
        source_id = record.get("source_id")
        if not isinstance(source, str) or not isinstance(source_id, str):
            raise SeedError(f"seed record {index} has invalid source identity")
        if record.get("id") != publication_id(source, source_id):
            raise SeedError(f"seed record {index} has an invalid content identity")
        if record.get("access") not in {"public", "restricted", "unknown"}:
            raise SeedError(f"seed record {index} has an invalid access state")
        if not isinstance(record.get("alternate_urls"), dict):
            raise SeedError(f"seed record {index} has invalid alternate URLs")
        _safe_https(
            record.get("canonical_url"),
            f"seed record {index}.canonical_url",
            SOURCE_HOSTS.get(source),
        )
        for label, url in record["alternate_urls"].items():
            if label not in SOURCE_HOSTS:
                raise SeedError(f"seed record {index} has an unreviewed alternate source")
            _safe_https(url, f"seed record {index}.alternate_urls[{label!r}]", SOURCE_HOSTS[label])
        title = record.get("title")
        subtitle = record.get("subtitle")
        slug = record.get("slug")
        if (
            not isinstance(title, str) or not title or len(title) > 500
            or not isinstance(subtitle, str) or len(subtitle) > 500
            or not isinstance(slug, str) or not slug or len(slug) > 240
            or not isinstance(source_id, str) or not source_id or len(source_id) > 128
        ):
            raise SeedError(f"seed record {index} has invalid bounded text")
        _published(record.get("published_at"), f"seed record {index}.published_at")
        projected.append(record)

    ids = [record["id"] for record in projected]
    urls = [record["canonical_url"] for record in projected]
    if len(ids) != len(set(ids)) or len(urls) != len(set(urls)):
        raise SeedError("stored seed has duplicate identities or canonical URLs")

    expected_by_access: dict[str, int] = dict(sorted(
        Counter(record["access"] for record in projected).items()
    ))
    expected_by_source: dict[str, int] = dict(sorted(
        Counter(record["source"] for record in projected).items()
    ))
    expected_counts: dict[str, Any] = {
        "by_access": expected_by_access,
        "by_source": expected_by_source,
        "records": len(projected),
    }
    if provenance.get("counts") != expected_counts:
        raise SeedError("seed manifest aggregate counts do not match its records")

    inputs = provenance.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != len(INPUT_NAMES):
        raise SeedError("seed manifest input list is invalid")
    by_path: dict[str, dict[str, Any]] = {}
    expected_roles = {
        "articles_index.json": "projected",
        "trades_extracted.json": "checksum-companion-only",
        "snapshot_manifest.json": "provenance",
    }
    for entry in inputs:
        if not isinstance(entry, dict) or set(entry) != {"bytes", "path", "role", "sha256"}:
            raise SeedError("seed manifest input entry is invalid")
        name = entry.get("path")
        if not isinstance(name, str) or name in by_path or name not in expected_roles:
            raise SeedError("seed manifest input paths must be exact and unique")
        if entry.get("role") != expected_roles[name]:
            raise SeedError(f"seed manifest input role for {name!r} is invalid")
        if not isinstance(entry.get("bytes"), int) or entry["bytes"] < 1:
            raise SeedError(f"seed manifest byte count for {name!r} is invalid")
        digest = entry.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise SeedError(f"seed manifest digest for {name!r} is invalid")
        by_path[name] = entry

    snapshot = provenance.get("source_snapshot")
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "article_count", "catalog_count", "catalog_latest_publication", "checked_at",
        "data_checksum", "manifest_schema_version", "observation_count_verified_but_omitted",
        "registry_count", "repository", "revision",
    }:
        raise SeedError("seed source snapshot is invalid")
    dataset_version = publications.get("source_dataset_version")
    if not isinstance(dataset_version, str) or not re.fullmatch(r"[0-9a-f]{64}", dataset_version):
        raise SeedError("seed dataset version is invalid")
    if dataset_version != snapshot.get("data_checksum"):
        raise SeedError("seed dataset version does not match source provenance")
    if snapshot.get("repository") != ARCHIVE_REPOSITORY:
        raise SeedError("seed source repository is invalid")
    revision = snapshot.get("revision")
    if not isinstance(revision, str) or not REVISION_RE.fullmatch(revision):
        raise SeedError("seed source revision is invalid")
    if snapshot.get("manifest_schema_version") != 2:
        raise SeedError("seed source manifest schema is unsupported")
    if snapshot.get("catalog_count") != len(projected):
        raise SeedError("seed source catalogue count is inconsistent")
    for field in ("article_count", "observation_count_verified_but_omitted", "registry_count"):
        if not isinstance(snapshot.get(field), int) or snapshot[field] < 0:
            raise SeedError(f"seed source {field} is invalid")
    if snapshot["article_count"] + snapshot["registry_count"] != len(projected):
        raise SeedError("seed source article and registry counts do not make the catalogue")
    _published(snapshot.get("catalog_latest_publication"), "seed latest publication")
    _published(snapshot.get("checked_at"), "seed checked_at")
    newest_publication = max(record["published_at"] for record in projected)
    if snapshot.get("catalog_latest_publication") != newest_publication:
        raise SeedError("seed source latest publication does not match its records")

    source_checks = provenance.get("source_checks")
    if not isinstance(source_checks, dict) or not source_checks:
        raise SeedError("seed source checks are missing")
    if set(source_checks) != set(expected_by_source):
        raise SeedError("seed source checks do not cover the exact publication sources")
    check_times: list[str] = []
    for source, state in source_checks.items():
        if source not in SOURCE_HOSTS or not isinstance(state, dict):
            raise SeedError(f"seed source check {source!r} is invalid")
        if set(state) != {"checked_at", "included_count", "newest", "status"}:
            raise SeedError(f"seed source check {source!r} has unexpected keys")
        checked_at = _published(
            state.get("checked_at"), f"seed source check {source!r}.checked_at"
        )
        check_times.append(checked_at)
        newest = state.get("newest")
        newest_instant = _publication_instant(
            newest, f"seed source check {source!r}.newest"
        )
        if not isinstance(state.get("included_count"), int) or state["included_count"] < 0:
            raise SeedError(f"seed source check {source!r} count is invalid")
        if state["included_count"] != expected_by_source[source]:
            raise SeedError(f"seed source check {source!r} count does not match its records")
        retained_source_newest = max(
            _publication_instant(
                record["published_at"],
                f"seed retained {source!r} publication",
            )
            for record in projected
            if record["source"] == source
        )
        # The archive source check describes the pre-deduplication discovery
        # edge. A newer item can therefore survive under another canonical
        # source while its source-specific alternate URL remains attached.
        if newest_instant < retained_source_newest:
            raise SeedError(
                f"seed source check {source!r} newest publication predates "
                "its retained records"
            )
        if state.get("status") not in ARCHIVE_SOURCE_STATUSES:
            raise SeedError(f"seed source check {source!r} is not publishable")
    if snapshot.get("checked_at") != max(check_times):
        raise SeedError("seed source checked_at is not the latest completed source check")
    return publications, provenance
