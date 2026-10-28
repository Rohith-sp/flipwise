import math

import pandas as pd
import pytest

from flipwise.errors import ChecksumError
from flipwise.ingest import build_jobs
from flipwise.trace import ARCHIVE_SHA256, JOB_COLUMNS, TASK_COLUMNS, verify_archives

NAN = math.nan


def _jobs(rows):
    return pd.DataFrame(rows, columns=JOB_COLUMNS)


def _tasks(rows):
    return pd.DataFrame(rows, columns=TASK_COLUMNS)


@pytest.fixture
def raw():
    # job_name, inst_id, user, status, start_time, end_time
    jobs = _jobs(
        [
            ["ok", "i", "u1", "Terminated", 100.0, 900.0],
            ["multi", "i", None, "Terminated", 50.0, 900.0],
            ["cpuonly", "i", "u2", "Terminated", 10.0, 90.0],
            ["zero_len", "i", "u2", "Terminated", 20.0, 30.0],
            ["failed", "i", "u1", "Failed", 1.0, 2.0],
            [None, "i", "u1", "Terminated", 1.0, 2.0],
            ["no_arrival", "i", "u1", "Terminated", NAN, 2.0],
            ["no_tasks", "i", "u1", "Terminated", 5.0, 9.0],
            ["bad_time", "i", "u1", "Terminated", 5.0, 9.0],
            ["neg_rt", "i", "u1", "Terminated", 5.0, 9.0],
            ["no_cpu", "i", "u1", "Terminated", 5.0, 9.0],
            ["no_mem", "i", "u1", "Terminated", 5.0, 9.0],
            ["gpu_typed_nan", "i", "u1", "Terminated", 5.0, 9.0],
        ]
    )
    # job_name, task_name, inst_num, status, start, end, plan_cpu, plan_mem, plan_gpu, gpu_type
    tasks = _tasks(
        [
            ["ok", "t", 2.0, "Terminated", 110.0, 410.0, 600.0, 10.0, 50.0, "V100"],
            ["multi", "a", 1.0, "Terminated", 60.0, 100.0, 100.0, 1.0, 100.0, "T4"],
            ["multi", "b", 1.0, "Terminated", 70.0, 200.0, 100.0, 1.0, 100.0, "P100"],
            ["multi", "c", 1.0, "Terminated", 80.0, 150.0, 100.0, 1.0, 100.0, "P100"],
            ["cpuonly", "t", 1.0, "Terminated", 11.0, 20.0, 400.0, 2.0, NAN, None],
            ["zero_len", "t", 1.0, "Terminated", 21.0, 21.0, 100.0, 1.0, 10.0, "MISC"],
            ["bad_time", "t", 1.0, "Terminated", NAN, 8.0, 100.0, 1.0, 100.0, "T4"],
            ["neg_rt", "t", 1.0, "Terminated", 9.0, 6.0, 100.0, 1.0, 100.0, "T4"],
            ["no_cpu", "t", 1.0, "Terminated", 6.0, 8.0, NAN, 1.0, 100.0, "T4"],
            ["no_mem", "t", 1.0, "Terminated", 6.0, 8.0, 100.0, NAN, 100.0, "T4"],
            ["gpu_typed_nan", "t", 1.0, "Terminated", 6.0, 8.0, 100.0, 1.0, NAN, "T4"],
        ]
    )
    return jobs, tasks


def test_canonical_jobs_and_drop_reasons_r_ing_2(raw):
    out, drops = build_jobs(*raw)
    assert list(out["job_id"]) == ["cpuonly", "zero_len", "multi", "ok"]  # by trace arrival
    r = out.set_index("job_id")
    assert r.loc["ok", "gpu_req"] == 1.0 and r.loc["ok", "cpu_req"] == 12.0
    assert r.loc["ok", "mem_req_gb"] == 20.0 and r.loc["ok", "runtime_actual_s"] == 300
    assert r.loc["multi", "trace_start_s"] == 60 and r.loc["multi", "trace_end_s"] == 200
    assert r.loc["multi", "gpu_req"] == 3.0 and r.loc["multi", "n_tasks"] == 3
    assert r.loc["multi", "gpu_type"] == "P100" and r.loc["multi", "user"] == "__unknown__"
    assert r.loc["cpuonly", "gpu_req"] == 0.0 and r.loc["cpuonly", "gpu_assumed_zero"] == 1
    assert r.loc["cpuonly", "gpu_type"] == "NONE"
    assert r.loc["zero_len", "runtime_actual_s"] == 1
    assert drops == {
        "not_terminated": 1,
        "missing_job_id": 1,
        "missing_arrival": 1,
        "no_tasks": 1,
        "invalid_task_times": 1,
        "nonpositive_runtime": 1,
        "missing_cpu": 1,
        "missing_mem": 1,
        "missing_gpu": 1,
    }


def test_missing_gpu_policy_drop_r_ing_2(raw):
    out, drops = build_jobs(*raw, missing_gpu_policy="drop")
    assert "cpuonly" not in set(out["job_id"])
    assert drops["missing_gpu"] == 2


