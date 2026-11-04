"""Per-run metrics from saved logs (PRD §14.1). Pure functions of `jobs.csv`, `decisions.csv` and
the policy's work counters, so `report` can rebuild every table without re-simulating (R-REP-2)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from flipwise.carbon import WIDEST_BUCKET, lead_bucket
from flipwise.models import floor_to_slot
from flipwise.simulator import Scenario

FALLBACK_FLAG_SHARE = 0.10  # PRD §10.7: a run above this share of comparisons is flagged


def _num(x) -> float | None:
    """A JSON-safe float; a missing or undefined value is None, never NaN (PRD §13.3)."""
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) or math.isinf(x) else x


def _ratio(a, b) -> float | None:
    return None if not b else _num(a / b)


def _quantiles_h(s: pd.Series) -> dict[str, float | None]:
    if s.empty:
        return {"mean": None, "median": None, "p95": None}
    return {
        "mean": _num(s.mean() / 3600),
        "median": _num(s.median() / 3600),
        "p95": _num(s.quantile(0.95) / 3600),
    }


def compute_metrics(
    jobs: pd.DataFrame,
    decisions: pd.DataFrame,
    stats: dict,
    dcs: list[dict],
    start_s: int,
    end_s: int,
) -> dict:
    """§14.1 metrics. `J` is every job in `jobs`; `J_c` those completed by the stop time."""
    n = len(jobs)
    done = jobs[jobs["incomplete"] == 0]
    kg, kwh = done["kg_co2"].sum(), done["energy_kwh"].sum()
    # Actual runtime is evaluator-only, so this rule changes reporting and never decisions (§14.1).
    estimable = done[done["runtime_s"] <= done["r_q90_s"]]
    kg_e, kwh_e = estimable["kg_co2"].sum(), estimable["energy_kwh"].sum()
    missed = int(done["deadline_missed"].sum()) + (n - len(done))
    tardy = (done["end_s"] - done["deadline_s"]).clip(lower=0)
    started = jobs[jobs["start_s"].notna()]
    m: dict = {
        "n_jobs": n,
        "n_completed": len(done),
        "completion": _ratio(len(done), n),
        "kg_co2": _num(kg),
        "energy_kwh": _num(kwh),
        "intensity_g_per_kwh": _ratio(kg * 1000, kwh),
        "n_estimable": len(estimable),
        "kg_co2_estimable": _num(kg_e),
        "energy_kwh_estimable": _num(kwh_e),
        "intensity_g_per_kwh_estimable": _ratio(kg_e * 1000, kwh_e),
        "miss_rate": _ratio(missed, n),
        "tardiness_mean_h": _num(tardy.mean() / 3600) if len(done) else None,
        "tardiness_p95_h": _num(tardy.quantile(0.95) / 3600) if len(done) else None,
    }
    for name, frm in (("release", "release_slot"), ("arrival", "arrival_s")):
        q = _quantiles_h(started["start_s"] - started[frm])
        m.update({f"wait_from_{name}_{k}_h": v for k, v in q.items()})

    horizon_s = end_s - start_s
    clipped = started["end_s"].fillna(end_s).clip(upper=end_s) - started["start_s"]
    for dc in dcs:
        here = started["dc_id"] == dc["dc_id"]
        for label, col, cap in (
            ("gpu", "gpu_req", dc["cap_gpu"]),
            ("cpu", "cpu_req", dc["cap_cpu"]),
            ("mem", "mem_req_gb", dc["cap_mem_gb"]),
        ):
            used = (started.loc[here, col] * clipped[here]).sum()
            m[f"util_{label}_dc{dc['dc_id']}"] = _ratio(used, cap * horizon_s)

    stage2, screened = stats.get("stage2_calls", 0), stats.get("screened", 0)
    fallbacks = stats.get("fallbacks", {})
    comparisons = stats.get("comparisons", 0)
    fallback_share = _ratio(sum(fallbacks.values()), comparisons)
    moves = jobs["n_moves"]
    m.update(
        {
            "stage2_calls": stage2,
            "screened": screened,
            "screen_pass_rate": _ratio(stage2, screened),
            "moves": int(moves.sum()),
            "moves_per_job": _ratio(moves.sum(), n),
            "moves_max": int(moves.max()) if n else 0,
            "moves_p95": _num(moves.quantile(0.95)) if n else None,
            "rescues": int(jobs["rescued"].sum()),
            "jobs_at_risk": int(jobs["deadline_risk"].sum()),
            "fallback_share": fallback_share,
            "fallback_flag": int(
                fallback_share is not None and fallback_share > FALLBACK_FLAG_SHARE
            ),
            "scheduler_placement_s": _num(stats.get("arrival_s", 0.0)),
            "scheduler_screen_s": _num(stats.get("screen_s", 0.0)),
            "scheduler_rescore_s": _num(stats.get("rescore_s", 0.0)),
            "scheduler_rescue_s": _num(stats.get("rescue_s", 0.0)),
        }
    )

    within = (done["r_q05_s"] <= done["runtime_s"]) & (done["runtime_s"] <= done["r_q95_s"])
    m["runtime_coverage"] = _num(within.mean()) if len(done) else None
    m["runtime_width_mean_h"] = (
        _num((done["r_q95_s"] - done["r_q05_s"]).mean() / 3600) if len(done) else None
    )
    planned = started[started["plan_w_hi_s"].notna()]
    realised = planned["start_s"] - planned["release_slot"]
    in_wait = (planned["plan_w_lo_s"] <= realised) & (realised <= planned["plan_w_hi_s"])
    m["wait_coverage"] = _num(in_wait.mean()) if len(planned) else None
    m["wait_width_mean_h"] = (
        _num((planned["plan_w_hi_s"] - planned["plan_w_lo_s"]).mean() / 3600)
        if len(planned)
        else None
    )
    m["decision_counts"] = {
        str(k): int(v) for k, v in sorted(decisions["kind"].value_counts().items())
    }
    m["reason_counts"] = {
        str(k): int(v)
        for k, v in sorted(decisions["reason"].dropna().value_counts().items())
        if str(k)
    }
    m["interval_fallbacks"] = dict(sorted(fallbacks.items()))
    return m


def metrics_from_run_dir(run_dir: Path) -> dict:
    """Recompute a run's metrics from its saved files alone."""
    manifest = json.loads((run_dir / "manifest.json").read_text())
    stats = json.loads((run_dir / "policy_stats.json").read_text())
    jobs = pd.read_csv(run_dir / "jobs.csv", dtype={"job_id": str, "user": str})
    decisions = pd.read_csv(run_dir / "decisions.csv", dtype={"job_id": str})
    return compute_metrics(
        jobs, decisions, stats, manifest["dcs"], manifest["start_s"], manifest["end_s"]
    )


