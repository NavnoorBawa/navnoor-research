"""Content addressing for the built bundle.

Every asset filename carries a digest of its own bytes. A changed file gets a
changed name, so a cache can be told to keep these forever and a reader can
never be served a stale half of a release.
"""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath

DIGEST_LENGTH = 16


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def short_digest(payload: bytes) -> str:
    return sha256_hex(payload)[:DIGEST_LENGTH]


def fingerprint_name(name: str, payload: bytes) -> str:
    """`app.css` plus its bytes becomes `app-<digest>.css`."""
    path = PurePosixPath(name)
    return f"{path.stem}-{short_digest(payload)}{path.suffix}"
