"""Matplotlib figures for `report` and `dashboard`, drawn from saved CSVs only (PRD §13.3)."""

from __future__ import annotations

import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display: figures are only ever written to files

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e6e5e0"
MUTED_MARK = "#a8a7a1"
HIGHLIGHT = "#2a78d6"
# Checked for colour-blind separation, all pairs. Chennai's green is under 3:1 on this surface, so
# the legend and the results table carry identity as well.
REGION_COLOURS = {1: "#2a78d6", 2: "#eb6834", 3: "#1baf7a"}
REGION_NAMES = {1: "Delhi NCR (NR)", 2: "Mumbai (WR)", 3: "Chennai (SR)"}
PROPOSED = "decision_flip"


def _axes(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.xaxis.label.set_color(INK_SECONDARY)
    ax.yaxis.label.set_color(INK_SECONDARY)


def _figure(w: float = 8.0, h: float = 4.5, **kw):
    fig, axes = plt.subplots(figsize=(w, h), dpi=130, facecolor=SURFACE, **kw)
    for ax in axes.flat if hasattr(axes, "flat") else [axes]:
        _axes(ax)
    return fig, axes


def _title(ax, text: str) -> None:
    ax.set_title(text, loc="left", fontsize=11, color=INK, pad=10)


def scatter_policies(
    means: pd.DataFrame, x: str, y: str, xlabel: str, ylabel: str, title: str
) -> plt.Figure:
    """One point per policy, each named beside it. The proposed policy carries the only colour:
    seven hues cannot all be told apart in a scatter, and the question is where that one sits."""
    fig, ax = _figure()
    for policy, row in means.sort_index().iterrows():
        proposed = policy == PROPOSED
        ax.scatter(
            row[x],
            row[y],
            s=90 if proposed else 55,
            color=HIGHLIGHT if proposed else MUTED_MARK,
            edgecolor=SURFACE,
            linewidth=2,
            zorder=3,
        )
        ax.annotate(
            policy,
            (row[x], row[y]),
            xytext=(8, 5),
            textcoords="offset points",
            fontsize=9,
            color=INK if proposed else INK_SECONDARY,
        )
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.margins(0.15)
    _title(ax, title)
    fig.tight_layout()
    return fig


def bars_by_policy(means: pd.Series, xlabel: str, title: str, percent: bool = False) -> plt.Figure:
    """Ranked horizontal bars, one hue, values printed at the end of each."""
    data = means.dropna().sort_values()
    fig, ax = _figure(h=max(2.2, 0.5 * len(data) + 1.2))
    bars = ax.barh(data.index, data.values, color=HIGHLIGHT, height=0.55, edgecolor=SURFACE)
    for bar, value in zip(bars, data.values, strict=True):
        label = f"{value * 100:.2f} %" if percent else f"{value:,.3g}"
        ax.annotate(
            label,
            (bar.get_width(), bar.get_y() + bar.get_height() / 2),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=INK_SECONDARY,
        )
    ax.grid(False, axis="y")
    ax.set_xlabel(xlabel)
    ax.margins(x=0.18)
    if percent:
        ax.xaxis.set_major_formatter(lambda v, _: f"{v * 100:g} %")
    _title(ax, title)
    fig.tight_layout()
    return fig


def coverage_by_bucket(coverage: pd.DataFrame) -> plt.Figure:
    """Carbon interval coverage per lead bucket, against the nominal 90 %."""
    labels = ["0–6 h", "6–12 h", "12–24 h", "24–48 h"]
    mean = coverage.groupby("lead_bucket")["coverage"].mean()
    fig, ax = _figure(h=3.6)
    ax.bar([labels[int(b)] for b in mean.index], mean.values, color=HIGHLIGHT, width=0.5)
    ax.axhline(0.9, color=INK_SECONDARY, linewidth=1, linestyle=(0, (4, 3)))
    ax.annotate(
        "nominal 90 %",
        (1, 0.9),
        xycoords=("axes fraction", "data"),
        xytext=(-4, 4),
        textcoords="offset points",
        ha="right",
        fontsize=9,
        color=INK_SECONDARY,
    )
    ax.grid(False, axis="x")
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v * 100:g} %")
    ax.set_xlabel("Forecast lead time")
    _title(ax, "Carbon interval coverage by lead time")
    fig.tight_layout()
    return fig


