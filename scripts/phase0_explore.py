"""Phase 0 command line: explore StatsBomb Open Data coverage.

Usage:
    python scripts/phase0_explore.py coverage
    python scripts/phase0_explore.py slice --competition-id 11 --season-id 90
    python scripts/phase0_explore.py probe --match-id 3773386
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from matchagent.coverage import build_coverage, probe_events, slice_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("coverage", help="table of all competition-seasons")

    p_slice = sub.add_parser("slice", help="teams of one competition-season")
    p_slice.add_argument("--competition-id", type=int, required=True)
    p_slice.add_argument("--season-id", type=int, required=True)

    p_probe = sub.add_parser("probe", help="event types of one match")
    p_probe.add_argument("--match-id", type=int, required=True)

    args = parser.parse_args()
    pd.set_option("display.width", 200, "display.max_rows", 200)

    if args.command == "coverage":
        table = build_coverage()
        Path("data").mkdir(exist_ok=True)
        table.to_csv("data/coverage.csv", index=False)
        print(table.to_string(index=False))
        print(f"\n{len(table)} competition-seasons, {table.n_matches.sum()} matches")
        print("Saved to data/coverage.csv")
    elif args.command == "slice":
        print(slice_report(args.competition_id, args.season_id).to_string(index=False))
    elif args.command == "probe":
        print(probe_events(args.match_id).to_string(index=False))


if __name__ == "__main__":
    main()
