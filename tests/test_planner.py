import pytest

from flipwise import planner
from flipwise.policies import Policy, initial_placement
from flipwise.simulator import Simulator

T0 = 1688342400


class _Probe(Policy):
    """place_once, plus a hook that inspects the planner at a chosen job's arrival."""

    name = "probe"

    def __init__(self, probe):
        self.probe = probe

    def on_arrival(self, view, job_id):
        self.probe(view, job_id)
        return initial_placement(view, job_id)


def _view_at(toy, job_id, evals=()):
    """Run the toy and, at `job_id`'s arrival, evaluate candidates `(dc, slot)` in `evals`.

    The view is live, so everything is computed inside the probe, at arrival time."""
    out = {}

    def probe(view, jid):
        if jid == job_id:
            job = view.job(jid)
            out["job"], out["params"] = job, view.params
            out["cands"] = planner.candidates(view, job)
            out["evals"] = {e: planner.evaluate(view, job, *e) for e in evals}

    Simulator(toy, _Probe(probe)).run()
    return out


def test_feasibility_reason_codes_r_plan_1(toy):
    import dataclasses

    toy.dcs[2] = dataclasses.replace(toy.dcs[2], cap_gpu=0.5)  # J4 (1 GPU) cannot fit dc2
    late = T0 + 21600 - 1800 + 1800  # after latest_release = floor(deadline - r_q90)
    far = T0 + 10 * 86400  # beyond the 9-day profile horizon: no projected start
    probes = [(2, T0 + 1800), (1, T0), (1, T0 + 1800), (1, late), (1, far)]
    ev = _view_at(toy, "J4", probes)["evals"]
    assert ev[(2, T0 + 1800)].reject_reason == planner.NO_FIT
    assert ev[(1, T0)].reject_reason == planner.OUT_OF_RANGE  # before slot0
    assert ev[(1, T0 + 1800)].feasible
    assert ev[(1, late)].reject_reason == planner.OUT_OF_RANGE
    assert ev[(1, far)].reject_reason == planner.NO_START
    j5 = _view_at(toy, "J5")
    assert all(c.reject_reason == planner.DEADLINE_RISK for c in j5["cands"])


def test_no_carbon_reason_r_plan_1(toy):
    import pandas as pd

    from flipwise.carbon import ForecastStore

    f = pd.read_csv("tests/fixtures/toy/carbon_forecast.csv")
    f = f[~((f.region_id == 3) & (f.slot_utc >= T0 + 1800))]  # Chennai unknown from slot 1
    cov = pd.read_csv("tests/fixtures/toy/capture_coverage.csv")
    toy.forecast = ForecastStore(f, cov, [1, 2, 3])
    ev = _view_at(toy, "J4", [(2, T0 + 1800), (2, T0 + 4 * 1800)])["evals"]
    # Slots 1..2 back-fill from slot 0 by persistence; slot 3 onward is unknown.
    assert ev[(2, T0 + 1800)].feasible
    assert ev[(2, T0 + 4 * 1800)].reject_reason == planner.NO_CARBON


def test_fallback_earliest_conservative_finish_r_plan_2(toy):
    ctx = _view_at(toy, "J5")
    fb = planner.fallback(ctx["cands"], ctx["job"], ctx["params"])
    assert fb is not None and (fb.dc_id, fb.release_slot) == (1, T0 + 1800)


def test_lead_bucket_edges():
    assert [planner.lead_bucket(T0 + h * 3600, T0) for h in (0, 5, 6, 11, 12, 23, 24, 50)] == [
        0, 0, 1, 1, 2, 2, 3, 3,
    ]  # fmt: skip


def test_score_matches_hand_value(toy):
    ctx = _view_at(toy, "J6")
    best = planner.best_candidate(ctx["cands"])
    assert (best.dc_id, best.release_slot, best.s_q50) == (0, T0 + 1800, T0 + 5400)
    assert best.s_hat == pytest.approx(0.15, abs=1e-12)
