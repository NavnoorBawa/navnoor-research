"""The release manifest.

The manifest lists every public byte in the bundle with its digest and binds the
whole set to one Git revision. `validate_release.py` replays it against the
files on disk, so a partial upload or an edited artefact is detectable rather
than merely unlikely.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

from .fingerprint import sha256_hex
from .schema import RELEASE_SCHEMA_VERSION

MANIFEST_NAME = "release.json"


def describe(site_dir: Path) -> list[dict[str, Any]]:
    """Digest and size of every file in the bundle except the manifest itself."""
    entries: list[dict[str, Any]] = []
    for path in sorted(site_dir.rglob("*")):
        if not path.is_file() or path.name == MANIFEST_NAME:
            continue
        payload = path.read_bytes()
        entries.append({
            "path": path.relative_to(site_dir).as_posix(),
            "sha256": sha256_hex(payload),
            "bytes": len(payload),
        })
    return entries


def build(site_dir: Path, revision: str, counts: dict[str, int]) -> dict[str, Any]:
    files = describe(site_dir)
    return {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "revision": revision,
        "counts": dict(sorted(counts.items())),
        "total_bytes": sum(entry["bytes"] for entry in files),
        "file_count": len(files),
        "files": files,
    }


def validate_document(value: Any, expected_revision: str = "") -> list[str]:
    """Validate only the manifest envelope and entries, without touching paths."""
    problems: list[str] = []
    if not isinstance(value, dict) or set(value) != {
        "counts", "file_count", "files", "revision", "schema_version", "total_bytes"
    }:
        return ["manifest envelope has unexpected fields"]
    if expected_revision and value.get("revision") != expected_revision:
        problems.append(
            f"revision mismatch: manifest says {value.get('revision')!r}, "
            f"expected {expected_revision!r}"
        )
    if value.get("schema_version") != RELEASE_SCHEMA_VERSION:
        problems.append(
            f"schema_version {value.get('schema_version')!r} is not "
            f"{RELEASE_SCHEMA_VERSION}"
        )
    revision = value.get("revision")
    if not isinstance(revision, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", revision):
        problems.append("revision is not a bounded release identifier")
    counts = value.get("counts")
    if (
        not isinstance(counts, dict) or not counts
        or any(not isinstance(key, str) or not key for key in counts)
        or any(not isinstance(value, int) or isinstance(value, bool) or value < 0
               for value in counts.values())
    ):
        problems.append("counts must be a non-empty map of non-negative integers")

    files = value.get("files")
    if not isinstance(files, list):
        return problems + ["files must be an array"]
    listed: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    declared_total = 0
    for index, entry in enumerate(files):
        if not isinstance(entry, dict) or set(entry) != {"bytes", "path", "sha256"}:
            problems.append(f"files[{index}] has unexpected fields")
            continue
        name = entry.get("path")
        if not isinstance(name, str):
            problems.append(f"files[{index}].path is not text")
            continue
        pure = PurePosixPath(name)
        if (
            not name or name == MANIFEST_NAME or pure.is_absolute() or pure.name != name
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", name)
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            problems.append(f"files[{index}].path is unsafe: {name!r}")
            continue
        if name in listed:
            problems.append(f"duplicate manifest path: {name}")
            continue
        size = entry.get("bytes")
        digest = entry.get("sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            problems.append(f"{name}: manifest byte count is invalid")
            continue
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            problems.append(f"{name}: manifest digest is invalid")
            continue
        listed[name] = entry
        order.append(name)
        declared_total += size
    if order != sorted(order):
        problems.append("manifest file entries are not in deterministic path order")
    if value.get("file_count") != len(files) or len(files) != len(listed):
        problems.append("file_count does not match the unique manifest entries")
    if value.get("total_bytes") != declared_total:
        problems.append("total_bytes does not match the manifest entries")
    return problems


def verify(
    site_dir: Path, manifest: Any, expected_revision: str = ""
) -> list[str]:
    """Return a list of problems. An empty list means the release is exact."""
    problems = validate_document(manifest, expected_revision)
    if problems:
        return problems
    files = manifest["files"]
    listed = {entry["path"]: entry for entry in files}

    on_disk = {
        path.relative_to(site_dir).as_posix()
        for path in site_dir.rglob("*")
        if path.is_file() and path.name != MANIFEST_NAME
    }
    for path in site_dir.rglob("*"):
        if path.is_symlink():
            problems.append(f"bundle contains a symbolic link: {path.relative_to(site_dir)}")

    for missing in sorted(set(listed) - on_disk):
        problems.append(f"missing from bundle: {missing}")
    for extra in sorted(on_disk - set(listed)):
        problems.append(f"present but unlisted: {extra}")

    for name in sorted(set(listed) & on_disk):
        payload = (site_dir / name).read_bytes()
        entry = listed[name]
        if len(payload) != entry["bytes"]:
            problems.append(
                f"{name}: {len(payload)} bytes on disk, manifest says {entry['bytes']}"
            )
        digest = sha256_hex(payload)
        if digest != entry["sha256"]:
            problems.append(f"{name}: digest {digest[:16]}… does not match manifest")

    return problems
