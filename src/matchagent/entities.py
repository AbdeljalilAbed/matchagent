from __future__ import annotations

from typing import Literal

import duckdb
from pydantic import BaseModel
from rapidfuzz import fuzz

from matchagent.transform import normalize_name

TOKEN_MATCH_MIN = 85  # un mot de la requête doit ressembler à un mot du nom à au moins 85 %
EXACT_BONUS = 10  # une correspondance exacte du nom complet passe devant une correspondance partielle
AMBIGUITY_MARGIN = 3  # les candidats à moins de 3 points du meilleur sont "à égalité"

TEAM_ALIASES = {
    "usa": "united states", "us": "united states", "usmnt": "united states",
    "holland": "netherlands", "korea": "south korea", "korea republic": "south korea",
    "ir iran": "iran", "ksa": "saudi arabia",
}

def name_score(query_tokens: list[str], name_tokens: list[str]) -> float:
    """0 si un mot de la requête ne correspond à rien, sinon la similarité moyenne (0-100)."""
    if not query_tokens or not name_tokens:
        return 0.0
    best = [max(fuzz.ratio(q, n) for n in name_tokens) for q in query_tokens]
    if min(best) < TOKEN_MATCH_MIN:
        return 0.0
    return sum(best) / len(best)

class Candidate(BaseModel):
    entity_id: int
    name: str
    score: float
    context: str = ""  # pour un joueur : son équipe, afin de distinguer les homonymes


class Resolution(BaseModel):
    query: str
    kind: Literal["team", "player"]
    status: Literal["resolved", "ambiguous", "not_found"]
    candidates: list[Candidate]
    total_matches: int = 0  # nombre de candidats à égalité, même si la liste est tronquée

class EntityResolver:
    def __init__(self, con: duckdb.DuckDBPyConnection):
        self._entities: dict[str, list[dict]] = {"team": [], "player": []}

        for team_id, name, norm in con.execute(
            "SELECT team_id, team_name, name_norm FROM teams"
        ).fetchall():
            self._entities["team"].append(
                {"id": team_id, "name": name, "forms": [norm], "context": ""}
            )

        teams_of: dict[int, list[str]] = {}
        for player_id, team in con.execute(
            "SELECT DISTINCT l.player_id, t.team_name FROM lineups l JOIN teams t USING (team_id)"
        ).fetchall():
            teams_of.setdefault(player_id, []).append(team)

        for player_id, name, nick, norm in con.execute(
            "SELECT player_id, player_name, player_nickname, name_norm FROM players"
        ).fetchall():
            forms = [norm] + ([normalize_name(nick)] if nick else [])
            self._entities["player"].append(
                {"id": player_id, "name": name, "forms": forms,
                 "context": ", ".join(sorted(teams_of.get(player_id, [])))}
            )
    def _rank(self, query: str, kind: str) -> list[tuple[float, dict]]:
        q = normalize_name(query)
        if kind == "team":
            q = TEAM_ALIASES.get(q, q)
        q_tokens = q.split()

        ranked = []
        for entity in self._entities[kind]:
            best = 0.0
            for form in entity["forms"]:
                score = name_score(q_tokens, form.split())
                if score and form == q:
                    score += EXACT_BONUS
                best = max(best, score)
            if best:
                ranked.append((best, entity))
        ranked.sort(key=lambda s: (-s[0], len(s[1]["name"])))
        return ranked

    def resolve(
        self, query: str, kind: Literal["team", "player"], max_candidates: int = 5
    ) -> Resolution:
        ranked = self._rank(query, kind)
        if not ranked:
            return Resolution(query=query, kind=kind, status="not_found", candidates=[])

        best_score = ranked[0][0]
        tied = [(s, e) for s, e in ranked if best_score - s <= AMBIGUITY_MARGIN]
        return Resolution(
            query=query,
            kind=kind,
            status="resolved" if len(tied) == 1 else "ambiguous",
            candidates=[
                Candidate(
                    entity_id=e["id"], name=e["name"],
                    score=round(min(s, 100.0), 1), context=e["context"],
                )
                for s, e in tied[:max_candidates]
            ],
            total_matches=len(tied),
        )