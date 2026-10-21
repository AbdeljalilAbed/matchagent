from matchagent.transform import events_frames, lineups_frames, matches_frame, normalize_name


def _event(etype, **extra):
    base = {
        "id": f"id-{etype}", "index": 1, "period": 1, "minute": 3, "second": 4,
        "type": {"name": etype}, "possession": 1,
        "possession_team": {"id": 10, "name": "A"}, "play_pattern": {"name": "Regular Play"},
        "team": {"id": 10, "name": "A"}, "player": {"id": 7, "name": "P One"},
        "position": {"name": "Center Forward"}, "location": [60.0, 40.0], "duration": 1.0,
    }
    return {**base, **extra}


def test_normalize_name_strips_accents_and_special_letters():
    assert normalize_name("Aïssa Højbjerg") == "aissa hojbjerg"
    assert normalize_name("Pierre-Emile  Højbjerg") == "pierre emile hojbjerg"
    assert normalize_name(None) == ""


def test_pass_without_outcome_is_complete():
    ok = _event("Pass", **{"pass": {"length": 5.0, "end_location": [65.0, 40.0]}})
    bad = _event("Pass", id="id-bad", **{"pass": {"outcome": {"name": "Incomplete"}, "end_location": [70, 40]}})
    f = events_frames(1, [ok, bad])
    assert f["passes"]["complete"].tolist() == [True, False]
    assert f["events"]["outcome"].tolist() == ["Complete", "Incomplete"]
    assert f["passes"]["end_x"].tolist() == [65.0, 70]


def test_shot_goal_flag_and_xg():
    shot = _event("Shot", shot={"statsbomb_xg": 0.3, "outcome": {"name": "Goal"},
                                "end_location": [120.0, 40.0, 1.2], "type": {"name": "Penalty"}})
    f = events_frames(1, [shot])
    row = f["shots"].iloc[0]
    assert row["is_goal"] and row["xg"] == 0.3 and row["end_z"] == 1.2 and row["shot_type"] == "Penalty"


def test_carry_distance_is_euclidean():
    carry = _event("Carry", location=[10.0, 10.0], carry={"end_location": [13.0, 14.0]})
    assert events_frames(1, [carry])["carries"].iloc[0]["distance"] == 5.0


def test_event_without_location_and_card_and_duel_type():
    start = _event("Half Start", location=None)
    start.pop("location")
    foul = _event("Foul Committed", foul_committed={"card": {"name": "Yellow Card"}})
    duel = _event("Duel", duel={"type": {"name": "Tackle"}, "outcome": {"name": "Won"}})
    ev = events_frames(1, [start, foul, duel])["events"]
    assert ev["x"].isna().tolist() == [True, False, False]
    assert ev["card"].isna().tolist() == [True, False, True]
    assert ev["card"].iloc[1] == "Yellow Card"
    assert ev["duel_type"].isna().tolist() == [True, True, False]
    assert ev["duel_type"].iloc[2] == "Tackle"
    assert ev["outcome"].tolist()[2] == "Won"


def test_matches_and_lineups_frames():
    raw = [{"match_id": 5, "match_date": "2022-12-18", "home_score": 3, "away_score": 3,
            "competition": {"competition_id": 43}, "season": {"season_id": 106},
            "home_team": {"home_team_id": 1, "home_team_name": "Argentina"},
            "away_team": {"away_team_id": 2, "away_team_name": "France"},
            "competition_stage": {"name": "Final"}}]
    m = matches_frame(raw).iloc[0]
    assert (m["home_team"], m["away_team"], m["stage"]) == ("Argentina", "France", "Final")

    lineups = [{"team_id": 1, "lineup": [
        {"player_id": 9, "player_name": "X", "jersey_number": 9,
         "positions": [{"start_reason": "Starting XI"}]},
        {"player_id": 12, "player_name": "Y", "jersey_number": 12, "positions": []}]}]
    players, lineup = lineups_frames(5, lineups)
    assert lineup["started"].tolist() == [True, False]
    assert lineup["played"].tolist() == [True, False]
    assert players["player_id"].tolist() == [9, 12]
