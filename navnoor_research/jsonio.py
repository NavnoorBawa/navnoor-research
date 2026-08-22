"""Deterministic JSON reading and writing.

Every byte the build emits must be reproducible, so all writes go through
`dumps` with sorted keys and fixed separators. Promotion is atomic: a partial
write can never replace a known-good file.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class JsonError(ValueError):
    """JSON is not strict UTF-8 data with unique object keys."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JsonError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def loads_strict(payload: bytes) -> Any:
    """Decode exact UTF-8 JSON, rejecting duplicate keys and non-finite values."""
    try:
        text = payload.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                JsonError(f"non-finite JSON value {value!r}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JsonError(str(exc)) from exc


def dumps(value: Any) -> str:
    """Canonical JSON: sorted keys, no incidental whitespace, UTF-8 preserved."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def dumps_pretty(value: Any) -> str:
    """Canonical JSON for files a human reviews in a diff."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def load(path: Path) -> Any:
    return loads_strict(path.read_bytes())


def write_atomic(path: Path, text: str) -> None:
    """Durably replace one JSON file without exposing a partial write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
