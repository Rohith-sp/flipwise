"""Copy what the team needs out of `results/` into small files that can go in git.

`results/` is about 2.5 GB and is never committed, so anyone without it would otherwise have to
re-run every simulation to see a number. This writes per-replicate tables, the sweep curves of PRD
§14.5, the logs' diagnostics, a hash per run to check a re-run against, and the dashboard.

    uv run python scripts/export_validation.py --compare results/compare_<hash> \
        --sweep results/sweep_<hash> [--sweep ...] --out docs/validation
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from flipwise import figures
from flipwise.dashboard import build_dashboard
from flipwise.reporting import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED

MISS_ALLOWANCE = 0.01  # PRD §14.5: 1 percentage point
BASE = "place_once"
PROPOSED = "decision_flip"
METRICS = [
    "kg_co2",
    "kg_co2_estimable",
    "intensity_g_per_kwh",
    "intensity_g_per_kwh_estimable",
    "miss_rate",
    "completion",
    "stage2_calls",
    "screened",
    "moves",
    "rescues",
    "fallback_share",
    "fallback_flag",
    "runtime_coverage",
    "wait_coverage",
]
DIFF_METRICS = ["kg_co2", "kg_co2_estimable", "miss_rate", "stage2_calls", "moves"]
# Rows where the policy looked at a job's plan, whether or not the screen let it through.
EXAMINED = {"SCREEN_FAIL", "NO_ALTERNATIVE", "KEEP", "MOVE"}
COMPARED = {"KEEP", "MOVE"}


def paired_ci(diff: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    """Percentile bootstrap over replicates, as in `paired.csv` (PRD §14.7)."""
    picks = rng.integers(0, len(diff), size=(BOOTSTRAP_RESAMPLES, len(diff)))
    boot = diff[picks].mean(axis=1)
    return float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def diff_rows(a: pd.DataFrame, b: pd.DataFrame, rng: np.random.Generator, **labels) -> list[dict]:
    """Difference `a − b` on each metric, paired by replicate."""
    rows = []
    for metric in DIFF_METRICS:
        pair = pd.concat([a[metric], b[metric]], axis=1, keys=["a", "b"]).dropna()
        if pair.empty:
            continue
        diff = (pair["a"] - pair["b"]).to_numpy(dtype=float)
        lo, hi = paired_ci(diff, rng)
        rows.append(
            {
                **labels,
                "metric": metric,
                "n_replicates": len(diff),
                "mean_diff": diff.mean(),
                "ci95_lo": lo,
                "ci95_hi": hi,
            }
        )
    return rows


def _policy_rows(summary: pd.DataFrame, policy: str) -> pd.DataFrame:
    return summary[summary["policy"] == policy].set_index("replicate").sort_index()


def pairwise(summary: pd.DataFrame) -> pd.DataFrame:
    """The proposed policy against every other, which `paired.csv` (all against BASE) can't show."""
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    mine = _policy_rows(summary, PROPOSED)
    rows = []
    for other in sorted(set(summary["policy"]) - {PROPOSED}):
        rows += diff_rows(mine, _policy_rows(summary, other), rng, policy=PROPOSED, against=other)
    return pd.DataFrame(rows)


def _sweep_info(data: pd.DataFrame) -> tuple[str, str, list[str]]:
    """Name, swept policy and grid columns of one sweep's `summary.csv`."""
    keys = [c for c in data.columns if c.startswith("policies.")]
    policy = keys[0].split(".")[1]
    return policy + "." + "+".join(k.split(".")[-1] for k in keys), policy, keys


def _label(row: pd.Series, keys: list[str]) -> str:
    return ", ".join(f"{k.split('.')[-1]}={row[k]:g}" for k in keys)


def _is_frozen(row: pd.Series, keys: list[str], frozen: dict) -> bool:
    return all(
        np.isclose(row[k], frozen.get(k.split(".")[1], {}).get(k.split(".")[-1], np.nan))
        for k in keys
    )


