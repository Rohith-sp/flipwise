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


# ---- NESO forecast-vintage archive (PRD §6.2, §6.7) ----------------------------------------

# The archive is the source of real forecast-error paths only (PRD v0.5, §6.2.3); the simulated
# world is Indian. Its capture schedule becomes the Indian vintages' schedule.
FORWARD_ENDPOINT = "regional_fw48h"  # forward forecasts: F_gb(g, k, v)
PAST_ENDPOINT = "regional_pt24h"  # later revisions of past slots; feed A_gb only


def _month_partitions(archive: Path, start: dt.date, end: dt.date) -> list[Path]:
    """Regional SQLite partitions whose month overlaps `[start, end]`, plus the next month (the
    run horizon extends past the last arrival, PRD §8.6)."""
    months = set()
    d = dt.date(start.year, start.month, 1)
    last = dt.date(end.year + (end.month == 12), end.month % 12 + 1, 1)
    while d <= last:
        months.add(f"{d.year}-{d.month:02d}")
        d = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    files = sorted((archive / "data" / "db").glob("20*/regional_*.sqlite"))
    return [f for f in files if f.stem.removeprefix("regional_")[:7] in months]


def _read_partition(path: Path, regions: list[int], lo: int, hi: int):
    import sqlite3

    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        q = ",".join("?" * len(regions))
        rows = pd.read_sql_query(
            f"SELECT region_id, window_utc AS slot_utc, capture_utc, forecast "
            f"FROM regional_intensity WHERE region_id IN ({q}) AND window_utc BETWEEN ? AND ?",
            con,
            params=[*regions, lo, hi],
        )
        caps = pd.read_sql_query(
            "SELECT capture_utc, endpoint, window_first_utc, window_last_utc, source FROM captures",
            con,
        )
        gaps = pd.read_sql_query(
            f"SELECT capture_utc, endpoint, window_utc, region_id FROM capture_gaps "
            f"WHERE region_id IN (0,{q})",
            con,
            params=regions,
        )
    finally:
        con.close()
    return rows, caps, gaps


def build_truth(forecast: pd.DataFrame, past_caps: pd.DataFrame, slots: range) -> pd.DataFrame:
    """Truth A(r, k) = value in effect at the last capture whose window covers slot `k`.

    Returns `region_id, slot_utc, truth_g_per_kwh, final_lag_s` with NaN truth where no capture
    covered the slot; `final_lag_s` is how long after the slot start that capture was.
    """
    import numpy as np

    caps = past_caps.sort_values("capture_utc")
    cap_t = caps["capture_utc"].to_numpy()
    first = caps["window_first_utc"].to_numpy()
    last = caps["window_last_utc"].to_numpy()
    slot_arr = np.asarray(list(slots), dtype=np.int64)
    # Last covering capture per slot: windows move forward monotonically, so scan in time order.
    last_cover = np.full(len(slot_arr), -1, dtype=np.int64)
    for c, a, b in zip(cap_t, first, last, strict=True):
        i0, i1 = np.searchsorted(slot_arr, [a, b + 1])
        last_cover[i0:i1] = c
    out = []
    for r, grp in forecast.groupby("region_id", sort=True):
        g = grp.sort_values(["slot_utc", "capture_utc"])
        by_slot = {k: (sub["capture_utc"].to_numpy(), sub["forecast_g_per_kwh"].to_numpy())
                   for k, sub in g.groupby("slot_utc", sort=True)}  # fmt: skip
        vals = np.full(len(slot_arr), np.nan)
        for i, k in enumerate(slot_arr):
            c = last_cover[i]
            h = by_slot.get(int(k))
            if c < 0 or h is None:
                continue
            j = np.searchsorted(h[0], c, side="right")
            if j:
                vals[i] = h[1][j - 1]
        lag = np.where(last_cover >= 0, last_cover - slot_arr, -1)
        out.append(pd.DataFrame({"region_id": int(r), "slot_utc": slot_arr,
                                 "truth_g_per_kwh": vals, "final_lag_s": lag}))  # fmt: skip
    return pd.concat(out, ignore_index=True)


