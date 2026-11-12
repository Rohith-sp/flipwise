"""Scenarios: load a directory (toy, PRD §6.9) or build a replicate from real data (PRD §14.2)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from flipwise.carbon import ForecastStore, Residuals, Truth, fit_residuals
from flipwise.config import canonical_json, date
from flipwise.energy import PowerModel
from flipwise.errors import ConfigError
from flipwise.estimates import fit_runtime
from flipwise.models import DcConfig, Job
from flipwise.planner import PlannerParams
from flipwise.simulator import Scenario
from flipwise.trace import sha256_file
from flipwise.validate import monday_start_utc

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


@dataclass(frozen=True)
class Replicate:
    """One trace slice crossed with one carbon start (PRD §14.2)."""

    name: str
    trace_days: tuple[int, int]
    carbon_monday: str
    sampling: float = 1.0


def dev_replicate(cfg: dict) -> Replicate:
    """The EL Phase 2 replicate from the `dev` block of the config."""
    dev = _req(cfg, "dev", "config")
    lo, hi = _req(dev, "trace_days", "dev")
    return Replicate(
        "dev", (int(lo), int(hi)), str(_req(dev, "carbon_monday", "dev")), float(dev["sampling"])
    )


def sampling_key(job_id: str, seed: int) -> float:
    """Deterministic value in [0, 1) deciding whether a job is sampled (PRD §14.2)."""
    return int(hashlib.sha256(f"{seed}:{job_id}".encode()).hexdigest()[:8], 16) / 2**32


def _load_power(cfg: dict, root: Path) -> tuple[PowerModel, str]:
    """Power model of PRD §7.2 (D58). `power_mode` in the experiment config overrides the energy
    file's `mode`, so `--set power_mode=nameplate` gives the other end of the bracket."""
    path = root / _req(cfg, "energy", "config")
    power = _req(yaml.safe_load(path.read_text()), "power", str(path))
    p_gpu, p_cpu = power.get("p_gpu_kw"), power.get("p_cpu_kw")
    if p_gpu is None or p_cpu is None:
        raise ConfigError(f"{path}: set power.p_gpu_kw and power.p_cpu_kw (blocker B3)")
    by_type = {str(k): float(v) for k, v in (power.get("gpu_kw_by_type") or {}).items()}
    mode = str(cfg.get("power_mode", power.get("mode", "nameplate")))
    try:
        model = PowerModel(float(p_gpu), float(p_cpu), by_type, mode)
    except ValueError as e:
        raise ConfigError(f"{path}: {e}") from None
    return model, mode


def load_or_fit_residuals(cfg: dict, root: Path = Path(".")) -> tuple[Residuals, dict]:
    """Residual quantiles for the configured calibration period, cached beside the data.

    Fitting expands every calibration vintage, so it is worth doing once, not per replicate.
    """
    data = cfg["data"]
    lo_d, hi_d = (
        date(x, "splits.residual_fit_carbon") for x in cfg["splits"]["residual_fit_carbon"]
    )
    lo_s = int(dt.datetime(lo_d.year, lo_d.month, lo_d.day, tzinfo=dt.UTC).timestamp())
    hi_s = int(dt.datetime(hi_d.year, hi_d.month, hi_d.day, tzinfo=dt.UTC).timestamp()) + 86400
    paths = [root / data[k] for k in ("forecast", "coverage", "truth")]
    key = hashlib.sha256(
        canonical_json(
            {"inputs": [sha256_file(p) for p in paths], "regions": cfg["regions"],
             "window": [lo_s, hi_s]}
        ).encode()
    ).hexdigest()  # fmt: skip
    cache = paths[0].parent / "carbon_residuals.json"
    if cache.exists():
        saved = json.loads(cache.read_text())
        if saved["key"] == key:
            by_region = saved["by_region"]
            return (
                Residuals(
                    tuple(saved["e05"]),
                    tuple(saved["e95"]),
                    None
                    if by_region is None
                    else {int(r): (tuple(v[0]), tuple(v[1])) for r, v in by_region.items()},
                ),
                saved["report"],
            )
    res, report = fit_residuals(
        pd.read_csv(paths[0]), pd.read_csv(paths[1]), pd.read_csv(paths[2]),
        [int(r) for r in cfg["regions"]], lo_s, hi_s,
    )  # fmt: skip
    cache.write_text(
        json.dumps(
            {"key": key, "e05": res.e05, "e95": res.e95, "by_region": res.by_region,
             "report": report},
            sort_keys=True,
        ) + "\n"
    )  # fmt: skip
    return res, report


