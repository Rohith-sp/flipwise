"""make_figures: tiny synthetic CSVs build figures; missing inputs skip without crashing."""

import importlib.util
from pathlib import Path

import pandas as pd

spec = importlib.util.spec_from_file_location(
    "make_figures", Path(__file__).parent.parent / "scripts" / "make_figures.py"
)
mf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mf)


def test_missing_inputs_skip(tmp_path, capsys):
    mf.main(["--out", str(tmp_path / "o"), "--root", str(tmp_path)])
    assert "SKIP" in capsys.readouterr().out
    assert (tmp_path / "o" / "README.md").exists()


def test_cost_and_scaling_figures(tmp_path):
    docs = tmp_path / "docs" / "test_results"
    docs.mkdir(parents=True)
    pd.DataFrame(
        {
            "policy": ["a", "b"],
            "kg_co2": [1.0, 2.0],
            "stage2_calls": [3, 4],
            "moves": [1, 2],
            "scheduler_placement_s": [1.0, 2.0],
            "scheduler_screen_s": [0.1, 0.2],
            "scheduler_rescore_s": [0.5, 0.5],
            "scheduler_rescue_s": [0.0, 0.1],
        }
    ).to_csv(docs / "summary.csv", index=False)
    sc = tmp_path / "scale.csv"
    pd.DataFrame(
        {
            "policy": ["a"] * 3,
            "mean_waiting_jobs": [10, 100, 1000],
            "scheduler_placement_s": [1.0, 10.0, 100.0],
        }
    ).to_csv(sc, index=False)
    out = tmp_path / "o"
    mf.main(["--out", str(out), "--root", str(tmp_path), "--scaling", str(sc)])
    for n in ["fig2_cost", "fig3_carbon_vs_cost", "fig7_load_scaling"]:
        assert (out / f"{n}.png").exists() and (out / f"{n}.pdf").exists()
