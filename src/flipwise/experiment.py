"""Run layout and experiments: `run`, `compare` and `sweep` (PRD §13.4, §14.2, §16).

Every run writes `results/<run_id>/`; a comparison only records which runs belong to it. A run that
already exists is reused, so an interrupted comparison resumes and sweep cells share baselines.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import platform
import subprocess
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

import pandas as pd
import yaml

from flipwise.config import apply_overrides, canonical_json, config_hash, policy_params
from flipwise.errors import ConfigError
from flipwise.metrics import carbon_coverage, carbon_timeline, metrics_from_run_dir
from flipwise.policies import make_policy
from flipwise.reporting import build_report, write_run
from flipwise.scenario import Replicate, build_replicate, dev_replicate, load_scenario
from flipwise.simulator import Scenario, Simulator

ALL_POLICIES = (
    "fcfs",
    "place_once",
    "periodic",
    "pred_error",
    "fixed_savings",
    "decision_flip",
    "pig",
)
TRACE_SLICE_DAYS = 7  # PRD §14.2
PACKAGES = ("pandas", "numpy", "pyyaml", "matplotlib")


def replicates_for(cfg: dict, split: str) -> list[Replicate]:
    """`dev`, or a full split: 7-day trace slices × that split's carbon Mondays (PRD §14.2)."""
    if split == "dev":
        return [dev_replicate(cfg)]
    block = cfg["splits"].get(split)
    if not isinstance(block, dict) or "carbon_mondays" not in block:
        raise ConfigError(f"split {split!r}: expected dev, validation or test")
    lo, hi = block["trace_days"]
    sampling = float(block.get("sampling", 1.0))
    return [
        Replicate(f"{split}_d{d}_{m}", (d, d + TRACE_SLICE_DAYS), str(m), sampling)
        for d, m in itertools.product(
            range(int(lo), int(hi), TRACE_SLICE_DAYS), block["carbon_mondays"]
        )
    ]


@dataclass(frozen=True)
class RunSpec:
    """One policy on one replicate. Exactly one of `replicate` and `scenario_dir` is set."""

    cfg: dict
    policy: str
    seed: int
    out: Path
    replicate: Replicate | None = None
    scenario_dir: Path | None = None
    debug: bool = False
    mode: str = "inproc"
    dc_urls: tuple[str, ...] | None = None


DEFAULT_DC_PORT = 8101  # PRD §13.5: services on 127.0.0.1:8101, 8102, …


def _clients(spec: RunSpec, scenario: Scenario) -> list | None:
    """Datacentre clients for `--mode remote` in `dc_id` order, or None for in-process ones.
    Each service is checked before the run, so a missing one fails before any event."""
    if spec.mode == "inproc":
        if spec.dc_urls:
            raise ConfigError("--dc-urls is only for --mode remote")
        return None
    if spec.mode != "remote":
        raise ConfigError(f"--mode {spec.mode!r}: expected inproc or remote")
    from flipwise.dcservice import HttpDatacentre

    n = len(scenario.dcs)
    urls = spec.dc_urls or tuple(f"http://127.0.0.1:{DEFAULT_DC_PORT + i}" for i in range(n))
    if len(urls) != n:
        raise ConfigError(f"--dc-urls gives {len(urls)} URLs; the scenario has {n} datacentres")
    clients = [HttpDatacentre(u) for u in urls]
    for d, c in zip(scenario.dcs, clients, strict=True):
        if c.health()["dc_id"] != d.dc_id:
            raise ConfigError(f"{c.url} serves another datacentre, not dc {d.dc_id}")
    return clients


_last_scenario: tuple[str, Scenario] | None = None


def scenario_for(spec: RunSpec) -> Scenario:
    """Per process, the last scenario built: consecutive runs reuse it. Building is deterministic,
    and `report` refuses runs whose hashes differ (R-FAIR-1), so processes cannot diverge."""
    global _last_scenario
    data_cfg = {k: v for k, v in spec.cfg.items() if k != "policies"}
    key = canonical_json(
        {"c": data_cfg, "r": repr(spec.replicate), "d": str(spec.scenario_dir), "s": spec.seed}
    )
    if _last_scenario is None or _last_scenario[0] != key:
        if spec.scenario_dir is not None:
            scenario = load_scenario(spec.scenario_dir)
        else:
            scenario = build_replicate(spec.cfg, spec.replicate, spec.seed)
        _last_scenario = (key, scenario)
    return _last_scenario[1]


