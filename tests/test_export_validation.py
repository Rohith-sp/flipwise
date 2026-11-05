"""The validation export works from saved runs alone, and is small enough for git."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from flipwise.experiment import ALL_POLICIES, compare, sweep

ROOT = Path(__file__).parent.parent
TOY_DIR = Path(__file__).parent / "fixtures" / "toy"


def _script():
    spec = importlib.util.spec_from_file_location(
        "export_validation", ROOT / "scripts" / "export_validation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _export(tmp_path):
    cfg = {"policies": {"decision_flip": {"theta": 0.1, "g_rel": 0.05}}}
    results = tmp_path / "results"
    cmp_dir = compare(cfg, list(ALL_POLICIES), out=results, scenario_dir=TOY_DIR)
    grid = tmp_path / "grid.yaml"
    grid.write_text(yaml.safe_dump({"grid": {"policies.decision_flip.theta": [0.1, 0.5]}}))
    swept = sweep(cfg, grid, ["place_once", "decision_flip"], out=results, scenario_dir=TOY_DIR)
    frozen = tmp_path / "policies.yaml"
    frozen.write_text(yaml.safe_dump(cfg["policies"]))
    out = tmp_path / "export"
    _script().export(cmp_dir, [swept], out, frozen)
    return out


def test_export_writes_every_table_and_marks_the_frozen_cell(tmp_path):
    out = _export(tmp_path)
    for name in ("summary.csv", "paired.csv", "pairwise.csv", "diagnostics.csv", "runs.csv"):
        assert not pd.read_csv(out / name).empty, name
    means = pd.read_csv(out / "sweep_means.csv").set_index("cell")
    assert means.loc["theta=0.1", "frozen"]
    assert not means.loc["theta=0.5", "frozen"]
    assert means.loc["theta=0.1", "kg_co2_vs_frozen"] == 0
    assert (out / "figures" / "sweep_decision_flip_theta.png").exists()
    assert (out / "dashboard.html").exists()


def test_score_scale_sets_the_sweep_values_of_prd_10_10(tmp_path):
    scale = json.loads((_export(tmp_path) / "score_scale.json").read_text())
    assert np.isclose(scale["g_abs_sweep_value"], 0.05 * scale["median_S"])
    assert np.isclose(scale["kappa_sweep_value"], 0.02 * scale["median_S"])


def test_pairwise_ci_contains_the_mean_and_pairs_by_replicate():
    module = _script()
    rows = [
        {"replicate": r, "policy": p, "kg_co2": v, "kg_co2_estimable": v}
        | {"miss_rate": 0.0, "stage2_calls": 0.0, "moves": 0.0}
        for r, a, b in (("x", 10.0, 7.0), ("y", 100.0, 99.0), ("z", 50.0, 48.0))
        for p, v in (("decision_flip", a), ("place_once", b))
    ]
    table = module.pairwise(pd.DataFrame(rows))
    row = table[table["metric"] == "kg_co2"].iloc[0]
    assert np.isclose(row["mean_diff"], 2.0)  # unpaired spread would swamp this
    assert 1.0 <= row["ci95_lo"] <= row["mean_diff"] <= row["ci95_hi"] <= 3.0


def test_gap_is_measured_against_the_frozen_comparison_not_the_last_cell(tmp_path):
    """A grid need not contain the frozen value, and cells must not overwrite the reference."""
    module = _script()

    def table(policy_kg):
        return pd.DataFrame(
            [
                {"replicate": "x", "policy": p, "kg_co2": v}
                | dict.fromkeys(module.METRICS[1:], 0.0)
                for p, v in policy_kg.items()
            ]
        )

    frozen_cmp = table({"decision_flip": 100.0, "place_once": 200.0})
    grid = tmp_path / "sweep_a"
    grid.mkdir()
    key = "policies.decision_flip.theta"
    rows = []
    for theta, kg in ((0.5, 130.0), (0.9, 170.0)):
        name = f"compare_{int(theta * 10)}"
        (tmp_path / name).mkdir()
        table({"decision_flip": kg, "place_once": 200.0}).to_csv(
            tmp_path / name / "summary.csv", index=False
        )
        rows.append({key: theta, "policy": "decision_flip", "compare": name})
    pd.DataFrame(rows).to_csv(grid / "summary.csv", index=False)
    _, means = module.sweep_tables([grid], {"decision_flip": {"theta": 0.1}}, frozen_cmp)
    assert list(means["kg_co2_vs_frozen"]) == [30.0, 70.0]
