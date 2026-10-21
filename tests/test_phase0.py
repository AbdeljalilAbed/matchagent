import pandas as pd

from matchagent import coverage, sb_api
from matchagent.scope import Slice, validate_scope


class FakeResponse:
    text = '{"a": 1}'

    def raise_for_status(self):
        pass

    def json(self):
        return {"a": 1}


def test_fetch_json_downloads_once_then_uses_cache(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse()

    monkeypatch.setattr(sb_api.httpx, "get", fake_get)
    assert sb_api.fetch_json("x/y.json", cache_dir=tmp_path) == {"a": 1}
    assert sb_api.fetch_json("x/y.json", cache_dir=tmp_path) == {"a": 1}
    assert len(calls) == 1
    assert (tmp_path / "x" / "y.json").exists()


def test_slice_report_counts_home_and_away(monkeypatch):
    matches = pd.DataFrame(
        {
            "home_team.home_team_name": ["A", "A", "B"],
            "away_team.away_team_name": ["B", "C", "C"],
        }
    )
    monkeypatch.setattr(coverage, "load_matches", lambda c, s: matches)
    result = coverage.slice_report(1, 1).set_index("team")["n_matches"].to_dict()
    assert result == {"A": 2, "B": 2, "C": 2}


def test_validate_scope_detects_unknown_slice():
    comps = pd.DataFrame({"competition_id": [43], "season_id": [106]})
    ok = Slice("wc", 43, 106, "primary")
    bad = Slice("nope", 1, 1, "primary")
    assert validate_scope([ok], comps) == []
    assert validate_scope([bad], comps) == ["nope: (1, 1) not in open data"]