def screen_pass_rates(rates: pd.Series) -> plt.Figure:
    """One tick per replicate: with few replicates a histogram would suggest a shape it lacks."""
    fig, ax = _figure(h=2.4)
    ax.scatter(rates.values, [0] * len(rates), s=70, color=HIGHLIGHT, edgecolor=SURFACE, zorder=3)
    ax.set_xlim(0, 1)
    ax.set_yticks([])
    ax.grid(False, axis="y")
    ax.xaxis.set_major_formatter(lambda v, _: f"{v * 100:g} %")
    ax.set_xlabel("Share of screened jobs that went on to a full re-score, per replicate")
    _title(ax, f"Screen pass rate: {rates.mean() * 100:.1f} % mean over {len(rates)} replicate(s)")
    fig.tight_layout()
    return fig


def timeline(
    curves: pd.DataFrame, jobs: pd.DataFrame, decisions: pd.DataFrame, regions: dict[int, int]
) -> plt.Figure:
    """The hero figure (PRD §4.1 item 9): forecasts above, one bar per job below, sharing one time
    axis. `regions` maps `dc_id` to `region_id`; a job's bar takes its region's colour."""
    t0 = min(curves["slot_utc"].min(), jobs["start_s"].min())
    to_day = lambda s: (s - t0) / 86400  # noqa: E731
    fig, (top, bottom) = _figure(h=6.5, nrows=2, sharex=True, gridspec_kw={"height_ratios": [2, 3]})
    for region, group in curves.groupby("region_id", sort=True):
        group = group.sort_values("slot_utc")
        top.plot(
            to_day(group["slot_utc"]),
            group["forecast_g_per_kwh"],
            color=REGION_COLOURS.get(region, MUTED_MARK),
            linewidth=1.5,
            label=REGION_NAMES.get(region, f"Region {region}"),
        )
    top.set_ylabel("Forecast (gCO2/kWh)")
    top.legend(loc="upper right", ncols=3, frameon=False, fontsize=9, labelcolor=INK_SECONDARY)
    top.margins(y=0.2)
    _title(top, "Forecast intensity, and where and when each job ran")

    ran = jobs[jobs["start_s"].notna()].sort_values(["dc_id", "start_s", "job_id"])
    n_lanes = 40
    offsets = {dc: i * (n_lanes + 8) for i, dc in enumerate(sorted(regions))}
    seen: dict[int, int] = {}
    segments, colours, rows = [], [], {}
    for j in ran.itertuples(index=False):
        dc = int(j.dc_id)
        row = offsets[dc] + seen.get(dc, 0) % n_lanes
        seen[dc] = seen.get(dc, 0) + 1
        rows[j.job_id] = row
        end = j.end_s if pd.notna(j.end_s) else j.start_s
        segments.append([(to_day(j.start_s), row), (to_day(end), row)])
        colours.append(REGION_COLOURS.get(regions[dc], MUTED_MARK))
    bottom.add_collection(LineCollection(segments, colors=colours, linewidths=1.1, alpha=0.75))
    moves = decisions[decisions["kind"] == "MOVE"]
    moved = moves[moves["job_id"].isin(rows)]
    if len(moved):
        bottom.scatter(
            to_day(moved["time_s"]),
            [rows[j] for j in moved["job_id"]],
            marker="|",
            s=14,
            color=INK,
            linewidth=0.8,
            alpha=0.7,
            zorder=3,
            label=f"Job moved ({len(moved):,})",
        )
        bottom.legend(loc="upper right", frameon=False, fontsize=9, labelcolor=INK_SECONDARY)
    bottom.set_yticks(
        [offsets[d] + n_lanes / 2 for d in sorted(regions)],
        [REGION_NAMES.get(regions[d], f"dc{d}") for d in sorted(regions)],
    )
    bottom.grid(False, axis="y")
    bottom.set_xlabel("Days since the run started")
    bottom.autoscale_view()
    fig.tight_layout()
    return fig


def theta_sweep(means: pd.DataFrame, theta: str, unit: str = "kgCO2") -> plt.Figure:
    """Two charts on one θ axis, never two scales on one chart."""
    fig, (left, right) = _figure(w=9, h=3.6, ncols=2)
    data = means.sort_values(theta)
    for ax, col, label in (
        (left, "kg_co2", f"Emissions ({unit})"),
        (right, "stage2_calls", "Full re-scores"),
    ):
        ax.plot(data[theta], data[col], color=HIGHLIGHT, linewidth=2, marker="o", markersize=7)
        ax.set_xlabel("θ")
        ax.margins(0.15)
        _title(ax, label)
    fig.tight_layout()
    return fig


def save(fig: plt.Figure, path: Path) -> None:
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def png_bytes(fig: plt.Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SURFACE)
    plt.close(fig)
    return buf.getvalue()
