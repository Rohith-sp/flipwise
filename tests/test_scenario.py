"""Real-trace scenario builder (PRD §6.3, §6.5, §6.6, §8.1, §14.2), on small hand-made files."""

import datetime as dt

import pandas as pd
import pytest
import yaml

from flipwise.config import apply_overrides
from flipwise.errors import ConfigError
from flipwise.estimates import fit_runtime, gpu_class
from flipwise.scenario import Replicate, build_replicate, sampling_key
from flipwise.validate import monday_start_utc

ORIGIN = -28800
DAY = 86400
C0 = monday_start_utc(dt.date(2023, 7, 3))
RES_LO = int(dt.datetime(2023, 3, 13, tzinfo=dt.UTC).timestamp())
RES_HI = int(dt.datetime(2023, 3, 16, tzinfo=dt.UTC).timestamp())


def _job(job_id, user, day, runtime, gpu=1.0, cpu=1.0, mem=1.0, seconds=0):
    t = ORIGIN + day * DAY + seconds
    return {
        "job_id": job_id, "user": user, "trace_arrival_s": t, "trace_start_s": t,
        "trace_end_s": t + runtime, "runtime_actual_s": runtime, "gpu_req": gpu, "cpu_req": cpu,
        "mem_req_gb": mem, "gpu_type": "V100", "n_tasks": 1, "gpu_assumed_zero": int(gpu == 0),
    }  # fmt: skip


@pytest.fixture
def world(tmp_path):
    jobs = [_job(f"cal{i}", "alice", 10, 100 + i) for i in range(20)]  # enough for user quantiles
    jobs += [_job("cal_bob", "bob", 10, 7000, gpu=4.0)]  # below n_min: GPU-class fallback
    jobs += [_job("late_cal", "alice", 22, 999999)]  # days 21-24 belong to no split
    jobs += [
        _job("a", "alice", 25, 3600, seconds=3600),
        _job("b", "bob", 26, 7200, gpu=4.0),
        _job("huge", "alice", 27, 60, gpu=1000.0),  # larger than any datacentre
        # Two week-long jobs set capacity at about 5.4 GPUs, so a, b and these fit.
        _job("long1", "alice", 25, 7 * DAY, gpu=4.0),
        _job("long2", "alice", 25, 7 * DAY, gpu=4.0),
        _job("next_week", "alice", 32, 3600),
    ]
    data = tmp_path / "data"
    data.mkdir()
    pd.DataFrame(jobs).to_csv(data / "jobs.csv", index=False)
    cal_slots = range(RES_LO, RES_HI, 1800)
    run_slots = range(C0 - DAY, C0 + 3 * DAY, 1800)
    caps = [(RES_LO, RES_LO, RES_HI - 1800), (C0 - 1800, C0 - 1800, C0 + 2 * DAY)]
    forecast = [(r, k, RES_LO, 500.0, "t") for r in (1, 2, 3) for k in cal_slots]
    forecast += [(r, k, C0 - 1800, 400.0 + r, "t") for r in (1, 2, 3) for k in run_slots
                 if k >= C0 - 1800]  # fmt: skip
    pd.DataFrame(
        forecast, columns=["region_id", "slot_utc", "capture_utc", "forecast_g_per_kwh", "source"]
    ).to_csv(data / "forecast.csv", index=False)
    pd.DataFrame(
        [(c, "regional_fw48h", a, b, "t") for c, a, b in caps],
        columns=["capture_utc", "endpoint", "window_first_utc", "window_last_utc", "source"],
    ).to_csv(data / "coverage.csv", index=False)
    pd.DataFrame(
        [(r, k, 510.0, "t", 0) for r in (1, 2, 3) for k in (*cal_slots, *run_slots)],
        columns=["region_id", "slot_utc", "truth_g_per_kwh", "truth_kind", "interpolated"],
    ).to_csv(data / "truth.csv", index=False)
    (tmp_path / "energy.yaml").write_text(
        yaml.safe_dump({"power": {"p_gpu_kw": 0.3, "p_cpu_kw": 0.01, "label": "relative"}})
    )
    cfg = {
        "data": {"jobs": "data/jobs.csv", "forecast": "data/forecast.csv",
                 "coverage": "data/coverage.csv", "truth": "data/truth.csv"},
        "regions": [1, 2, 3], "horizon_days": 15, "energy": "energy.yaml",
        "trace_day_origin_s": ORIGIN,
        "cluster_totals": {"machines": 1897, "cpu_cores": 156576, "mem_gb": 948224, "gpus": 6742},
        "scenario": {"rho": 0.5, "slack_base_s": 14400, "k_slack": 2.0, "h_defer_s": 86400,
                     "feasibility": "conservative", "missing_gpu_policy": "zero",
                     "phase_shift_h": 0, "n_min": 20},
        "splits": {"runtime_fit_trace_days": [0, 21],
                   "residual_fit_carbon": ["2023-03-13", "2023-03-15"]},
    }  # fmt: skip
    return cfg, tmp_path


