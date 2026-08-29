"""Loader for the curated system → archive.org query map (sources.yml)."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import yaml

SOURCES_PATH = Path(__file__).resolve().parent / "sources.yml"


@dataclass(frozen=True)
class BiosSource:
    id: str
    name: str
    platform_id: str | None
    query: str


@functools.lru_cache(maxsize=1)
def load_sources() -> tuple[BiosSource, ...]:
    raw = yaml.safe_load(SOURCES_PATH.read_text()) or []
    return tuple(
        BiosSource(
            id=entry["id"],
            name=entry["name"],
            platform_id=entry.get("platform_id") or None,
            query=entry["query"],
        )
        for entry in raw
    )


def get_source(source_id: str) -> BiosSource | None:
    return next((s for s in load_sources() if s.id == source_id), None)


def build_query(source: BiosSource, user_query: str = "") -> str:
    """The curated query always holds; the user's text narrows it further."""
    user_query = (user_query or "").strip()
    if not user_query:
        return source.query
    escaped = user_query.replace('"', " ")
    return f'{source.query} AND ("{escaped}")'
