"""Thin client for the StatsBomb Open Data GitHub repository.

Data is served as static JSON files, so no API key or SDK is needed.
Every file is cached on disk (data/raw/) so that it is downloaded only once.

Data attribution: StatsBomb Open Data (https://github.com/statsbomb/open-data).
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pandas as pd

BASE_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
RAW_DIR = Path("data/raw")


def fetch_json(relative_path: str, cache_dir: Path = RAW_DIR, refresh: bool = False):
    """Return the parsed JSON at BASE_URL/relative_path, using a local cache.

    relative_path examples: "competitions.json", "matches/11/90.json",
    "events/3773386.json".
    """
    local = cache_dir / relative_path
    if local.exists() and not refresh:
        return json.loads(local.read_text(encoding="utf-8"))
    response = httpx.get(f"{BASE_URL}/{relative_path}", timeout=60, follow_redirects=True)
    response.raise_for_status()
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(response.text, encoding="utf-8")
    return response.json()


def load_competitions() -> pd.DataFrame:
    """One row per (competition, season) available in the open data."""
    return pd.DataFrame(fetch_json("competitions.json"))


def load_matches(competition_id: int, season_id: int) -> pd.DataFrame:
    """One row per match of a competition-season.

    Nested JSON is flattened with dots, e.g. "home_team.home_team_name".
    """
    data = fetch_json(f"matches/{competition_id}/{season_id}.json")
    return pd.json_normalize(data)


def load_events(match_id: int) -> pd.DataFrame:
    """All events of one match (passes, shots, pressures, ...), flattened."""
    return pd.json_normalize(fetch_json(f"events/{match_id}.json"))