def _run_config(cfg: dict, policy: str) -> dict:
    """The config this run depends on: other policies' parameters are left out, so changing them
    in a sweep does not repeat this run."""
    out = {k: v for k, v in cfg.items() if k != "policies"}
    out["policies"] = {policy: policy_params(cfg, policy)}
    return out


def _git_commit() -> dict:
    try:
        run = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}
    return {"commit": run.stdout.strip(), "dirty": bool(dirty.stdout.strip())}


def _sha256_if_exists(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _cpu_model() -> str:
    info = Path("/proc/cpuinfo")
    if info.exists():
        for line in info.read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor()


def _data_manifests(cfg: dict) -> dict:
    root = Path(cfg.get("data", {}).get("manifests", "data/manifests"))
    return {p.name: _sha256_if_exists(p) for p in sorted(root.glob("*.json"))}


def execute_run(spec: RunSpec) -> dict:
    """Run one policy, or reuse its saved run. Returns the record a comparison keeps."""
    scenario = scenario_for(spec)
    run_cfg = _run_config(spec.cfg, spec.policy)
    key = canonical_json(run_cfg) + scenario.scenario_hash + spec.policy + str(spec.seed)
    if spec.mode == "remote":
        # Its own run_id, so a remote run is never satisfied by a saved in-process one; the
        # output files must still be byte-identical to that run (R-DEP-1).
        key += "|remote"
    run_id = hashlib.sha256(key.encode()).hexdigest()[:12]  # PRD §16.1
    run_dir = spec.out / run_id
    record = {
        "replicate": scenario.name,
        "policy": spec.policy,
        "run_id": run_id,
        "scenario_hash": scenario.scenario_hash,
    }
    if (run_dir / "metrics.json").exists():
        return record
    params = policy_params(spec.cfg, spec.policy)
    clients = _clients(spec, scenario)
    started = dt.datetime.now(dt.UTC).isoformat()
    sim = Simulator(scenario, make_policy(spec.policy, **params), clients, debug=spec.debug)
    result = sim.run()
    finished = dt.datetime.now(dt.UTC).isoformat()
    write_run(
        result,
        run_dir,
        {
            "run_id": run_id,
            "seed": spec.seed,
            "config": run_cfg,
            "config_hash": config_hash(run_cfg),
            "policy_params": params,
            "build": scenario.build_report,
            "dcs": [
                {
                    "dc_id": d.dc_id,
                    "region_id": d.region_id,
                    "cap_gpu": d.cap_gpu,
                    "cap_cpu": d.cap_cpu,
                    "cap_mem_gb": d.cap_mem_gb,
                }
                for d in scenario.dcs
            ],
            "start_s": scenario.start_s,
            "end_s": scenario.end_s,
            "git": _git_commit(),
            "uv_lock_sha256": _sha256_if_exists(Path("uv.lock")),
            "data_manifests": _data_manifests(spec.cfg),
            "packages": {p: metadata.version(p) for p in PACKAGES},
            "cpu_model": _cpu_model(),
            "wall_clock": {"start": started, "end": finished},
            "mode": spec.mode,
            "dc_urls": [c.url for c in clients] if clients else None,
        },
    )
    # Written last: its presence is what marks a run as complete and reusable.
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics_from_run_dir(run_dir), indent=2, sort_keys=True) + "\n"
    )
    return record


