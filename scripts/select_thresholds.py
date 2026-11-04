"""Pick a policy's parameters from sweep results by the rule of PRD §14.5.

Lowest total emissions among cells whose miss rate is at most `place_once`'s + 1 pp; ties go to
fewer full re-scorings. Run on validation sweeps only, never on test data (PRD §14.3).

    uv run python scripts/select_thresholds.py --policy decision_flip results/sweep_<hash> ...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

MISS_ALLOWANCE = 0.01  # PRD §14.5: 1 percentage point
SHOWN = ["kg_co2", "intensity_g_per_kwh_estimable", "miss_rate", "stage2_calls", "moves"]


def select(sweeps: list[pd.DataFrame], policy: str) -> pd.DataFrame:
    """All cells of `policy`, best first, with whether each meets the miss-rate limit."""
    cells = []
    for data in sweeps:
        keys = [c for c in data.columns if c.startswith("policies.")]
        limit = data.loc[data["policy"] == "place_once", "miss_rate"].mean() + MISS_ALLOWANCE
        here = data[data["policy"] == policy].copy()
        here["params"] = [
            ", ".join(f"{k.split('.')[-1]}={row[k]:g}" for k in keys) for _, row in here.iterrows()
        ]
        here["allowed"] = here["miss_rate"] <= limit
        cells.append(here)
    table = pd.concat(cells, ignore_index=True).drop_duplicates(["params"])
    return table.sort_values(
        ["allowed", "kg_co2", "stage2_calls"], ascending=[False, True, True], kind="stable"
    )[["params", "allowed", *SHOWN]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--policy", required=True)
    ap.add_argument("sweeps", nargs="+", type=Path)
    args = ap.parse_args()
    table = select([pd.read_csv(p / "summary.csv") for p in args.sweeps], args.policy)
    if table.empty:
        print(f"no cells for {args.policy}")
        return 1
    print(table.to_string(index=False))
    best = table.iloc[0]
    if not best["allowed"]:
        print("no cell meets the miss-rate limit")
        return 1
    print(f"selected: {best['params']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
