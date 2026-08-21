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


def dumps(value: Any) -> str:
    """Canonical JSON: sorted keys, no incidental whitespace, UTF-8 preserved."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def dumps_pretty(value: Any) -> str:
    """Canonical JSON for files a human reviews in a diff."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def load(path: Path) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file in the same directory, then rename over the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
