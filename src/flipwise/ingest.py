"""Raw data → canonical CSVs + manifests (PRD §6.4, §6.7, §13.3)."""

from __future__ import annotations

import datetime as dt
import json
import platform
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from flipwise.trace import ARCHIVE_SHA256, read_jobs, read_tasks, sha256_file, verify_archives

JOB_SCHEMA = [
    "job_id",
    "user",
    "trace_arrival_s",
    "trace_start_s",
    "trace_end_s",
    "runtime_actual_s",
    "gpu_req",
    "cpu_req",
    "mem_req_gb",
    "gpu_type",
    "n_tasks",
    "gpu_assumed_zero",
]

# Drop reasons, in the order they are applied (each job is counted once, under the first hit).
DROP_REASONS = [
    "not_terminated",
    "missing_job_id",
    "missing_arrival",
    "no_tasks",
    "invalid_task_times",
    "nonpositive_runtime",
    "missing_cpu",
    "missing_mem",
    "missing_gpu",
]


def build_jobs(
    jobs: pd.DataFrame, tasks: pd.DataFrame, missing_gpu_policy: str = "zero"
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Derive the canonical job table and the count of dropped jobs per reason.

    `missing_gpu_policy`: "zero" treats NaN plan_gpu with NaN gpu_type as CPU-only
    (`gpu_assumed_zero = 1`); "drop" drops those jobs (PRD §6.4 sensitivity).
    """
    if missing_gpu_policy not in ("zero", "drop"):
        raise ValueError(f"missing_gpu_policy must be 'zero' or 'drop', got {missing_gpu_policy!r}")
    drops = dict.fromkeys(DROP_REASONS, 0)

    def drop(df: pd.DataFrame, mask: pd.Series, reason: str) -> pd.DataFrame:
        drops[reason] += int(mask.sum())
        return df[~mask]

    j = jobs.copy()
    j = drop(j, j["status"] != "Terminated", "not_terminated")
    j = drop(j, j["job_name"].isna(), "missing_job_id")
    j = drop(j, j["start_time"].isna(), "missing_arrival")
    # A few job_names repeat (one row per instance); keep the earliest submission.
    j = j.sort_values(["job_name", "start_time"], kind="stable").drop_duplicates("job_name")

    t = tasks[tasks["job_name"].isin(j["job_name"])].copy()
    t["bad_time"] = t["start_time"].isna() | t["end_time"].isna() | (t["start_time"] <= 0)
    gpu_nan = t["plan_gpu"].isna()
    t["gpu_zero_ok"] = gpu_nan & t["gpu_type"].isna()
    t["gpu_bad"] = gpu_nan & t["gpu_type"].notna()
    t["gpu"] = (t["inst_num"] * t["plan_gpu"] / 100).fillna(0.0)
    t["cpu"] = t["inst_num"] * t["plan_cpu"] / 100
    t["mem"] = t["inst_num"] * t["plan_mem"]
    t["cpu_nan"], t["mem_nan"] = t["cpu"].isna(), t["mem"].isna()
    g = t.groupby("job_name", sort=True)
    per = pd.DataFrame(
        {
            "n_tasks": g.size(),
            "bad_time": g["bad_time"].any(),
            "trace_start_s": g["start_time"].min(),
            "trace_end_s": g["end_time"].max(),
            "gpu_req": g["gpu"].sum(),
            "cpu_req": g["cpu"].sum().where(~g["cpu_nan"].any()),
            "mem_req_gb": g["mem"].sum().where(~g["mem_nan"].any()),
            "gpu_zero_ok": g["gpu_zero_ok"].any(),
            "gpu_bad": g["gpu_bad"].any(),
            "gpu_type": _mode_by_job(t),
        }
    )
    m = j.merge(per, left_on="job_name", right_index=True, how="left")
    m = drop(m, m["n_tasks"].isna(), "no_tasks")
    m = drop(m, m["bad_time"].astype(bool), "invalid_task_times")
    runtime = m["trace_end_s"] - m["trace_start_s"]
    m = drop(m, runtime < 0, "nonpositive_runtime")
    m = drop(m, m["cpu_req"].isna(), "missing_cpu")
    m = drop(m, m["mem_req_gb"].isna(), "missing_mem")
    gpu_missing = m["gpu_bad"].astype(bool)
    if missing_gpu_policy == "drop":
        gpu_missing |= m["gpu_zero_ok"].astype(bool)
    m = drop(m, gpu_missing, "missing_gpu")

    out = pd.DataFrame(
        {
            "job_id": m["job_name"],
            "user": m["user"].fillna("__unknown__"),
            "trace_arrival_s": m["start_time"].astype(np.int64),
            "trace_start_s": m["trace_start_s"].astype(np.int64),
            "trace_end_s": m["trace_end_s"].astype(np.int64),
            # Zero-length jobs exist at 1 s resolution; keep them with runtime 1 s (PRD §6.4).
            "runtime_actual_s": np.maximum(1, (m["trace_end_s"] - m["trace_start_s"])).astype(
                np.int64
            ),
            "gpu_req": m["gpu_req"].astype(float),
            "cpu_req": m["cpu_req"].astype(float),
            "mem_req_gb": m["mem_req_gb"].astype(float),
            "gpu_type": m["gpu_type"],
            "n_tasks": m["n_tasks"].astype(np.int64),
            "gpu_assumed_zero": m["gpu_zero_ok"].astype(bool).astype(np.int64),
        }
    )
    out = out.sort_values(["trace_arrival_s", "job_id"], kind="stable").reset_index(drop=True)
    return out[JOB_SCHEMA], drops


def _mode_by_job(t: pd.DataFrame) -> pd.Series:
    """Most frequent gpu_type per job; ties broken alphabetically; "NONE" if all missing."""
    c = t.dropna(subset=["gpu_type"]).groupby(["job_name", "gpu_type"]).size().rename("n")
    c = c.reset_index().sort_values(["job_name", "n", "gpu_type"], ascending=[True, False, True])
    mode = c.drop_duplicates("job_name").set_index("job_name")["gpu_type"]
    jobs = pd.Index(sorted(t["job_name"].unique()), name="job_name")
    return mode.reindex(jobs).fillna("NONE")


def _base_manifest() -> dict:
    return {
        "created_utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
    }


def ingest_alibaba(
    raw_dir: Path, out_dir: Path, manifest_dir: Path, missing_gpu_policy: str = "zero"
) -> dict:
    """Verify checksums, build `jobs_v2020.csv`, write manifest + ingest report."""
    checksums = verify_archives(raw_dir)
    jobs, tasks = read_jobs(raw_dir), read_tasks(raw_dir)
    canon, drops = build_jobs(jobs, tasks, missing_gpu_policy)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "jobs_v2020.csv"
    canon.to_csv(out_path, index=False, lineterminator="\n")
    manifest = {
        **_base_manifest(),
        "source": "https://github.com/alibaba/clusterdata/tree/master/cluster-trace-gpu-v2020",
        "archives_sha256": checksums,
        "raw_rows": {"jobs": len(jobs), "tasks": len(tasks)},
        "filters": {"status": "Terminated", "missing_gpu_policy": missing_gpu_policy},
        "dropped_by_reason": drops,
        "output": {
            "path": out_path.name,
            "rows": len(canon),
            "sha256": sha256_file(out_path),
            "gpu_assumed_zero": int(canon["gpu_assumed_zero"].sum()),
        },
    }
    (manifest_dir / "jobs_v2020.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def git_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


__all__ = ["ARCHIVE_SHA256", "build_jobs", "ingest_alibaba", "git_head"]