def build_replicate(
    cfg: dict, replicate: Replicate, seed: int = 0, root: Path = Path(".")
) -> Scenario:
    """Build one replicate; every policy then runs on this same object (PRD §11, §14.2)."""
    params = _req(cfg, "scenario", "config")
    data = cfg["data"]
    origin_s = int(_req(cfg, "trace_day_origin_s", "config"))
    regions = [int(r) for r in cfg["regions"]]
    jobs_path = root / data["jobs"]
    jobs_df = pd.read_csv(jobs_path, dtype={"job_id": str, "user": str})
    if params["missing_gpu_policy"] == "drop":
        jobs_df = jobs_df[jobs_df["gpu_assumed_zero"] == 0]
    elif params["missing_gpu_policy"] != "zero":
        raise ConfigError(f"missing_gpu_policy: expected zero or drop, got "
                          f"{params['missing_gpu_policy']!r}")  # fmt: skip

    def day_s(d: int) -> int:
        return origin_s + int(d) * 86400

    # Estimates come from the calibration slice alone and are frozen (PRD §6.5).
    fit_lo, fit_hi = cfg["splits"]["runtime_fit_trace_days"]
    calibration = jobs_df[jobs_df["trace_arrival_s"].between(day_s(fit_lo), day_s(fit_hi) - 1)]
    runtime_model = fit_runtime(calibration, int(params["n_min"]))

    t0_s, t1_s = day_s(replicate.trace_days[0]), day_s(replicate.trace_days[1])
    window_s = t1_s - t0_s
    chosen = jobs_df[jobs_df["trace_arrival_s"].between(t0_s, t1_s - 1)]
    chosen = chosen[[sampling_key(j, seed) < replicate.sampling for j in chosen["job_id"]]]
    if chosen.empty:
        raise ConfigError(f"replicate {replicate.name}: no jobs in trace slice")
    power, power_label = _load_power(cfg, root)
    usage_path = root / data["usage"] if data.get("usage") else None
    if power.mode == "measured":
        if usage_path is None or not usage_path.exists():
            raise ConfigError("measured power needs data.usage: run `flipwise ingest usage`")
        usage = pd.read_csv(usage_path, dtype={"job_id": str}).set_index("job_id")
        missing = ~chosen["job_id"].isin(usage.index)
        if missing.any():
            raise ConfigError(f"{usage_path}: no usage for {int(missing.sum())} jobs; re-run "
                              "`flipwise ingest usage` after `ingest alibaba`")  # fmt: skip
        used = usage.loc[chosen["job_id"], ["gpu_used", "cpu_used"]].to_numpy()
    else:
        used = [(None, None)] * len(chosen)

    # Capacity from target load over the whole sampled slice (PRD §8.1), before any exclusion.
    rho, n_dc = float(params["rho"]), len(regions)
    if rho <= 0:
        raise ConfigError(f"scenario.rho: expected > 0, got {rho}")
    gpu_seconds = float((chosen["gpu_req"] * chosen["runtime_actual_s"]).sum())
    cap_gpu = gpu_seconds / (n_dc * rho * window_s)
    totals = _req(cfg, "cluster_totals", "config")
    cap_cpu = cap_gpu * totals["cpu_cores"] / totals["gpus"]
    cap_mem = cap_gpu * totals["mem_gb"] / totals["gpus"]
    dcs = [DcConfig(i, r, cap_gpu, cap_cpu, cap_mem) for i, r in enumerate(regions)]

    # Monday 00:00 IST; a phase shift moves arrivals, so the run starts with them (PRD §6.3).
    c0_s = monday_start_utc(date(replicate.carbon_monday, "carbon_monday"))
    shift_s = int(float(params["phase_shift_h"]) * 3600)
    end_s = c0_s + int(cfg["horizon_days"]) * 86400
    slack_s, k_slack = int(params["slack_base_s"]), float(params["k_slack"])
    jobs, excluded, sources = [], 0, {"user": 0, "class": 0, "global": 0}
    for r, (gpu_used, cpu_used) in zip(chosen.itertuples(index=False), used, strict=True):
        if r.gpu_req > cap_gpu or r.cpu_req > cap_cpu or r.mem_req_gb > cap_mem:
            excluded += 1  # fits no datacentre, and all three are equal (PRD §8.1)
            continue
        (q05, q50, q90, q95), source = runtime_model.estimate(r.user, float(r.gpu_req))
        sources[source] += 1
        arrival_s = c0_s + shift_s + int(r.trace_arrival_s) - t0_s
        jobs.append(
            Job(
                job_id=r.job_id, user=r.user, arrival_s=arrival_s, gpu_req=float(r.gpu_req),
                cpu_req=float(r.cpu_req), mem_req_gb=float(r.mem_req_gb), r_q05_s=q05,
                r_q50_s=q50, r_q90_s=q90, r_q95_s=q95,
                deadline_s=arrival_s + slack_s + int(k_slack * q90),
                runtime_actual_s=int(r.runtime_actual_s), gpu_type=str(r.gpu_type),
                gpu_used=None if gpu_used is None else float(gpu_used),
                cpu_used=None if cpu_used is None else float(cpu_used),
            )
        )  # fmt: skip
    jobs.sort(key=lambda j: (j.arrival_s, j.job_id))

    residuals, residual_report = load_or_fit_residuals(cfg, root)
    start_s = c0_s + min(shift_s, 0)
    # A day of earlier captures guarantees a vintage is already visible when the run starts.
    lead_in_s = start_s - 86400
    forecast = pd.read_csv(root / data["forecast"])
    forecast = forecast[forecast["slot_utc"].between(lead_in_s, end_s)]
    coverage = pd.read_csv(root / data["coverage"])
    coverage = coverage[coverage["capture_utc"].between(lead_in_s, end_s - 1)]
    truth = pd.read_csv(root / data["truth"])
    truth = truth[truth["region_id"].isin(regions) & truth["slot_utc"].between(start_s, end_s)]

    report = {
        "replicate": replicate.name, "trace_days": list(replicate.trace_days),
        "carbon_monday": replicate.carbon_monday, "sampling": replicate.sampling, "seed": seed,
        "jobs": len(jobs), "excluded_no_fit": excluded, "cap_gpu": cap_gpu, "cap_cpu": cap_cpu,
        "cap_mem_gb": cap_mem, "runtime_source": sources, "residuals": residual_report,
        "power_label": power_label,
        "power": {"p_gpu_kw": power.p_gpu_kw, "p_cpu_kw": power.p_cpu_kw,
                  "gpu_kw_by_type": dict(sorted(power.gpu_kw_by_type.items()))},
    }  # fmt: skip
    # Inputs by content, never by path, so the hash is the same on every machine (R-FAIR-1).
    h = hashlib.sha256(canonical_json({"params": params, "report": report}).encode())
    h.update(canonical_json({"e05": residuals.e05, "e95": residuals.e95,
                             "by_region": residuals.by_region}).encode())  # fmt: skip
    for p in (root / data[k] for k in ("jobs", "forecast", "coverage", "truth")):
        h.update(sha256_file(p).encode())
    if power.mode == "measured":
        h.update(sha256_file(usage_path).encode())  # type: ignore[arg-type]
    return Scenario(
        name=f"{replicate.name}_{replicate.carbon_monday}",
        jobs=jobs,
        dcs=dcs,
        forecast=ForecastStore(forecast, coverage, regions),
        truth=Truth(truth),
        power=power,
        start_s=start_s,
        end_s=end_s,
        params=PlannerParams(int(params["h_defer_s"]), str(params["feasibility"])),
        residuals=residuals,
        scenario_hash=h.hexdigest(),
        build_report=report,
    )
