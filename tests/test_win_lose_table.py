"""win_lose_table: verdicts from tiny synthetic sweeps (PRD 18.2 goal 1, §14.8, D70)."""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

spec = importlib.util.spec_from_file_location(
    "win_lose_table", Path(__file__).parent.parent / "scripts" / "win_lose_table.py"
)
wl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wl)

SLICES = (25, 32, 39)
STARTS = ("2023-07-03", "2023-07-17", "2023-07-31", "2023-08-14")


def _compare(root: Path, name: str, flip_gap: float, split: str = "validation") -> None:
    rows = []
    for i, d in enumerate(SLICES):
        for j, m in enumerate(STARTS):
            rep = f"{split}_d{d}_{m}"
            base = 1000.0 + 10 * i + j
            noise = 0.5 if (i + j) % 2 else -0.5  # mean 0 over the 3 × 4 grid
            for policy, kg, calls in (
                ("place_once", base, 0),
                ("fixed_savings", base + flip_gap, 400),
                ("decision_flip", base + flip_gap + noise, 100),
            ):
                rows.append(
                    {"replicate": rep, "policy": policy, "kg_co2": kg, "miss_rate": 0.04,
                     "stage2_calls": calls}
                )  # fmt: skip
    (root / name).mkdir(parents=True)
    pd.DataFrame(rows).to_csv(root / name / "summary.csv", index=False)


def _sweep(root: Path, cells: dict[str, str]) -> Path:
    rows = [
        {"scenario.rho": rho, "policy": p, "compare": cmp, "kg_co2": 0.0, "miss_rate": 0.0}
        for rho, cmp in cells.items()
        for p in ("place_once", "decision_flip")
    ]
    path = root / "sweep_x"
    path.mkdir()
    pd.DataFrame(rows).to_csv(path / "summary.csv", index=False)
    return path


def test_verdicts_follow_the_crossed_interval(tmp_path):
    _compare(tmp_path, "compare_low", flip_gap=-50.0)
    _compare(tmp_path, "compare_high", flip_gap=+50.0)
    _compare(tmp_path, "compare_same", flip_gap=0.0)
    sweep = _sweep(tmp_path, {"0.4": "compare_low", "0.9": "compare_high", "0.7": "compare_same"})
    out = tmp_path / "out"
    wl.main(["--sweep", f"rho={sweep}", "--out", str(out)])
    t = pd.read_csv(out / "win_lose.csv")
    vs_once = t[t["rival"] == "place_once"].set_index("cell")["verdict"].to_dict()
    assert vs_once == {"rho=0.4": "wins", "rho=0.9": "loses", "rho=0.7": "tie"}
    assert set(t["ci_used"]) == {"crossed"}
    assert (t[t["rival"] == "fixed_savings"]["rescore_ratio"] == 0.25).all()
    md = (out / "win_lose.md").read_text(encoding="utf-8")
    assert "Helps against `place_once` when:** rho: rho=0.4" in md


def test_refuses_test_split_replicates(tmp_path):
    """PRD §14.3: the test split is spent; the table is for validation sweeps only."""
    _compare(tmp_path, "compare_t", flip_gap=-50.0, split="test")
    sweep = _sweep(tmp_path, {"0.7": "compare_t"})
    with pytest.raises(SystemExit, match="test-split"):
        wl.main(["--sweep", f"rho={sweep}", "--out", str(tmp_path / "out")])
