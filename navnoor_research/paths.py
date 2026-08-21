"""Filesystem locations used by the pipeline and the build."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

ARTICLES_PATH = DATA_DIR / "articles.json"
NEWS_PATH = DATA_DIR / "news.json"

DEFAULT_SITE_DIR = ROOT / "_site"


def site_output_dir() -> Path:
    """Where `build_site.py` writes. Overridable for throwaway audit builds."""
    return Path(os.environ.get("SITE_OUTPUT_DIR") or DEFAULT_SITE_DIR)


def site_revision() -> str:
    """The Git revision the release manifest is bound to."""
    return os.environ.get("SITE_REVISION") or "dev"


def corpus_dir() -> Path:
    """Read-only source corpus. Never written to by this project."""
    raw = os.environ.get("CORPUS_DIR")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / "Downloads" / "substack trades"