REP = Replicate("w", (25, 32), "2023-07-03")


def test_time_mapping_keeps_weekday_and_clock_pr_6_3(world):
    """Day 25 + 1 h maps to one hour after Monday 00:00 IST."""
    cfg, root = world
    sc = build_replicate(cfg, REP, root=root)
    jobs = {j.job_id: j for j in sc.jobs}
    assert jobs["a"].arrival_s == C0 + 3600
    assert jobs["b"].arrival_s == C0 + DAY
    assert (sc.start_s, sc.end_s) == (C0, C0 + 15 * DAY)


def test_slice_excludes_other_weeks_and_jobs_that_fit_nowhere(world):
    cfg, root = world
    sc = build_replicate(cfg, REP, root=root)
    assert {j.job_id for j in sc.jobs} == {"a", "b", "long1", "long2"}
    assert sc.build_report["excluded_no_fit"] == 1


def test_capacity_follows_load_and_cluster_ratios(world):
    """PRD §8.1: cap_gpu = Σ g·r / (N ρ W), computed before excluding anything; CPU and memory
    follow the cluster totals."""
    cfg, root = world
    sc = build_replicate(cfg, REP, root=root)
    gpu_s = 1.0 * 3600 + 4.0 * 7200 + 1000.0 * 60 + 2 * 4.0 * 7 * DAY
    expected = gpu_s / (3 * 0.5 * 7 * DAY)
    assert sc.dcs[0].cap_gpu == pytest.approx(expected)
    assert sc.dcs[0].cap_cpu == pytest.approx(expected * 156576 / 6742)
    assert sc.dcs[0].cap_mem_gb == pytest.approx(expected * 948224 / 6742)
    assert [d.region_id for d in sc.dcs] == [1, 2, 3]


def test_estimates_are_frozen_from_calibration_only_and_deadline_uses_q90(world):
    """PRD §6.5, §6.6: evaluation jobs and days 21-24 do not affect estimates."""
    cfg, root = world
    sc = build_replicate(cfg, REP, root=root)
    jobs = {j.job_id: j for j in sc.jobs}
    a, b = jobs["a"], jobs["b"]
    assert a.r_q50_s < 120  # alice's calibration runtimes are 100..119; 999999 and 3600 ignored
    assert b.r_q50_s == 7000  # bob has too few jobs: class (1, 8] holds only his calibration job
    assert a.deadline_s == a.arrival_s + 14400 + int(2.0 * a.r_q90_s)
    assert sc.build_report["runtime_source"] == {"user": 3, "class": 1, "global": 0}


def test_residuals_fit_and_are_cached(world):
    cfg, root = world
    first = build_replicate(cfg, REP, root=root)
    assert (root / "data" / "carbon_residuals.json").exists()
    second = build_replicate(cfg, REP, root=root)
    assert first.residuals == second.residuals
    assert first.scenario_hash == second.scenario_hash
    assert first.residuals.e05[0] == pytest.approx(10.0)  # A − F = 510 − 500 everywhere


def test_sampling_is_deterministic_and_seed_dependent():
    assert sampling_key("job", 0) == sampling_key("job", 0)
    assert sampling_key("job", 0) != sampling_key("job", 1)
    keys = [sampling_key(f"job{i}", 0) for i in range(2000)]
    assert 0.07 < sum(k < 0.1 for k in keys) / len(keys) < 0.13


def test_hash_changes_with_inputs(world):
    cfg, root = world
    base = build_replicate(cfg, REP, root=root).scenario_hash
    other = build_replicate(apply_overrides(cfg, ["scenario.rho=0.9"]), REP, root=root)
    assert other.scenario_hash != base


def test_missing_power_is_refused(world):
    cfg, root = world
    (root / "energy.yaml").write_text(yaml.safe_dump({"power": {"p_gpu_kw": None}}))
    with pytest.raises(ConfigError, match="B3"):
        build_replicate(cfg, REP, root=root)


def test_overrides_reject_unknown_keys():
    cfg = {"scenario": {"rho": 0.7}}
    assert apply_overrides(cfg, ["scenario.rho=0.4"])["scenario"]["rho"] == 0.4
    assert cfg["scenario"]["rho"] == 0.7
    for bad in ("scenario.nope=1", "nope.rho=1", "scenario.rho"):
        with pytest.raises(ConfigError):
            apply_overrides(cfg, [bad])


def test_gpu_classes_and_runtime_fallback_chain():
    assert [gpu_class(g) for g in (0, 0.5, 1, 2, 8, 9)] == [0, 1, 1, 2, 2, 3]
    cal = pd.DataFrame({"user": ["u"] * 3, "gpu_req": [1.0] * 3, "runtime_actual_s": [10, 20, 30]})
    model = fit_runtime(cal, n_min=3)
    assert model.estimate("u", 1.0) == ((11, 20, 28, 29), "user")
    assert model.estimate("other", 1.0)[1] == "class"
    assert model.estimate("other", 100.0)[1] == "global"
