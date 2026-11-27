"""X10 learned runtime quantiles (PRD §4.2 X10, D66): an alternative input to the same rules.

One gradient-boosted quantile regressor per quantile on log runtime, fitted on the calibration
slice only (trace days `splits.runtime_fit_trace_days`, PRD §6.5). Features are what a policy may
see at arrival (PRD §8.7); `runtime_actual_s` is the target and never a feature. scikit-learn is
imported lazily so the base install works without the `ml` extra.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
import pandas as pd

from flipwise.errors import ConfigError
from flipwise.estimates import RUNTIME_QUANTILES, RuntimeModel, RuntimeQuantiles

# Columns the model may read; checked by the leakage test (R-LEAK-1 spirit).
FEATURE_SOURCE_COLUMNS = (
    "user", "gpu_req", "cpu_req", "mem_req_gb", "gpu_type", "n_tasks", "trace_arrival_s",
)  # fmt: skip
TARGET_COLUMN = "runtime_actual_s"
MAX_USER_CODES = 254  # HistGradientBoosting categoricals need codes below max_bins (255)
MAX_ITER = 100
_FITTED: dict[str, LearnedRuntimeModel] = {}  # in-process cache keyed by training-data checksum


@dataclass(frozen=True)
class LearnedRuntimeModel:
    users: dict[str, int]  # the most frequent calibration users; everyone else is "other"
    gpu_types: dict[str, int]
    models: tuple  # one fitted regressor per quantile in RUNTIME_QUANTILES

    def features(self, jobs: pd.DataFrame) -> pd.DataFrame:
        t = jobs["trace_arrival_s"].to_numpy(dtype=np.int64)
        user = jobs["user"].astype(str).map(self.users).fillna(len(self.users)).astype(int)
        gtype = jobs["gpu_type"].astype(str).map(self.gpu_types)
        return pd.DataFrame(
            {
                "user": user.to_numpy(),
                "gpu_type": gtype.fillna(len(self.gpu_types)).astype(int).to_numpy(),
                "gpu_req": jobs["gpu_req"].to_numpy(dtype=float),
                "cpu_req": jobs["cpu_req"].to_numpy(dtype=float),
                "mem_req_gb": jobs["mem_req_gb"].to_numpy(dtype=float),
                "n_tasks": jobs["n_tasks"].to_numpy(dtype=float),
                "hour": (t // 3600) % 24,
                "weekday": (t // 86400) % 7,
            }
        )  # fmt: skip

    def predict(self, jobs: pd.DataFrame) -> np.ndarray:
        """Integer seconds, shape (n, 4) for q05, q50, q90, q95; sorted per job so they never
        cross, and at least 1 s like the table estimates."""
        x = self.features(jobs)
        raw = np.column_stack([np.exp(m.predict(x)) for m in self.models])
        return np.maximum(1, np.rint(np.sort(raw, axis=1))).astype(np.int64)

    def estimate_all(self, jobs: pd.DataFrame) -> list[RuntimeQuantiles]:
        return [tuple(int(v) for v in row) for row in self.predict(jobs)]  # type: ignore[misc]


def _checksum(calibration: pd.DataFrame) -> str:
    cols = [*FEATURE_SOURCE_COLUMNS, TARGET_COLUMN]
    data = calibration[cols].astype(str).agg("|".join, axis=1)
    return hashlib.sha256("\n".join(data).encode()).hexdigest()


def fit_learned(calibration: pd.DataFrame) -> LearnedRuntimeModel:
    """Fit on calibration jobs only (the caller slices to the fit days, PRD §6.5)."""
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor
    except ImportError as e:
        raise ConfigError(
            "scenario.runtime_model x10 needs scikit-learn: uv sync --extra ml"
        ) from e
    if calibration.empty:
        raise ConfigError("x10: no calibration jobs to fit on")
    key = _checksum(calibration)
    if key in _FITTED:
        return _FITTED[key]
    counts = calibration["user"].astype(str).value_counts()
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_USER_CODES]
    users = {u: i for i, (u, _) in enumerate(ranked)}
    gpu_types = {g: i for i, g in enumerate(sorted(calibration["gpu_type"].astype(str).unique()))}
    shell = LearnedRuntimeModel(users, gpu_types, ())
    x = shell.features(calibration)
    y = np.log(np.maximum(1, calibration[TARGET_COLUMN].to_numpy(dtype=float)))
    cats = [c in ("user", "gpu_type") for c in x.columns]
    models = tuple(
        HistGradientBoostingRegressor(
            loss="quantile", quantile=q, categorical_features=cats, max_iter=MAX_ITER,
            early_stopping=False, random_state=0,
        ).fit(x, y)
        for q in RUNTIME_QUANTILES
    )  # fmt: skip
    model = LearnedRuntimeModel(users, gpu_types, models)
    _FITTED[key] = model
    return model


def table_quantiles(model: RuntimeModel, jobs: pd.DataFrame) -> np.ndarray:
    """The PRD §6.5 table estimates for each job, shape (n, 4)."""
    return np.array(
        [
            model.estimate(str(u), float(g))[0]
            for u, g in zip(jobs["user"], jobs["gpu_req"], strict=True)
        ],
        dtype=np.int64,
    )


def pinball_loss(y_s: np.ndarray, q_s: np.ndarray) -> list[float]:
    """Mean pinball loss per quantile (seconds); `q_s` has columns q05, q50, q90, q95."""
    y = np.asarray(y_s, dtype=float)[:, None]
    tau = np.asarray(RUNTIME_QUANTILES)[None, :]
    d = y - np.asarray(q_s, dtype=float)
    return [float(v) for v in np.mean(np.maximum(tau * d, (tau - 1) * d), axis=0)]


def interval_coverage(y_s: np.ndarray, q_s: np.ndarray) -> dict[str, float]:
    """Share of jobs inside [q05, q95] (nominal 0.90), the one-sided rates and the mean width."""
    y, q = np.asarray(y_s), np.asarray(q_s)
    return {
        "coverage_q05_q95": float(np.mean((q[:, 0] <= y) & (y <= q[:, 3]))),
        "below_q90": float(np.mean(y <= q[:, 2])),  # nominal 0.90
        "below_q50": float(np.mean(y <= q[:, 1])),  # nominal 0.50
        "mean_width_h": float(np.mean(q[:, 3] - q[:, 0]) / 3600),
    }
