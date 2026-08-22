"""Public record shapes. Only fields listed here ever reach the built site."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Article:
    """One published article, reduced to rights-safe metadata."""

    id: str
    title: str
    url: str
    source: str
    published: str
    access: str
    topic: str
    entities: list[str] = field(default_factory=list)
    summary: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class NewsItem:
    """One checked headline. Never a body, image, or publisher asset."""

    id: str
    title: str
    url: str
    source_id: str
    attribution: str
    publisher: str
    published: str
    entities: list[str] = field(default_factory=list)
    topic: str = "general"

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class Company:
    """One SEC-backed ticker/company listing used only for local discovery."""

    id: str
    cik: str
    ticker: str
    exchange: str
    name: str
    url: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)
