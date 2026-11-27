"""Paired statistics in the result tables (PRD 18.2 goal 3, D66)."""

import numpy as np
import pandas as pd

from flipwise.reporting import (
    BOOTSTRAP_SEED,
    PAIRED_METRICS,
    _paired,
    add_holm,
    bootstrap_ci,
    cohens_dz,
    holm_adjust,
    paired_p_value,
)


def test_holm_hand_computed():
    assert np.allclose(holm_adjust([0.01, 0.04, 0.03]), [0.03, 0.06, 0.06])


def test_holm_caps_at_one_and_groups_by_metric():
    t = pd.DataFrame({"metric": ["a", "a", "b"], "p_value": [0.6, 0.7, 0.2]})
    out = add_holm(t)
    assert list(out["p_holm"]) == [1.0, 1.0, 0.2]


def test_cohens_dz_small_example():
    d = np.array([1.0, 2.0, 3.0])  # mean 2, sd 1
    assert cohens_dz(d) == 2.0
    assert np.isnan(cohens_dz(np.array([1.0, 1.0])))
    assert np.isnan(cohens_dz(np.array([1.0])))


def test_p_value_exact_and_deterministic():
    d = np.array([1.0, 2.0, 3.0])  # only +++ and --- reach |sum| = 6, of 8 patterns
    assert paired_p_value(d) == 2 / 8
    big = np.linspace(0.1, 2.0, 30)
    assert paired_p_value(big, seed=5) == paired_p_value(big, seed=5)
    assert paired_p_value(big) < 0.01
    assert paired_p_value(np.zeros(5)) == 1.0


def test_paired_keeps_existing_columns_and_ci():
    rows = []
    for rep in range(6):
        rows.append({"policy": "place_once", "replicate": rep, "kg_co2": 100.0 + rep})
        rows.append({"policy": "fcfs", "replicate": rep, "kg_co2": 90.0 + 2 * rep})
    s = pd.DataFrame(rows)
    for m in PAIRED_METRICS[1:]:
        s[m] = s["kg_co2"]
    out = _paired(s)
    row = out[out["metric"] == "kg_co2"].iloc[0]
    diff = np.array([-10.0 + rep for rep in range(6)])
    lo, hi = bootstrap_ci(diff, np.random.default_rng(BOOTSTRAP_SEED))
    assert row["mean_diff"] == diff.mean() and row["ci95_lo"] == lo and row["ci95_hi"] == hi
    assert list(out.columns)[-3:] == ["p_value", "p_holm", "cohens_dz"]
