"""Run outputs (PRD §16.1) and comparison tables and figures rebuilt from them (PRD §16.2)."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import re
from pathlib import Path

import numpy as np
import pandas as pd

from flipwise.errors import ReportError
from flipwise.models import JobState
from flipwise.simulator import RunResult, job_outcome

JOBS_CSV = [
    "job_id", "user", "gpu_req", "cpu_req", "mem_req_gb", "arrival_s", "deadline_s",
    "r_q05_s", "r_q50_s", "r_q90_s", "r_q95_s", "dc_id", "region_id", "release_slot", "start_s",
    "end_s", "wait_s",
    "runtime_s", "energy_kwh", "kg_co2", "deadline_missed", "n_moves", "rescued",
    "deadline_risk", "incomplete", "plan_w_lo_s", "plan_w_hi_s",
]  # fmt: skip
DECISIONS_CSV = [
    "time_s", "job_id", "kind", "from_dc", "from_slot", "to_dc", "to_slot", "S_a", "S_b",
    "LB", "w_ab", "g_min", "theta_eff", "reason",
]  # fmt: skip


def _fmt(v) -> str:
    # repr gives the shortest round-trip float, so outputs are byte-stable across runs and modes.
    if v is None:
        return ""
    if isinstance(v, float):
        return repr(v)
    return str(v)


def job_rows(result: RunResult) -> list[dict]:
    region = {d.dc_id: d.region_id for d in result.scenario.dcs}
    rows = []
    for j in sorted(result.jobs, key=lambda j: j.job_id):
        out = job_outcome(j, result.scenario)
        done = j.state == JobState.COMPLETED
        rows.append(
            {
                "job_id": j.job_id, "user": j.user, "gpu_req": j.gpu_req, "cpu_req": j.cpu_req,
                "mem_req_gb": j.mem_req_gb, "arrival_s": j.arrival_s, "deadline_s": j.deadline_s,
                "r_q05_s": j.r_q05_s, "r_q50_s": j.r_q50_s, "r_q90_s": j.r_q90_s,
                "r_q95_s": j.r_q95_s, "dc_id": j.dc_id,
                "region_id": region.get(j.dc_id), "release_slot": j.release_slot,  # type: ignore[arg-type]
                "start_s": j.start_s, "end_s": j.end_s,
                "wait_s": None if j.start_s is None else j.start_s - j.arrival_s,
                "runtime_s": j.runtime_actual_s if done else None,
                "energy_kwh": out["energy_kwh"], "kg_co2": out["kg_co2"],
                "deadline_missed": int(done and j.end_s > j.deadline_s),  # type: ignore[operator]
                "n_moves": j.n_moves, "rescued": j.rescued, "deadline_risk": j.deadline_risk,
                "incomplete": int(not done),
                "plan_w_lo_s": j.plan_w_lo_s, "plan_w_hi_s": j.plan_w_hi_s,
            }
        )  # fmt: skip
    return rows


def write_run(result: RunResult, out_dir: Path, manifest: dict | None = None) -> dict[str, str]:
    """Write the run files; return their SHA-256 (the R-SIM-1 / R-DEP-1 comparison)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "jobs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, JOBS_CSV, lineterminator="\n")
        w.writeheader()
        for r in job_rows(result):
            w.writerow({k: _fmt(v) for k, v in r.items()})
    with open(out_dir / "decisions.csv", "w", newline="") as f:
        w = csv.DictWriter(f, DECISIONS_CSV, lineterminator="\n")
        w.writeheader()
        for r in result.decisions:
            w.writerow({k: _fmt(r.get(k)) for k in DECISIONS_CSV})
    with open(out_dir / "events.log", "w", newline="") as f:
        f.write("time_s,priority,seq,kind,job_id\n")
        f.writelines(line + "\n" for line in result.events)
    hashes = {
        name: hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
        for name in ("jobs.csv", "decisions.csv", "events.log")
    }
    (out_dir / "policy_stats.json").write_text(
        json.dumps(result.stats, indent=2, sort_keys=True) + "\n"
    )
    man = {
        "policy": result.policy,
        "scenario": result.scenario.name,
        "scenario_hash": result.scenario.scenario_hash,
        "uses_oracle": result.uses_oracle,
        "output_sha256": hashes,
        "python": platform.python_version(),
        "platform": platform.platform(),
        **(manifest or {}),
    }
    (out_dir / "manifest.json").write_text(json.dumps(man, indent=2, sort_keys=True) + "\n")
    return hashes