def carbon_coverage(scenario: Scenario) -> list[dict]:
    """Carbon interval coverage per lead bucket (§14.1). It depends only on the replicate, so it
    is computed once per replicate, not per policy. Uses truth: evaluator side only."""
    inside = [0] * (WIDEST_BUCKET + 1)
    total = [0] * (WIDEST_BUCKET + 1)
    width = [0.0] * (WIDEST_BUCKET + 1)
    truth = scenario.truth
    regions = sorted({d.region_id for d in scenario.dcs})
    for capture in scenario.forecast.captures:
        if not scenario.start_s <= capture <= scenario.end_s:
            continue
        vintage = scenario.forecast.at(capture)
        for r in regions:
            e05, e95 = scenario.residuals.for_region(r)
            for k, f in vintage.items(r):
                if k < capture or not truth.has(r, k):
                    continue
                b = lead_bucket(k, capture)
                lo, hi = max(0.0, f + e05[b]), f + e95[b]
                total[b] += 1
                inside[b] += lo <= truth.get(r, k) <= hi
                width[b] += hi - lo
    return [
        {
            "lead_bucket": b,
            "n": total[b],
            "coverage": _ratio(inside[b], total[b]),
            "mean_width_g_per_kwh": _ratio(width[b], total[b]),
        }
        for b in range(WIDEST_BUCKET + 1)
    ]


def carbon_timeline(scenario: Scenario) -> list[dict]:
    """The latest forecast of each slot as a run saw it: the curves on the dashboard's timeline.
    Saved at `compare` time because the dashboard reads saved files only (PRD §13.3)."""
    rows = []
    regions = sorted({d.region_id for d in scenario.dcs})
    for capture in scenario.forecast.captures:
        if not scenario.start_s <= capture <= scenario.end_s:
            continue
        vintage = scenario.forecast.at(capture)
        slot = floor_to_slot(capture)
        for r in regions:
            value = vintage.get(r, slot)
            if value is not None:
                rows.append(
                    {"region_id": r, "slot_utc": slot, "forecast_g_per_kwh": value.g_per_kwh}
                )
    return rows
