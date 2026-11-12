"""Scenarios for the dashboard: demo-sized slices and the multi-datacentre scale study.

Both are built by the normal `build_replicate` (PRD §14.2) on validation-period data, never test
data (PRD §14.3). The scale study then spreads the same total load over more datacentres.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

from flipwise.config import load_config
from flipwise.models import DcConfig
from flipwise.scenario import Replicate, build_replicate
from flipwise.simulator import Scenario

ROOT = Path(__file__).resolve().parents[3]
CONFIG = Path("configs/base.yaml")

# name -> (trace days, sampling). Validation trace days and carbon Monday (PRD §14.2).
PRESETS: dict[str, tuple[tuple[int, int], float, str]] = {
    "small": ((25, 27), 0.02, "~450 jobs over 2 days"),
    "medium": ((25, 28), 0.03, "~940 jobs over 3 days"),
    "large": ((25, 28), 0.06, "~1,900 jobs over 3 days"),
}
DEMO_MONDAY = "2023-07-03"
REGION_NAMES = {1: ("Delhi NCR", "NR"), 2: ("Mumbai", "WR"), 3: ("Chennai", "SR")}


def in_root() -> None:
    """Data paths in the config are relative to the repository root."""
    os.chdir(ROOT)


def config() -> dict:
    in_root()
    return load_config(CONFIG)


def demo_scenario(cfg: dict, preset: str) -> Scenario:
    days, sampling, _ = PRESETS[preset]
    return build_replicate(cfg, Replicate(f"demo_{preset}", days, DEMO_MONDAY, sampling), 0)


def scaled_scenario(cfg: dict, n_dcs: int, base_sampling: float, monday: str) -> Scenario:
    """`n_dcs` datacentres over the 3 grid regions, with load growing in step.

    Jobs are sampled at `base_sampling * n_dcs / 3`, so each datacentre keeps about the same
    capacity and utilisation (target ρ) as in the 3-datacentre setup: a bigger federation, not
    a thinner one. Regions repeat (dc i is in region i mod 3) because only 3 Indian grids have
    forecasts; extra datacentres add planner work, not new carbon diversity.
    """
    regions = [int(r) for r in cfg["regions"]]
    sampling = base_sampling * n_dcs / len(regions)
    sc = build_replicate(cfg, Replicate(f"scale_n{n_dcs}", (25, 28), monday, sampling), 0)
    share = len(regions) / n_dcs
    d0 = sc.dcs[0]
    dcs = [
        DcConfig(i, regions[i % len(regions)], d0.cap_gpu * share, d0.cap_cpu * share,
                 d0.cap_mem_gb * share, d0.pue)
        for i in range(n_dcs)
    ]  # fmt: skip
    cap = dcs[0].cap
    jobs = [j for j in sc.jobs if j.request.fits_in(cap)]
    report = {**sc.build_report, "n_dcs": n_dcs, "dropped_no_fit": len(sc.jobs) - len(jobs)}
    return dataclasses.replace(sc, name=f"{sc.name}_n{n_dcs}", dcs=dcs, jobs=jobs,
                               build_report=report)  # fmt: skip
