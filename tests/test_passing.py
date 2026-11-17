import duckdb
import pandas as pd
import pytest

from matchagent.metrics import team_passing
from matchagent.schema import create_schema

# passes : (event_id, match_id, période, team_id, x, y, end_x, end_y, réussie ?)
# Le but adverse est en (120, 40). Passe progressive = réussie ET gain >= 25 % de d_start.
PASSES = [
    ("p1", 1, 1, 1, 60, 40, 90, 40, True),     # 60 -> 30, gain 30 >= 15          : progressive
    ("p2", 1, 1, 1, 60, 40, 65, 40, True),     # 60 -> 55, gain 5 < 15            : non
    ("p3", 1, 1, 1, 60, 40, 90, 40, False),    # longue mais ratée                : non
    ("p4", 1, 2, 1, 60, 40, 40, 40, True),     # en arrière, gain négatif         : non
    ("p5", 1, 2, 1, 80, 40, 90, 40, True),     # 40 -> 30, gain 10 == 0.25 * 40   : progressive (limite)
    ("p6", 1, 3, 1, 100, 20, 110, 40, True),   # diagonale, prolongation, 28.3 -> 10 : progressive
    ("p7", 1, 5, 1, 60, 40, 90, 40, True),     # période 5 : ignorée
    ("p8", 2, 1, 1, 60, 40, 61, 40, True),     # match 2 : une passe réussie de A
    ("p9", 2, 1, 3, 60, 40, 61, 40, False),    # match 2 : une passe ratée de C
]


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    create_schema(con)
    con.execute("""INSERT INTO matches (match_id, home_team_id, home_team, away_team_id, away_team,
                   home_score, away_score) VALUES
                   (1, 1, 'A', 2, 'B', 1, 0),
                   (2, 1, 'A', 3, 'C', 0, 0)""")
    for event_id, match_id, period, team_id, x, y, end_x, end_y, complete in PASSES:
        con.execute("""INSERT INTO passes (event_id, match_id, period, team_id, x, y, end_x, end_y, complete)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [event_id, match_id, period, team_id, x, y, end_x, end_y, complete])
    return con


def row(df, match_id, team_id):
    return df[(df.match_id == match_id) & (df.team_id == team_id)].iloc[0]


def test_one_row_per_team_per_match(con):
    assert len(team_passing(con)) == 4


def test_counts_attempted_and_completed(con):
    r = row(team_passing(con), 1, 1)
    assert r.passes == 6        # p1 à p6 ; p7 (période 5) est ignorée
    assert r.completed == 5     # toutes sauf p3


def test_completion_rate(con):
    assert row(team_passing(con), 1, 1).completion_rate == pytest.approx(5 / 6)


def test_team_without_passes(con):
    r = row(team_passing(con), 1, 2)
    assert r.passes == 0
    assert r.completed == 0
    assert r.progressive == 0
    assert pd.isna(r.completion_rate)   # indéfini, pas 0 %


def test_progressive_passes(con):
    # p1 + p5 (cas limite, >=) + p6 (diagonale). Pas p2 (courte), p3 (ratée), p4 (en arrière).
    assert row(team_passing(con), 1, 1).progressive == 3


def test_only_periods_1_to_4_count(con):
    r = row(team_passing(con), 1, 1)
    assert r.passes == 6        # p6 (période 3) compte, p7 (période 5) non


def test_filters(con):
    assert len(team_passing(con, match_id=2)) == 2              # A et C
    assert len(team_passing(con, team_id=1)) == 2               # A dans les deux matchs
    assert len(team_passing(con, match_id=2, team_id=1)) == 1   # A, match 2