def _gap_runs(grp: pd.DataFrame, min_slots: int = 3) -> list[list[str]]:
    """`[first, last]` ISO times of every run of ≥ `min_slots` slots with no truth."""
    miss = grp.sort_values("slot_utc")
    m = miss["truth_g_per_kwh"].isna().to_numpy()
    t = miss["slot_utc"].to_numpy()
    runs, i = [], 0
    while i < len(m):
        if m[i]:
            j = i
            while j + 1 < len(m) and m[j + 1]:
                j += 1
            if j - i + 1 >= min_slots:
                iso = [dt.datetime.fromtimestamp(int(x), dt.UTC).strftime("%Y-%m-%dT%H:%MZ")
                       for x in (t[i], t[j])]  # fmt: skip
                runs.append(iso)
            i = j + 1
        else:
            i += 1
    return runs


def ingest_carbon(
    archive: Path,
    start: dt.date,
    end: dt.date,
    gb_regions: list[int],
    out_dir: Path,
    manifest_dir: Path,
) -> dict:
    """Reconstruct GB vintages and write the error paths E_g(k, v) = F_gb − A_gb (PRD §6.2.3).

    Outputs `gb_error_paths.csv` (one row per forecast change), `gb_truth.csv` (A_gb, needed for
    the scale factor s_r) and `capture_coverage.csv` (forward captures with their windows). Slots
    cover `[start, end]` inclusive; `end` already includes the 8-day run tail.
    """
    from flipwise.carbon import interpolate_truth
    from flipwise.errors import CarbonDataError
    from flipwise.models import SLOT_S

    lo = _utc_midnight(start)
    hi = _utc_midnight(end + dt.timedelta(days=1)) - SLOT_S
    parts = _month_partitions(archive, start, end)
    if not parts:
        raise CarbonDataError(f"no regional partitions under {archive}/data/db for {start}..{end}")
    rows, caps, gaps = zip(*(_read_partition(p, gb_regions, lo - 2 * 86400, hi) for p in parts),
                           strict=True)  # fmt: skip
    f = pd.concat(rows, ignore_index=True)
    n_null = int(f["forecast"].isna().sum())
    f = f.dropna(subset=["forecast"]).rename(columns={"forecast": "forecast_g_per_kwh"})
    f = f.drop_duplicates(["region_id", "slot_utc", "capture_utc"]).sort_values(
        ["region_id", "slot_utc", "capture_utc"], kind="stable"
    )
    c = pd.concat(caps, ignore_index=True).drop_duplicates(["capture_utc", "endpoint"])
    c = c.sort_values(["capture_utc", "endpoint"], kind="stable")
    g = pd.concat(gaps, ignore_index=True).drop_duplicates()
    found = sorted(int(r) for r in f["region_id"].unique())
    if found != sorted(gb_regions):
        raise CarbonDataError(f"GB regions {sorted(gb_regions)} requested, archive has {found}")

    fwd = c[
        (c.endpoint == FORWARD_ENDPOINT) & (c.capture_utc >= lo - 86400) & (c.capture_utc <= hi)
    ]
    covering = c[c.endpoint.isin([FORWARD_ENDPOINT, PAST_ENDPOINT])]
    slots = range(lo, hi + 1, SLOT_S)
    raw_truth = build_truth(f, covering, slots)

    truth_parts, gap_report = [], {}
    for r, grp in raw_truth.groupby("region_id", sort=True):
        s_ = grp.set_index("slot_utc")["truth_g_per_kwh"].dropna()
        try:
            t = interpolate_truth(s_)
            unfillable: str | int = 0
        except CarbonDataError as e:
            # Keep going so the report lists every gap; error paths simply have no rows there.
            t = s_.reset_index().assign(interpolated=0)
            unfillable = str(e)
        t["region_id"] = int(r)
        truth_parts.append(t)
        lag = grp.loc[grp["final_lag_s"] >= 0, "final_lag_s"]
        gap_report[int(r)] = {
            "slots": len(grp),
            "missing_truth_slots": int(grp["truth_g_per_kwh"].isna().sum()),
            "unfillable_gap": unfillable,
            "gap_runs_utc": _gap_runs(grp),
            "final_lag_h_p05_p50": [float(lag.quantile(0.05)) / 3600, float(lag.median()) / 3600],
            "mean_truth_g_per_kwh": float(s_.mean()),
        }
    gb_truth = pd.concat(truth_parts, ignore_index=True).rename(
        columns={"region_id": "gb_region_id"}
    )
    gb_truth = gb_truth[["gb_region_id", "slot_utc", "truth_g_per_kwh", "interpolated"]]

    # E = F_gb − A_gb on every forecast change; slots without A_gb carry no error path.
    e = f[f.capture_utc <= hi].merge(
        gb_truth.rename(columns={"gb_region_id": "region_id"}), on=["region_id", "slot_utc"]
    )
    e["error_g_per_kwh"] = e["forecast_g_per_kwh"] - e["truth_g_per_kwh"]
    errors = e.rename(columns={"region_id": "gb_region_id"})[
        ["gb_region_id", "slot_utc", "capture_utc", "error_g_per_kwh"]
    ].sort_values(["gb_region_id", "slot_utc", "capture_utc"], kind="stable")

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    errors.to_csv(out_dir / "gb_error_paths.csv", index=False, lineterminator="\n")
    gb_truth.to_csv(out_dir / "gb_truth.csv", index=False, lineterminator="\n")
    fwd[["capture_utc", "endpoint", "window_first_utc", "window_last_utc", "source"]].to_csv(
        out_dir / "capture_coverage.csv", index=False, lineterminator="\n"
    )

    fwd_days = pd.to_datetime(fwd["capture_utc"], unit="s").dt.date.value_counts()
    all_days = pd.date_range(start, end).date
    report = {
        **_base_manifest(),
        "source": "https://github.com/nmpowell/carbon-intensity-forecast-tracking",
        "role": "GB forecast-error paths applied to Indian truth (PRD v0.5 §6.2.3-6.2.4)",
        "archive_commit": git_head(archive),
        "partitions": {p.name: sha256_file(p) for p in parts},
        "window": {"start": str(start), "end": str(end), "slots_lo_utc": lo, "slots_hi_utc": hi},
        "gb_regions": gb_regions,
        "gb_truth_rule": "value at the last fw48h/pt24h capture whose window covers the slot",
        "rows": {
            "forecast_changes": int((f.capture_utc <= hi).sum()),
            "error_paths": len(errors),
            "gb_truth": len(gb_truth),
            "forward_captures": len(fwd),
            "null_forecasts_dropped": n_null,
            "capture_gaps": len(g),
        },  # fmt: skip
        "forward_captures_per_day": {
            "min": int(fwd_days.reindex(all_days, fill_value=0).min()),
            "median": float(fwd_days.reindex(all_days, fill_value=0).median()),
            "days_without_capture": [str(d) for d in all_days if fwd_days.get(d, 0) == 0],
        },
        "gb_truth_by_region": gap_report,
        "outputs_sha256": {
            n: sha256_file(out_dir / n)
            for n in ("gb_error_paths.csv", "gb_truth.csv", "capture_coverage.csv")
        },
    }
    (manifest_dir / "carbon_archive.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def _utc_midnight(d: dt.date) -> int:
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.UTC).timestamp())


