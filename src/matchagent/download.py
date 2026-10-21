"""Phase 1: download every raw file needed by a slice (matches, lineups, events)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from matchagent.sb_api import fetch_json


def download_slice(competition_id: int, season_id: int, workers: int = 8) -> list[int]:
    """Download matches, lineups and events of one competition-season.

    Files are cached in data/raw/, so a second run downloads nothing.
    Returns the list of match ids.
    """
    matches = fetch_json(f"matches/{competition_id}/{season_id}.json")
    match_ids = [m["match_id"] for m in matches]

    def fetch_match(match_id: int) -> None:
        fetch_json(f"events/{match_id}.json")
        fetch_json(f"lineups/{match_id}.json")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(fetch_match, match_ids))  # list() re-raises any exception
    return match_ids
