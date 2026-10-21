"""Phase 1 entry point: raw StatsBomb JSON -> typed DuckDB tables -> Parquet files.

Usage:
    python -m matchagent.build_db                     # every slice of scope.toml
    python -m matchagent.build_db --slice worldcup2022
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd

from matchagent.checks import format_report, run_checks
from matchagent.download import download_slice
from matchagent.schema import TABLES, create_schema
from matchagent.sb_api import fetch_json
from matchagent.scope import load_scope, validate_scope
from matchagent.transform import events_frames, lineups_frames, matches_frame, normalize_name


def _insert(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> None:
    """Append a DataFrame; BY NAME matches columns by name, so column order is irrelevant."""
    if df.empty:
        return
    con.register("_tmp", df)
    con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM _tmp")
    con.unregister("_tmp")


def build(db_path: Path, parquet_dir: Path, slice_names: list[str] | None, workers: int = 8) -> bool:
    slices = load_scope()
    problems = validate_scope(slices)
    if problems:
        sys.exit("Invalid scope.toml: " + "; ".join(problems))
    if slice_names:
        slices = [s for s in slices if s.name in slice_names]
        if not slices:
            sys.exit(f"No slice named {slice_names} in scope.toml")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    create_schema(con)

    all_players: list[pd.DataFrame] = []
    for s in slices:
        print(f"[{s.name}] downloading (cached files are skipped)...")
        match_ids = download_slice(s.competition_id, s.season_id, workers=workers)
        _insert(con, "matches", matches_frame(fetch_json(f"matches/{s.competition_id}/{s.season_id}.json")))
        for i, match_id in enumerate(match_ids, start=1):
            frames = events_frames(match_id, fetch_json(f"events/{match_id}.json"))
            for table, df in frames.items():
                _insert(con, table, df)
            players, lineup = lineups_frames(match_id, fetch_json(f"lineups/{match_id}.json"))
            all_players.append(players)
            _insert(con, "lineups", lineup)
            if i % 10 == 0 or i == len(match_ids):
                print(f"[{s.name}] {i}/{len(match_ids)} matches loaded")

    # Reference tables, derived once everything is loaded.
    teams = con.execute("""
        SELECT home_team_id AS team_id, home_team AS team_name FROM matches
        UNION SELECT away_team_id, away_team FROM matches ORDER BY team_id""").df()
    teams["name_norm"] = teams["team_name"].map(normalize_name)
    _insert(con, "teams", teams)

    players = pd.concat(all_players).drop_duplicates("player_id").sort_values("player_id")
    players["name_norm"] = players["player_name"].map(normalize_name)
    _insert(con, "players", players)

    results = run_checks(con)
    report = format_report(results)
    print("\n" + report)
    Path("data").mkdir(exist_ok=True)
    Path("data/quality_report.md").write_text("# Data quality report\n\n" + report + "\n", encoding="utf-8")

    parquet_dir.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        con.execute(f"COPY {table} TO '{(parquet_dir / (table + '.parquet')).as_posix()}' "
                    "(FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()
    return all(r.ok or not r.critical for r in results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slice", action="append", dest="slices", help="slice name (repeatable)")
    parser.add_argument("--db", type=Path, default=Path("data/matchagent.duckdb"))
    parser.add_argument("--parquet-dir", type=Path, default=Path("data/parquet"))
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    ok = build(args.db, args.parquet_dir, args.slices, args.workers)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
