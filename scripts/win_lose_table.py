"""Where decision-flip wins and loses (PRD 18.2 goal 1, §14.8; B6 in HANDOFF).

Reads finished sweeps only; never runs a simulation, and refuses test-split replicates (§14.3).
For every sweep cell and every rival policy in it, the paired difference `decision_flip − rival`
in kgCO2 over that cell's replicates, with the crossed (trace slice × carbon start) bootstrap
interval that headline claims use (D70), plus the miss-rate gap and the re-scoring ratio.

Verdict per (cell, rival), fixed here before any sweep result is seen:
  wins   crossed CI of ΔkgCO2 entirely below 0, and miss rate at most 1 pp above the rival's
  loses  crossed CI entirely above 0, or miss rate more than 1 pp above the rival's
  tie    otherwise (the two cannot be told apart on carbon)

Usage:
  uv run python scripts/win_lose_table.py --out docs/win_lose \
      --sweep rho=results/sweep_<hash> --sweep slack_base=results/sweep_<hash> ...
Writes `win_lose.csv` (every row) and `win_lose.md` (tables plus "helps when / loses when").
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

from flipwise.reporting import (
    BOOTSTRAP_SEED,
    MISS_ALLOWANCE,
    bootstrap_ci,
    crossed_bootstrap_ci,
    replicate_cell,
)

FLIP = "decision_flip"
SUMMARY_FIELDS = {"policy", "compare", "kg_co2", "miss_rate"}


def grid_columns(sweep: pd.DataFrame) -> list[str]:
    """The swept config keys: `experiment.sweep` writes them first, before `policy`."""
    return list(sweep.columns[: list(sweep.columns).index("policy")])


def cell_label(row: pd.Series, keys: list[str]) -> str:
    return ", ".join(f"{k.split('.')[-1]}={row[k]}" for k in keys)


def compare_rows(cmp: pd.DataFrame, rival: str) -> dict | None:
    """Paired `decision_flip − rival` on one compare's replicates; None if either is missing."""
    if not {FLIP, rival} <= set(cmp["policy"]):
        return None
    a = cmp[cmp["policy"] == FLIP].set_index("replicate")
    b = cmp[cmp["policy"] == rival].set_index("replicate")
    pair = a.join(b, how="inner", lsuffix="_a", rsuffix="_b")
    if pair.empty:
        return None
    bad = [r for r in pair.index if str(r).startswith("test")]
    if bad:
        raise SystemExit(f"refusing test-split replicates (PRD §14.3): {bad[:3]}")
    diff = (pair["kg_co2_a"] - pair["kg_co2_b"]).to_numpy(dtype=float)
    lo, hi = bootstrap_ci(diff, np.random.default_rng(BOOTSTRAP_SEED))
    cells = [replicate_cell(r) for r in pair.index]
    xlo, xhi = (
        crossed_bootstrap_ci(diff, cells)  # type: ignore[arg-type]
        if all(cells)
        else (math.nan, math.nan)
    )
    crossed = not math.isnan(xlo)
    use_lo, use_hi = (xlo, xhi) if crossed else (lo, hi)
    miss_gap = float((pair["miss_rate_a"] - pair["miss_rate_b"]).mean())
    if miss_gap > MISS_ALLOWANCE or use_lo > 0:
        verdict = "loses"
    elif use_hi < 0:
        verdict = "wins"
    else:
        verdict = "tie"
    row = {
        "n_replicates": len(diff),
        "kg_co2_flip": float(pair["kg_co2_a"].mean()),
        "kg_co2_rival": float(pair["kg_co2_b"].mean()),
        "delta_kg_co2": float(diff.mean()),
        "ci95_lo": lo,
        "ci95_hi": hi,
        "ci95_lo_crossed": xlo,
        "ci95_hi_crossed": xhi,
        "ci_used": "crossed" if crossed else "replicate",
        "miss_gap_pp": 100 * miss_gap,
        "verdict": verdict,
    }
    if "stage2_calls_a" in pair and float(pair["stage2_calls_b"].mean()) > 0:
        row["rescore_ratio"] = float(pair["stage2_calls_a"].mean() / pair["stage2_calls_b"].mean())
    return row


