"""Run layout, compare, sweep, report, dashboard (R-POL-1, R-REP-1, R-REP-2, R-FAIR-1, §14.8)."""

import json
import shutil

import pandas as pd
import pytest
import yaml

from flipwise.cli import main
from flipwise.config import load_config
from flipwise.dashboard import build_dashboard
from flipwise.errors import ConfigError, ReportError
from flipwise.experiment import ALL_POLICIES, _baselines_worse, compare, replicates_for, sweep
from flipwise.reporting import build_report
from flipwise.smoke import TOY_DIR

SOME = ["fcfs", "place_once", "fixed_savings", "decision_flip"]


@pytest.fixture(scope="module")
def toy_compare(tmp_path_factory):
    out = tmp_path_factory.mktemp("results")
    return compare({"policies": {}}, list(ALL_POLICIES), out=out, scenario_dir=TOY_DIR), out


def test_all_seven_policies_run_r_pol_1(toy_compare):
    cmp_dir, _ = toy_compare
    summary = pd.read_csv(cmp_dir / "summary.csv")
    assert len(ALL_POLICIES) == 7
    assert sorted(summary["policy"]) == sorted(ALL_POLICIES)
    # The estimable-job columns sit beside the all-jobs ones (PRD §14.1).
    for col in ("kg_co2_estimable", "intensity_g_per_kwh_estimable", "n_estimable"):
        assert col in summary.columns


def test_summary_deltas_against_baselines_prd_14_1(toy_compare):
    summary = pd.read_csv(toy_compare[0] / "summary.csv").set_index("policy")
    assert summary.loc["place_once", "delta_kg_co2_pct_vs_place_once"] == 0
    # fixed_savings 1.504 against place_once 2.308 (expected.yaml).
    assert summary.loc["fixed_savings", "delta_kg_co2_pct_vs_place_once"] == pytest.approx(
        100 * (1.504 - 2.308) / 2.308
    )


def test_manifest_schema_r_rep_1(toy_compare):
    cmp_dir, out = toy_compare
    records = json.loads((cmp_dir / "runs.json").read_text())
    by_policy = {r["policy"]: r for r in records}
    man = json.loads((out / by_policy["decision_flip"]["run_id"] / "manifest.json").read_text())
    for key in (
        "config", "config_hash", "scenario_hash", "data_manifests", "policy", "policy_params",
        "seed", "git", "uv_lock_sha256", "packages", "python", "platform", "cpu_model",
        "wall_clock", "uses_oracle", "output_sha256", "dcs", "run_id",
    ):  # fmt: skip
        assert key in man, key
    assert man["uses_oracle"] is False
    pig = json.loads((out / by_policy["pig"]["run_id"] / "manifest.json").read_text())
    assert pig["uses_oracle"] is True


def test_report_rebuilds_from_saved_logs_alone_r_rep_2(toy_compare):
    cmp_dir, out = toy_compare
    before = {n: (cmp_dir / n).read_bytes() for n in ("summary.csv", "paired.csv")}
    shutil.rmtree(cmp_dir / "figures")
    (cmp_dir / "summary.csv").unlink()
    (cmp_dir / "paired.csv").unlink()
    build_report(cmp_dir, out)
    assert {n: (cmp_dir / n).read_bytes() for n in before} == before
    assert (cmp_dir / "figures" / "emissions_vs_stage2.png").exists()


def test_report_refuses_mismatched_scenario_hashes_r_fair_1(toy_compare, tmp_path):
    cmp_dir, out = toy_compare
    tampered = tmp_path / "tampered"
    tampered.mkdir()
    records = json.loads((cmp_dir / "runs.json").read_text())
    records[0]["scenario_hash"] = "something else"
    (tampered / "runs.json").write_text(json.dumps(records))
    with pytest.raises(ReportError, match="different scenario hashes"):
        build_report(tampered, out)


def test_report_refuses_a_run_whose_manifest_disagrees_r_fair_1(toy_compare, tmp_path):
    cmp_dir, out = toy_compare
    records = json.loads((cmp_dir / "runs.json").read_text())
    for r in records:
        r["scenario_hash"] = "a different world"
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "runs.json").write_text(json.dumps(records))
    with pytest.raises(ReportError, match="scenario hash differs"):
        build_report(bad, out)


def test_report_refuses_missing_logs(toy_compare, tmp_path):
    cmp_dir, _ = toy_compare
    empty_root = tmp_path / "elsewhere"
    empty_root.mkdir()
    with pytest.raises(ReportError, match="logs are missing"):
        build_report(cmp_dir, empty_root)


def test_existing_runs_are_reused(tmp_path):
    compare({"policies": {}}, ["fcfs"], out=tmp_path, scenario_dir=TOY_DIR)
    run_dir = next(p for p in tmp_path.iterdir() if not p.name.startswith("compare_"))
    stamp = (run_dir / "manifest.json").read_text()
    (run_dir / "manifest.json").write_text(stamp + " ")
    compare({"policies": {}}, ["fcfs"], out=tmp_path, scenario_dir=TOY_DIR)
    assert (run_dir / "manifest.json").read_text() == stamp + " "


