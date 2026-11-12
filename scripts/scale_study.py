"""Scale study for the dashboard: how planner work grows with the number of datacentres.

Runs the re-planning policies on 3, 6, 9 and 12 datacentres, with load growing in step (see
`flipwise.web.scenarios.scaled_scenario`), on validation-period data only (PRD §14.3). Writes
`results/web/scale.json`, which the dashboard reads. Nothing here tunes a threshold.

    uv run python scripts/scale_study.py            # about 10-20 minutes on a laptop
    uv run python scripts/scale_study.py --quick    # 3 and 6 datacentres, one carbon Monday
"""

from __future__ import annotations

import argparse
import collections
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from flipwise.config import policy_params
from flipwise.models import JobState
from flipwise.policies import make_policy
from flipwise.simulator import Simulator, job_outcome
from flipwise.web.scenarios import ROOT, config, scaled_scenario

POLICIES = ("fcfs", "place_once", "periodic", "pred_error", "fixed_savings", "decision_flip")
BASE_SAMPLING = 0.02
MONDAYS = ("2023-07-03", "2023-07-17")  # validation carbon Mondays (configs/base.yaml)

_scenarios: dict = {}


def run_cell(n_dcs: int, monday: str, policy: str) -> dict:
    cfg = config()
    key = (n_dcs, monday)
    if key not in _scenarios:
        _scenarios.clear()
        _scenarios[key] = scaled_scenario(cfg, n_dcs, BASE_SAMPLING, monday)
    sc = _scenarios[key]
    pol = make_policy(policy, **policy_params(cfg, policy))
    t0 = time.perf_counter()
    res = Simulator(sc, pol, debug=False).run()
    wall_s = time.perf_counter() - t0
    kinds = collections.Counter(d["kind"] for d in res.decisions)
    kg = kwh = 0.0
    done = missed = 0
    wait_h = []
    for j in res.jobs:
        if j.state != JobState.COMPLETED:
            continue
        out = job_outcome(j, sc)
        kg += out["kg_co2"]
        kwh += out["energy_kwh"]
        done += 1
        missed += j.end_s > j.deadline_s
        wait_h.append((j.start_s - j.arrival_s) / 3600)
    st = res.stats
    planner_s = sum(st.get(k, 0.0) for k in ("arrival_s", "screen_s", "rescore_s", "rescue_s"))
    return {
        "n_dcs": n_dcs, "monday": monday, "policy": policy, "n_jobs": len(sc.jobs),
        "wall_s": wall_s, "planner_s": planner_s, "rescore_s": st.get("rescore_s", 0.0),
        "stage2_calls": st.get("stage2_calls", 0), "screened": st.get("screened", 0),
        "moves": kinds.get("MOVE", 0), "rescues": kinds.get("RESCUE", 0),
        "screen_fail": kinds.get("SCREEN_FAIL", 0), "kg_co2": kg, "energy_kwh": kwh,
        "completed": done, "miss_rate": missed / max(len(sc.jobs), 1),
        "wait_mean_h": sum(wait_h) / max(len(wait_h), 1), "decisions": dict(kinds),
    }  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    sizes = (3, 6) if args.quick else (3, 6, 9, 12)
    mondays = MONDAYS[:1] if args.quick else MONDAYS
    cells = [(n, m, p) for n in sizes for m in mondays for p in POLICIES]
    rows = []
    with ProcessPoolExecutor(args.workers) as ex:
        futs = {ex.submit(run_cell, *c): c for c in cells}
        for f in as_completed(futs):
            r = f.result()
            rows.append(r)
            print(f"n={r['n_dcs']:>2} {r['monday']} {r['policy']:<14} jobs={r['n_jobs']:>5} "
                  f"wall={r['wall_s']:6.1f}s rescores={r['stage2_calls']:>6} moves={r['moves']:>5} "
                  f"kg={r['kg_co2']:.1f}", flush=True)  # fmt: skip
    rows.sort(key=lambda r: (r["n_dcs"], r["monday"], POLICIES.index(r["policy"])))
    out = ROOT / "results" / "web" / "scale.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {"base_sampling": BASE_SAMPLING, "trace_days": [25, 28], "mondays": list(mondays),
            "sizes": list(sizes), "policies": list(POLICIES), "split": "validation"}  # fmt: skip
    out.write_text(json.dumps({"meta": meta, "rows": rows}, indent=1) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
