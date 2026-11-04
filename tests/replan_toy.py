"""Small hand-checkable scenarios for re-planning tests (PRD §15.3).

The committed toy keeps its own hand-computed results, so each re-planning case here is one short
scenario whose expected outcome is worked out in the test itself. 3 datacentres, 4 GPUs each,
1 kW per GPU, regions 1, 2, 3 for dc0, dc1, dc2. All times are offsets from T0 in seconds.
"""

from __future__ import annotations

import pandas as pd

from flipwise.carbon import ForecastStore, Residuals, Truth
from flipwise.energy import PowerModel
from flipwise.models import DcConfig, Job, Placement
from flipwise.planner import PlannerParams
from flipwise.policies import Decision, PlaceOnce
from flipwise.simulator import Scenario

T0 = 1688342400
SLOT = 1800
N_SLOTS = 48


def job(job_id, gpu=1.0, runtime=3600, arrival=0, deadline=40000, q=None, cpu=0.0):
    """`q` is `(r_q05, r_q50, r_q90, r_q95)`; by default every estimate equals the runtime."""
    q05, q50, q90, q95 = q or (runtime,) * 4
    return Job(job_id, "u", T0 + arrival, gpu, cpu, 1.0, q05, q50, q90, q95, T0 + deadline, runtime)


def scenario(jobs, forecast, truth=None, residuals=None, h_defer_s=86400, end_slots=N_SLOTS):
    """`forecast`: `{capture_offset: {region: value or {first_slot_index: value, ...}}}`.

    A dict value is a step series: each key starts a new value, and `None` leaves slots unknown.
    A capture's slots run from that capture to the end of the scenario.
    """
    rows, cov = [], []
    for cap, by_region in forecast.items():
        cov.append((T0 + cap, "regional", T0 + cap, T0 + (end_slots - 1) * SLOT))
        for region, series in by_region.items():
            steps = series if isinstance(series, dict) else {0: series}
            for i in range(cap // SLOT, end_slots):
                value = steps[max(k for k in steps if k <= i)]
                if value is not None:
                    rows.append((region, T0 + i * SLOT, T0 + cap, float(value), "toy"))
    f = pd.DataFrame(
        rows, columns=["region_id", "slot_utc", "capture_utc", "forecast_g_per_kwh", "source"]
    )
    c = pd.DataFrame(
        cov, columns=["capture_utc", "endpoint", "window_first_utc", "window_last_utc"]
    )
    truth = truth or next(iter(forecast.values()))
    t_rows = []
    for region, series in truth.items():
        steps = series if isinstance(series, dict) else {0: series}
        for i in range(end_slots):
            value = steps[max(k for k in steps if k <= i)]
            t_rows.append((region, T0 + i * SLOT, 0.0 if value is None else float(value)))
    t = pd.DataFrame(t_rows, columns=["region_id", "slot_utc", "truth_g_per_kwh"])
    return Scenario(
        name="replan",
        jobs=list(jobs),
        dcs=[DcConfig(i, i + 1, 4.0, 32.0, 100.0) for i in range(3)],
        forecast=ForecastStore(f, c, [1, 2, 3]),
        truth=Truth(t),
        power=PowerModel(1.0, 0.0),
        start_s=T0,
        end_s=T0 + end_slots * SLOT,
        params=PlannerParams(h_defer_s=h_defer_s),
        residuals=residuals or Residuals(),
        scenario_hash="replan",
    )


def forced(base, plans):
    """`base` policy instance, but listed jobs are placed where `plans` says at arrival."""

    def on_arrival(view, job_id):
        if job_id in plans:
            dc, offset = plans[job_id]
            d = Decision(job_id, "PLACE", Placement(dc, T0 + offset))
            if hasattr(base, "after_placement"):
                base.after_placement(view, d)
            return d
        return type(base).on_arrival(base, view, job_id)

    base.on_arrival = on_arrival
    return base


def forced_place_once(plans):
    return forced(PlaceOnce(), plans)


def by_id(result):
    return {j.job_id: j for j in result.jobs}


def kinds(result, job_id):
    return [d["kind"] for d in result.decisions if d["job_id"] == job_id]


def state_changes(result):
    """The rows that change a plan; check-only rows may differ between equivalent policies."""
    keep = {"PLACE", "FALLBACK", "MOVE", "RESCUE", "REJECT"}
    return [d for d in result.decisions if d["kind"] in keep]
