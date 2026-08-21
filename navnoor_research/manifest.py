"""The release manifest.

The manifest lists every public byte in the bundle with its digest and binds the
whole set to one Git revision. `validate_release.py` replays it against the
files on disk, so a partial upload or an edited artefact is detectable rather
than merely unlikely.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION
from .fingerprint import sha256_hex

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
        "schema_version": SCHEMA_VERSION,
        "revision": revision,
        "counts": dict(sorted(counts.items())),
        "total_bytes": sum(entry["bytes"] for entry in files),
        "file_count": len(files),
        "files": files,
    }


def verify(
    site_dir: Path, manifest: dict[str, Any], expected_revision: str = ""
) -> list[str]:
    """Return a list of problems. An empty list means the release is exact."""
    problems: list[str] = []

    if expected_revision and manifest.get("revision") != expected_revision:
        problems.append(
            f"revision mismatch: manifest says {manifest.get('revision')!r}, "
            f"expected {expected_revision!r}"
        )
    if manifest.get("schema_version") != SCHEMA_VERSION:
        problems.append(
            f"schema_version {manifest.get('schema_version')!r} is not {SCHEMA_VERSION}"
        )

    listed = {entry["path"]: entry for entry in manifest.get("files", [])}
    on_disk = {
        path.relative_to(site_dir).as_posix()
        for path in site_dir.rglob("*")
        if path.is_file() and path.name != MANIFEST_NAME
    }

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
