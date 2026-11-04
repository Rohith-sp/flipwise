"""Metrics follow PRD §14.1 (R-MET-1). Expected values are worked out by hand."""

from pathlib import Path

import pandas as pd
import pytest
import yaml

from flipwise.metrics import carbon_coverage, compute_metrics
from flipwise.policies import make_policy
from flipwise.reporting import job_rows
from flipwise.simulator import Simulator

EXPECTED = yaml.safe_load((Path(__file__).parent / "fixtures/toy/expected.yaml").read_text())
DCS = [{"dc_id": 0, "cap_gpu": 4.0, "cap_cpu": 32.0, "cap_mem_gb": 100.0}]


def _metrics_for(toy, policy):
    res = Simulator(toy, make_policy(policy)).run()
    dcs = [
        {"dc_id": d.dc_id, "cap_gpu": d.cap_gpu, "cap_cpu": d.cap_cpu, "cap_mem_gb": d.cap_mem_gb}
        for d in toy.dcs
    ]
    decisions = pd.DataFrame(res.decisions).assign(reason=lambda d: d["reason"].fillna(""))
    return compute_metrics(
        pd.DataFrame(job_rows(res)), decisions, res.stats, dcs, toy.start_s, toy.end_s
    )


@pytest.mark.parametrize("policy", ["fcfs", "place_once"])
def test_toy_metrics_match_expected_r_met_1(toy, policy):
    got = _metrics_for(toy, policy)
    for key, want in EXPECTED["policies"][policy]["metrics"].items():
        assert got[key] == pytest.approx(want, abs=1e-9), key


def _jobs(**overrides):
    base = {
        "job_id": ["a", "b", "c"],
        "gpu_req": [1.0, 1.0, 1.0],
        "cpu_req": [0.0, 0.0, 0.0],
        "mem_req_gb": [1.0, 1.0, 1.0],
        "arrival_s": [0, 0, 0],
        "release_slot": [0, 0, 0],
        "start_s": [0, 3600, None],
        "end_s": [3600, 7200 + 3600, None],
        "deadline_s": [7200, 7200, 7200],
        "dc_id": [0, 0, 0],
        "runtime_s": [3600, 7200, None],
        "r_q05_s": [1800, 1800, 1800],
        "r_q50_s": [3600, 3600, 3600],
        "r_q90_s": [3600, 3600, 3600],
        "r_q95_s": [7200, 7200, 7200],
        "energy_kwh": [1.0, 2.0, None],
        "kg_co2": [0.1, 0.8, None],
        "deadline_missed": [0, 1, 0],
        "n_moves": [0, 2, 1],
        "rescued": [0, 1, 0],
        "deadline_risk": [0, 1, 0],
        "incomplete": [0, 0, 1],
        "plan_w_lo_s": [0, 0, None],
        "plan_w_hi_s": [0, 1800, None],
    }
    return pd.DataFrame({**base, **overrides})


NO_DECISIONS = pd.DataFrame({"kind": ["PLACE"], "reason": [""]})


def test_estimable_jobs_exclude_overruns_and_keep_both_values_r_met_1():
    """§14.1: job b outran r_q90, so J_e = {a}; both totals are always reported."""
    m = compute_metrics(_jobs(), NO_DECISIONS, {}, DCS, 0, 86400)
    assert m["kg_co2"] == pytest.approx(0.9) and m["kg_co2_estimable"] == pytest.approx(0.1)
    assert m["intensity_g_per_kwh"] == pytest.approx(300.0)
    assert m["intensity_g_per_kwh_estimable"] == pytest.approx(100.0)
    assert m["n_estimable"] == 1


def test_miss_rate_counts_late_and_unfinished_jobs_r_met_1():
    m = compute_metrics(_jobs(), NO_DECISIONS, {}, DCS, 0, 86400)
    assert m["miss_rate"] == pytest.approx(2 / 3)
    assert m["completion"] == pytest.approx(2 / 3)


def test_coverages_and_tardiness_r_met_1():
    m = compute_metrics(_jobs(), NO_DECISIONS, {}, DCS, 0, 86400)
    assert m["runtime_coverage"] == 1.0
    # a waited 0 within [0, 0]; b waited 3600 beyond [0, 1800].
    assert m["wait_coverage"] == 0.5
    assert m["tardiness_mean_h"] == pytest.approx(0.5)  # (0 + 1 h) over completed jobs


def test_utilisation_is_clipped_to_the_horizon_r_met_1():
    m = compute_metrics(_jobs(), NO_DECISIONS, {}, DCS, 0, 7200)
    # GPU-seconds inside 2 h: a 3600, b 3600 (of 7200) over 4 GPUs × 7200 s.
    assert m["util_gpu_dc0"] == pytest.approx(7200 / (4 * 7200))


def test_undefined_values_are_null_not_nan_prd_13_3():
    empty = _jobs().iloc[0:0]
    m = compute_metrics(empty, NO_DECISIONS.iloc[0:0], {}, DCS, 0, 86400)
    for key in ("completion", "miss_rate", "intensity_g_per_kwh", "screen_pass_rate"):
        assert m[key] is None
    assert m["moves_per_job"] is None


def test_screen_pass_rate_and_fallback_flag_prd_10_7():
    stats = {
        "stage2_calls": 20,
        "screened": 100,
        "comparisons": 20,
        "fallbacks": {"INTERVAL_TOO_WIDE": 3},
    }
    m = compute_metrics(_jobs(), NO_DECISIONS, stats, DCS, 0, 86400)
    assert m["screen_pass_rate"] == 0.2 and m["fallback_share"] == pytest.approx(0.15)
    assert m["fallback_flag"] == 1
    stats["fallbacks"] = {"INTERVAL_TOO_WIDE": 2}
    assert compute_metrics(_jobs(), NO_DECISIONS, stats, DCS, 0, 86400)["fallback_flag"] == 0


def test_carbon_coverage_on_the_toy_r_met_1(toy):
    """Zero residuals: an interval holds only slots where forecast equals truth exactly."""
    rows = carbon_coverage(toy)
    assert [r["lead_bucket"] for r in rows] == [0, 1, 2, 3]
    assert rows[0]["n"] > 0 and rows[0]["mean_width_g_per_kwh"] == 0.0
    assert rows[3]["coverage"] is None  # no lead time that long on the toy
