import duckdb
import pytest

from matchagent.metrics import team_shooting
from matchagent.schema import create_schema

# shots: (event_id, match_id, period, team_id, is_goal, xg, shot_type)
SHOTS = [
    ("s1", 1, 1, 1, False, 0.10, "Open Play"),
    ("s2", 1, 1, 1, True, 0.80, "Penalty"),
    ("s3", 1, 2, 1, True, 0.30, "Open Play"),
    ("s4", 2, 1, 1, False, 0.20, "Open Play"),
    ("s5", 2, 2, 3, True, 0.50, "Open Play"),
    ("s6", 2, 3, 3, False, 0.10, "Open Play"),   # extra time
    ("s7", 2, 5, 1, True, 0.78, "Penalty"),      # shootout
    ("s8", 2, 5, 3, False, 0.78, "Penalty"),     # shootout
]


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    create_schema(con)
    con.execute("""INSERT INTO matches (match_id, home_team_id, home_team, away_team_id, away_team,
                   home_score, away_score) VALUES
                   (1, 1, 'A', 2, 'B', 2, 0),
                   (2, 1, 'A', 3, 'C', 1, 1)""")
    for event_id, match_id, period, team_id, is_goal, xg, shot_type in SHOTS:
        con.execute("""INSERT INTO shots (event_id, match_id, period, team_id, is_goal, xg, shot_type)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [event_id, match_id, period, team_id, is_goal, xg, shot_type])
    return con


def row(df, match_id, team_id):
    return df[(df.match_id == match_id) & (df.team_id == team_id)].iloc[0]


def test_one_row_per_team_per_match(con):
    assert len(team_shooting(con)) == 4


def test_team_without_shots_gets_zeros(con):
    r = row(team_shooting(con), 1, 2)
    assert r.shots == 0
    assert r.goals == 0
    assert r.xg == 0      # 0, not NaN
    assert r.npxg == 0


def test_shootout_is_excluded(con):
    df = team_shooting(con)
    r = row(df, 2, 1)
    assert r.shots == 1                         # s7 (period 5) is not counted
    assert r.xg == pytest.approx(0.20)          # 0.98 if the shootout leaked in
    assert df.xg.sum() == pytest.approx(2.0)    # 3.56 if the shootout leaked in


def test_extra_time_shots_count(con):
    r = row(team_shooting(con), 2, 3)
    assert r.shots == 2                         # s5 (period 2) + s6 (period 3)


def test_npxg_excludes_penalties(con):
    r = row(team_shooting(con), 1, 1)
    assert r.goals == 2                         # s2 (penalty) + s3
    assert r.xg == pytest.approx(1.2)           # 0.10 + 0.80 + 0.30
    assert r.npxg == pytest.approx(0.4)         # without the 0.80 penalty


def test_filters(con):
    assert len(team_shooting(con, match_id=2)) == 2              # A and C
    assert len(team_shooting(con, team_id=1)) == 2               # A in both matches
    assert len(team_shooting(con, match_id=2, team_id=1)) == 1   # A, match 2