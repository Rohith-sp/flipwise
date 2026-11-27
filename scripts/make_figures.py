"""Build every paper/slide figure from committed result CSVs (D66 stage C3).

Reads CSVs only; never runs a simulation. Missing inputs skip that figure with a note.
Usage: uv run python scripts/make_figures.py --out docs/figures \
    [--sweep rho=results/sweep_x] [--sweep slack=results/sweep_y] [--scaling results/scale_z]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
W = 3.5  # IEEE single-column width, inches
# Okabe-Ito colour-blind-safe palette.
PAL = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#000000", "#F0E442"]
CPU_COLS = [
    "scheduler_placement_s",
    "scheduler_screen_s",
    "scheduler_rescore_s",
    "scheduler_rescue_s",
]
SAVED: list[tuple[str, str]] = []  # (figure name, source) for the README


def style() -> None:
    plt.rcParams.update(
        {
            "font.size": 7,
            "axes.labelsize": 7,
            "legend.fontsize": 6,
            "xtick.labelsize": 6,
            "ytick.labelsize": 6,
            "axes.linewidth": 0.6,
            "lines.linewidth": 1.0,
            "pdf.fonttype": 42,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def read(path: Path) -> pd.DataFrame | None:
    return pd.read_csv(path) if path.is_file() else None


def save(fig, out: Path, name: str, source: str) -> None:
    fig.tight_layout()
    # Fixed metadata keeps repeated runs byte-stable.
    fig.savefig(out / f"{name}.png", dpi=300, metadata={"Software": None})
    fig.savefig(
        out / f"{name}.pdf",
        metadata={"Creator": None, "Producer": None, "CreationDate": None},
    )
    plt.close(fig)
    SAVED.append((name, source))
    print(f"wrote {name}.png/.pdf")


def skip(name: str, why: str) -> None:
    print(f"SKIP {name}: {why}")


def policy_means(summ: pd.DataFrame) -> pd.DataFrame:
    d = summ.copy()
    d["cpu_s"] = d[[c for c in CPU_COLS if c in d]].sum(axis=1)
    cols = [c for c in ["kg_co2", "stage2_calls", "moves", "cpu_s"] if c in d]
    return d.groupby("policy")[cols].mean().sort_index()


def fig1(out: Path, br: pd.DataFrame | None) -> None:
    name = "fig1_test_kgco2_vs_place_once"
    if br is None:
        return skip(name, "docs/power_bracket/bracket.csv missing")
    d = br[(br["split"] == "test") & (br["policy"] != "place_once")]
    if d.empty:
        return skip(name, "no test rows in bracket.csv")
    pols = sorted(d["policy"].unique())
    fig, ax = plt.subplots(figsize=(W, 2.6))
    y = np.arange(len(pols))
    for k, (mode, mk) in enumerate([("measured", "o"), ("nameplate", "s")]):
        m = d[d["mode"] == mode].set_index("policy").reindex(pols)
        diff = m["diff_vs_place_once_kg"]
        ax.errorbar(
            diff,
            y + (k - 0.5) * 0.3,
            xerr=[diff - m["ci95_lo"], m["ci95_hi"] - diff],
            fmt=mk,
            ms=3,
            capsize=2,
            color=PAL[k],
            label=f"{mode} power",
        )
    ax.axvline(0, color="grey", lw=0.6)
    ax.set_yticks(y, pols)
    ax.set_xlabel("kgCO2 difference vs place_once (paired, 95% CI)")
    ax.legend(frameon=False)
    save(fig, out, name, "docs/power_bracket/bracket.csv")


def fig2_3(out: Path, summ: pd.DataFrame | None) -> None:
    if summ is None:
        skip("fig2_cost", "docs/test_results/summary.csv missing")
        return skip("fig3_carbon_vs_cost", "docs/test_results/summary.csv missing")
    m = policy_means(summ)
    pols = list(m.index)
    fig, axs = plt.subplots(3, 1, figsize=(W, 4.2), sharex=True)
    labels = ["Full re-scores per run", "Moves per run", "Scheduler CPU (s per run)"]
    for ax, col, lab in zip(axs, ["stage2_calls", "moves", "cpu_s"], labels, strict=True):
        ax.bar(pols, m[col], color=PAL[: len(pols)], width=0.6)
        ax.set_ylabel(lab)
    axs[-1].tick_params(axis="x", rotation=40)
    save(fig, out, "fig2_cost", "docs/test_results/summary.csv")

    fig, ax = plt.subplots(figsize=(W, 2.6))
    for i, p in enumerate(pols):
        ax.scatter(m.loc[p, "cpu_s"], m.loc[p, "kg_co2"], s=18, color=PAL[i % len(PAL)], label=p)
    ax.set_xlabel("Scheduler CPU (s per run)")
    ax.set_ylabel("Test kgCO2 per run (relative power)")
    ax.legend(frameon=False, ncol=2)
    save(fig, out, "fig3_carbon_vs_cost", "docs/test_results/summary.csv")


def theta_rows(sw: pd.DataFrame | None) -> pd.DataFrame | None:
    if sw is None:
        return None
    d = sw[sw["sweep"] == "decision_flip.theta"].copy()
    if d.empty:
        return None
    d["theta"] = d["cell"].str.extract(r"=([0-9.eE+-]+)")[0].astype(float)
    return d.sort_values("theta")


def fig4_5(out: Path, sw: pd.DataFrame | None) -> None:
    d = theta_rows(sw)
    if d is None:
        skip("fig4_theta_sweep", "docs/validation/sweep_means.csv or theta rows missing")
        return skip("fig5_screen_pass_rate", "same")
    fig, ax = plt.subplots(figsize=(W, 2.4))
    ax.plot(d["theta"], d["kg_co2"], "o-", color=PAL[0])
    ax.set_xlabel("theta")
    ax.set_ylabel("Validation kgCO2 (frozen units)", color=PAL[0])
    ax2 = ax.twinx()
    ax2.spines["right"].set_visible(True)
    ax2.plot(d["theta"], d["moves"], "s--", color=PAL[1])
    ax2.set_ylabel("Moves per run", color=PAL[1])
    save(fig, out, "fig4_theta_sweep", "docs/validation/sweep_means.csv")

    pas = (d["stage2_calls"] / d["screened"]).clip(0, 1)
    fig, ax = plt.subplots(figsize=(W, 2.4))
    x = np.arange(len(d))
    ax.bar(x, pas, color=PAL[0], width=0.6, label="passed screen (full re-score)")
    ax.bar(x, 1 - pas, bottom=pas, color=PAL[5], width=0.6, label="skipped by screen")
    ax.set_xticks(x, [f"{t:g}" for t in d["theta"]])
    ax.set_xlabel("theta")
    ax.set_ylabel("Share of screened checks")
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.25), ncol=2)
    save(fig, out, "fig5_screen_pass_rate", "docs/validation/sweep_means.csv")


def fig6(out: Path, sweeps: dict[str, Path]) -> None:
    if not sweeps:
        return skip("fig6_rho_slack_sensitivity", "no --sweep given")
    n = len(sweeps)
    fig, axs = plt.subplots(2, n, figsize=(W * n, 3.6), squeeze=False)
    used = False
    for j, (nm, p) in enumerate(sweeps.items()):
        d = read(p / "sweep_means.csv" if p.is_dir() else p)
        if d is None or "cell" not in d or "place_once_kg_co2" not in d:
            print(f"note: sweep {nm}: no usable sweep_means.csv at {p}")
            continue
        d = d.copy()
        d["x"] = d["cell"].astype(str).str.extract(r"=\s*([0-9.eE+-]+)")[0].astype(float)
        d["delta"] = 100 * (d["kg_co2"] / d["place_once_kg_co2"] - 1)
        for i, (pol, g) in enumerate(d.dropna(subset=["x"]).groupby("policy")):
            g = g.sort_values("x")
            axs[0, j].plot(g["x"], g["delta"], "o-", ms=3, color=PAL[i % 8], label=pol)
            axs[1, j].plot(g["x"], 100 * g["miss_rate"], "o-", ms=3, color=PAL[i % 8])
        axs[0, j].set_ylabel("kgCO2 vs place_once (%)")
        axs[1, j].set_ylabel("Deadline miss rate (%)")
        axs[1, j].set_xlabel(nm)
        axs[0, j].axhline(0, color="grey", lw=0.6)
        axs[0, j].legend(frameon=False)
        used = True
    if not used:
        plt.close(fig)
        return skip("fig6_rho_slack_sensitivity", "no usable sweep data")
    save(fig, out, "fig6_rho_slack_sensitivity", "--sweep results (sweep_means.csv)")


def fig7(out: Path, scaling: Path | None) -> None:
    name = "fig7_load_scaling"
    if scaling is None:
        return skip(name, "no --scaling given")
    f = scaling / "summary.csv" if scaling.is_dir() else scaling
    d = read(f)
    if d is None or "mean_waiting_jobs" not in d:
        return skip(name, f"{f} missing or lacks mean_waiting_jobs")
    d = d.copy()
    d["cpu_s"] = d[[c for c in CPU_COLS if c in d]].sum(axis=1)
    # CPU time depends on the machine (and its throttling); the operation count does not (D71),
    # so it is plotted beside CPU time when the summary has it.
    panels = [("cpu_s", "Scheduler CPU (s per run)")]
    if "ops_start_queries" in d and d["ops_start_queries"].fillna(0).gt(0).any():
        panels.append(("ops_start_queries", "Wait-profile queries per run"))
    fig, axes = plt.subplots(1, len(panels), figsize=(W * len(panels), 2.8), squeeze=False)
    for ax, (col, label) in zip(axes[0], panels, strict=True):
        for i, (pol, g) in enumerate(d.groupby("policy")):
            g = g[(g[col] > 0) & (g["mean_waiting_jobs"] > 0)]
            gx = g.groupby("mean_waiting_jobs")[col].mean()
            if len(gx) < 2:
                continue
            slope = np.polyfit(np.log10(gx.index.values), np.log10(gx.values), 1)[0]
            ax.loglog(
                gx.index,
                gx.values,
                "o-",
                ms=3,
                color=PAL[i % 8],
                label=f"{pol} (slope {slope:.2f})",
            )
        ax.set_xlabel("Mean waiting jobs")
        ax.set_ylabel(label)
        ax.legend(frameon=False)
    save(fig, out, name, str(f))


def write_readme(out: Path) -> None:
    lines = ["# Figures", "", "Built by `scripts/make_figures.py` from committed CSVs only.", ""]
    lines += [f"- `{n}.png` / `{n}.pdf`: source `{s}`" for n, s in SAVED]
    (out / "README.md").write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/figures")
    ap.add_argument("--sweep", action="append", default=[], metavar="NAME=PATH")
    ap.add_argument("--scaling")
    ap.add_argument("--root", default=str(ROOT), help="repo root holding docs/")
    a = ap.parse_args(argv)
    root = Path(a.root)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    SAVED.clear()
    style()
    sweeps = {}
    for s in a.sweep:
        k, _, v = s.partition("=")
        sweeps[k] = Path(v)
    fig1(out, read(root / "docs/power_bracket/bracket.csv"))
    fig2_3(out, read(root / "docs/test_results/summary.csv"))
    fig4_5(out, read(root / "docs/validation/sweep_means.csv"))
    fig6(out, sweeps)
    fig7(out, Path(a.scaling) if a.scaling else None)
    write_readme(out)


if __name__ == "__main__":
    main()
