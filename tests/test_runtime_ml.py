"""X10 learned runtime quantiles (PRD §4.2, D66): monotone, deterministic, no leakage."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from flipwise import runtime_ml
from flipwise.config import load_config
from flipwise.errors import ConfigError
from flipwise.estimates import fit_runtime
from flipwise.runtime_ml import (
    FEATURE_SOURCE_COLUMNS,
    TARGET_COLUMN,
    fit_learned,
    interval_coverage,
    pinball_loss,
    table_quantiles,
)
from flipwise.scenario import Replicate, build_replicate

pytest.importorskip("sklearn")


def _jobs(n: int = 400, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    user = rng.choice(["a", "b", "c"], n)
    base = np.where(user == "a", 600.0, np.where(user == "b", 6000.0, 60000.0))
    return pd.DataFrame(
        {
            "job_id": [f"j{i}" for i in range(n)], "user": user,
            "trace_arrival_s": rng.integers(0, 86400 * 20, n),
            "runtime_actual_s": (base * rng.lognormal(0, 0.5, n)).astype(int) + 1,
            "gpu_req": rng.choice([0.0, 0.5, 1.0, 4.0], n), "cpu_req": 6.0, "mem_req_gb": 30.0,
            "gpu_type": rng.choice(["V100", "T4"], n), "n_tasks": 1,
        }
    )  # fmt: skip


def test_quantiles_monotone_and_learn_user_level():
    df = _jobs()
    q = fit_learned(df).predict(df)
    assert q.shape == (len(df), 4)
    assert (np.diff(q, axis=1) >= 0).all() and (q >= 1).all()
    med = pd.Series(q[:, 1]).groupby(df["user"].to_numpy()).mean()
    assert med["a"] < med["b"] < med["c"]


def test_unseen_user_and_gpu_type_still_predict():
    model = fit_learned(_jobs())
    new = _jobs(5, seed=2).assign(user="zzz", gpu_type="NEW")
    assert (np.diff(model.predict(new), axis=1) >= 0).all()


def test_deterministic_same_input_same_quantiles_r_sim_1():
    df = _jobs()
    first = fit_learned(df).predict(df)
    runtime_ml._FITTED.clear()  # force a real refit, not the cache
    assert (fit_learned(df).predict(df) == first).all()


def test_realised_runtime_is_not_a_feature_r_leak_1():
    df = _jobs()
    model = fit_learned(df)
    assert TARGET_COLUMN not in FEATURE_SOURCE_COLUMNS
    cols = set(model.features(df.iloc[:3]).columns)
    assert cols == {
        "user", "gpu_type", "gpu_req", "cpu_req", "mem_req_gb", "n_tasks", "hour", "weekday"
    }  # fmt: skip
    # Changing the realised runtime of the jobs being predicted changes nothing.
    other = df.assign(runtime_actual_s=df["runtime_actual_s"] * 7 + 3)
    assert (model.predict(df) == model.predict(other)).all()


def test_pinball_and_coverage():
    y = np.array([10, 20, 30, 40])
    q = np.tile([5, 20, 35, 45], (4, 1))
    cov = interval_coverage(y, q)
    assert cov["coverage_q05_q95"] == 1.0 and cov["below_q90"] == 0.75
    assert pinball_loss(y, np.tile(y[:, None], (1, 4))) == [0.0] * 4
    # q50 loss: 0.5 * mean |y - 20| = 0.5 * (10 + 0 + 10 + 20) / 4 = 5
    assert pinball_loss(y, q)[1] == pytest.approx(5.0)


def test_table_quantiles_shape():
    df = _jobs()
    assert table_quantiles(fit_runtime(df, 20), df).shape == (len(df), 4)


def test_default_runtime_model_is_table_and_bad_value_rejected():
    cfg = load_config(Path("configs/base.yaml"))
    assert cfg["scenario"]["runtime_model"] == "table"
    if not Path(cfg["data"]["jobs"]).exists():
        pytest.skip("real jobs file not present")
    cfg["scenario"]["runtime_model"] = "nope"
    with pytest.raises(ConfigError):
        build_replicate(cfg, Replicate("t", (25, 26), "2023-07-03", 0.01))
