import duckdb

from matchagent.checks import run_checks
from matchagent.schema import create_schema


def _db():
    con = duckdb.connect(":memory:")
    create_schema(con)
    con.execute("""INSERT INTO matches (match_id, home_team_id, home_team, away_team_id, away_team,
                   home_score, away_score) VALUES (1, 10, 'A', 20, 'B', 1, 0)""")
    con.execute("INSERT INTO events (id, match_id, type, team_id, x, y) VALUES ('e1', 1, 'Pass', 10, 50, 40)")
    con.execute("INSERT INTO lineups (match_id, team_id, player_id) VALUES (1, 10, 1), (1, 20, 2)")
    return con


def _by_name(results):
    return {r.name: r for r in results}


def test_score_mismatch_is_detected():
    con = _db()  # official score 1-0 but no goal event
    res = _by_name(run_checks(con))
    assert not res["goals from events match official scores"].ok


def test_consistent_database_passes_goal_check():
    con = _db()
    con.execute("""INSERT INTO shots (event_id, match_id, period, team_id, is_goal, xg)
                   VALUES ('s1', 1, 1, 10, TRUE, 0.4)""")
    res = _by_name(run_checks(con))
    assert res["goals from events match official scores"].ok


def test_off_pitch_and_duplicate_ids_are_detected():
    con = _db()
    con.execute("INSERT INTO events (id, match_id, type, team_id, x, y) VALUES ('e1', 1, 'Pass', 10, 130, 40)")
    res = _by_name(run_checks(con))
    assert not res["event ids unique"].ok
    assert not res["coordinates inside the 120x80 pitch"].ok


def test_shootout_view_resolves_winner():
    con = _db()
    con.execute("""INSERT INTO shots (event_id, match_id, period, team_id, is_goal) VALUES
        ('p1', 1, 5, 10, TRUE), ('p2', 1, 5, 20, FALSE)""")
    row = con.execute("""SELECT shootout_for, shootout_against, shootout_result
                         FROM team_matches WHERE team_id = 10""").fetchone()
    assert row == (1, 0, "W")