# ---- Indian generation by fuel, constructed (PRD §6.2.2, source option 3) --------------------

IST_OFFSET_S = 19_800  # UTC+5:30
SLOTS_PER_DAY = 48
# Fuel in the Grid-India daily report → national SCADA series whose within-day shape it takes.
# Biomass and other RES have no national series and are spread evenly over the day.
FUEL_SHAPE = {"coal": "thermal", "lignite": "thermal", "gas": "gas", "hydro": "hydro",
              "nuclear": "nuclear", "wind": "wind", "solar": "solar", "biomass": None}  # fmt: skip


def _ist_day_start_utc(d: dt.date) -> int:
    return _utc_midnight(d) - IST_OFFSET_S


def construct_india_generation(
    daily: pd.DataFrame, profile: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Regional daily energy by fuel × national within-day shape of that fuel [Synthetic].

    `daily`: `ist_date, region_id, fuel, mwh_day` from the Grid-India daily PSP reports.
    `profile`: `slot_utc, shape, mw` national mean MW per 30-minute slot from Grid-India SCADA.

    G(r, f, k) = E(r, f, d) × MW(s(f), k) / Σ_{k' in d} MW(s(f), k'). The regional daily totals
    are measured; only the shape inside each IST day is borrowed from the national series. A day
    whose national series is incomplete takes the typical shape of its month (mean over complete
    days at the same slot of day); with no complete day in the month, the typical shape over the
    whole profile (the 2024 SCADA file has wind and solar only); with no data at all for the
    fuel, an even spread. Every fallback is counted for the manifest.
    """
    unknown = sorted(set(daily["fuel"]) - set(FUEL_SHAPE))
    if unknown:
        raise ValueError(f"no within-day shape mapping for fuels {unknown}")

    p = profile.assign(mw=profile["mw"].clip(lower=0.0))
    local = pd.to_datetime(p["slot_utc"] + IST_OFFSET_S, unit="s")
    p = p.assign(ist_date=local.dt.date, j=(local.dt.hour * 2 + local.dt.minute // 30),
                 month=local.dt.strftime("%Y-%m"))  # fmt: skip
    day = p.groupby(["shape", "ist_date"])["mw"].agg(["count", "sum"])
    complete = day[(day["count"] == SLOTS_PER_DAY) & (day["sum"] > 0)].index
    p_ok = p.set_index(["shape", "ist_date"]).loc[lambda x: x.index.isin(complete)].reset_index()
    own = p_ok.assign(w=p_ok["mw"] / p_ok.groupby(["shape", "ist_date"])["mw"].transform("sum"))
    own_w = {(s, d): g.set_index("j")["w"] for (s, d), g in own.groupby(["shape", "ist_date"])}
    typ = own.groupby(["shape", "month", "j"])["w"].mean()
    typ_w = {(s, m): g.droplevel([0, 1]) / g.sum() for (s, m), g in typ.groupby(level=[0, 1])}
    typ_all = own.groupby(["shape", "j"])["w"].mean()
    all_w = {s: g.droplevel(0) / g.sum() for s, g in typ_all.groupby(level=0)}

    flat = pd.Series(1.0 / SLOTS_PER_DAY, index=range(SLOTS_PER_DAY))
    counts = {"days_typical_month": 0, "days_typical_overall": 0, "days_flat_shape": 0}
    rows = []
    for (d, r, f), e in daily.groupby(["ist_date", "region_id", "fuel"], sort=True)["mwh_day"]:
        shape, month = FUEL_SHAPE[f], f"{d:%Y-%m}"
        if shape is None:
            w = flat
        elif (shape, d) in own_w:
            w = own_w[(shape, d)]
        elif (shape, month) in typ_w:
            w = typ_w[(shape, month)]
            counts["days_typical_month"] += 1
        elif shape in all_w:
            w = all_w[shape]
            counts["days_typical_overall"] += 1
        else:
            w = flat
            counts["days_flat_shape"] += 1
        w = w.reindex(range(SLOTS_PER_DAY), fill_value=0.0)
        start = _ist_day_start_utc(d)
        rows.append(pd.DataFrame({"region_id": int(r), "fuel": f,
                                  "slot_utc": start + 1800 * np.arange(SLOTS_PER_DAY),
                                  "mwh": float(e.sum()) * w.to_numpy()}))  # fmt: skip
    gen = pd.concat(rows, ignore_index=True)
    gen = gen.sort_values(["region_id", "slot_utc", "fuel"], kind="stable", ignore_index=True)
    return gen[["region_id", "slot_utc", "fuel", "mwh"]], counts


# ---- Indian truth (PRD §6.2.2) -------------------------------------------------------------

ZERO_CARBON_FUELS = ("hydro", "nuclear", "solar", "wind")


def india_truth(generation: pd.DataFrame, factors_g_per_kwh: dict[str, float]) -> pd.DataFrame:
    """A(r, k) = Σ_f G(r, f, k) · EF_f / Σ_f G(r, f, k) per region and 30-min slot (R-ING-5).

    `generation`: `region_id, slot_utc, fuel, mwh`, where `slot_utc` may be a 15-minute block
    start; blocks are summed into their 30-minute slot. Every fuel needs a factor (zero-carbon
    fuels default to 0), so an unexpected fuel name fails loudly instead of counting as clean.
    """
    from flipwise.errors import CarbonDataError
    from flipwise.models import SLOT_S

    ef = {f: 0.0 for f in ZERO_CARBON_FUELS} | {
        k.lower(): float(v) for k, v in factors_g_per_kwh.items()
    }
    g = generation.assign(fuel=generation["fuel"].str.lower())
    unknown = sorted(set(g["fuel"]) - set(ef))
    if unknown:
        raise CarbonDataError(f"no emission factor for fuels {unknown}")
    g = g.assign(slot_utc=(g["slot_utc"] // SLOT_S) * SLOT_S)
    g["g_co2"] = g["mwh"] * g["fuel"].map(ef)  # MWh × g/kWh = kg; only the ratio matters
    agg = g.groupby(["region_id", "slot_utc"], sort=True).agg(mwh=("mwh", "sum"),
                                                              g_co2=("g_co2", "sum"))  # fmt: skip
    if (agg["mwh"] <= 0).any():
        raise CarbonDataError("slot with zero total generation")
    out = (agg["g_co2"] / agg["mwh"]).rename("truth_g_per_kwh").reset_index()
    return out


# ---- Indian forecast vintages (PRD §6.2.4) -------------------------------------------------


def scale_factors(
    truth: pd.DataFrame, gb_truth: pd.DataFrame, mapping: dict[int, int], lo: int, hi: int
) -> dict[int, float]:
    """s_r = mean A(r, ·) / mean A_gb(g(r), ·) over calibration slots `[lo, hi]`."""
    from flipwise.errors import CarbonDataError

    out = {}
    for r, gb in sorted(mapping.items()):
        a = truth.loc[(truth.region_id == r) & truth.slot_utc.between(lo, hi), "truth_g_per_kwh"]
        b = gb_truth.loc[(gb_truth.gb_region_id == gb) & gb_truth.slot_utc.between(lo, hi),
                         "truth_g_per_kwh"]  # fmt: skip
        if a.empty or b.empty or b.mean() <= 0:
            raise CarbonDataError(f"cannot compute s_r for region {r} from GB region {gb}")
        out[r] = float(a.mean() / b.mean())
    return out


def build_forecasts(
    truth: pd.DataFrame,
    errors: pd.DataFrame,
    mapping: dict[int, int],
    s_r: dict[int, float],
    alpha: float = 1.0,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """F(r, k, v) = max(0, A(r, k) + α · s_r · E_g(r)(k, v)), one row per error change (R-ING-6).

    Rows inherit the archive's capture times, so missing captures stay missing. Error rows whose
    slot has no Indian truth are dropped and counted.
    """
    parts, dropped = [], 0
    for r, gb in sorted(mapping.items()):
        e = errors[errors.gb_region_id == gb]
        a = truth[truth.region_id == r][["slot_utc", "truth_g_per_kwh"]]
        m = e.merge(a, on="slot_utc", how="left")
        dropped += int(m["truth_g_per_kwh"].isna().sum())
        m = m.dropna(subset=["truth_g_per_kwh"])
        fc = (m["truth_g_per_kwh"] + alpha * s_r[r] * m["error_g_per_kwh"]).clip(lower=0.0)
        parts.append(pd.DataFrame({"region_id": r, "slot_utc": m["slot_utc"],
                                   "capture_utc": m["capture_utc"], "forecast_g_per_kwh": fc,
                                   "source": f"india+gb{gb}"}))  # fmt: skip
    out = pd.concat(parts, ignore_index=True).sort_values(
        ["region_id", "slot_utc", "capture_utc"], kind="stable"
    )
    return out.reset_index(drop=True), {"error_rows_without_truth": dropped}
