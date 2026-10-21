"""Data-quality checks run on the built DuckDB database."""
from __future__ import annotations

from dataclasses import dataclass

import duckdb


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    critical: bool = True  # a failed critical check makes the build fail


def _scalar(con, sql: str):
    return con.execute(sql).fetchone()[0]


def run_checks(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    results: list[CheckResult] = []

    def add(name, ok, detail, critical=True):
        results.append(CheckResult(name, bool(ok), detail, critical))

    n_matches = _scalar(con, "SELECT COUNT(*) FROM matches")
    n_events = _scalar(con, "SELECT COUNT(*) FROM events")
    add("tables not empty", n_matches > 0 and n_events > 0, f"{n_matches} matches, {n_events} events")

    no_events = _scalar(con, """SELECT COUNT(*) FROM matches m
        WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.match_id = m.match_id)""")
    add("every match has events", no_events == 0, f"{no_events} matches without events")

    dupes = n_events - _scalar(con, "SELECT COUNT(DISTINCT id) FROM events")
    add("event ids unique", dupes == 0, f"{dupes} duplicated ids")

    orphans = _scalar(con, """SELECT COUNT(*) FROM events e
        WHERE NOT EXISTS (SELECT 1 FROM matches m WHERE m.match_id = e.match_id)""")
    add("events reference known matches", orphans == 0, f"{orphans} orphan events")

    off_pitch = _scalar(con, """SELECT COUNT(*) FROM events
        WHERE x < 0 OR x > 120 OR y < 0 OR y > 80""")
    add("coordinates inside the 120x80 pitch", off_pitch == 0, f"{off_pitch} events outside")

    bad_xg = _scalar(con, "SELECT COUNT(*) FROM shots WHERE xg < 0 OR xg > 1")
    null_xg = _scalar(con, "SELECT COUNT(*) FROM shots WHERE xg IS NULL")
    add("xG within [0, 1]", bad_xg == 0, f"{bad_xg} out of range, {null_xg} shots without xG")

    mismatches = con.execute("""
        WITH goals AS (
            SELECT match_id, team_id, COUNT(*) AS g FROM shots
            WHERE is_goal AND period <= 4 GROUP BY ALL            -- period 5 = shootout
            UNION ALL
            SELECT match_id, team_id, COUNT(*) FROM events
            WHERE type = 'Own Goal For' GROUP BY ALL
        ), by_team AS (
            SELECT match_id, team_id, SUM(g) AS computed FROM goals GROUP BY ALL
        ), official AS (
            SELECT match_id, home_team_id AS team_id, home_score AS score FROM matches
            UNION ALL
            SELECT match_id, away_team_id, away_score FROM matches
        )
        SELECT o.match_id, o.team_id, o.score, COALESCE(b.computed, 0) AS computed
        FROM official o LEFT JOIN by_team b USING (match_id, team_id)
        WHERE o.score <> COALESCE(b.computed, 0)
    """).fetchall()
    add("goals from events match official scores", not mismatches,
        f"{len(mismatches)} team-scores differ" + (f", e.g. {mismatches[:3]}" if mismatches else ""))

    bad_lineups = _scalar(con, """SELECT COUNT(*) FROM (
        SELECT match_id FROM lineups GROUP BY match_id HAVING COUNT(DISTINCT team_id) <> 2)""")
    add("2 teams per lineup", bad_lineups == 0, f"{bad_lineups} matches with a different count")

    unknown_players = _scalar(con, """SELECT COUNT(DISTINCT player_id) FROM events e
        WHERE player_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM players p WHERE p.player_id = e.player_id)""")
    add("event players exist in players", unknown_players == 0,
        f"{unknown_players} unknown player ids", critical=False)

    no_winner = _scalar(con, """SELECT COUNT(*) FROM (
        SELECT match_id FROM team_matches WHERE shootout_for IS NOT NULL
        GROUP BY match_id HAVING COUNT(DISTINCT shootout_result) <> 2)""")
    add("every shootout has a winner", no_winner == 0, f"{no_winner} shootouts without a winner")

    tm = _scalar(con, "SELECT COUNT(*) FROM team_matches")
    add("team_matches has 2 rows per match", tm == 2 * n_matches, f"{tm} rows for {n_matches} matches")
    return results


def format_report(results: list[CheckResult]) -> str:
    lines = ["| check | status | detail |", "|---|---|---|"]
    for r in results:
        status = "OK" if r.ok else ("FAIL" if r.critical else "WARN")
        lines.append(f"| {r.name} | {status} | {r.detail} |")
    return "\n".join(lines)
