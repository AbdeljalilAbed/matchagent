"""The agent's tools: plain functions, testable without any LLM.

In phase 3 each function gets wrapped by the agent framework. The docstring of
every tool is what the LLM reads to decide when to call it: write it as a prompt.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import duckdb

from matchagent.entities import EntityResolver, Resolution
from matchagent.metrics import team_passing, team_ppda, team_shooting
from matchagent.schemas import (
    DEFINITIONS,
    MAX_ROWS,
    MatchList,
    MatchStatsResult,
    MatchSummary,
    MetricDefinition,
    PassingStats,
    PressingStats,
    ShootingStats,
    TeamMatchStats,
    ToolError,
)


@dataclass
class Deps:
    """What the tools need: a database connection and the entity resolver."""

    con: duckdb.DuckDBPyConnection
    resolver: EntityResolver


# A match with its shootout winner (official scores exclude the shootout).
_MATCH_SELECT = """
    SELECT m.match_id, CAST(m.match_date AS VARCHAR) AS date, m.stage,
           m.home_team, m.away_team, m.home_score, m.away_score,
           (SELECT tm.team FROM team_matches tm
            WHERE tm.match_id = m.match_id AND tm.shootout_result = 'W') AS shootout_winner
    FROM matches m
"""


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list) -> list[dict]:
    """Run a query and return plain Python dicts (None for NULL, no NaN)."""
    cursor = con.execute(sql, params)
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def explain_metric(name: str) -> MetricDefinition | ToolError:
    """Give the exact definition of a metric (xg, npxg, ppda, progressive...).

    Call this before explaining a number to the user, or when asked what a metric means.
    """
    key = name.strip().lower()
    if key in DEFINITIONS:
        return MetricDefinition(name=key, definition=DEFINITIONS[key])
    return ToolError(
        error="invalid_argument",
        message=f"Unknown metric '{name}'.",
        hint="Available metrics: " + ", ".join(sorted(DEFINITIONS)),
    )


def resolve_entity(deps: Deps, query: str, kind: Literal["team", "player"]) -> Resolution:
    """Find the id of a team or a player from the name the user typed.

    ALWAYS call this first: the other tools need ids, never names. If the status is
    'ambiguous', ask the user which candidate they mean (use the context field);
    never pick one yourself. If 'not_found', say so.
    """
    return deps.resolver.resolve(query, kind)


def find_matches(
    deps: Deps,
    team_id: int | None = None,
    stage: str | None = None,
    limit: int = MAX_ROWS,
) -> MatchList | ToolError:
    """List matches, oldest first, optionally for one team and/or one stage.

    Use it to find match ids and results. Scores exclude the penalty shootout:
    check shootout_winner to know who won a drawn knockout match.
    The list is capped: check 'truncated' and 'total'.
    """
    con = deps.con
    limit = max(1, min(limit, MAX_ROWS))
    conditions, params = [], []

    if team_id is not None:
        if con.execute("SELECT 1 FROM teams WHERE team_id = ?", [team_id]).fetchone() is None:
            return ToolError(
                error="not_found",
                message=f"No team with id {team_id}.",
                hint="Use resolve_entity with kind='team' to get a valid team id.",
            )
        conditions.append("(m.home_team_id = ? OR m.away_team_id = ?)")
        params += [team_id, team_id]

    if stage is not None:
        known = [r[0] for r in con.execute("SELECT DISTINCT stage FROM matches ORDER BY 1").fetchall()]
        if stage.lower() not in [s.lower() for s in known if s]:
            return ToolError(
                error="invalid_argument",
                message=f"Unknown stage '{stage}'.",
                hint="Available stages: " + ", ".join(s for s in known if s),
            )
        conditions.append("LOWER(m.stage) = LOWER(?)")
        params.append(stage)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    total = con.execute(f"SELECT COUNT(*) FROM matches m {where}", params).fetchone()[0]
    rows = _rows(con, f"{_MATCH_SELECT} {where} ORDER BY m.match_date, m.match_id LIMIT ?", params + [limit])
    return MatchList(
        matches=[MatchSummary(**r) for r in rows],
        total=total,
        truncated=total > len(rows),
    )


def match_stats(deps: Deps, match_id: int) -> MatchStatsResult | ToolError:
    """Shooting, passing and pressing statistics of both teams in one match.

    Use a match_id obtained from find_matches. Numbers are rounded; a null value
    means 'not defined' (for example no pass), not zero.
    """
    con = deps.con
    matches = _rows(con, f"{_MATCH_SELECT} WHERE m.match_id = ?", [match_id])
    if not matches:
        return ToolError(
            error="not_found",
            message=f"No match with id {match_id}.",
            hint="Use find_matches to look up valid match ids.",
        )

    shooting = team_shooting(con, match_id=match_id).to_dict("records")
    passing = {r["team_id"]: r for r in team_passing(con, match_id=match_id).to_dict("records")}
    pressing = {r["team_id"]: r for r in team_ppda(con, match_id=match_id).to_dict("records")}

    teams = []
    for s in shooting:
        p, d = passing[s["team_id"]], pressing[s["team_id"]]
        teams.append(
            TeamMatchStats(
                team_id=s["team_id"],
                team=s["team"],
                shooting=ShootingStats(shots=s["shots"], goals=s["goals"], xg=s["xg"], npxg=s["npxg"]),
                passing=PassingStats(
                    passes=p["passes"],
                    completed=p["completed"],
                    completion_pct=p["completion_rate"] * 100,   # fraction -> percent
                    progressive=p["progressive"],
                ),
                pressing=PressingStats(
                    opp_passes=d["opp_passes"], defensive_actions=d["defensive_actions"], ppda=d["ppda"]
                ),
            )
        )
    return MatchStatsResult(match=MatchSummary(**matches[0]), teams=teams, sources=[match_id])