# ---- comparison tables and figures (PRD §14.1, §14.7, §16.2) ----------------------------------

BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261104
COMPLETION_SPREAD = 0.005  # PRD §14.1: policies must complete within 0.5 pp of each other
PAIRED_BASE = "place_once"
MISS_ALLOWANCE = 0.01  # PRD §14.5: a setting may miss at most 1 pp more deadlines than place_once
PAIRED_METRICS = (
    "kg_co2",
    "kg_co2_estimable",
    "intensity_g_per_kwh",
    "intensity_g_per_kwh_estimable",
    "miss_rate",
    "stage2_calls",
    "moves",
)


def _summary_row(record: dict, runs_root: Path) -> dict:
    from flipwise.metrics import metrics_from_run_dir

    run_dir = runs_root / record["run_id"]
    if not (run_dir / "jobs.csv").exists():
        raise ReportError(f"run {record['run_id']} is listed but its logs are missing")
    manifest = json.loads((run_dir / "manifest.json").read_text())
    if manifest["scenario_hash"] != record["scenario_hash"]:
        raise ReportError(f"run {record['run_id']}: scenario hash differs from the comparison's")
    metrics = metrics_from_run_dir(run_dir)
    flat = {k: v for k, v in metrics.items() if not isinstance(v, dict)}
    power = manifest.get("build", {}).get("power_label", "absolute")
    return {**record, "uses_oracle": int(manifest["uses_oracle"]), "power_label": power, **flat}


def _add_deltas(summary: pd.DataFrame) -> pd.DataFrame:
    """`ΔM%` against `place_once` and `fcfs`, within each replicate (PRD §14.1)."""
    out = summary.copy()
    for base in ("place_once", "fcfs"):
        for col in ("kg_co2", "kg_co2_estimable"):
            ref = out[out["policy"] == base].set_index("replicate")[col]
            values = out["replicate"].map(ref)
            out[f"delta_{col}_pct_vs_{base}"] = 100 * (out[col] - values) / values
    spread = out.groupby("replicate")["completion"].transform(lambda s: s.max() - s.min())
    out["completion_flag"] = (spread > COMPLETION_SPREAD).astype(int)
    return out


