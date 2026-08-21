"""Loading and shape-checking of the reviewed configuration tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import jsonio, paths


class ConfigError(Exception):
    """A configuration table is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class Entity:
    id: str
    label: str
    kind: str
    aliases: list[str]

    def surfaces(self) -> list[str]:
        """Every string that should resolve to this entity, longest first.

        Longest-first matters: 'Long-Term Capital Management' must win over
        'Capital' when both could match the same span of text.
        """
        return sorted({self.label, *self.aliases}, key=lambda s: (-len(s), s))


@dataclass(frozen=True)
class Topic:
    id: str
    label: str
    keywords: list[str]
    entities: list[str]


@dataclass(frozen=True)
class Source:
    id: str
    label: str
    status: str
    allowed_hosts: list[str]
    allowed_fields: list[str]
    prohibited_fields: list[str]
    attribution: str
    poll_interval_seconds: int
    retention_days: int


def _require(node: dict, key: str, where: str) -> Any:
    if key not in node:
        raise ConfigError(f"{where}: missing required key {key!r}")
    return node[key]


def load_entities() -> list[Entity]:
    raw = jsonio.load(paths.CONFIG_DIR / "entity_aliases.json")
    out: list[Entity] = []
    seen = set()
    for item in raw.get("entities", []):
        where = f"entity_aliases.json[{item.get('id', '?')}]"
        ent = Entity(
            id=str(_require(item, "id", where)),
            label=str(_require(item, "label", where)),
            kind=str(_require(item, "kind", where)),
            aliases=[str(a) for a in item.get("aliases", [])],
        )
        if ent.id in seen:
            raise ConfigError(f"{where}: duplicate entity id")
        seen.add(ent.id)
        out.append(ent)
    if not out:
        raise ConfigError("entity_aliases.json defines no entities")
    return out


def load_topics() -> list[Topic]:
    raw = jsonio.load(paths.CONFIG_DIR / "topics.json")
    known = {e.id for e in load_entities()}
    out: list[Topic] = []
    for item in raw.get("topics", []):
        where = f"topics.json[{item.get('id', '?')}]"
        topic = Topic(
            id=str(_require(item, "id", where)),
            label=str(_require(item, "label", where)),
            keywords=[str(k) for k in item.get("keywords", [])],
            entities=[str(e) for e in item.get("entities", [])],
        )
        unknown = [e for e in topic.entities if e not in known]
        if unknown:
            raise ConfigError(f"{where}: references unknown entity ids {unknown}")
        out.append(topic)
    if not out:
        raise ConfigError("topics.json defines no topics")
    return out


def load_sources() -> dict[str, Source]:
    raw = jsonio.load(paths.CONFIG_DIR / "source_rights.json")
    out: dict[str, Source] = {}
    for item in raw.get("sources", []):
        where = f"source_rights.json[{item.get('id', '?')}]"
        src = Source(
            id=str(_require(item, "id", where)),
            label=str(_require(item, "label", where)),
            status=str(_require(item, "status", where)),
            allowed_hosts=[str(h) for h in _require(item, "allowed_hosts", where)],
            allowed_fields=[str(f) for f in _require(item, "allowed_fields", where)],
            prohibited_fields=[str(f) for f in item.get("prohibited_fields", [])],
            attribution=str(_require(item, "attribution", where)),
            poll_interval_seconds=int(item.get("poll_interval_seconds", 0)),
            retention_days=int(item.get("retention_days", 0)),
        )
        out[src.id] = src
    if not out:
        raise ConfigError("source_rights.json defines no sources")
    return out
