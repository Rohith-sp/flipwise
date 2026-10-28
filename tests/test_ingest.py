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