def test_unfinished_run_is_not_reused(tmp_path):
    compare({"policies": {}}, ["fcfs"], out=tmp_path, scenario_dir=TOY_DIR)
    run_dir = next(p for p in tmp_path.iterdir() if not p.name.startswith("compare_"))
    (run_dir / "metrics.json").unlink()
    compare({"policies": {}}, ["fcfs"], out=tmp_path, scenario_dir=TOY_DIR)
    assert (run_dir / "metrics.json").exists()


def test_parallel_runs_give_the_same_summary(tmp_path):
    a = compare({"policies": {}}, SOME, out=tmp_path / "a", scenario_dir=TOY_DIR)
    b = compare({"policies": {}}, SOME, out=tmp_path / "b", scenario_dir=TOY_DIR, jobs=2)
    drop = [c for c in pd.read_csv(a / "summary.csv").columns if c.startswith("scheduler_")]
    left = pd.read_csv(a / "summary.csv").drop(columns=drop)
    right = pd.read_csv(b / "summary.csv").drop(columns=drop)
    pd.testing.assert_frame_equal(left, right)


def test_policy_parameters_change_the_run_but_not_other_policies_runs(tmp_path):
    def runs(theta):
        cfg = {"policies": {"decision_flip": {"theta": theta}}}
        cmp_dir = compare(cfg, ["fcfs", "decision_flip"], out=tmp_path, scenario_dir=TOY_DIR)
        return {r["policy"]: r["run_id"] for r in json.loads((cmp_dir / "runs.json").read_text())}

    a, b = runs(0.1), runs(0.5)
    assert a["fcfs"] == b["fcfs"]
    assert a["decision_flip"] != b["decision_flip"]


def test_a_mistyped_policy_fails_before_anything_runs(tmp_path):
    with pytest.raises(ConfigError):
        compare({"policies": {}}, ["fcfs", "nope"], out=tmp_path, scenario_dir=TOY_DIR)
    assert not list(tmp_path.iterdir())


def test_replicates_follow_prd_14_2():
    cfg = load_config("configs/base.yaml")
    assert len(replicates_for(cfg, "dev")) == 1
    validation = replicates_for(cfg, "validation")
    assert len(validation) == 12
    assert {r.trace_days[0] for r in validation} == {25, 32, 39}
    test = replicates_for(cfg, "test")
    assert len(test) == 16 and {r.trace_days[0] for r in test} == {46, 53, 60, 67}
    with pytest.raises(ConfigError):
        replicates_for(cfg, "nope")


def test_sweep_writes_one_row_per_cell_and_policy(tmp_path):
    grid = tmp_path / "g.yaml"
    grid.write_text(yaml.safe_dump({"grid": {"policies.decision_flip.theta": [0, 0.5]}}))
    cfg = {"policies": {"decision_flip": {"theta": 0.1}}}
    out = sweep(cfg, grid, ["place_once", "decision_flip"], out=tmp_path, scenario_dir=TOY_DIR)
    data = pd.read_csv(out / "summary.csv")
    assert len(data) == 4
    assert sorted(data["policies.decision_flip.theta"].unique()) == [0, 0.5]


def test_sweep_needs_a_grid(tmp_path):
    bad = tmp_path / "g.yaml"
    bad.write_text("nothing: here\n")
    with pytest.raises(ConfigError):
        sweep({"policies": {}}, bad, ["fcfs"], out=tmp_path, scenario_dir=TOY_DIR)


def test_worse_regimes_list_prd_14_8():
    means = pd.DataFrame(
        {"kg_co2": [10.0, 9.0, 9.0, 11.0], "miss_rate": [0.1, 0.1, 0.2, 0.05]},
        index=["decision_flip", "better", "cleaner_but_later", "dirtier"],
    )
    assert _baselines_worse(means) == "better"
    assert _baselines_worse(means.drop("decision_flip")) == ""


def test_dashboard_is_self_contained(toy_compare, tmp_path):
    cmp_dir, out = toy_compare
    page = build_dashboard(cmp_dir, None, tmp_path / "d.html", out).read_text(encoding="utf-8")
    assert page.count('<section class="panel"') == 4
    assert "data:image/png;base64," in page and "kgCO2" in page
    assert "http://" not in page and "https://" not in page
    assert "No data yet" in page  # the θ tab, since no sweep was given


def test_dashboard_survives_missing_inputs(tmp_path):
    (tmp_path / "compare_x").mkdir()
    page = build_dashboard(tmp_path / "compare_x", tmp_path / "no_sweep", tmp_path / "d.html")
    assert page.read_text(encoding="utf-8").count("No data yet") == 4


def test_cli_compare_report_dashboard(tmp_path, capsys):
    results = str(tmp_path)
    args = ["--scenario", str(TOY_DIR), "--out", results]
    assert main(["compare", *args, "--policies", "fcfs,place_once"]) == 0
    cmp_dir = next(tmp_path.glob("compare_*"))
    assert main(["report", "--runs", str(cmp_dir)]) == 0
    out = tmp_path / "d.html"
    assert main(["dashboard", "--runs", str(cmp_dir), "--out", str(out)]) == 0
    assert out.exists()
    assert main(["run", *args, "--policy", "decision_flip"]) == 0
