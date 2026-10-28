"""Toy scenario vs hand-computed `expected.yaml` (PRD §6.9, `flipwise smoke`)."""

from __future__ import annotations

import math
from pathlib import Path

import yaml

from flipwise.policies import make_policy
from flipwise.reporting import job_rows
from flipwise.scenario import load_scenario
from flipwise.simulator import RunResult, Simulator

TOY_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "toy"
TOL_KG = 1e-9


def run_policy(scenario_dir: Path, policy: str) -> RunResult:
    return Simulator(load_scenario(scenario_dir), make_policy(policy)).run()


def check(result: RunResult, expected: dict, t0: int) -> list[str]:
    """Return mismatch messages (empty when the run matches)."""
    errs = []
    rows = {r["job_id"]: r for r in job_rows(result)}
    for job_id, exp in expected["jobs"].items():
        r = rows[job_id]
        got = {
            "dc_id": r["dc_id"],
            "release": r["release_slot"] - t0,
            "start": r["start_s"] - t0,
            "end": r["end_s"] - t0,
            "kg_co2": r["kg_co2"],
            "deadline_missed": r["deadline_missed"],
            "deadline_risk": r["deadline_risk"],
        }
        for k, v in exp.items():
            ok = math.isclose(got[k], v, abs_tol=TOL_KG) if k == "kg_co2" else got[k] == v
            if not ok:
                errs.append(f"{result.policy} {job_id}.{k}: got {got[k]}, expected {v}")
    total = sum(r["kg_co2"] or 0.0 for r in rows.values())
    if not math.isclose(total, expected["total_kg_co2"], abs_tol=TOL_KG):
        errs.append(
            f"{result.policy} total_kg_co2: got {total}, expected {expected['total_kg_co2']}"
        )
    return errs


def smoke(scenario_dir: Path = TOY_DIR, out_dir: Path | None = None) -> list[str]:
    from flipwise.reporting import write_run

    expected = yaml.safe_load((scenario_dir / "expected.yaml").read_text())
    t0 = load_scenario(scenario_dir).start_s
    errs = []
    for policy, exp in expected["policies"].items():
        res = run_policy(scenario_dir, policy)
        errs += check(res, exp, t0)
        if out_dir is not None:
            write_run(res, out_dir / policy)
    return errs
