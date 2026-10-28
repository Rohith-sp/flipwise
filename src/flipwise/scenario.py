"""Load a scenario directory: `scenario.yaml` plus canonical CSVs (PRD §6.7, §6.9)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import yaml

from flipwise.carbon import ForecastStore, Truth
from flipwise.energy import PowerModel
from flipwise.errors import ConfigError
from flipwise.models import DcConfig, Job
from flipwise.planner import PlannerParams, Residuals
from flipwise.simulator import Scenario

JOB_COLUMNS = [
    "job_id", "user", "arrival_s", "gpu_req", "cpu_req", "mem_req_gb",
    "r_q05_s", "r_q50_s", "r_q90_s", "r_q95_s", "deadline_s", "runtime_actual_s",
]  # fmt: skip


def _req(d: dict, key: str, ctx: str):
    if key not in d:
        raise ConfigError(f"{ctx}: missing required key {key!r}")
    return d[key]


def load_scenario(path: Path) -> Scenario:
    """`path` is a directory holding `scenario.yaml` or the YAML file itself."""
    yml = path / "scenario.yaml" if path.is_dir() else path
    root = yml.parent
    cfg = yaml.safe_load(yml.read_text())
    if not isinstance(cfg, dict):
        raise ConfigError(f"{yml}: expected a mapping")
    files = _req(cfg, "files", str(yml))
    h = hashlib.sha256(yml.read_bytes())
    paths = {}
    for key in ("jobs", "forecast", "coverage", "truth"):
        p = root / _req(files, key, "files")
        paths[key] = p
        h.update(p.read_bytes())

    jobs_df = pd.read_csv(paths["jobs"], dtype={"job_id": str, "user": str})
    missing = set(JOB_COLUMNS) - set(jobs_df.columns)
    if missing:
        raise ConfigError(f"{paths['jobs']}: missing columns {sorted(missing)}")
    jobs = [
        Job(
            job_id=r.job_id,
            user=r.user,
            arrival_s=int(r.arrival_s),
            gpu_req=float(r.gpu_req),
            cpu_req=float(r.cpu_req),
            mem_req_gb=float(r.mem_req_gb),
            r_q05_s=int(r.r_q05_s),
            r_q50_s=int(r.r_q50_s),
            r_q90_s=int(r.r_q90_s),
            r_q95_s=int(r.r_q95_s),
            deadline_s=int(r.deadline_s),
            runtime_actual_s=int(r.runtime_actual_s),
        )  # fmt: skip
        for r in jobs_df.itertuples(index=False)
    ]
    dcs = [
        DcConfig(
            dc_id=int(_req(d, "dc_id", "datacentres")),
            region_id=int(_req(d, "region_id", "datacentres")),
            cap_gpu=float(_req(d, "cap_gpu", "datacentres")),
            cap_cpu=float(_req(d, "cap_cpu", "datacentres")),
            cap_mem_gb=float(_req(d, "cap_mem_gb", "datacentres")),
            pue=float(d.get("pue", 1.0)),
        )
        for d in _req(cfg, "datacentres", str(yml))
    ]
    if [d.dc_id for d in dcs] != list(range(len(dcs))):
        raise ConfigError("datacentres must have dc_id 0..N-1 in order")
    power = _req(cfg, "power", str(yml))
    planner_cfg = cfg.get("planner", {})
    res = cfg.get("residuals", {})
    regions = sorted({d.region_id for d in dcs})
    return Scenario(
        name=str(cfg.get("name", root.name)),
        jobs=jobs,
        dcs=dcs,
        forecast=ForecastStore(
            pd.read_csv(paths["forecast"]), pd.read_csv(paths["coverage"]), regions
        ),
        truth=Truth(pd.read_csv(paths["truth"])),
        power=PowerModel(float(power["p_gpu_kw"]), float(power["p_cpu_kw"])),
        start_s=int(_req(cfg, "start_utc", str(yml))),
        end_s=int(_req(cfg, "end_utc", str(yml))),
        params=PlannerParams(
            h_defer_s=int(planner_cfg.get("h_defer_s", 86400)),
            feasibility=str(planner_cfg.get("feasibility", "conservative")),
        ),
        residuals=Residuals(
            e05=tuple(res.get("e05", (0.0,) * 4)), e95=tuple(res.get("e95", (0.0,) * 4))
        ),
        scenario_hash=h.hexdigest(),
    )
