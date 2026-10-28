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

FORWARD_ENDPOINT = "regional_fw48h"  # forecasts the scheduler sees
PAST_ENDPOINT = "regional_pt24h"  # later revisions of past slots; feed truth only
TRUTH_KIND = "regional_final_forecast"


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
    regions: list[int],
    out_dir: Path,
    manifest_dir: Path,
    tail_days: int = 9,
) -> dict:
    """Build carbon_forecast.csv, carbon_truth.csv, capture_coverage.csv and a coverage report.

    The covered slot range is `[start, end + tail_days)`: the run horizon extends up to 8 days
    past the last arrival (PRD §8.6), plus one day for the truth lag.
    """
    from flipwise.carbon import interpolate_truth
    from flipwise.errors import CarbonDataError
    from flipwise.models import SLOT_S

    lo = int(dt.datetime(start.year, start.month, start.day, tzinfo=dt.UTC).timestamp())
    hi_day = end + dt.timedelta(days=tail_days)
    hi = int(dt.datetime(hi_day.year, hi_day.month, hi_day.day, tzinfo=dt.UTC).timestamp()) - SLOT_S
    parts = _month_partitions(archive, start, hi_day)
    if not parts:
        raise CarbonDataError(f"no regional partitions under {archive}/data/db for {start}..{end}")
    rows, caps, gaps = zip(*(_read_partition(p, regions, lo - 2 * 86400, hi) for p in parts),
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

    fwd = c[
        (c.endpoint == FORWARD_ENDPOINT) & (c.capture_utc >= lo - 86400) & (c.capture_utc <= hi)
    ]
    covering = c[c.endpoint.isin([FORWARD_ENDPOINT, PAST_ENDPOINT])]
    slots = range(lo, hi + 1, SLOT_S)
    raw_truth = build_truth(f, covering, slots)

    truth_parts, gap_report = [], {}
    for r, grp in raw_truth.groupby("region_id", sort=True):
        s = grp.set_index("slot_utc")["truth_g_per_kwh"].dropna()
        missing = int(grp["truth_g_per_kwh"].isna().sum())
        try:
            t = interpolate_truth(s.reindex(slots).dropna())
            longest = 0
        except CarbonDataError as e:
            # Keep going so the coverage report lists every problem; `validate` will refuse
            # any replicate whose horizon touches an unfilled gap (R-ING-4).
            t = s.reset_index().assign(interpolated=0)
            longest = str(e)
        t["region_id"] = int(r)
        truth_parts.append(t)
        lag = grp.loc[grp["final_lag_s"] >= 0, "final_lag_s"]
        gap_report[int(r)] = {
            "slots": len(grp),
            "missing_truth_slots": missing,
            "unfillable_gap": longest,
            "gap_runs_utc": _gap_runs(grp),
            "final_lag_h_p05_p50": [float(lag.quantile(0.05)) / 3600, float(lag.median()) / 3600],
        }
    truth = pd.concat(truth_parts, ignore_index=True)
    truth["truth_kind"] = TRUTH_KIND
    truth = truth[["region_id", "slot_utc", "truth_g_per_kwh", "truth_kind", "interpolated"]]

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    f_out = f[(f.capture_utc <= hi)].assign(source="archive")
    f_out[["region_id", "slot_utc", "capture_utc", "forecast_g_per_kwh", "source"]].astype(
        {"forecast_g_per_kwh": float}
    ).to_csv(out_dir / "carbon_forecast.csv", index=False, lineterminator="\n")
    truth.to_csv(out_dir / "carbon_truth.csv", index=False, lineterminator="\n")
    fwd[["capture_utc", "endpoint", "window_first_utc", "window_last_utc", "source"]].to_csv(
        out_dir / "capture_coverage.csv", index=False, lineterminator="\n"
    )

    fwd_days = pd.to_datetime(fwd["capture_utc"], unit="s").dt.date.value_counts()
    all_days = pd.date_range(start, end).date
    report = {
        **_base_manifest(),
        "source": "https://github.com/nmpowell/carbon-intensity-forecast-tracking",
        "archive_commit": git_head(archive),
        "partitions": {p.name: sha256_file(p) for p in parts},
        "window": {"start": str(start), "end": str(end), "slots_lo_utc": lo, "slots_hi_utc": hi},
        "regions": regions,
        "truth_rule": "value at the last fw48h/pt24h capture whose window covers the slot",
        "rows": {
            "forecast": len(f_out),
            "truth": len(truth),
            "forward_captures": len(fwd),
            "null_forecasts_dropped": n_null,
            "capture_gaps": len(g),
        },  # fmt: skip
        "forward_captures_per_day": {
            "min": int(fwd_days.reindex(all_days, fill_value=0).min()),
            "median": float(fwd_days.reindex(all_days, fill_value=0).median()),
            "days_without_capture": [str(d) for d in all_days if fwd_days.get(d, 0) == 0],
        },
        "truth_by_region": gap_report,
        "outputs_sha256": {
            n: sha256_file(out_dir / n)
            for n in ("carbon_forecast.csv", "carbon_truth.csv", "capture_coverage.csv")
        },
    }
    (manifest_dir / "carbon_archive.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
