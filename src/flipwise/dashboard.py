"""Static `dashboard.html` from saved result files (PRD §4.1 item 9, §13.3).

Reads files only: it never runs a simulation or opens a network connection. A tab whose input does
not exist yet shows "no data", and the other tabs still render.
"""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path

import pandas as pd

from flipwise import figures
from flipwise.reporting import read_summary

TABS = (
    ("timeline", "Timeline"),
    ("pareto", "Pareto"),
    ("results", "Results"),
    ("theta", "θ sweep"),
)
RESULT_COLUMNS = (
    ("policy", "Policy", None),
    ("kg_co2", "kgCO2", "{:,.1f}"),
    ("kg_co2_estimable", "kgCO2, estimable jobs", "{:,.1f}"),
    ("intensity_g_per_kwh", "g/kWh", "{:,.1f}"),
    ("intensity_g_per_kwh_estimable", "g/kWh, estimable jobs", "{:,.1f}"),
    ("miss_rate", "Deadline misses", "{:.2%}"),
    ("stage2_calls", "Re-scores", "{:,.0f}"),
    ("moves", "Moves", "{:,.0f}"),
    ("rescues", "Rescues", "{:,.0f}"),
)
NO_DATA = '<p class="empty">No data yet for this tab.</p>'
STYLE = """
:root { color-scheme: light; }
body { margin: 0; background: #fcfcfb; color: #0b0b0b; font: 15px/1.5 system-ui, sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 24px; }
h1 { font-size: 22px; margin: 0 0 4px; }
.note { color: #52514e; margin: 0 0 16px; }
.tabs { display: flex; flex-wrap: wrap; gap: 4px; }
.panels { flex-basis: 100%; border-top: 1px solid #e6e5e0; padding-top: 16px; }
.tabs label { padding: 8px 14px; cursor: pointer; color: #52514e; border-radius: 6px 6px 0 0; }
input[name=tab] { position: absolute; opacity: 0; }
.panel { display: none; }
input:focus-visible + label { outline: 2px solid #2a78d6; }
img { max-width: 100%; height: auto; display: block; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { padding: 8px 10px; border-bottom: 1px solid #e6e5e0; text-align: right; }
th:first-child, td:first-child { text-align: left; }
th { color: #52514e; font-weight: 500; }
.empty { color: #52514e; padding: 48px 0; text-align: center; }
"""


def _img(fig, alt: str) -> str:
    data = base64.b64encode(figures.png_bytes(fig)).decode()
    return f'<img alt="{html.escape(alt)}" src="data:image/png;base64,{data}">'


def _table(means: pd.DataFrame) -> str:
    head = "".join(f"<th>{html.escape(label)}</th>" for _, label, _ in RESULT_COLUMNS)
    rows = []
    for policy, row in means.sort_index().iterrows():
        cells = []
        for col, _, fmt in RESULT_COLUMNS:
            if fmt is None:
                cells.append(f"<td>{html.escape(str(policy))}</td>")
            elif pd.isna(row.get(col)):
                cells.append("<td>–</td>")
            else:
                cells.append(f"<td>{fmt.format(row[col])}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _timeline_tab(runs_dir: Path, runs_root: Path) -> str:
    curves_path = runs_dir / "carbon_timeline.csv"
    runs_path = runs_dir / "runs.json"
    if not (curves_path.exists() and runs_path.exists()):
        return NO_DATA
    records = json.loads(runs_path.read_text())
    wanted = next((r for r in records if r["policy"] == "decision_flip"), None)
    wanted = wanted or next(iter(records), None)
    if wanted is None:
        return NO_DATA
    run_dir = runs_root / wanted["run_id"]
    if not (run_dir / "jobs.csv").exists():
        return NO_DATA
    manifest = json.loads((run_dir / "manifest.json").read_text())
    curves = pd.read_csv(curves_path)
    curves = curves[curves["replicate"] == wanted["replicate"]]
    if curves.empty:
        return NO_DATA
    regions = {d["dc_id"]: d["region_id"] for d in manifest["dcs"]}
    fig = figures.timeline(
        curves,
        pd.read_csv(run_dir / "jobs.csv", dtype={"job_id": str}),
        pd.read_csv(run_dir / "decisions.csv", dtype={"job_id": str}),
        regions,
    )
    alt = f"Forecast curves and one bar per job for {wanted['policy']}, {wanted['replicate']}"
    who = f"{wanted['policy']} on {wanted['replicate']}"
    caption = f"<p class='note'>{html.escape(who)}.</p>"
    return caption + _img(fig, alt)


def _theta_tab(sweep_dir: Path | None, unit: str) -> str:
    path = sweep_dir / "summary.csv" if sweep_dir is not None else None
    if path is None or not path.exists():
        return NO_DATA
    data = pd.read_csv(path)
    theta = next((c for c in data.columns if c.endswith(".theta")), None)
    flip = data[data["policy"] == "decision_flip"] if theta else data.iloc[0:0]
    if flip.empty:
        return NO_DATA
    means = flip.groupby(theta, as_index=False).mean(numeric_only=True)
    fig = figures.theta_sweep(means, theta, unit)
    return _img(fig, "Emissions and full re-scores against theta")


def build_dashboard(
    runs_dir: Path, sweep_dir: Path | None, out: Path, runs_root: Path | None = None
) -> Path:
    runs_root = runs_root if runs_root is not None else runs_dir.parent
    summary = read_summary(runs_dir)
    relative = summary is not None and (summary["power_label"] == "relative").any()
    unit = "relative kgCO2" if relative else "kgCO2"
    label = "kgCO2 are relative until power values are cited (B3)" if relative else "kgCO2 modelled"
    panels = {"timeline": _timeline_tab(runs_dir, runs_root), "theta": _theta_tab(sweep_dir, unit)}
    if summary is None:
        panels["pareto"] = panels["results"] = NO_DATA
    else:
        means = summary.groupby("policy", sort=True).mean(numeric_only=True)
        panels["pareto"] = _img(
            figures.scatter_policies(
                means,
                "stage2_calls",
                "kg_co2",
                "Full re-scores",
                f"Emissions ({unit})",
                "Emissions against re-scoring effort",
            ),
            "Emissions against full re-scores, one point per policy",
        )
        panels["results"] = _table(means)
    reps = 0 if summary is None else summary["replicate"].nunique()
    inputs, rules, sections = [], [], []
    for i, (key, title) in enumerate(TABS):
        checked = " checked" if i == 0 else ""
        inputs.append(f'<input type="radio" name="tab" id="t{i}"{checked}>')
        inputs.append(f'<label for="t{i}">{html.escape(title)}</label>')
        rules.append(f"#t{i}:checked ~ .panels #p{i} {{ display: block; }}")
        rules.append(f"#t{i}:checked + label {{ color: #0b0b0b; font-weight: 600; }}")
        sections.append(f'<section class="panel" id="p{i}">{panels[key]}</section>')
    note = (
        f"{reps} replicate(s). {html.escape(label)}. "
        "One week is noisy: read results across replicates, never from one."
    )
    page = (
        '<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        "<title>Flipwise results</title>"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<style>{STYLE}{''.join(rules)}</style></head><body><main>"
        f'<h1>Flipwise results</h1><p class="note">{note}</p>'
        f'<div class="tabs">{"".join(inputs)}'
        f'<div class="panels">{"".join(sections)}</div></div>'
        "</main></body></html>\n"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out