def _replicate_tables(spec: RunSpec) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Coverage and timeline depend only on the replicate, so sweep cells share one saved copy."""
    scenario = scenario_for(spec)
    folder = spec.out / f"replicate_{scenario.scenario_hash[:12]}"
    cov_path, line_path = folder / "carbon_coverage.csv", folder / "carbon_timeline.csv"
    if not (cov_path.exists() and line_path.exists()):
        folder.mkdir(parents=True, exist_ok=True)
        for rows, path in (
            (carbon_coverage(scenario), cov_path),
            (carbon_timeline(scenario), line_path),
        ):
            data = pd.DataFrame(rows).assign(replicate=scenario.name)
            data.to_csv(path, index=False, lineterminator="\n")
    return pd.read_csv(cov_path), pd.read_csv(line_path)


def compare(
    cfg: dict,
    policies: list[str],
    split: str = "dev",
    seed: int = 0,
    out: Path = Path("results"),
    scenario_dir: Path | None = None,
    jobs: int = 1,
    debug: bool = False,
) -> Path:
    """Every policy on identical replicates → `results/compare_<hash>/` (PRD §16.2)."""
    for p in policies:
        make_policy(p, **policy_params(cfg, p))  # a typo fails now, not hours into the run
    replicates: list[Replicate | None] = (
        [None] if scenario_dir is not None else list(replicates_for(cfg, split))
    )
    specs = [
        RunSpec(cfg, p, seed, out, r, scenario_dir, debug)
        for r, p in itertools.product(replicates, policies)
    ]
    if jobs > 1 and len(specs) > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            records = list(pool.map(execute_run, specs))  # in `specs` order, however they finish
    else:
        records = [execute_run(s) for s in specs]

    identity = {
        "config": {k: v for k, v in cfg.items() if k != "policies"},
        "policies": {p: policy_params(cfg, p) for p in policies},
        "scenario_hashes": sorted({r["scenario_hash"] for r in records}),
        "seed": seed,
    }
    cmp_dir = out / f"compare_{hashlib.sha256(canonical_json(identity).encode()).hexdigest()[:12]}"
    cmp_dir.mkdir(parents=True, exist_ok=True)
    (cmp_dir / "runs.json").write_text(json.dumps(records, indent=2) + "\n")

    coverage, timeline = [], []
    for r in replicates:
        spec = RunSpec(cfg, policies[0], seed, out, r, scenario_dir)
        cov, line = _replicate_tables(spec)
        coverage.append(cov)
        timeline.append(line)
    pd.concat(coverage).to_csv(cmp_dir / "carbon_coverage.csv", index=False, lineterminator="\n")
    pd.concat(timeline).to_csv(cmp_dir / "carbon_timeline.csv", index=False, lineterminator="\n")
    build_report(cmp_dir, runs_root=out)
    return cmp_dir


def _baselines_worse(means: pd.DataFrame) -> str:
    """`dflip_worse_than` (PRD §14.8): baselines with lower emissions and no higher miss rate."""
    if "decision_flip" not in means.index:
        return ""
    flip = means.loc["decision_flip"]
    return ";".join(
        p
        for p in means.index
        if p != "decision_flip"
        and means.loc[p, "kg_co2"] < flip["kg_co2"]
        and means.loc[p, "miss_rate"] <= flip["miss_rate"]
    )


def sweep(
    cfg: dict,
    sweep_path: Path,
    policies: list[str],
    split: str = "dev",
    seed: int = 0,
    out: Path = Path("results"),
    scenario_dir: Path | None = None,
    jobs: int = 1,
) -> Path:
    """A grid over config values; each cell is one `compare` (PRD §13.4, §14.8)."""
    spec = yaml.safe_load(Path(sweep_path).read_text())
    grid = spec.get("grid") if isinstance(spec, dict) else None
    if not isinstance(grid, dict) or not grid:
        raise ConfigError(f"{sweep_path}: expected a mapping `grid: {{key: [values]}}`")
    names = sorted(grid)
    sets = {k: v for k, v in spec.items() if k != "grid"}
    rows = []
    for values in itertools.product(*(grid[k] for k in names)):
        overrides = [f"{k}={json.dumps(v)}" for k, v in zip(names, values, strict=True)]
        cell_cfg = apply_overrides(cfg, overrides)
        cmp_dir = compare(cell_cfg, policies, split, seed, out, scenario_dir, jobs)
        summary = pd.read_csv(cmp_dir / "summary.csv")
        means = summary.groupby("policy", sort=True).mean(numeric_only=True)
        worse = _baselines_worse(means)
        for policy, row in means.iterrows():
            rows.append(
                {
                    **dict(zip(names, values, strict=True)),
                    "policy": policy,
                    "compare": cmp_dir.name,
                    "kg_co2": row["kg_co2"],
                    "kg_co2_estimable": row["kg_co2_estimable"],
                    "intensity_g_per_kwh": row["intensity_g_per_kwh"],
                    "intensity_g_per_kwh_estimable": row["intensity_g_per_kwh_estimable"],
                    "miss_rate": row["miss_rate"],
                    "stage2_calls": row["stage2_calls"],
                    "moves": row["moves"],
                    "dflip_worse_than": worse,
                }
            )
    identity = canonical_json({"grid": grid, "sets": sets, "cfg": config_hash(cfg), "seed": seed})
    sweep_dir = out / f"sweep_{hashlib.sha256(identity.encode()).hexdigest()[:12]}"
    sweep_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(sweep_dir / "summary.csv", index=False, lineterminator="\n")
    return sweep_dir
