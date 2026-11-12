"""Saved results for the dashboard: test and validation tables, the scale study, carbon curves.

Read-only: these are the files `compare`/`report` already wrote (docs/test_results/,
docs/validation/) and `scripts/scale_study.py` (results/web/scale.json).
"""

from __future__ import annotations

import json
import math

import pandas as pd

from flipwise.simulator import Scenario
from flipwise.web.scenarios import REGION_NAMES, ROOT

SPLIT_DIRS = {"test": ROOT / "docs" / "test_results", "validation": ROOT / "docs" / "validation"}
ORDER = ("fcfs", "place_once", "periodic", "pred_error", "fixed_savings", "decision_flip", "pig")

# key, label, unit, better (low/high/none), group, plain-language meaning
METRICS = [
    (
        "kg_co2",
        "Emissions",
        "kg CO₂",
        "low",
        "Carbon",
        "Total CO₂ of all completed jobs, measured against carbon truth (not the forecast).",
    ),
    (
        "delta_kg_co2_pct_vs_fcfs",
        "vs fcfs",
        "%",
        "low",
        "Carbon",
        "Change in emissions relative to the carbon-blind fcfs baseline on the same replicate.",
    ),
    (
        "delta_kg_co2_pct_vs_place_once",
        "vs place_once",
        "%",
        "low",
        "Carbon",
        "Change in emissions relative to placing each job well once and never re-planning.",
    ),
    (
        "intensity_g_per_kwh",
        "Avg intensity",
        "g/kWh",
        "low",
        "Carbon",
        "Emissions divided by energy: how clean the electricity the jobs used was, on average.",
    ),
    (
        "energy_kwh",
        "Energy",
        "kWh",
        "none",
        "Carbon",
        "Energy used. Identical for every policy: they move work in time and space, they never "
        "make it use less.",
    ),
    (
        "completion",
        "Completed",
        "share",
        "high",
        "Service",
        "Share of jobs that finished before the simulation ended.",
    ),
    (
        "miss_rate",
        "Deadline misses",
        "share",
        "low",
        "Service",
        "Share of jobs that finished after their deadline (or not at all).",
    ),
    (
        "tardiness_mean_h",
        "Mean lateness",
        "h",
        "low",
        "Service",
        "Average hours past the deadline, counting on-time jobs as 0.",
    ),
    (
        "wait_from_arrival_mean_h",
        "Mean wait",
        "h",
        "low",
        "Service",
        "Average hours between a job arriving and starting (deferral plus queueing).",
    ),
    (
        "wait_from_arrival_p95_h",
        "p95 wait",
        "h",
        "low",
        "Service",
        "95th-percentile wait: the slow tail users notice.",
    ),
    (
        "stage2_calls",
        "Full re-scorings",
        "count",
        "low",
        "Scheduler work",
        "Times the planner scored every (datacentre × start slot) alternative for a pending job. "
        "The expensive operation decision-flip is designed to avoid.",
    ),
    (
        "screened",
        "Cheap screens",
        "count",
        "none",
        "Scheduler work",
        "Times decision-flip's Stage-1 lower-bound check ran (cheap; only decision-flip has it).",
    ),
    (
        "moves",
        "Moves",
        "count",
        "low",
        "Scheduler work",
        "Times a pending job was re-planned to a different datacentre or start slot.",
    ),
    (
        "moves_per_job",
        "Moves / job",
        "count",
        "low",
        "Scheduler work",
        "Average moves per job: how much a user's plan churns.",
    ),
    (
        "rescues",
        "Rescues",
        "count",
        "none",
        "Scheduler work",
        "Forced re-plans because the current plan became infeasible "
        "(e.g. would miss its deadline). "
        "Every policy except fcfs has the same rescue rule.",
    ),
    (
        "scheduler_s",
        "Planner CPU time",
        "s",
        "low",
        "Scheduler work",
        "Wall time inside the planner: placement + screen + re-score + rescue.",
    ),
    (
        "jobs_at_risk",
        "Jobs at risk",
        "count",
        "low",
        "Service",
        "Jobs that had to fall back to 'earliest finish' because no plan met the deadline.",
    ),
]

