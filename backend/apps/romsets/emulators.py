"""Loader for the curated emulator → archive.org query map (emulators.yml)."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import yaml

EMULATORS_PATH = Path(__file__).resolve().parent / "emulators.yml"


@dataclass(frozen=True)
class Emulator:
    id: str
    name: str
    platform_id: str | None
    query: str


@functools.lru_cache(maxsize=1)
def load_emulators() -> tuple[Emulator, ...]:
    raw = yaml.safe_load(EMULATORS_PATH.read_text()) or []
    return tuple(
        Emulator(
            id=entry["id"],
            name=entry["name"],
            platform_id=entry.get("platform_id") or None,
            query=entry["query"],
        )
        for entry in raw
    )


def get_emulator(emulator_id: str) -> Emulator | None:
    return next((e for e in load_emulators() if e.id == emulator_id), None)


def build_query(emulator: Emulator, user_query: str = "") -> str:
    """The curated query always holds; the user's text narrows it further."""
    user_query = (user_query or "").strip()
    if not user_query:
        return emulator.query
    escaped = user_query.replace('"', " ")
    return f'{emulator.query} AND ("{escaped}")'
