"""DuckDB schema of the project (tables and views)."""
from __future__ import annotations

import duckdb

TABLES = ["matches", "teams", "players", "lineups", "events", "passes", "shots", "carries"]

# Columns shared by events / passes / shots / carries (denormalised on purpose:
# it keeps the SQL the agent has to write short and join-free).
_COMMON = """
    event_id VARCHAR, match_id INTEGER, period TINYINT, minute SMALLINT, second SMALLINT,
    team_id INTEGER, team VARCHAR, player_id INTEGER, player VARCHAR,
    x DOUBLE, y DOUBLE
"""

DDL = {
    "matches": """
        match_id INTEGER, competition_id INTEGER, season_id INTEGER,
        competition_name VARCHAR, season_name VARCHAR, match_date DATE, kick_off VARCHAR,
        stage VARCHAR, match_week INTEGER,
        home_team_id INTEGER, home_team VARCHAR, away_team_id INTEGER, away_team VARCHAR,
        home_score INTEGER, away_score INTEGER, stadium VARCHAR, referee VARCHAR
    """,
    "teams": "team_id INTEGER, team_name VARCHAR, name_norm VARCHAR",
    "players": "player_id INTEGER, player_name VARCHAR, player_nickname VARCHAR, name_norm VARCHAR",
    "lineups": """
        match_id INTEGER, team_id INTEGER, player_id INTEGER, jersey_number SMALLINT,
        country VARCHAR, started BOOLEAN, played BOOLEAN
    """,
    "events": """
        id VARCHAR, match_id INTEGER, event_index INTEGER, period TINYINT,
        minute SMALLINT, second SMALLINT, type VARCHAR,
        team_id INTEGER, team VARCHAR, player_id INTEGER, player VARCHAR, position VARCHAR,
        possession INTEGER, possession_team_id INTEGER, possession_team VARCHAR,
        play_pattern VARCHAR, x DOUBLE, y DOUBLE, duration DOUBLE,
        under_pressure BOOLEAN, counterpress BOOLEAN,
        outcome VARCHAR, card VARCHAR, duel_type VARCHAR
    """,
    "passes": f"""{_COMMON},
        recipient_id INTEGER, recipient VARCHAR, length DOUBLE, angle DOUBLE, height VARCHAR,
        end_x DOUBLE, end_y DOUBLE, pass_type VARCHAR, body_part VARCHAR,
        outcome VARCHAR, complete BOOLEAN, is_cross BOOLEAN, is_switch BOOLEAN,
        is_through_ball BOOLEAN, is_cut_back BOOLEAN, is_shot_assist BOOLEAN, is_goal_assist BOOLEAN
    """,
    "shots": f"""{_COMMON},
        end_x DOUBLE, end_y DOUBLE, end_z DOUBLE, xg DOUBLE, outcome VARCHAR, is_goal BOOLEAN,
        shot_type VARCHAR, body_part VARCHAR, technique VARCHAR, first_time BOOLEAN,
        key_pass_id VARCHAR
    """,
    "carries": f"""{_COMMON},
        end_x DOUBLE, end_y DOUBLE, distance DOUBLE
    """,
}

# Penalty shootout goals (period 5). Official scores exclude them, so a drawn
# knockout match (e.g. the 2022 final, 3-3) needs this to know who advanced.
SHOOTOUTS_VIEW = """
CREATE OR REPLACE VIEW shootouts AS
SELECT match_id, team_id, COUNT(*) FILTER (WHERE is_goal) AS goals
FROM shots WHERE period = 5 GROUP BY ALL
"""

# One row per team per match: the base of most team-level questions.
# `result` covers regulation + extra time; `shootout_*` are NULL when there was no shootout.
TEAM_MATCHES_VIEW = """
CREATE OR REPLACE VIEW team_matches AS
WITH base AS (
    SELECT match_id, match_date, home_team_id AS team_id, home_team AS team,
           away_team_id AS opponent_id, away_team AS opponent, TRUE AS is_home,
           home_score AS goals_for, away_score AS goals_against
    FROM matches
    UNION ALL
    SELECT match_id, match_date, away_team_id, away_team, home_team_id, home_team, FALSE,
           away_score, home_score
    FROM matches
)
SELECT b.*,
       CASE WHEN goals_for > goals_against THEN 'W' WHEN goals_for < goals_against THEN 'L' ELSE 'D' END AS result,
       sf.goals AS shootout_for, sa.goals AS shootout_against,
       CASE WHEN sf.goals > sa.goals THEN 'W' WHEN sf.goals < sa.goals THEN 'L' END AS shootout_result
FROM base b
LEFT JOIN shootouts sf ON sf.match_id = b.match_id AND sf.team_id = b.team_id
LEFT JOIN shootouts sa ON sa.match_id = b.match_id AND sa.team_id = b.opponent_id
"""


def create_schema(con: duckdb.DuckDBPyConnection) -> None:
    """(Re)create every table and view. Idempotent: a build always starts clean."""
    con.execute("DROP VIEW IF EXISTS team_matches")
    con.execute("DROP VIEW IF EXISTS shootouts")
    for table in TABLES:
        con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute(f"CREATE TABLE {table} ({DDL[table]})")
    con.execute(SHOOTOUTS_VIEW)
    con.execute(TEAM_MATCHES_VIEW)
