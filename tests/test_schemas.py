import numpy as np
import pytest
from pydantic import ValidationError

from matchagent.schemas import (
    DEFINITIONS,
    MAX_ROWS,
    MatchList,
    MatchStatsResult,
    MatchSummary,
    PassingStats,
    PressingStats,
    ShootingStats,
    TeamMatchStats,
)


def shooting(**overrides):
    return ShootingStats(**{"shots": 3, "goals": 2, "xg": 1.2, "npxg": 0.4, **overrides})


def passing(**overrides):
    return PassingStats(**{"passes": 6, "completed": 5, "completion_pct": 83.3, "progressive": 3, **overrides})


def match_summary(**overrides):
    return MatchSummary(**{"match_id": 1, "date": "2022-12-18", "home_team": "A", "away_team": "B",
                           "home_score": 1, "away_score": 0, **overrides})


def team_stats(team_id=1, team="A"):
    return TeamMatchStats(
        team_id=team_id, team=team, shooting=shooting(), passing=passing(),
        pressing=PressingStats(opp_passes=6, defensive_actions=3, ppda=2.0),
    )


def test_floats_are_rounded():
    s = shooting(xg=1.2000000000000002, npxg=0.3949999)
    assert s.xg == 1.2
    assert s.npxg == 0.39


def test_nan_becomes_null():
    p = passing(passes=0, completed=0, progressive=0, completion_pct=float("nan"))
    assert p.completion_pct is None
    assert '"completion_pct":null' in p.model_dump_json()


def test_numpy_values_from_pandas_are_accepted():
    s = shooting(shots=np.int64(3), goals=np.int64(2), xg=np.float64(1.2000000000000002))
    assert s.shots == 3 and s.xg == 1.2


@pytest.mark.parametrize("bad", [{"shots": -1}, {"xg": -0.1}, {"goals": 4}, {"npxg": 1.3}])
def test_impossible_shooting_values_are_rejected(bad):
    with pytest.raises(ValidationError):
        shooting(**bad)


@pytest.mark.parametrize("bad", [{"completed": 7}, {"progressive": 6}, {"completion_pct": 101}])
def test_impossible_passing_values_are_rejected(bad):
    with pytest.raises(ValidationError):
        passing(**bad)


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        shooting(shoots=3)             # typo for "shots"


def test_match_list_is_capped():
    too_many = [match_summary(match_id=i) for i in range(MAX_ROWS + 1)]
    with pytest.raises(ValidationError):
        MatchList(matches=too_many, total=len(too_many), truncated=False)


def test_a_match_result_needs_exactly_two_teams():
    with pytest.raises(ValidationError):
        MatchStatsResult(match=match_summary(), teams=[team_stats()], sources=[1])
    ok = MatchStatsResult(match=match_summary(), teams=[team_stats(1, "A"), team_stats(2, "B")], sources=[1])
    assert len(ok.teams) == 2


def test_field_descriptions_come_from_the_definitions():
    props = ShootingStats.model_json_schema()["properties"]
    assert props["xg"]["description"] == DEFINITIONS["xg"]
