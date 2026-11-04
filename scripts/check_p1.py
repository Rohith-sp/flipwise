"""P1 on one real replicate (PRD §10.9, R-TRIG-2): at θ = 0, `decision_flip` and `fixed_savings`
must write identical `jobs.csv` and `events.log` and identical state-changing decisions.

    uv run python scripts/check_p1.py --config configs/base.yaml

Exits non-zero on any difference. A mismatch is a bug in the bound or the implementation.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from flipwise.config import load_config, policy_params
from flipwise.policies import make_policy
from flipwise.reporting import write_run
from flipwise.scenario import build_replicate, dev_replicate
from flipwise.simulator import Simulator

STATE_KINDS = {"PLACE", "FALLBACK", "MOVE", "RESCUE", "REJECT"}
# The screen and margin columns are what the two policies are allowed to differ in.
SCREEN_COLUMNS = {"LB", "w_ab", "theta_eff"}


def _run(args: tuple[Path, str, dict]) -> dict:
    config, name, params = args
    cfg = load_config(config)
    scenario = build_replicate(cfg, dev_replicate(cfg), 0)
    result = Simulator(scenario, make_policy(name, **params), debug=False).run()
    with tempfile.TemporaryDirectory() as tmp:
        hashes = write_run(result, Path(tmp))
        with open(Path(tmp) / "decisions.csv", newline="") as f:
            rows = [
                {k: v for k, v in r.items() if k not in SCREEN_COLUMNS}
                for r in csv.DictReader(f)
                if r["kind"] in STATE_KINDS
            ]
    return {"hashes": hashes, "state_rows": rows, "stats": result.stats}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=Path("configs/base.yaml"))
    args = ap.parse_args()
    params = policy_params(load_config(args.config), "fixed_savings")
    runs = [
        (args.config, "fixed_savings", params),
        (args.config, "decision_flip", {**params, "theta": 0.0}),
    ]
    with ProcessPoolExecutor(max_workers=2) as pool:
        fixed, flip = pool.map(_run, runs)
    same = {
        "jobs.csv": fixed["hashes"]["jobs.csv"] == flip["hashes"]["jobs.csv"],
        "events.log": fixed["hashes"]["events.log"] == flip["hashes"]["events.log"],
        "state_rows": fixed["state_rows"] == flip["state_rows"],
    }
    calls_a, calls_b = fixed["stats"]["stage2_calls"], flip["stats"]["stage2_calls"]
    report = {
        "identical": same,
        "state_rows": len(fixed["state_rows"]),
        "stage2_calls": {"fixed_savings": calls_a, "decision_flip": calls_b},
        "screened": flip["stats"]["screened"],
        "screen_pass_rate": calls_b / flip["stats"]["screened"] if flip["stats"]["screened"] else 0,
        "rescore_s": {
            "fixed_savings": fixed["stats"]["rescore_s"],
            "decision_flip": flip["stats"]["rescore_s"],
        },
    }
    print(json.dumps(report, indent=2))
    ok = all(same.values()) and calls_b <= calls_a
    print("P1: HOLDS" if ok else "P1: FAILS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
