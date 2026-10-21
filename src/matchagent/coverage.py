"""Phase 0: measure what the open data actually contains."""
from __future__ import annotations

import pandas as pd

from matchagent.sb_api import load_competitions, load_events, load_matches


def build_coverage() -> pd.DataFrame:
    """One row per competition-season with match count, teams, dates, 360 data.

    Downloads one matches file per competition-season (cached afterwards).
    """
    rows = []
    for comp in load_competitions().itertuples(index=False):
        matches = load_matches(comp.competition_id, comp.season_id)
        dates = pd.to_datetime(matches["match_date"])
        n_360 = (
            int((matches["match_status_360"] == "available").sum())
            if "match_status_360" in matches
            else 0
        )
        teams = set(matches["home_team.home_team_name"]) | set(
            matches["away_team.away_team_name"]
        )
        rows.append(
            {
                "competition_id": comp.competition_id,
                "season_id": comp.season_id,
                "competition": comp.competition_name,
                "season": comp.season_name,
                "country": comp.country_name,
                "gender": comp.competition_gender,
                "n_matches": len(matches),
                "n_teams": len(teams),
                "n_matches_360": n_360,
                "first_date": dates.min().date(),
                "last_date": dates.max().date(),
            }
        )
    return pd.DataFrame(rows).sort_values("n_matches", ascending=False, ignore_index=True)


def slice_report(competition_id: int, season_id: int) -> pd.DataFrame:
    """Matches played per team inside one competition-season."""
    matches = load_matches(competition_id, season_id)
    home = matches["home_team.home_team_name"].rename("team")
    away = matches["away_team.away_team_name"].rename("team")
    return (
        pd.concat([home, away])
        .value_counts()
        .rename_axis("team")
        .reset_index(name="n_matches")
    )


def probe_events(match_id: int) -> pd.DataFrame:
    """Event types of one match with counts, to learn the schema before Phase 1."""
    events = load_events(match_id)
    return (
        events["type.name"]
        .value_counts()
        .rename_axis("event_type")
        .reset_index(name="count")
    )
