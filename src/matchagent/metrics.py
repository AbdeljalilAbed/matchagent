from __future__ import annotations

import duckdb
import pandas as pd


def team_shooting(
    con: duckdb.DuckDBPyConnection,
    match_id: int | None = None,
    team_id: int | None = None,
) -> pd.DataFrame:
    """Shooting metrics, one row per team per match.

    Definitions:
    - shots: shots taken in periods 1-4 (the shootout, period 5, is excluded)
    - goals: those shots that scored (own goals are not shots, so not counted)
    - xg: sum of the StatsBomb xG of those shots
    - npxg: same, without penalties (shot_type = 'Penalty')
    A team with no shot gets 0, not a missing row.
    """
    conditions, params = [], []
    if match_id is not None:
        conditions.append("tm.match_id = ?")
        params.append(match_id)
    if team_id is not None:
        conditions.append("tm.team_id = ?")
        params.append(team_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = f"""
        SELECT tm.match_id, tm.team_id, tm.team,
               COUNT(s.event_id) AS shots,
               COUNT(s.event_id) FILTER (WHERE s.is_goal) AS goals,
               COALESCE(SUM(s.xg), 0) AS xg,
               COALESCE(SUM(s.xg) FILTER (WHERE s.shot_type <> 'Penalty'), 0) AS npxg
        FROM team_matches tm
        LEFT JOIN shots s
          ON s.match_id = tm.match_id AND s.team_id = tm.team_id AND s.period <= 4
        {where}
        GROUP BY ALL
        ORDER BY tm.match_id, tm.team
    """
    return con.execute(sql, params).df()