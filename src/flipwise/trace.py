"""Readers for the raw Alibaba GPU trace v2020 (PRD §6.1).

The CSVs ship without a header row; column names come from the upstream `.header` files.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from flipwise.errors import ChecksumError

JOB_COLUMNS = ["job_name", "inst_id", "user", "status", "start_time", "end_time"]
TASK_COLUMNS = [
    "job_name",
    "task_name",
    "inst_num",
    "status",
    "start_time",
    "end_time",
    "plan_cpu",
    "plan_mem",
    "plan_gpu",
    "gpu_type",
]
MACHINE_COLUMNS = ["machine", "gpu_type", "cap_cpu", "cap_mem", "cap_gpu"]

# Archive SHA-256 from the upstream README (verified in the PRD §6.1 audit).
ARCHIVE_SHA256 = {
    "pai_job_table.tar.gz": "5aad7f7caac501136d14ed6a48e40546f825d7b0617a3a4f337e2348fe0a6cb0",
    "pai_task_table.tar.gz": "cd1d6dc3215d2a8607ccf6b6dd952b5db776df86926c73259fea7c1499ac40e5",
    "pai_machine_spec.tar.gz": "cc0d38a4045af1b1af8179de8b1b54b1ddd995e6160d6d061a6b1000f1276c2d",
}


def sha256_file(path: Path, chunk_bytes: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_bytes):
            h.update(chunk)
    return h.hexdigest()


def verify_archives(raw_dir: Path) -> dict[str, str]:
    """Return {archive: sha256}; raise ChecksumError on mismatch or absence."""
    out = {}
    for name, expected in ARCHIVE_SHA256.items():
        path = raw_dir / name
        if not path.exists():
            raise ChecksumError(f"missing archive {path}")
        got = sha256_file(path)
        if got != expected:
            raise ChecksumError(f"{name}: sha256 {got} != expected {expected}")
        out[name] = got
    return out


def _csv(raw_dir: Path, stem: str) -> Path:
    path = raw_dir / f"{stem}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; extract {stem}.tar.gz into {raw_dir}")
    return path


def read_jobs(raw_dir: Path) -> pd.DataFrame:
    return pd.read_csv(
        _csv(raw_dir, "pai_job_table"),
        header=None,
        names=JOB_COLUMNS,
        dtype={"job_name": str, "inst_id": str, "user": str, "status": str},
    )


def read_tasks(raw_dir: Path) -> pd.DataFrame:
    return pd.read_csv(
        _csv(raw_dir, "pai_task_table"),
        header=None,
        names=TASK_COLUMNS,
        dtype={"job_name": str, "task_name": str, "status": str, "gpu_type": str},
    )


def read_machines(raw_dir: Path) -> pd.DataFrame:
    return pd.read_csv(_csv(raw_dir, "pai_machine_spec"), header=None, names=MACHINE_COLUMNS)