def sweep_table(name: str, sweep_dir: Path) -> pd.DataFrame:
    sweep = pd.read_csv(sweep_dir / "summary.csv")
    missing = SUMMARY_FIELDS - set(sweep.columns)
    if missing:
        raise SystemExit(f"{sweep_dir}: not a sweep summary (missing {sorted(missing)})")
    keys = grid_columns(sweep)
    rows = []
    for compare, cell in sweep.groupby("compare", sort=False):
        first = cell.iloc[0]
        cmp_path = sweep_dir.parent / str(compare) / "summary.csv"
        if not cmp_path.exists():
            raise SystemExit(f"{cmp_path} is listed by {sweep_dir} but missing")
        cmp = pd.read_csv(cmp_path)
        for rival in sorted(set(cmp["policy"]) - {FLIP, "pig"}):
            r = compare_rows(cmp, rival)
            if r is not None:
                rows.append({"sweep": name, "cell": cell_label(first, keys), "rival": rival, **r})
    return pd.DataFrame(rows)


def _fmt(v: float, digits: int = 0) -> str:
    return "n/a" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:,.{digits}f}"


def markdown(table: pd.DataFrame) -> str:
    out = [
        "# Where decision-flip wins and loses (validation only)",
        "",
        "Built by `scripts/win_lose_table.py` from finished sweeps; verdict rules are in its "
        "docstring (crossed bootstrap, D70; miss allowance 1 pp, PRD §14.5).",
        "",
    ]
    for name, t in table.groupby("sweep", sort=False):
        out += [
            f"## {name}",
            "",
            "| Cell | Rival | ΔkgCO2 | 95 % CI (crossed) | Miss gap (pp) | Re-scorings ratio "
            "| Verdict |",
            "|---|---|---|---|---|---|---|",
        ]
        for _, r in t.iterrows():
            ci = f"{_fmt(r['ci95_lo_crossed'])} to {_fmt(r['ci95_hi_crossed'])}"
            if r["ci_used"] != "crossed":
                ci = f"{_fmt(r['ci95_lo'])} to {_fmt(r['ci95_hi'])} (replicate)"
            out.append(
                f"| {r['cell']} | {r['rival']} | {_fmt(r['delta_kg_co2'])} | {ci} | "
                f"{_fmt(r['miss_gap_pp'], 2)} | {_fmt(r.get('rescore_ratio', math.nan), 2)} | "
                f"**{r['verdict']}** |"
            )
        out.append("")
    vs_once = table[table["rival"] == "place_once"]
    for verdict, head in (("wins", "Helps"), ("loses", "Loses")):
        hits = vs_once[vs_once["verdict"] == verdict]
        cells = "; ".join(f"{s}: {c}" for s, c in zip(hits["sweep"], hits["cell"], strict=True))
        out.append(f"**{head} against `place_once` when:** {cells or 'no cell'}.")
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sweep", action="append", required=True, metavar="NAME=DIR")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    parts = []
    for spec in a.sweep:
        name, sep, path = spec.partition("=")
        if not sep:
            raise SystemExit(f"--sweep {spec!r}: expected NAME=DIR")
        parts.append(sweep_table(name, Path(path)))
    table = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if table.empty:
        raise SystemExit("no decision_flip comparisons found in the given sweeps")
    a.out.mkdir(parents=True, exist_ok=True)
    table.to_csv(a.out / "win_lose.csv", index=False, lineterminator="\n")
    (a.out / "win_lose.md").write_text(markdown(table) + "\n", encoding="utf-8")
    print(f"wrote {a.out / 'win_lose.csv'} and {a.out / 'win_lose.md'} ({len(table)} rows)")


if __name__ == "__main__":
    main()
