"""`flipwise validate`: config, data presence, checksums, coverage, split separation."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from flipwise.config import date
from flipwise.errors import ConfigError
from flipwise.models import SLOT_S
from flipwise.trace import sha256_file

MAX_CAPTURE_SPACING_S = 6 * 3600  # longer silences make the scheduler's view stale
IST_OFFSET_S = 19800  # UTC+5:30; carbon starts are Monday 00:00 IST (PRD v0.5 §6.3)


def monday_start_utc(d: dt.date) -> int:
    """Monday 00:00 IST as Unix seconds (Sunday 18:30 UTC)."""
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.UTC).timestamp()) - IST_OFFSET_S


def check_splits(cfg: dict) -> list[str]:
    """Chronological separation (PRD §14.3): no overlap between fit, validation and test."""
    errs = []
    sp = cfg["splits"]
    rf = [date(x, "splits.residual_fit_carbon") for x in sp["residual_fit_carbon"]]
    horizon = dt.timedelta(days=int(cfg["horizon_days"]))
    periods = {}
    for name in ("validation", "test"):
        s = sp[name]
        lo, hi = (date(x, f"splits.{name}.carbon_period") for x in s["carbon_period"])
        periods[name] = (lo, hi)
        for m in s["carbon_mondays"]:
            d = date(m, f"splits.{name}.carbon_mondays")
            if d.weekday() != 0:
                errs.append(f"{name}: carbon start {d} is not a Monday")
            if d < lo or d + horizon - dt.timedelta(days=1) > hi:
                errs.append(f"{name}: horizon of {d} leaves its carbon period {lo}..{hi}")
    (vlo, vhi), (tlo, _thi) = periods["validation"], periods["test"]
    if not (rf[1] < vlo and vhi < tlo):
        errs.append("carbon periods overlap: residual fit < validation < test is required")
    tr = [sp["runtime_fit_trace_days"], sp["validation"]["trace_days"], sp["test"]["trace_days"]]
    if not (tr[0][1] <= tr[1][0] and tr[1][1] <= tr[2][0]):
        errs.append("trace-day windows overlap: runtime fit < validation < test is required")
    return errs


# (manifest, {output name: config data key}); a manifest is checked only if its outputs exist.
MANIFESTS = (
    ("jobs_v2020.json", {"jobs_v2020.csv": "jobs"}),
    (
        "carbon_archive.json",
        {
            "gb_error_paths.csv": "gb_error_paths",
            "gb_truth.csv": "gb_truth",
            "capture_coverage.csv": "coverage",
        },
    ),  # fmt: skip
    ("india_truth.json", {"carbon_truth.csv": "truth"}),
    ("india_forecasts.json", {"carbon_forecast.csv": "forecast"}),
)


def _truth_gaps(truth: pd.DataFrame, region_col: str, regions, lo: int, hi: int) -> dict[int, int]:
    need = set(range(lo - lo % SLOT_S, hi, SLOT_S))
    out = {}
    for r in regions:
        t = truth[(truth[region_col] == r) & truth.slot_utc.between(lo - SLOT_S, hi - 1)]
        have = set(t.loc[t.truth_g_per_kwh.notna(), "slot_utc"].astype(int))
        if need - have:
            out[int(r)] = len(need - have)
    return out


def check_data(cfg: dict, root: Path = Path(".")) -> list[str]:
    errs = []
    data = cfg["data"]
    paths = {k: root / v for k, v in data.items() if k != "manifests"}
    for k in ("jobs", "coverage", "gb_error_paths", "gb_truth"):
        if not paths[k].exists():
            errs.append(f"missing {k} file {paths[k]}; run `flipwise ingest`")
    for k, cmd in (("truth", "ingest india"), ("forecast", "build-forecasts")):
        if not paths[k].exists():
            errs.append(f"missing Indian {k} {paths[k]}; run `flipwise {cmd}` (blocker B4)")
    man_dir = root / data["manifests"]
    for man_name, outputs in MANIFESTS:
        present = {n: paths[k] for n, k in outputs.items() if paths[k].exists()}
        if not present:
            continue
        mp = man_dir / man_name
        if not mp.exists():
            errs.append(f"missing manifest {mp}")
            continue
        man = json.loads(mp.read_text())
        recorded = man.get("outputs_sha256") or {man["output"]["path"]: man["output"]["sha256"]}
        for name, p in present.items():
            if recorded.get(name) != sha256_file(p):
                errs.append(f"{p}: sha256 differs from {mp.name}; re-run the command")
    if not (paths["coverage"].exists() and paths["gb_truth"].exists()):
        return errs

    caps = pd.read_csv(paths["coverage"])["capture_utc"].sort_values().to_numpy()
    gb_truth = pd.read_csv(paths["gb_truth"])
    truth = pd.read_csv(paths["truth"]) if paths["truth"].exists() else None
    gb_regions = sorted(set(cfg["error_source"].values()))
    if truth is not None:
        missing_regions = set(cfg["regions"]) - set(truth["region_id"].unique())
        if missing_regions:
            errs.append(f"regions {sorted(missing_regions)} absent from Indian truth")
    horizon_s = int(cfg["horizon_days"]) * 86400
    mondays = [m for s in ("validation", "test") for m in cfg["splits"][s]["carbon_mondays"]]
    for m in mondays:
        lo = monday_start_utc(date(m, "carbon_mondays"))
        hi = lo + horizon_s
        for r, n in _truth_gaps(gb_truth, "gb_region_id", gb_regions, lo, hi).items():
            errs.append(f"replicate {m}: GB error source {r} lacks truth for {n} slots")
        if truth is not None:
            for r, n in _truth_gaps(truth, "region_id", cfg["regions"], lo, hi).items():
                errs.append(f"replicate {m}: Indian region {r} lacks truth for {n} slots")
        c = caps[(caps >= lo - MAX_CAPTURE_SPACING_S) & (caps < hi)]
        gaps = (pd.Series(c).diff().dropna() > MAX_CAPTURE_SPACING_S).sum() if len(c) else 1
        if gaps:
            errs.append(f"replicate {m}: {int(gaps)} forecast silences longer than 6 h")
    return errs


def validate(cfg: dict, root: Path = Path(".")) -> list[str]:
    try:
        return check_splits(cfg) + check_data(cfg, root)
    except KeyError as e:
        raise ConfigError(f"missing config key {e}") from None