def test_checksum_mismatch_aborts_r_ing_1(tmp_path):
    for name in ARCHIVE_SHA256:
        (tmp_path / name).write_bytes(b"corrupt")
    with pytest.raises(ChecksumError):
        verify_archives(tmp_path)


def test_truth_is_value_at_last_covering_capture():
    """PRD §6.2 truth: last value in effect at the last capture whose window covers the slot."""
    from flipwise.ingest import build_truth

    s = 1800
    f = pd.DataFrame(
        # slot 0 revised at captures 0 and 3s; slot s revised at 0 and 9s (after coverage ends)
        [(1, 0, 0, 100.0), (1, 0, 3 * s, 120.0), (1, s, 0, 200.0), (1, s, 9 * s, 999.0)],
        columns=["region_id", "slot_utc", "capture_utc", "forecast_g_per_kwh"],
    )
    caps = pd.DataFrame(
        # capture 4s covers slots 0..s; capture 9s covers only slots ≥ 5s
        [(0, 0, 4 * s), (4 * s, 0, s), (9 * s, 5 * s, 9 * s)],
        columns=["capture_utc", "window_first_utc", "window_last_utc"],
    )
    t = build_truth(f, caps, range(0, 3 * s, s)).set_index("slot_utc")
    assert t.loc[0, "truth_g_per_kwh"] == 120.0 and t.loc[0, "final_lag_s"] == 4 * s
    assert t.loc[s, "truth_g_per_kwh"] == 200.0  # the 9s revision is outside coverage
    assert t.loc[2 * s, "truth_g_per_kwh"] != t.loc[2 * s, "truth_g_per_kwh"]  # NaN: no data


def test_india_truth_hand_example_r_ing_5():
    """R-ING-5: two regions, three fuels, four 15-min blocks → two 30-min slots.

    Region 1, slot 0: coal 100+100, solar 50+150, gas 0+0 MWh → 200·1000 / 400 = 500 g/kWh.
    Region 1, slot S: coal 300, gas 100, solar 0 (one block each) → (300·1000 + 100·400) / 400
    = 850. Region 2, slot 0: gas 40+40, solar 120 (first block only) → 80·400 / 200 = 160.
    """
    from flipwise.ingest import india_truth

    s, b = 1800, 900
    gen = pd.DataFrame(
        [
            (1, 0, "coal", 100.0), (1, b, "coal", 100.0), (1, 0, "Solar", 50.0),
            (1, b, "solar", 150.0), (1, 0, "gas", 0.0), (1, b, "gas", 0.0),
            (1, s, "coal", 300.0), (1, s + b, "gas", 100.0), (1, s, "solar", 0.0),
            (2, 0, "gas", 40.0), (2, b, "gas", 40.0), (2, 0, "solar", 120.0),
        ],
        columns=["region_id", "slot_utc", "fuel", "mwh"],
    )  # fmt: skip
    t = india_truth(gen, {"coal": 1000.0, "gas": 400.0}).set_index(["region_id", "slot_utc"])
    assert t.loc[(1, 0), "truth_g_per_kwh"] == pytest.approx(500.0, abs=1e-9)
    assert t.loc[(1, s), "truth_g_per_kwh"] == pytest.approx(850.0, abs=1e-9)
    assert t.loc[(2, 0), "truth_g_per_kwh"] == pytest.approx(160.0, abs=1e-9)
    with pytest.raises(Exception, match="no emission factor"):
        india_truth(gen.assign(fuel="peat"), {"coal": 1000.0})


def test_india_forecasts_from_error_paths_r_ing_6():
    """R-ING-6: F = max(0, A + α s_r E); captures (and missing captures) follow the archive.

    GB truth mean over calibration = 100, Indian truth mean = 500 → s_r = 5. With α = 2:
    slot 0: E = +10 at capture 0, −60 at 2S (S was a missing capture) → F = 600, then
    max(0, 500 − 600) = 0. Slot S has no Indian truth → dropped and counted.
    """
    from flipwise.ingest import build_forecasts, scale_factors

    s = 1800
    truth = pd.DataFrame({"region_id": [1, 1], "slot_utc": [0, 2 * s],
                          "truth_g_per_kwh": [500.0, 500.0]})  # fmt: skip
    gb_truth = pd.DataFrame({"gb_region_id": [13, 13], "slot_utc": [0, 2 * s],
                             "truth_g_per_kwh": [80.0, 120.0]})  # fmt: skip
    errors = pd.DataFrame(
        [(13, 0, 0, 10.0), (13, 0, 2 * s, -60.0), (13, s, 0, 5.0)],
        columns=["gb_region_id", "slot_utc", "capture_utc", "error_g_per_kwh"],
    )
    s_r = scale_factors(truth, gb_truth, {1: 13}, 0, 2 * s)
    assert s_r == {1: 5.0}
    fc, counts = build_forecasts(truth, errors, {1: 13}, s_r, alpha=2.0)
    assert list(fc["capture_utc"]) == [0, 2 * s]
    assert list(fc["forecast_g_per_kwh"]) == [600.0, 0.0]
    assert counts == {"error_rows_without_truth": 1}
