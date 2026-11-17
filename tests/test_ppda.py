import duckdb
import pandas as pd
import pytest

from matchagent.metrics import team_ppda
from matchagent.schema import create_schema

# Zone de pressing = les 60 % du terrain les plus éloignés du but de l'équipe qui presse.
#   - actions défensives de l'équipe : x >= 48 (son propre repère)
#   - passes de l'adversaire         : x <= 72 (le repère de l'adversaire)

# passes : (event_id, match_id, période, team_id, x)
PASSES = [
    ("b1", 1, 1, 2, 50),    # B, dans la zone
    ("b2", 1, 1, 2, 72),    # B, pile sur la limite (<=) : compte
    ("b3", 1, 1, 2, 73),    # B, juste hors zone
    ("b4", 1, 1, 2, 100),   # B, loin hors zone
    ("b5", 1, 3, 2, 10),    # B, prolongation : compte
    ("b6", 1, 1, 2, 30),
    ("b7", 1, 1, 2, 30),
    ("b8", 1, 1, 2, 30),
    ("ap1", 1, 1, 1, 20),   # A, dans la zone
    ("ap2", 1, 1, 1, 90),   # A, hors zone
    ("c1", 2, 1, 3, 10),    # match 2 : une passe de C dans la zone
]

# événements : (id, match_id, période, type, team_id, x, duel_type)
EVENTS = [
    ("a1", 1, 1, "Interception", 1, 60, None),        # compte
    ("a2", 1, 1, "Duel", 1, 48, "Tackle"),            # compte (limite : >=)
    ("a3", 1, 1, "Foul Committed", 1, 50, None),      # compte
    ("a4", 1, 1, "Duel", 1, 80, "Aerial Lost"),       # pas un tacle : ne compte pas
    ("a5", 1, 1, "Interception", 1, 47, None),        # juste hors zone
    ("a6", 1, 1, "Pressure", 1, 90, None),            # pression : ne compte pas
    ("a8", 1, 5, "Interception", 1, 60, None),        # période 5 : ignorée
    ("e1", 1, 1, "Pressure", 2, 60, None),            # B ne fait que presser : 0 action
    ("m1", 2, 1, "Interception", 1, 60, None),        # match 2 : une action de A
]


@pytest.fixture
def con():
    con = duckdb.connect(":memory:")
    create_schema(con)
    con.execute("""INSERT INTO matches (match_id, home_team_id, home_team, away_team_id, away_team,
                   home_score, away_score) VALUES
                   (1, 1, 'A', 2, 'B', 1, 0),
                   (2, 1, 'A', 3, 'C', 0, 0)""")
    for event_id, match_id, period, team_id, x in PASSES:
        con.execute("INSERT INTO passes (event_id, match_id, period, team_id, x) VALUES (?, ?, ?, ?, ?)",
                    [event_id, match_id, period, team_id, x])
    for event_id, match_id, period, etype, team_id, x, duel_type in EVENTS:
        con.execute("""INSERT INTO events (id, match_id, period, type, team_id, x, duel_type)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [event_id, match_id, period, etype, team_id, x, duel_type])
    return con


def row(df, match_id, team_id):
    return df[(df.match_id == match_id) & (df.team_id == team_id)].iloc[0]


def test_one_row_per_team_per_match(con):
    assert len(team_ppda(con)) == 4


def test_opponent_passes_counted_only_inside_the_zone(con):
    # passes de B dans la zone : b1, b2 (limite), b5 (prolongation), b6, b7, b8 = 6
    # exclues : b3 (73) et b4 (100). Un join mal fait multiplierait ce nombre.
    assert row(team_ppda(con), 1, 1).opp_passes == 6


def test_only_tackles_interceptions_and_fouls_count(con):
    # a1, a2 (limite), a3 = 3 ; exclus : a4 (duel aérien), a5 (x=47), a6 (pression), a8 (période 5)
    assert row(team_ppda(con), 1, 1).defensive_actions == 3


def test_ppda_value(con):
    df = team_ppda(con)
    assert row(df, 1, 1).ppda == pytest.approx(2.0)    # 6 passes / 3 actions
    assert row(df, 2, 1).ppda == pytest.approx(1.0)    # 1 passe / 1 action


def test_no_defensive_action_gives_undefined_ppda(con):
    r = row(team_ppda(con), 1, 2)                      # B : 1 passe de A dans la zone, 0 action
    assert r.opp_passes == 1
    assert r.defensive_actions == 0
    assert pd.isna(r.ppda)                             # indéfini, pas infini


def test_filters(con):
    assert len(team_ppda(con, match_id=2)) == 2
    assert len(team_ppda(con, team_id=1)) == 2
    assert len(team_ppda(con, match_id=2, team_id=1)) == 1
