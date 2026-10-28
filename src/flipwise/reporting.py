"""Run outputs: jobs.csv, decisions.csv, events.log, manifest.json (PRD §16.1)."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
from pathlib import Path

from flipwise.models import JobState
from flipwise.simulator import RunResult, job_outcome

JOBS_CSV = [
    "job_id", "user", "gpu_req", "cpu_req", "mem_req_gb", "arrival_s", "deadline_s",
    "r_q50_s", "r_q90_s", "dc_id", "region_id", "release_slot", "start_s", "end_s", "wait_s",
    "runtime_s", "energy_kwh", "kg_co2", "deadline_missed", "n_moves", "rescued",
    "deadline_risk", "incomplete",
]  # fmt: skip
DECISIONS_CSV = [
    "time_s", "job_id", "kind", "from_dc", "from_slot", "to_dc", "to_slot", "S_a", "S_b",
    "LB", "w_ab", "g_min", "theta_eff", "reason",
]  # fmt: skip


def _fmt(v) -> str:
    # repr gives the shortest round-trip float, so outputs are byte-stable across runs and modes.
    if v is None:
        return ""
    if isinstance(v, float):
        return repr(v)
    return str(v)


def job_rows(result: RunResult) -> list[dict]:
    region = {d.dc_id: d.region_id for d in result.scenario.dcs}
    rows = []
    for j in sorted(result.jobs, key=lambda j: j.job_id):
        out = job_outcome(j, result.scenario)
        done = j.state == JobState.COMPLETED
        rows.append(
            {
                "job_id": j.job_id, "user": j.user, "gpu_req": j.gpu_req, "cpu_req": j.cpu_req,
                "mem_req_gb": j.mem_req_gb, "arrival_s": j.arrival_s, "deadline_s": j.deadline_s,
                "r_q50_s": j.r_q50_s, "r_q90_s": j.r_q90_s, "dc_id": j.dc_id,
                "region_id": region.get(j.dc_id), "release_slot": j.release_slot,  # type: ignore[arg-type]
                "start_s": j.start_s, "end_s": j.end_s,
                "wait_s": None if j.start_s is None else j.start_s - j.arrival_s,
                "runtime_s": j.runtime_actual_s if done else None,
                "energy_kwh": out["energy_kwh"], "kg_co2": out["kg_co2"],
                "deadline_missed": int(done and j.end_s > j.deadline_s),  # type: ignore[operator]
                "n_moves": j.n_moves, "rescued": j.rescued, "deadline_risk": j.deadline_risk,
                "incomplete": int(not done),
            }
        )  # fmt: skip
    return rows


def write_run(result: RunResult, out_dir: Path, manifest: dict | None = None) -> dict[str, str]:
    """Write the run files; return their SHA-256 (the R-SIM-1 / R-DEP-1 comparison)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "jobs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, JOBS_CSV, lineterminator="\n")
        w.writeheader()
        for r in job_rows(result):
            w.writerow({k: _fmt(v) for k, v in r.items()})
    with open(out_dir / "decisions.csv", "w", newline="") as f:
        w = csv.DictWriter(f, DECISIONS_CSV, lineterminator="\n")
        w.writeheader()
        for r in result.decisions:
            w.writerow({k: _fmt(r.get(k)) for k in DECISIONS_CSV})
    with open(out_dir / "events.log", "w", newline="") as f:
        f.write("time_s,priority,seq,kind,job_id\n")
        f.writelines(line + "\n" for line in result.events)
    hashes = {
        name: hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
        for name in ("jobs.csv", "decisions.csv", "events.log")
    }
    man = {
        "policy": result.policy,
        "scenario": result.scenario.name,
        "scenario_hash": result.scenario.scenario_hash,
        "uses_oracle": False,
        "output_sha256": hashes,
        "python": platform.python_version(),
        "platform": platform.platform(),
        **(manifest or {}),
    }
    (out_dir / "manifest.json").write_text(json.dumps(man, indent=2, sort_keys=True) + "\n")
    return hashes
