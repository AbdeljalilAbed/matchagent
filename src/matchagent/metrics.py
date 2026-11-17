from __future__ import annotations

import duckdb
import pandas as pd

# Le terrain StatsBomb fait 120 x 80 ; chaque équipe attaque vers x = 120
# (les coordonnées sont toujours du point de vue de l'équipe qui agit).
PITCH_LENGTH = 120
PITCH_WIDTH = 80


def _filters(match_id: int | None, team_id: int | None) -> tuple[str, list]:
    """Clause WHERE optionnelle (sur team_matches aliasée tm) et ses paramètres."""
    conditions, params = [], []
    if match_id is not None:
        conditions.append("tm.match_id = ?")
        params.append(match_id)
    if team_id is not None:
        conditions.append("tm.team_id = ?")
        params.append(team_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where, params


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
    where, params = _filters(match_id, team_id)
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


PROGRESSIVE_RATIO = 0.25  # une passe progressive se rapproche du but d'au moins 25 %


def team_passing(
    con: duckdb.DuckDBPyConnection,
    match_id: int | None = None,
    team_id: int | None = None,
) -> pd.DataFrame:
    """Passing metrics, one row per team per match.

    Definitions (periods 1-4):
    - passes: passes attempted
    - completed: passes with no outcome (StatsBomb: no outcome = completed)
    - completion_rate: completed / passes, between 0 and 1 (NULL if no pass)
    - progressive: completed passes that reduce the distance to the opponent's
      goal (centre of the line, x = 120, y = 40) by at least 25 % of the
      starting distance
    """
    where, params = _filters(match_id, team_id)
    goal_x, goal_y = PITCH_LENGTH, PITCH_WIDTH / 2
    sql = f"""
        WITH p AS (
            SELECT event_id, match_id, team_id, complete,
                   SQRT(POWER({goal_x} - x, 2) + POWER({goal_y} - y, 2)) AS d_start,
                   SQRT(POWER({goal_x} - end_x, 2) + POWER({goal_y} - end_y, 2)) AS d_end
            FROM passes
            WHERE period <= 4
        )
        SELECT tm.match_id, tm.team_id, tm.team,
               COUNT(p.event_id) AS passes,
               COUNT(p.event_id) FILTER (WHERE p.complete) AS completed,
               COUNT(p.event_id) FILTER (WHERE p.complete) * 1.0
                   / NULLIF(COUNT(p.event_id), 0) AS completion_rate,
               COUNT(p.event_id) FILTER (
                   WHERE p.complete AND p.d_start - p.d_end >= {PROGRESSIVE_RATIO} * p.d_start
               ) AS progressive
        FROM team_matches tm
        LEFT JOIN p ON p.match_id = tm.match_id AND p.team_id = tm.team_id
        {where}
        GROUP BY ALL
        ORDER BY tm.match_id, tm.team
    """
    return con.execute(sql, params).df()


# --- pressing (PPDA) ---------------------------------------------------------
# Zone de pressing : les 60 % du terrain les plus éloignés du but de l'équipe qui presse.
# Le même endroit se lit avec deux repères : x >= 48 pour l'équipe qui presse,
# x <= 72 pour l'adversaire (x_adversaire = 120 - x_presseur).
PPDA_ZONE = 0.6
PPDA_OPP_MAX_X = PITCH_LENGTH * PPDA_ZONE            # 72 : passes de l'adversaire
PPDA_PRESS_MIN_X = PITCH_LENGTH - PPDA_OPP_MAX_X     # 48 : actions défensives


def team_ppda(
    con: duckdb.DuckDBPyConnection,
    match_id: int | None = None,
    team_id: int | None = None,
) -> pd.DataFrame:
    """PPDA (passes allowed per defensive action), one row per team per match.

    Definitions (periods 1-4, pressing zone = the 60 % of the pitch farthest
    from the team's own goal):
    - opp_passes: passes made by the opponent inside the zone
    - defensive_actions: tackles (duels of type Tackle), interceptions and fouls
      committed by the team inside the zone, whatever their outcome
      (pressures are not counted)
    - ppda: opp_passes / defensive_actions (NULL if no defensive action);
      the lower, the more intense the pressing
    """
    where, params = _filters(match_id, team_id)
    sql = f"""
        WITH opp_passes AS (
            SELECT match_id, team_id, COUNT(*) AS n
            FROM passes
            WHERE period <= 4 AND x <= {PPDA_OPP_MAX_X}
            GROUP BY ALL
        ), actions AS (
            SELECT match_id, team_id, COUNT(*) AS n
            FROM events
            WHERE period <= 4 AND x >= {PPDA_PRESS_MIN_X}
              AND (type IN ('Interception', 'Foul Committed')
                   OR (type = 'Duel' AND duel_type = 'Tackle'))
            GROUP BY ALL
        )
        SELECT tm.match_id, tm.team_id, tm.team,
               COALESCE(op.n, 0) AS opp_passes,
               COALESCE(a.n, 0) AS defensive_actions,
               COALESCE(op.n, 0) * 1.0 / NULLIF(COALESCE(a.n, 0), 0) AS ppda
        FROM team_matches tm
        LEFT JOIN opp_passes op ON op.match_id = tm.match_id AND op.team_id = tm.opponent_id
        LEFT JOIN actions a ON a.match_id = tm.match_id AND a.team_id = tm.team_id
        {where}
        ORDER BY tm.match_id, tm.team
    """
    return con.execute(sql, params).df()