def bootstrap_ci(diff: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    """95 % percentile bootstrap of the mean of paired differences, over replicates (§14.7)."""
    picks = rng.integers(0, len(diff), size=(BOOTSTRAP_RESAMPLES, len(diff)))
    boot = diff[picks].mean(axis=1)
    return float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


PERM_EXACT_MAX_N = 16  # 2**16 sign patterns are enumerated; above that, Monte Carlo flips
PERM_RESAMPLES = 20_000


def paired_p_value(diff: np.ndarray, seed: int = BOOTSTRAP_SEED) -> float:
    """Two-sided paired sign-flip permutation p-value for mean(diff) = 0.

    Exact for n <= 16, else seeded Monte Carlo with the +1 correction, so it is never 0.
    A separate generator keeps the bootstrap CI draws unchanged.
    """
    diff = np.asarray(diff, dtype=float)
    n = len(diff)
    if n == 0 or not np.any(diff):
        return 1.0
    obs = abs(diff.sum())
    tol = 1e-12 * max(1.0, float(np.abs(diff).sum()))
    if n <= PERM_EXACT_MAX_N:
        bits = (np.arange(2**n)[:, None] >> np.arange(n)) & 1
        sums = np.abs(((1 - 2 * bits) * diff).sum(axis=1))
        return float(np.mean(sums >= obs - tol))
    signs = np.random.default_rng(seed).choice([-1.0, 1.0], size=(PERM_RESAMPLES, n))
    sums = np.abs((signs * diff).sum(axis=1))
    return float((np.sum(sums >= obs - tol) + 1) / (PERM_RESAMPLES + 1))


def cohens_dz(diff: np.ndarray) -> float:
    """Paired effect size mean(diff) / sd(diff, ddof=1); NaN when undefined (n < 2, sd = 0)."""
    diff = np.asarray(diff, dtype=float)
    if len(diff) < 2:
        return float("nan")
    sd = float(diff.std(ddof=1))
    return float(diff.mean() / sd) if sd > 0 else float("nan")


CROSSED_SEED_OFFSET = 1  # own generator, so the existing ci95 draws stay byte-identical
_REPLICATE_CELL = re.compile(r"_d(\d+)_(.+)$")


def replicate_cell(replicate: object) -> tuple[str, str] | None:
    """`(trace slice, carbon start)` of a split replicate id `<split>_d<day>_<monday>` (§14.2)."""
    m = _REPLICATE_CELL.search(str(replicate))
    return None if m is None else (m.group(1), m.group(2))


def crossed_bootstrap_ci(
    diff: np.ndarray, cells: list[tuple[str, str]], seed: int = BOOTSTRAP_SEED
) -> tuple[float, float]:
    """95 % pigeonhole (two-way) bootstrap of the mean paired difference (PRD §14.7, D70).

    Replicates cross trace slices with carbon starts, so two replicates that share either are
    not independent. Resampling slices and carbon starts separately, then averaging every
    sampled pair (Owen 2007), keeps both sources of shared variation; resampling the replicates
    as if independent (`bootstrap_ci`) leaves them out and gives intervals that are too narrow.
    Missing cells are skipped in each resample's mean. NaN when either factor has one level,
    since there is then nothing to resample along it.
    """
    diff = np.asarray(diff, dtype=float)
    slices = sorted({s for s, _ in cells})
    starts = sorted({c for _, c in cells})
    if len(cells) != len(diff) or len(slices) < 2 or len(starts) < 2:
        return float("nan"), float("nan")
    grid = np.zeros((len(slices), len(starts)))
    have = np.zeros_like(grid)
    for (s, c), d in zip(cells, diff, strict=True):
        i, j = slices.index(s), starts.index(c)
        grid[i, j] += d
        have[i, j] += 1
    rng = np.random.default_rng(seed + CROSSED_SEED_OFFSET)

    def counts(n: int) -> np.ndarray:
        picks = rng.integers(0, n, size=(BOOTSTRAP_RESAMPLES, n))
        w = np.zeros((BOOTSTRAP_RESAMPLES, n))
        np.add.at(w, (np.arange(BOOTSTRAP_RESAMPLES)[:, None], picks), 1.0)
        return w

    w_s, w_c = counts(len(slices)), counts(len(starts))
    num = np.einsum("bi,ij,bj->b", w_s, grid, w_c)
    den = np.einsum("bi,ij,bj->b", w_s, have, w_c)
    boot = num[den > 0] / den[den > 0]
    return float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def holm_adjust(p: np.ndarray | list[float]) -> np.ndarray:
    """Holm-Bonferroni adjusted p-values (step-down, monotone, capped at 1), input order."""
    p = np.asarray(p, dtype=float)
    m = len(p)
    order = np.argsort(p, kind="stable")
    adj = np.minimum(1.0, (m - np.arange(m)) * p[order])
    adj = np.maximum.accumulate(adj)
    out = np.empty(m)
    out[order] = adj
    return out


STAT_COLS = ["p_value", "p_holm", "cohens_dz"]


def add_holm(table: pd.DataFrame, family: str = "metric") -> pd.DataFrame:
    """Add `p_holm` (Holm across the policy comparisons within each `family` group), and put
    the statistics columns last, after the existing CI columns."""
    table = table.copy()
    if table.empty:
        table["p_holm"] = pd.Series(dtype=float)
    else:
        table["p_holm"] = table.groupby(family)["p_value"].transform(
            lambda s: pd.Series(holm_adjust(s.to_numpy()), index=s.index)
        )
    keep = [c for c in STAT_COLS if c in table.columns]
    return table[[c for c in table.columns if c not in STAT_COLS] + keep]


def _paired(summary: pd.DataFrame) -> pd.DataFrame:
    """Mean difference from `place_once` with a percentile bootstrap over replicates (§14.7)."""
    rows = []
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    if PAIRED_BASE not in set(summary["policy"]):
        return pd.DataFrame(
            columns=["policy", "metric", "n_replicates", "mean", "mean_base", "mean_diff"]
            + ["ci95_lo", "ci95_hi", "ci95_lo_crossed", "ci95_hi_crossed"]
            + ["p_value", "p_holm", "cohens_dz"]
        )
    base = summary[summary["policy"] == PAIRED_BASE].set_index("replicate")
    for policy in sorted(set(summary["policy"]) - {PAIRED_BASE}):
        here = summary[summary["policy"] == policy].set_index("replicate")
        for metric in PAIRED_METRICS:
            pair = pd.concat([here[metric], base[metric]], axis=1, keys=["a", "b"]).dropna()
            if pair.empty:
                continue
            diff = (pair["a"] - pair["b"]).to_numpy(dtype=float)
            lo, hi = bootstrap_ci(diff, rng)
            cells = [replicate_cell(r) for r in pair.index]
            xlo, xhi = (
                crossed_bootstrap_ci(diff, cells)  # type: ignore[arg-type]
                if all(cells)
                else (float("nan"), float("nan"))
            )
            rows.append(
                {
                    "policy": policy,
                    "metric": metric,
                    "n_replicates": len(diff),
                    "mean": pair["a"].mean(),
                    "mean_base": pair["b"].mean(),
                    "mean_diff": diff.mean(),
                    "ci95_lo": lo,
                    "ci95_hi": hi,
                    "ci95_lo_crossed": xlo,
                    "ci95_hi_crossed": xhi,
                    "p_value": paired_p_value(diff),
                    "cohens_dz": cohens_dz(diff),
                }
            )
    return add_holm(pd.DataFrame(rows))


def read_summary(runs_dir: Path) -> pd.DataFrame | None:
    path = runs_dir / "summary.csv"
    return pd.read_csv(path) if path.exists() else None


def _report_figures(summary: pd.DataFrame, coverage_path: Path, out: Path) -> None:
    from flipwise import figures

    out.mkdir(parents=True, exist_ok=True)
    means = summary.groupby("policy", sort=True).mean(numeric_only=True)
    unit = "relative kgCO2" if (summary["power_label"] == "relative").any() else "kgCO2"
    for name, x, xlabel, title in (
        ("emissions_vs_stage2", "stage2_calls", "Full re-scores", "Emissions against effort"),
        ("emissions_vs_moves", "moves", "Placement changes", "Emissions against churn"),
    ):
        figures.save(
            figures.scatter_policies(means, x, "kg_co2", xlabel, f"Emissions ({unit})", title),
            out / f"{name}.png",
        )
    figures.save(
        figures.bars_by_policy(
            means["miss_rate"], "Deadline-miss rate", "Deadline misses by policy", percent=True
        ),
        out / "miss_rate.png",
    )
    if coverage_path.exists():
        coverage = pd.read_csv(coverage_path).dropna(subset=["coverage"])
        if not coverage.empty:
            figures.save(figures.coverage_by_bucket(coverage), out / "carbon_coverage.png")
    rates = summary.loc[summary["policy"] == "decision_flip", "screen_pass_rate"].dropna()
    if not rates.empty:
        figures.save(figures.screen_pass_rates(rates), out / "screen_pass_rate.png")


def build_report(cmp_dir: Path, runs_root: Path | None = None) -> pd.DataFrame:
    """Rebuild `summary.csv`, `paired.csv` and figures from saved logs alone (R-REP-2)."""
    runs_root = runs_root if runs_root is not None else cmp_dir.parent
    if not (cmp_dir / "runs.json").exists():
        raise ReportError(f"{cmp_dir}: no runs.json; expected a results/compare_<hash> folder")
    records = json.loads((cmp_dir / "runs.json").read_text())
    if not records:
        raise ReportError(f"{cmp_dir}: no runs listed")
    # Every policy in a replicate must have seen the same inputs (R-FAIR-1, PRD §14.2).
    by_replicate: dict[str, set[str]] = {}
    for r in records:
        by_replicate.setdefault(r["replicate"], set()).add(r["scenario_hash"])
    mixed = {k: sorted(v) for k, v in by_replicate.items() if len(v) > 1}
    if mixed:
        raise ReportError(f"refusing to compare runs with different scenario hashes: {mixed}")
    summary = _add_deltas(pd.DataFrame([_summary_row(r, runs_root) for r in records]))
    summary = summary.sort_values(["replicate", "policy"], kind="stable").reset_index(drop=True)
    summary.to_csv(cmp_dir / "summary.csv", index=False, lineterminator="\n")
    _paired(summary).to_csv(cmp_dir / "paired.csv", index=False, lineterminator="\n")
    _report_figures(summary, cmp_dir / "carbon_coverage.csv", cmp_dir / "figures")
    return summary
