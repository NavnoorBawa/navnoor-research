"""Filesystem locations used by the pipeline and the build."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
SEED_DIR = ROOT / "seed"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

PUBLICATIONS_PATH = SEED_DIR / "publications.json"
SEED_MANIFEST_PATH = SEED_DIR / "manifest.json"
RESEARCH_PATH = DATA_DIR / "research.json"
COMPANIES_PATH = DATA_DIR / "companies.json"
NEWS_PATH = DATA_DIR / "news.json"

DEFAULT_SITE_DIR = ROOT / "_site"
