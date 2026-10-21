"""Read and validate scope.toml (the slices of data the project covers)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from matchagent.sb_api import load_competitions


@dataclass(frozen=True)
class Slice:
    name: str
    competition_id: int
    season_id: int
    priority: str


def load_scope(path: Path = Path("scope.toml")) -> list[Slice]:
    """Parse scope.toml into Slice objects."""
    with path.open("rb") as f:
        raw = tomllib.load(f)
    return [Slice(**item) for item in raw["slices"]]


def validate_scope(slices: list[Slice], competitions: pd.DataFrame | None = None) -> list[str]:
    """Return a list of problems (empty list = scope is consistent with the data)."""
    competitions = load_competitions() if competitions is None else competitions
    known = set(zip(competitions["competition_id"], competitions["season_id"]))
    problems = []
    names = [s.name for s in slices]
    if len(names) != len(set(names)):
        problems.append("duplicate slice names")
    for s in slices:
        if (s.competition_id, s.season_id) not in known:
            problems.append(f"{s.name}: ({s.competition_id}, {s.season_id}) not in open data")
    return problems
