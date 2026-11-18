import duckdb
import pytest

from matchagent.entities import EntityResolver
from matchagent.schema import create_schema
from matchagent.schemas import DEFINITIONS, MatchList, MatchStatsResult, ToolError
from matchagent.tools import Deps, explain_metric, find_matches, match_stats, resolve_entity
from matchagent.transform import normalize_name

TEAMS = [(1, "Alpha"), (2, "Bravo"), (3, "Charlie")]

# matches : (match_id, date, stage, home id, home, away id, away, home score, away score)
MATCHES = [
    (1, "2022-11-20", "Group Stage", 1, "Alpha", 2, "Bravo", 1, 0),
    (2, "2022-12-18", "Final", 1, "Alpha", 3, "Charlie", 1, 1),   # Alpha wins the shootout 2-1
]

# tirs : (event_id, match_id, période, team_id, but ?, xG, type)
SHOTS = [
    ("s1", 1, 1, 1, True, 0.30, "Open Play"),
    ("s2", 1, 2, 1, False, 0.10, "Open Play"),
    ("s3", 1, 1, 2, False, 0.20, "Open Play"),
    ("s4", 2, 1, 1, True, 0.50, "Open Play"),
    ("s5", 2, 2, 3, True, 0.40, "Open Play"),
    ("s6", 2, 5, 1, True, 0.78, "Penalty"),     # tirs au but
    ("s7", 2, 5, 1, True, 0.78, "Penalty"),
    ("s8", 2, 5, 3, True, 0.78, "Penalty"),
    ("s9", 2, 5, 3, False, 0.78, "Penalty"),
]

# passes : (event_id, match_id, période, team_id, x, y, end_x, end_y, réussie ?)
PASSES = [
    ("pa1", 1, 1, 1, 60, 40, 90, 40, True),     # progressive
    ("pa2", 1, 1, 1, 60, 40, 61, 40, True),
    ("pa3", 1, 1, 1, 60, 40, 61, 40, False),
    ("pb1", 1, 2, 2, 20, 40, 22, 40, True),
    ("pb2", 1, 2, 2, 50, 40, 52, 40, True),
]

# événements : (id, match_id, période, type, team_id, x, duel_type)
EVENTS = [
    ("ev1", 1, 1, "Interception", 1, 60, None),
    ("ev2", 1, 1, "Duel", 1, 50, "Tackle"),
]


@pytest.fixture
def deps():
    con = duckdb.connect(":memory:")
    create_schema(con)
    for team_id, name in TEAMS:
        con.execute("INSERT INTO teams VALUES (?, ?, ?)", [team_id, name, normalize_name(name)])
    for m in MATCHES:
        con.execute("""INSERT INTO matches (match_id, match_date, stage, home_team_id, home_team,
                       away_team_id, away_team, home_score, away_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", list(m))
    for s in SHOTS:
        con.execute("""INSERT INTO shots (event_id, match_id, period, team_id, is_goal, xg, shot_type)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""", list(s))
    for p in PASSES:
        con.execute("""INSERT INTO passes (event_id, match_id, period, team_id, x, y, end_x, end_y, complete)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", list(p))
    for e in EVENTS:
        con.execute("""INSERT INTO events (id, match_id, period, type, team_id, x, duel_type)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""", list(e))
    return Deps(con=con, resolver=EntityResolver(con))


def team(result, name):
    return next(t for t in result.teams if t.team == name)


# --- explain_metric ---------------------------------------------------------

def test_explain_metric_returns_the_definition(deps):
    result = explain_metric(" PPDA ")                 # espaces et majuscules tolérés
    assert result.name == "ppda"
    assert result.definition == DEFINITIONS["ppda"]


def test_explain_unknown_metric_lists_the_available_ones(deps):
    result = explain_metric("foo")
    assert isinstance(result, ToolError)
    assert result.error == "invalid_argument"
    assert "xg" in result.hint


# --- resolve_entity ---------------------------------------------------------

def test_resolve_entity_uses_the_resolver(deps):
    result = resolve_entity(deps, "alpha", "team")
    assert result.status == "resolved"
    assert result.candidates[0].entity_id == 1


# --- find_matches -----------------------------------------------------------

def test_find_matches_for_a_team_oldest_first(deps):
    result = find_matches(deps, team_id=1)
    assert isinstance(result, MatchList)
    assert [m.match_id for m in result.matches] == [1, 2]
    assert result.total == 2 and result.truncated is False


def test_shootout_winner_is_reported(deps):
    final = find_matches(deps, stage="final").matches[0]      # casse ignorée
    assert (final.home_score, final.away_score) == (1, 1)
    assert final.shootout_winner == "Alpha"


def test_match_without_shootout_has_no_winner(deps):
    assert find_matches(deps, stage="Group Stage").matches[0].shootout_winner is None


def test_find_matches_unknown_stage_lists_stages(deps):
    result = find_matches(deps, stage="Semis")
    assert isinstance(result, ToolError) and result.error == "invalid_argument"
    assert "Group Stage" in result.hint and "Final" in result.hint


def test_find_matches_unknown_team(deps):
    result = find_matches(deps, team_id=99)
    assert isinstance(result, ToolError) and result.error == "not_found"
    assert "resolve_entity" in result.hint


def test_valid_filters_without_match_give_an_empty_list(deps):
    result = find_matches(deps, team_id=3, stage="Group Stage")   # Charlie n'a joué que la finale
    assert isinstance(result, MatchList)
    assert result.matches == [] and result.total == 0 and result.truncated is False


def test_find_matches_reports_truncation(deps):
    result = find_matches(deps, limit=1)
    assert len(result.matches) == 1
    assert result.total == 2
    assert result.truncated is True


def test_limit_is_clamped(deps):
    assert len(find_matches(deps, limit=0).matches) == 1      # au moins une ligne
    assert len(find_matches(deps, limit=-5).matches) == 1


# --- match_stats ------------------------------------------------------------

def test_match_stats_values(deps):
    result = match_stats(deps, 1)
    assert isinstance(result, MatchStatsResult)
    assert result.sources == [1]
    a, b = team(result, "Alpha"), team(result, "Bravo")

    assert (a.shooting.shots, a.shooting.goals, a.shooting.xg, a.shooting.npxg) == (2, 1, 0.4, 0.4)
    assert (a.passing.passes, a.passing.completed, a.passing.completion_pct, a.passing.progressive) == (3, 2, 66.7, 1)
    assert (a.pressing.opp_passes, a.pressing.defensive_actions, a.pressing.ppda) == (2, 2, 1.0)

    assert (b.shooting.shots, b.shooting.xg) == (1, 0.2)
    assert (b.passing.passes, b.passing.completion_pct, b.passing.progressive) == (2, 100.0, 0)
    assert (b.pressing.opp_passes, b.pressing.defensive_actions) == (3, 0)
    assert b.pressing.ppda is None                       # indéfini, pas 0 ni infini


def test_match_stats_excludes_the_shootout_and_handles_missing_data(deps):
    result = match_stats(deps, 2)
    a = team(result, "Alpha")
    assert a.shooting.shots == 1 and a.shooting.xg == 0.5     # les tirs au but ne comptent pas
    assert a.passing.passes == 0 and a.passing.completion_pct is None
    assert result.match.shootout_winner == "Alpha"


def test_match_stats_unknown_match(deps):
    result = match_stats(deps, 999)
    assert isinstance(result, ToolError) and result.error == "not_found"
    assert "find_matches" in result.hint


def test_match_stats_is_json_serialisable(deps):
    text = match_stats(deps, 1).model_dump_json()
    assert "NaN" not in text and "Infinity" not in text
