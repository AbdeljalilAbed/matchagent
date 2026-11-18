"""Typed results of the agent's tools: what the LLM receives (as JSON)."""
from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

MAX_ROWS = 20  # no tool ever returns more than this many rows to the LLM

# Single source of truth for the definitions of the metrics. It feeds the field
# descriptions below, and later the explain_metric tool and the agent's prompt.
DEFINITIONS = {
    "score": "Goals after regulation and extra time; the penalty shootout is not included.",
    "shots": "Shots taken in periods 1-4 (the penalty shootout is excluded).",
    "goals": "Shots that scored in periods 1-4 (own goals are not shots, so not counted).",
    "xg": "Sum of the StatsBomb expected goals of the shots (periods 1-4, shootout excluded).",
    "npxg": "Same as xg, without penalties.",
    "passes": "Passes attempted in periods 1-4.",
    "completed": "Passes with no outcome (StatsBomb: no outcome = completed).",
    "completion_pct": "completed / passes, in percent; null if the team made no pass.",
    "progressive": (
        "Completed passes that reduce the distance to the opponent's goal "
        "by at least 25 % of the starting distance."
    ),
    "opp_passes": "Passes made by the opponent inside the pressing zone (its own 60 % of the pitch).",
    "defensive_actions": (
        "Tackles, interceptions and fouls committed by the team inside the pressing zone "
        "(the 60 % of the pitch farthest from its own goal); pressures are not counted."
    ),
    "ppda": "opp_passes / defensive_actions; null if no defensive action. Lower = more intense pressing.",
}


def _nan_to_none(value):
    """pandas gives NaN for a missing value; JSON has no NaN, so use None (null)."""
    return None if isinstance(value, float) and math.isnan(value) else value


def _rounded(digits: int):
    def rounder(value):
        return None if value is None else round(value, digits)

    return rounder


# Reusable constrained types: the constraint and the rounding live in one place.
Count = Annotated[int, Field(ge=0)]
Xg = Annotated[float, Field(ge=0), AfterValidator(_rounded(2))]
Pct = Annotated[
    Annotated[float, Field(ge=0, le=100), AfterValidator(_rounded(1))] | None,
    BeforeValidator(_nan_to_none),
]
Ppda = Annotated[
    Annotated[float, Field(ge=0), AfterValidator(_rounded(2))] | None,
    BeforeValidator(_nan_to_none),
]


class Strict(BaseModel):
    """Base class: an unknown field is an error, not silently ignored."""

    model_config = ConfigDict(extra="forbid")


class MatchSummary(Strict):
    match_id: int = Field(description="StatsBomb match id, to pass to the other tools.")
    date: str = Field(description="Match date, YYYY-MM-DD.")
    stage: str | None = Field(default=None, description="Stage of the competition, e.g. 'Final'.")
    home_team: str
    away_team: str
    home_score: Count = Field(description=DEFINITIONS["score"])
    away_score: Count = Field(description=DEFINITIONS["score"])
    shootout_winner: str | None = Field(
        default=None, description="Team that won the penalty shootout; null if there was none."
    )


class ShootingStats(Strict):
    shots: Count = Field(description=DEFINITIONS["shots"])
    goals: Count = Field(description=DEFINITIONS["goals"])
    xg: Xg = Field(description=DEFINITIONS["xg"])
    npxg: Xg = Field(description=DEFINITIONS["npxg"])

    @model_validator(mode="after")
    def _consistent(self):
        if self.goals > self.shots:
            raise ValueError("goals cannot exceed shots")
        if self.npxg > self.xg:
            raise ValueError("npxg cannot exceed xg")
        return self


class PassingStats(Strict):
    passes: Count = Field(description=DEFINITIONS["passes"])
    completed: Count = Field(description=DEFINITIONS["completed"])
    completion_pct: Pct = Field(description=DEFINITIONS["completion_pct"])
    progressive: Count = Field(description=DEFINITIONS["progressive"])

    @model_validator(mode="after")
    def _consistent(self):
        if self.completed > self.passes:
            raise ValueError("completed cannot exceed passes")
        if self.progressive > self.completed:
            raise ValueError("progressive cannot exceed completed")
        return self


class PressingStats(Strict):
    opp_passes: Count = Field(description=DEFINITIONS["opp_passes"])
    defensive_actions: Count = Field(description=DEFINITIONS["defensive_actions"])
    ppda: Ppda = Field(description=DEFINITIONS["ppda"])


class TeamMatchStats(Strict):
    team_id: int
    team: str
    shooting: ShootingStats
    passing: PassingStats
    pressing: PressingStats


class MatchStatsResult(Strict):
    match: MatchSummary
    teams: list[TeamMatchStats] = Field(min_length=2, max_length=2)
    sources: list[int] = Field(description="Match ids the numbers come from.")


class MatchList(Strict):
    matches: list[MatchSummary] = Field(max_length=MAX_ROWS)
    total: Count = Field(description="Number of matches found, even if the list is truncated.")
    truncated: bool = Field(description="True if more matches exist than the ones listed.")


class MetricDefinition(Strict):
    name: str
    definition: str


class ToolError(Strict):
    """Returned (as data, not raised) when a tool cannot do what was asked.

    error: "not_found" = an id does not exist; "invalid_argument" = a value is not allowed.
    hint: what the LLM should do next to recover.
    """

    error: Literal["not_found", "invalid_argument"]
    message: str
    hint: str | None = None