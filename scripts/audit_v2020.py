"""Reproduce the PRD §6.1 audit table from the raw v2020 CSVs (build phase 1 exit criterion).

Usage: uv run python scripts/audit_v2020.py [--raw data/raw/v2020]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from flipwise.trace import read_jobs, read_machines, read_tasks, verify_archives


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=Path("data/raw/v2020"))
    args = ap.parse_args()

    for name, digest in verify_archives(args.raw).items():
        print(f"checksum ok  {name}  {digest[:8]}…{digest[-4:]}")

    jobs, tasks, machines = read_jobs(args.raw), read_tasks(args.raw), read_machines(args.raw)
    print(f"rows: jobs {len(jobs):,}  tasks {len(tasks):,}  machines {len(machines):,}")
    print("job status:", jobs["status"].value_counts().to_dict())
    span_d = (jobs["start_time"].max() - jobs["start_time"].min()) / 86400
    print(f"job start_time span: {span_d:.1f} days")

    term = jobs.loc[jobs["status"] == "Terminated", "job_name"]
    t = tasks[tasks["job_name"].isin(term)].copy()
    t["gpu"] = t["inst_num"] * t["plan_gpu"] / 100
    g = t.groupby("job_name")
    per_job = g.agg(
        n_tasks=("task_name", "size"),
        start=("start_time", "min"),
        end=("end_time", "max"),
        gpu=("gpu", lambda s: s.sum(min_count=1)),
        gpu_types=("gpu_type", "nunique"),
        any_nan_gpu=("plan_gpu", lambda s: s.isna().any()),
    )
    q = [0.10, 0.50, 0.90, 0.99]
    all_mean = tasks.groupby("job_name").size().mean()
    print(
        f"tasks per job: {per_job.n_tasks.min()}–{per_job.n_tasks.max()}"
        f" (mean {per_job.n_tasks.mean():.2f} Terminated; {all_mean:.2f} all jobs)"
    )
    rt = (per_job.end - per_job.start).dropna()
    print("runtime p10/p50/p90/p99/max:", np.quantile(rt, q).round(0).tolist(), rt.max())
    gpu = per_job.gpu.dropna()
    print(
        "gpu req p50/p90/p99/max:", np.quantile(gpu, [0.5, 0.9, 0.99]).round(2).tolist(), gpu.max()
    )
    print(
        f"jobs with missing plan_gpu: {int(per_job.any_nan_gpu.sum()):,}"
        f" ({per_job.any_nan_gpu.mean():.1%})"
    )
    print(f"jobs mixing GPU types: {(per_job.gpu_types > 1).mean():.2%}")
    uj = jobs[jobs.status == "Terminated"].groupby("user").size()
    big = uj[uj >= 20]
    print(
        f"users with >=20 Terminated jobs: {len(big)} of {len(uj)};"
        f" own {big.sum() / uj.sum():.1%} of jobs"
    )
    print(f"machines / GPUs: {len(machines):,} / {int(machines.cap_gpu.sum()):,}")


if __name__ == "__main__":
    main()
