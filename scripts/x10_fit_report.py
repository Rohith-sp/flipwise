"""X10 fit report: table vs learned runtime quantiles on the validation days (PRD X10, D66).

Fits on `splits.runtime_fit_trace_days` and scores on `splits.validation.trace_days` only; the
test slice is never read. Needs `uv sync --extra ml`.

    uv run --extra ml python scripts/x10_fit_report.py [--config configs/base.yaml]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from flipwise.config import load_config
from flipwise.estimates import RUNTIME_QUANTILES, fit_runtime
from flipwise.runtime_ml import fit_learned, interval_coverage, pinball_loss, table_quantiles


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=Path("configs/base.yaml"))
    args = ap.parse_args()
    cfg = load_config(args.config)
    origin = int(cfg["trace_day_origin_s"])
    day = lambda d: origin + int(d) * 86400  # noqa: E731
    jobs = pd.read_csv(Path(cfg["data"]["jobs"]), dtype={"job_id": str, "user": str})
    fit_lo, fit_hi = cfg["splits"]["runtime_fit_trace_days"]
    val_lo, val_hi = cfg["splits"]["validation"]["trace_days"]
    fit = jobs[jobs["trace_arrival_s"].between(day(fit_lo), day(fit_hi) - 1)]
    val = jobs[jobs["trace_arrival_s"].between(day(val_lo), day(val_hi) - 1)]
    y = val["runtime_actual_s"].to_numpy()
    table = fit_runtime(fit, int(cfg["scenario"]["n_min"]))
    learned = fit_learned(fit)
    out = {"fit_jobs": len(fit), "validation_jobs": len(val), "quantiles": list(RUNTIME_QUANTILES)}
    for name, q in (("table", table_quantiles(table, val)), ("x10", learned.predict(val))):
        out[name] = {"pinball_s": pinball_loss(y, q), **interval_coverage(y, q)}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
