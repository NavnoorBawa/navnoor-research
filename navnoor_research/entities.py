"""Deterministic entity and topic extraction.

No model, no network, no randomness: the same text always yields the same
entities and the same topic, which is what makes the built index reproducible
and the release manifest verifiable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from re import Pattern

from .config import Entity, Topic

# An alias that is short and fully capitalised is a ticker or an acronym, so it
# must match case-sensitively. Without this, 'BP' matches inside 'bp', 'US'
# matches 'us', and 'SEC' matches the first syllable of 'second'.
_STRICT_MAX_LEN = 6

# Boundaries that survive punctuation inside a surface form, so 'S&P 500' and
# 'D.E. Shaw' behave the same way '\b' would for a plain word.
_LEFT = r"(?<![A-Za-z0-9])"
_RIGHT = r"(?![A-Za-z0-9])"


def _is_strict(surface: str) -> bool:
    return surface.isupper() and len(surface) <= _STRICT_MAX_LEN


def _surface_pattern(surface: str) -> str:
    """Escape a surface form, allowing any run of whitespace between words."""
    return r"\s+".join(re.escape(part) for part in surface.split())


def _compile(surfaces: Sequence[str], ignore_case: bool) -> Pattern[str] | None:
    if not surfaces:
        return None
    body = "|".join(_surface_pattern(s) for s in surfaces)
    flags = re.IGNORECASE if ignore_case else 0
    return re.compile(f"{_LEFT}(?:{body}){_RIGHT}", flags)


class EntityMatcher:
    """Matches a reviewed entity vocabulary against free text."""

    def __init__(self, entities: Iterable[Entity]) -> None:
        self._entities = list(entities)
        self._labels: dict[str, str] = {e.id: e.label for e in self._entities}
        self._kinds: dict[str, str] = {e.id: e.kind for e in self._entities}
        self._patterns: list[tuple[str, Pattern[str] | None, Pattern[str] | None]] = []
        for entity in self._entities:
            surfaces = entity.surfaces()
            strict = [s for s in surfaces if _is_strict(s)]
            loose = [s for s in surfaces if not _is_strict(s)]
            self._patterns.append((entity.id, _compile(strict, False), _compile(loose, True)))

    def label(self, entity_id: str) -> str:
        return self._labels.get(entity_id, entity_id)

    def kind(self, entity_id: str) -> str:
        return self._kinds.get(entity_id, "concept")

    def find(self, text: str) -> list[str]:
        """Entity ids mentioned in `text`, in configuration order."""
        if not text:
            return []
        found: list[str] = []
        for entity_id, strict, loose in self._patterns:
            if (strict is not None and strict.search(text)) or (
                loose is not None and loose.search(text)
            ):
                found.append(entity_id)
        return found


class TopicClassifier:
    """Assigns exactly one topic per record, using keywords plus entity hits."""

    # An entity mention is stronger evidence than a loose keyword, so it counts
    # for more when topics compete for the same article.
    ENTITY_WEIGHT = 2
    KEYWORD_WEIGHT = 1
    FALLBACK = "general"
    FALLBACK_LABEL = "General"

    def __init__(self, topics: Iterable[Topic]) -> None:
        self._topics = list(topics)
        self._keyword_patterns: dict[str, Pattern[str] | None] = {
            t.id: _compile(t.keywords, True) for t in self._topics
        }
        self._entity_sets: dict[str, set] = {t.id: set(t.entities) for t in self._topics}

    def labels(self) -> dict[str, str]:
        out = {t.id: t.label for t in self._topics}
        out[self.FALLBACK] = self.FALLBACK_LABEL
        return out

    def order(self) -> list[str]:
        return [t.id for t in self._topics] + [self.FALLBACK]

    def classify(self, text: str, entity_ids: Sequence[str]) -> str:
        mentioned = set(entity_ids)
        best_id = self.FALLBACK
        best_score = 0
        for topic in self._topics:
            score = self.ENTITY_WEIGHT * len(self._entity_sets[topic.id] & mentioned)
            pattern = self._keyword_patterns[topic.id]
            if pattern is not None:
                score += self.KEYWORD_WEIGHT * len(set(m.group(0).lower() for m in
                                                       pattern.finditer(text)))
            # Strictly greater keeps configuration order as the tie-break.
            if score > best_score:
                best_score = score
                best_id = topic.id
        return best_id
