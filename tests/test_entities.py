import duckdb
import pytest

from matchagent.entities import AMBIGUITY_MARGIN, EXACT_BONUS, EntityResolver, name_score
from matchagent.schema import create_schema
from matchagent.transform import normalize_name

TEAMS = [(1, "Argentina"), (2, "United States"), (3, "Portugal"), (4, "Brazil")]
PLAYERS = [  # (player_id, nom, surnom, team_id)
    (10, "Lionel Andrés Messi Cuccittini", "Lionel Messi", 1),
    (11, "Cristian Gabriel Romero", None, 1),
    (12, "Cristian Roldán León", None, 2),
    (13, "Bernardo Mota Veiga de Carvalho e Silva", "Bernardo Silva", 3),
    (14, "Danilo Luiz da Silva", "Danilo", 4),
    (15, "Thiago Emiliano da Silva", None, 4),
    (16, "Christian Pulisic", None, 2),
    (17, "Danilo Pereira", None, 3),
]


@pytest.fixture
def resolver():
    con = duckdb.connect(":memory:")
    create_schema(con)
    for team_id, name in TEAMS:
        con.execute("INSERT INTO teams VALUES (?, ?, ?)", [team_id, name, normalize_name(name)])
    for player_id, name, nick, team_id in PLAYERS:
        con.execute("INSERT INTO players VALUES (?, ?, ?, ?)",
                    [player_id, name, nick, normalize_name(name)])
        con.execute("INSERT INTO lineups (match_id, team_id, player_id) VALUES (1, ?, ?)",
                    [team_id, player_id])
    return EntityResolver(con)

def test_one_unmatched_word_rejects_the_candidate():
    assert name_score(["lionel", "ronaldo"], ["cristiano", "ronaldo"]) == 0.0

def test_exact_bonus_stays_above_margin():
    assert EXACT_BONUS > AMBIGUITY_MARGIN

def test_resolves_by_partial_name(resolver):
    res = resolver.resolve("Messi", "player")
    assert res.status == "resolved"
    assert res.candidates[0].entity_id == 10

def test_tolerates_a_typo(resolver):
    res = resolver.resolve("Mesi", "player")
    assert res.status == "resolved"
    assert res.candidates[0].entity_id == 10

def test_homonyms_are_ambiguous_with_context(resolver):
    res = resolver.resolve("Silva", "player")
    assert res.status == "ambiguous"
    assert res.total_matches == 3
    assert {c.context for c in res.candidates} == {"Brazil", "Portugal"}

def test_margin_excludes_near_misses(resolver):
    res = resolver.resolve("Cristian", "player")
    assert res.status == "ambiguous"
    assert res.total_matches == 2
    assert 16 not in {c.entity_id for c in res.candidates}

def test_exact_form_beats_partial_match(resolver):
    res = resolver.resolve("Danilo", "player")
    assert res.status == "resolved"
    assert res.total_matches == 1
    assert res.candidates[0].entity_id == 14

def test_truncation_is_reported(resolver):
    res = resolver.resolve("Silva", "player",max_candidates=2)
    assert res.status == "ambiguous"
    assert res.total_matches == 3

def test_unknown_name_is_not_found(resolver):
    res = resolver.resolve("Zzzz", "player")
    assert res.status == "not_found"
    assert res.candidates == [] 

def test_team_alias(resolver):
    res = resolver.resolve("USA", "team")
    assert res.status == "resolved"
    assert res.candidates[0].name == "United States"



