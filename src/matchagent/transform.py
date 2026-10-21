"""Pure functions turning raw StatsBomb JSON into flat DataFrames (no I/O, easy to test)."""
from __future__ import annotations

import math
import re
import unicodedata

import pandas as pd

_SPECIAL = str.maketrans({"ø": "o", "đ": "d", "ł": "l", "ß": "ss", "æ": "ae", "œ": "oe"})

# event type -> key of the JSON sub-dictionary holding its specific fields
_SUBKEY = {
    "Pass": "pass", "Shot": "shot", "Carry": "carry", "Duel": "duel", "Dribble": "dribble",
    "Interception": "interception", "Ball Receipt*": "ball_receipt", "50/50": "50_50",
    "Goal Keeper": "goalkeeper", "Substitution": "substitution",
    "Foul Committed": "foul_committed", "Bad Behaviour": "bad_behaviour",
}


def normalize_name(text: str | None) -> str:
    """'Aïssa Højbjerg' -> 'aissa hojbjerg': lowercase, no accents, single spaces.

    Used by the entity resolver (Phase 2) to match user spellings with data names.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text.lower().translate(_SPECIAL))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _get(d, *path, default=None):
    """Safe nested lookup: _get(e, 'pass', 'height', 'name')."""
    for key in path:
        if not isinstance(d, dict):
            return default
        d = d.get(key)
        if d is None:
            return default
    return d


def _xy(location, i):
    return location[i] if location and len(location) > i else None


def matches_frame(raw_matches: list[dict]) -> pd.DataFrame:
    rows = [
        {
            "match_id": m["match_id"],
            "competition_id": _get(m, "competition", "competition_id"),
            "season_id": _get(m, "season", "season_id"),
            "competition_name": _get(m, "competition", "competition_name"),
            "season_name": _get(m, "season", "season_name"),
            "match_date": m["match_date"],
            "kick_off": m.get("kick_off"),
            "stage": _get(m, "competition_stage", "name"),
            "match_week": m.get("match_week"),
            "home_team_id": _get(m, "home_team", "home_team_id"),
            "home_team": _get(m, "home_team", "home_team_name"),
            "away_team_id": _get(m, "away_team", "away_team_id"),
            "away_team": _get(m, "away_team", "away_team_name"),
            "home_score": m.get("home_score"),
            "away_score": m.get("away_score"),
            "stadium": _get(m, "stadium", "name"),
            "referee": _get(m, "referee", "name"),
        }
        for m in raw_matches
    ]
    return pd.DataFrame(rows)


def lineups_frames(match_id: int, raw_lineups: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (players, lineups) rows for one match."""
    players, lineup = [], []
    for team in raw_lineups:
        for p in team["lineup"]:
            positions = p.get("positions") or []
            players.append(
                {
                    "player_id": p["player_id"],
                    "player_name": p["player_name"],
                    "player_nickname": p.get("player_nickname"),
                }
            )
            lineup.append(
                {
                    "match_id": match_id,
                    "team_id": team["team_id"],
                    "player_id": p["player_id"],
                    "jersey_number": p.get("jersey_number"),
                    "country": _get(p, "country", "name"),
                    "started": any(pos.get("start_reason") == "Starting XI" for pos in positions),
                    "played": bool(positions),
                }
            )
    return pd.DataFrame(players), pd.DataFrame(lineup)


def events_frames(match_id: int, raw_events: list[dict]) -> dict[str, pd.DataFrame]:
    """Split one match's events into events / passes / shots / carries tables."""
    events, passes, shots, carries = [], [], [], []
    for e in raw_events:
        etype = e["type"]["name"]
        sub = e.get(_SUBKEY.get(etype, ""), {}) or {}
        loc = e.get("location")
        x, y = _xy(loc, 0), _xy(loc, 1)
        common = {
            "event_id": e["id"], "match_id": match_id, "period": e["period"],
            "minute": e["minute"], "second": e["second"],
            "team_id": _get(e, "team", "id"), "team": _get(e, "team", "name"),
            "player_id": _get(e, "player", "id"), "player": _get(e, "player", "name"),
            "x": x, "y": y,
        }

        if etype == "Pass":
            outcome = _get(sub, "outcome", "name")
            passes.append({
                **common,
                "recipient_id": _get(sub, "recipient", "id"),
                "recipient": _get(sub, "recipient", "name"),
                "length": sub.get("length"), "angle": sub.get("angle"),
                "height": _get(sub, "height", "name"),
                "end_x": _xy(sub.get("end_location"), 0), "end_y": _xy(sub.get("end_location"), 1),
                "pass_type": _get(sub, "type", "name"), "body_part": _get(sub, "body_part", "name"),
                "outcome": outcome, "complete": outcome is None,  # no outcome = completed pass
                "is_cross": bool(sub.get("cross")), "is_switch": bool(sub.get("switch")),
                "is_through_ball": bool(sub.get("through_ball")),
                "is_cut_back": bool(sub.get("cut_back")),
                "is_shot_assist": bool(sub.get("shot_assist")),
                "is_goal_assist": bool(sub.get("goal_assist")),
            })
            event_outcome = outcome or "Complete"
        elif etype == "Shot":
            outcome = _get(sub, "outcome", "name")
            end = sub.get("end_location")
            shots.append({
                **common,
                "end_x": _xy(end, 0), "end_y": _xy(end, 1), "end_z": _xy(end, 2),
                "xg": sub.get("statsbomb_xg"), "outcome": outcome, "is_goal": outcome == "Goal",
                "shot_type": _get(sub, "type", "name"), "body_part": _get(sub, "body_part", "name"),
                "technique": _get(sub, "technique", "name"),
                "first_time": bool(sub.get("first_time")), "key_pass_id": sub.get("key_pass_id"),
            })
            event_outcome = outcome
        elif etype == "Carry":
            end = sub.get("end_location")
            ex, ey = _xy(end, 0), _xy(end, 1)
            dist = math.hypot(ex - x, ey - y) if None not in (x, y, ex, ey) else None
            carries.append({**common, "end_x": ex, "end_y": ey, "distance": dist})
            event_outcome = None
        else:
            event_outcome = _get(sub, "outcome", "name")

        events.append({
            "id": e["id"], "match_id": match_id, "event_index": e["index"],
            "period": e["period"], "minute": e["minute"], "second": e["second"], "type": etype,
            "team_id": common["team_id"], "team": common["team"],
            "player_id": common["player_id"], "player": common["player"],
            "position": _get(e, "position", "name"),
            "possession": e.get("possession"),
            "possession_team_id": _get(e, "possession_team", "id"),
            "possession_team": _get(e, "possession_team", "name"),
            "play_pattern": _get(e, "play_pattern", "name"),
            "x": x, "y": y, "duration": e.get("duration"),
            "under_pressure": bool(e.get("under_pressure")),
            "counterpress": bool(e.get("counterpress")),
            "outcome": event_outcome,
            "card": _get(sub, "card", "name") if etype in ("Foul Committed", "Bad Behaviour") else None,
            "duel_type": _get(sub, "type", "name") if etype == "Duel" else None,
        })
    return {
        "events": pd.DataFrame(events), "passes": pd.DataFrame(passes),
        "shots": pd.DataFrame(shots), "carries": pd.DataFrame(carries),
    }