def sweep_tables(
    sweeps: list[Path], frozen: dict, summary: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One row per replicate per cell, then one per cell with its gap to the frozen setting.

    The gap is measured against the frozen comparison, because a grid need not contain the frozen
    value (`w_max` = 2 isn't in the `w_max` grid)."""
    cells, means = [], []
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    for sweep_dir in sweeps:
        data = pd.read_csv(sweep_dir / "summary.csv")
        name, policy, keys = _sweep_info(data)
        here = data[data["policy"] == policy]
        loaded = {}
        for _, row in here.iterrows():
            cell_summary = pd.read_csv(sweep_dir.parent / row["compare"] / "summary.csv")
            loaded[_label(row, keys)] = (row, cell_summary)
        reference = _policy_rows(summary, policy)
        for label, (row, cell) in loaded.items():
            rows = _policy_rows(cell, policy)
            limit = _policy_rows(cell, BASE)["miss_rate"].mean() + MISS_ALLOWANCE
            cells.append(rows[METRICS].reset_index().assign(sweep=name, cell=label, policy=policy))
            mean = {
                "sweep": name,
                "cell": label,
                "policy": policy,
                "frozen": _is_frozen(row, keys, frozen),
                "miss_limit": limit,
                "allowed": rows["miss_rate"].mean() <= limit,
                "place_once_kg_co2": _policy_rows(cell, BASE)["kg_co2"].mean(),
                **rows[METRICS].mean().to_dict(),
            }
            gap = (rows["kg_co2"] - reference["kg_co2"]).to_numpy(dtype=float)
            lo, hi = paired_ci(gap, rng)
            mean.update(kg_co2_vs_frozen=gap.mean(), ci95_lo=lo, ci95_hi=hi)
            means.append(mean)
    first = ["sweep", "cell", "policy", "replicate"]
    table = pd.concat(cells, ignore_index=True)
    return table[first + METRICS], pd.DataFrame(means)


def _log_diagnostics(run_dir: Path) -> dict:
    """What only the job and decision logs can tell (F4, F7, F9, F10)."""
    jobs = pd.read_csv(run_dir / "jobs.csv")
    done = jobs[jobs["incomplete"] == 0]
    energy = done["energy_kwh"].sort_values(ascending=False)
    outran = jobs["runtime_s"] > jobs["r_q90_s"]
    missed = jobs["deadline_missed"] == 1
    row = {
        "n_jobs": len(jobs),
        "top_1pct_jobs_energy_share": energy.head(max(1, len(jobs) // 100)).sum() / energy.sum(),
        "share_of_jobs_outran_q90": outran.mean(),
        "share_of_misses_outran_q90": (outran & missed).sum() / max(1, missed.sum()),
        "miss_rate_outran_q90": missed[outran].mean(),
        "miss_rate_within_q90": missed[~outran].mean(),
        "at_risk_jobs": int((jobs["deadline_risk"] == 1).sum()),
        "at_risk_energy_share": done.loc[done["deadline_risk"] == 1, "energy_kwh"].sum()
        / done["energy_kwh"].sum(),
        "mean_deferral_h": (jobs["start_s"] - jobs["arrival_s"]).mean() / 3600,
    }
    log = pd.read_csv(run_dir / "decisions.csv")
    compared = log[log["kind"].isin(COMPARED)]
    if compared["w_ab"].notna().any():
        usable = compared[compared["S_a"] > 0]
        moves = compared[compared["kind"] == "MOVE"]
        row["median_w_ab_over_S_a"] = (usable["w_ab"] / usable["S_a"]).median()
        row["moves_with_theta_off"] = (moves["reason"] == "INTERVAL_TOO_WIDE").mean()
    return row


def diagnostics(cmp_dir: Path, summary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-run log diagnostics, and every reason and decision count in long form."""
    rows, counts = [], []
    for _, run in summary.iterrows():
        run_dir = cmp_dir.parent / run["run_id"]
        labels = {"replicate": run["replicate"], "policy": run["policy"]}
        rows.append({**labels, **_log_diagnostics(run_dir)})
        metrics = json.loads((run_dir / "metrics.json").read_text())
        for field in ("decision_counts", "reason_counts", "interval_fallbacks"):
            counts += [
                {**labels, "field": field, "key": k, "count": v}
                for k, v in sorted((metrics.get(field) or {}).items())
            ]
    return pd.DataFrame(rows), pd.DataFrame(counts)


def score_scale(cmp_dir: Path, summary: pd.DataFrame) -> dict:
    """Median Ŝ over every examined plan: PRD §10.10 sets `g_abs` and `κ` from it."""
    values, medians = [], {}
    for _, run in summary[summary["policy"] == PROPOSED].iterrows():
        log = pd.read_csv(cmp_dir.parent / run["run_id"] / "decisions.csv")
        here = log.loc[log["kind"].isin(EXAMINED), "S_a"].dropna()
        values.append(here.to_numpy())
        medians[run["replicate"]] = float(here.median())
    pooled = float(np.median(np.concatenate(values)))
    return {
        "source": f"S_a of every examined plan in the frozen {PROPOSED} runs, pooled",
        "unit": "kgCO2",
        "median_S": pooled,
        "g_abs_sweep_value": 0.05 * pooled,
        "kappa_sweep_value": 0.02 * pooled,
        "median_S_per_replicate": medians,
    }


def p1_check(sweeps: list[Path]) -> pd.DataFrame:
    """R-TRIG-2 on each replicate: θ = 0 against `fixed_savings` at the same `g_rel`."""
    records: dict[str, dict] = {}
    for sweep_dir in sweeps:
        data = pd.read_csv(sweep_dir / "summary.csv")
        name, policy, keys = _sweep_info(data)
        for _, row in data[data["policy"] == policy].iterrows():
            flip = name == "decision_flip.theta" and row[keys[0]] == 0
            saving = name == "fixed_savings.g_rel" and np.isclose(row[keys[0]], 0.05)
            if flip or saving:
                runs = json.loads((sweep_dir.parent / row["compare"] / "runs.json").read_text())
                mine = [r for r in runs if r["policy"] == policy]
                records[policy] = {r["replicate"]: r["run_id"] for r in mine}
    if len(records) < 2:
        return pd.DataFrame()
    rows = []
    root = sweeps[0].parent
    for replicate, flip_id in sorted(records[PROPOSED].items()):
        a = json.loads((root / flip_id / "manifest.json").read_text())["output_sha256"]
        b_id = records["fixed_savings"][replicate]
        b = json.loads((root / b_id / "manifest.json").read_text())["output_sha256"]
        stats = [json.loads((root / i / "metrics.json").read_text()) for i in (flip_id, b_id)]
        rows.append(
            {
                "replicate": replicate,
                "jobs_csv_identical": a["jobs.csv"] == b["jobs.csv"],
                "events_log_identical": a["events.log"] == b["events.log"],
                "stage2_calls_decision_flip": stats[0]["stage2_calls"],
                "stage2_calls_fixed_savings": stats[1]["stage2_calls"],
            }
        )
    return pd.DataFrame(rows)


def run_index(cmp_dir: Path, sweeps: list[Path]) -> pd.DataFrame:
    """Every run once: its hashes to check a re-run against, and how long it took (R-PERF-1)."""
    dirs = [cmp_dir]
    for sweep_dir in sweeps:
        dirs += [sweep_dir.parent / c for c in pd.read_csv(sweep_dir / "summary.csv")["compare"]]
    seen: dict[str, dict] = {}
    for folder in dirs:
        for record in json.loads((folder / "runs.json").read_text()):
            seen.setdefault(record["run_id"], record)
    rows = []
    for run_id, record in sorted(seen.items()):
        man = json.loads((cmp_dir.parent / run_id / "manifest.json").read_text())
        clock = man["wall_clock"]
        took = datetime.fromisoformat(clock["end"]) - datetime.fromisoformat(clock["start"])
        rows.append(
            {
                "run_id": run_id,
                "replicate": record["replicate"],
                "policy": record["policy"],
                "policy_params": json.dumps(man["policy_params"], sort_keys=True),
                "git_commit": man["git"]["commit"] if isinstance(man["git"], dict) else man["git"],
                "wall_clock_min": took.total_seconds() / 60,
                **{f"sha256_{k}": v for k, v in sorted(man["output_sha256"].items())},
            }
        )
    return pd.DataFrame(rows)


def _short(cell: str) -> str:
    """Six labels share these panels, and the full names run into each other."""
    return cell.replace("theta=", "θ=").replace("w_max=", "w=").replace("epsilon=", "ε=")


def sweep_figure(cells: pd.DataFrame, title: str) -> figures.plt.Figure:
    """Emissions against both costs on one y scale, so a cheaper setting's price is readable."""
    fig, axes = figures._figure(w=10, h=3.8, ncols=2, sharey=True)
    base = cells["place_once_kg_co2"].mean()
    for ax, col, xlabel in (
        (axes[0], "stage2_calls", "Full re-scorings"),
        (axes[1], "moves", "Moves"),
    ):
        ax.axhline(base, color=figures.INK_SECONDARY, linewidth=1, linestyle=(0, (4, 3)))
        ax.annotate(
            BASE,
            (1, base),
            xycoords=("axes fraction", "data"),
            xytext=(0, 4),
            textcoords="offset points",
            ha="right",
            fontsize=8,
            color=figures.INK_SECONDARY,
        )
        for _, row in cells.iterrows():
            ax.scatter(
                row[col],
                row["kg_co2"],
                s=90 if row["frozen"] else 55,
                color=figures.HIGHLIGHT if row["frozen"] else figures.MUTED_MARK,
                edgecolor=figures.SURFACE,
                linewidth=2,
                zorder=3,
            )
            ax.annotate(
                _short(row["cell"]) + (" (frozen)" if row["frozen"] else ""),
                (row[col], row["kg_co2"]),
                xytext=(7, 5),
                textcoords="offset points",
                fontsize=8,
                color=figures.INK if row["frozen"] else figures.INK_SECONDARY,
            )
        ax.set_xlabel(xlabel)
        ax.margins(x=0.28, y=0.18)
    axes[0].set_ylabel("Emissions (relative kgCO2)")
    figures._title(axes[0], title)
    fig.tight_layout()
    return fig


def write_sweep_figures(means: pd.DataFrame, out: Path, frozen: dict) -> None:
    for name, cells in means.groupby("sweep", sort=True):
        cells = cells.copy()
        if name.endswith("theta+w_max"):
            # The grid leaves out the frozen w_max; those cells are in the θ sweep.
            w_max = frozen[PROPOSED]["w_max"]
            extra = means[means["sweep"] == f"{PROPOSED}.theta"].copy()
            extra = extra[extra["cell"].isin([f"theta={t:g}" for t in (0.1, 0.25)])]
            extra["cell"] = extra["cell"] + f", w_max={w_max:g}"
            cells = pd.concat([cells, extra], ignore_index=True)
        path = out / f"sweep_{re.sub(r'[^a-z0-9_]+', '_', name.lower())}.png"
        figures.save(sweep_figure(cells, f"{name}: emissions against cost"), path)


def export(cmp_dir: Path, sweeps: list[Path], out: Path, policies_yaml: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    fig_dir = out / "figures"
    fig_dir.mkdir(exist_ok=True)
    frozen = yaml.safe_load(policies_yaml.read_text())
    summary = pd.read_csv(cmp_dir / "summary.csv")
    for name in ("summary.csv", "paired.csv", "carbon_coverage.csv"):
        shutil.copyfile(cmp_dir / name, out / name)
    for png in sorted((cmp_dir / "figures").glob("*.png")):
        shutil.copyfile(png, fig_dir / png.name)
    tables = {"pairwise.csv": pairwise(summary)}
    diag, counts = diagnostics(cmp_dir, summary)
    tables |= {"diagnostics.csv": diag, "decision_counts.csv": counts}
    tables["runs.csv"] = run_index(cmp_dir, sweeps)
    if sweeps:
        cells, means = sweep_tables(sweeps, frozen, summary)
        tables |= {"sweep_replicates.csv": cells, "sweep_means.csv": means}
        tables["p1.csv"] = p1_check(sweeps)
        write_sweep_figures(means, fig_dir, frozen)
    for name, table in tables.items():
        table.to_csv(out / name, index=False, lineterminator="\n", float_format="%.6g")
    if PROPOSED in set(summary["policy"]):
        scale = score_scale(cmp_dir, summary)
        (out / "score_scale.json").write_text(json.dumps(scale, indent=2, sort_keys=True) + "\n")
    theta = [s for s in sweeps if _sweep_info(pd.read_csv(s / "summary.csv"))[0].endswith(".theta")]
    build_dashboard(cmp_dir, theta[0] if theta else None, out / "dashboard.html")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--compare", required=True, type=Path)
    ap.add_argument("--sweep", action="append", default=[], type=Path)
    ap.add_argument("--out", type=Path, default=Path("docs/validation"))
    ap.add_argument("--policies", type=Path, default=Path("configs/policies.yaml"))
    args = ap.parse_args()
    export(args.compare, args.sweep, args.out, args.policies)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
