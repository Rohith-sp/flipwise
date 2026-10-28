"""Information boundary (PRD §8.7)."""

import copy
import dataclasses

import pandas as pd
import pytest

from flipwise.carbon import ForecastStore, Truth
from flipwise.policies import make_policy
from flipwise.simulator import JobInfo, SchedulerView, Simulator

T0 = 1688342400


def _decisions_until(res, t):
    return [d for d in res.decisions if d["time_s"] <= t]


@pytest.mark.parametrize("policy", ["fcfs", "place_once"])
def test_future_captures_and_truth_do_not_leak_r_leak_2(toy, policy):
    t = T0 + 1800  # all arrivals done; capture v1 (T0+3600) is in the future
    base = Simulator(toy, make_policy(policy)).run()
    f = pd.read_csv("tests/fixtures/toy/carbon_forecast.csv")
    f.loc[f.capture_utc > t, "forecast_g_per_kwh"] = 9999.0
    cov = pd.read_csv("tests/fixtures/toy/capture_coverage.csv")
    tr = pd.read_csv("tests/fixtures/toy/carbon_truth.csv")
    tr["truth_g_per_kwh"] = 1.0
    sc = copy.copy(toy)
    sc.forecast, sc.truth = ForecastStore(f, cov, [1, 2, 3]), Truth(tr)
    assert _decisions_until(Simulator(sc, make_policy(policy)).run(), t) == _decisions_until(
        base, t
    )


@pytest.mark.parametrize("policy", ["fcfs", "place_once"])
def test_unfinished_runtimes_do_not_leak_r_leak_1(toy, policy):
    t = T0 + 1800
    base = Simulator(toy, make_policy(policy)).run()
    done_by_t = {j.job_id for j in base.jobs if j.end_s is not None and j.end_s <= t}
    sc = copy.copy(toy)
    sc.jobs = [
        j
        if j.job_id in done_by_t
        else dataclasses.replace(j, runtime_actual_s=j.runtime_actual_s * 10)
        for j in toy.jobs
    ]
    assert _decisions_until(Simulator(sc, make_policy(policy)).run(), t) == _decisions_until(
        base, t
    )


def test_view_exposes_no_hidden_fields():
    hidden = {"runtime_actual_s", "end_s"}
    assert not hidden & {f.name for f in dataclasses.fields(JobInfo)}
    assert not hidden & {n for n in dir(SchedulerView) if not n.startswith("_")}
    assert "truth" not in {n for n in dir(SchedulerView) if not n.startswith("_")}