# Two-sided 95 % t quantiles by degrees of freedom (scipy is not an allowed dependency).
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
        9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120,
        17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 25: 2.060, 30: 2.042}  # fmt: skip


def _t95(df: int) -> float:
    return _T95.get(df) or _T95[min(_T95, key=lambda k: abs(k - df))]


def _clean(x):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return float(x)


def results(split: str) -> dict:
    d = SPLIT_DIRS[split]
    s = pd.read_csv(d / "summary.csv")
    s["scheduler_s"] = s[["scheduler_placement_s", "scheduler_screen_s", "scheduler_rescore_s",
                          "scheduler_rescue_s"]].sum(axis=1)  # fmt: skip
    table = {}
    for pol in ORDER:
        rows = s[s["policy"] == pol]
        out = {}
        for key, *_ in METRICS:
            v = pd.to_numeric(rows[key], errors="coerce").dropna()
            n = len(v)
            mean = v.mean() if n else None
            half = _t95(n - 1) * v.std(ddof=1) / math.sqrt(n) if n > 1 else None
            out[key] = {"mean": _clean(mean), "ci": _clean(half), "n": n}
        table[pol] = out
    pairwise = pd.read_csv(d / "pairwise.csv").to_dict(orient="records")
    dc = pd.read_csv(d / "decision_counts.csv")
    counts = (dc[dc["field"] == "decision_counts"].groupby(["policy", "key"])["count"].sum()
              / s["replicate"].nunique())  # fmt: skip
    decisions = {p: {k: float(v) for k, v in counts[p].items()} for p in ORDER if p in counts}
    diag = pd.read_csv(d / "diagnostics.csv")
    df_diag = diag[diag["policy"] == "decision_flip"]
    return {
        "split": split,
        "replicates": int(s["replicate"].nunique()),
        "jobs_per_replicate": float(s.groupby("replicate")["n_jobs"].first().mean()),
        "metrics": [
            dict(zip(("key", "label", "unit", "better", "group", "help"), m, strict=True))
            for m in METRICS
        ],  # fmt: skip
        "table": table,
        "pairwise": [
            {k: (_clean(v) if isinstance(v, float) else v) for k, v in r.items()} for r in pairwise
        ],  # fmt: skip
        "decisions": decisions,
        "theta_off_moves": _clean(pd.to_numeric(df_diag["moves_with_theta_off"]).mean()),
    }


def scale() -> dict | None:
    p = ROOT / "results" / "web" / "scale.json"
    return json.loads(p.read_text()) if p.exists() else None


def carbon_curves(sc: Scenario, step_s: int = 1800) -> dict:
    """Truth per region over the run, for the arena's carbon strip and the data page."""
    regions = sorted({d.region_id for d in sc.dcs})
    t0 = sc.start_s - sc.start_s % step_s
    slots = list(range(t0, sc.end_s, step_s))
    series = {}
    for r in regions:
        vals = []
        for s in slots:
            v = sc.truth.get(r, s) if sc.truth.has(r, s) else None
            vals.append(None if v is None else round(v, 1))
        series[r] = vals
    return {"t0": t0, "step": step_s, "series": series,
            "names": {r: REGION_NAMES.get(r, (f"Region {r}", ""))[0] for r in regions}}  # fmt: skip


def forecast_at(sc: Scenario, t_s: int, ahead_s: int = 36 * 3600) -> dict:
    """The newest forecast a scheduler could see at `t_s`, for the next `ahead_s`."""
    cap = sc.forecast.latest_capture(int(t_s))
    if cap is None:
        return {"capture": None, "series": {}}
    v = sc.forecast.at(cap)
    regions = sorted({d.region_id for d in sc.dcs})
    lo, hi = int(t_s) - int(t_s) % 1800, int(t_s) + ahead_s
    series = {r: [(s, round(x, 1)) for s, x in v.items(r) if lo <= s <= hi] for r in regions}
    return {"capture": cap, "series": series}
