import copy
import hashlib
import random

import pandas as pd
import pytest

from flipwise.carbon import ForecastStore, Truth
from flipwise.energy import PowerModel
from flipwise.errors import MigrationError
from flipwise.models import DcConfig, Job, Placement
from flipwise.policies import Decision, Fcfs, PlaceOnce, Policy, make_policy
from flipwise.reporting import write_run
from flipwise.simulator import Scenario, Simulator
from flipwise.smoke import TOY_DIR, smoke

T0 = 1688342400


def test_toy_matches_expected_yaml():
    """Toy FCFS and place_once equal the hand-computed expected.yaml (phase 3/4 exit, R-EN-2)."""
    assert smoke(TOY_DIR) == []


@pytest.mark.parametrize("policy", ["fcfs", "place_once"])
def test_byte_identical_reruns_r_sim_1(toy, tmp_path, policy):
    h1 = write_run(Simulator(toy, make_policy(policy)).run(), tmp_path / "a")
    h2 = write_run(Simulator(toy, make_policy(policy)).run(), tmp_path / "b")
    assert h1 == h2


def test_same_time_priority_order_r_sim_2(toy):
    """At T0+3600 the carbon update precedes completions; at T0+1800 completion precedes
    arrival, which precedes releases."""
    ev = Simulator(toy, PlaceOnce()).run().events
    for t in (T0 + 1800, T0 + 3600, T0 + 5400):
        prios = [int(e.split(",")[1]) for e in ev if int(e.split(",")[0]) == t]
        assert prios == sorted(prios) and prios
    at_3600 = [e.split(",")[3] for e in ev if e.startswith(f"{T0 + 3600},")]
    assert at_3600[0] == "CARBON_UPDATE"


class _MoveRunning(Policy):
    name = "move_running"

    def on_arrival(self, view, job_id):
        return Decision(job_id, "PLACE", Placement(0, view.now_s - view.now_s % 1800))

    def on_carbon_update(self, view):
        return [Decision("J1", "MOVE", Placement(1, view.now_s))] if view.now_s > T0 else []


def test_moving_running_job_raises_r_sim_4(toy):
    with pytest.raises(MigrationError):
        Simulator(toy, _MoveRunning()).run()


class _MoveTwice(Policy):
    """Places J4 at dc0 slot +4, then moves it twice on the T0+3600 update."""

    name = "move_twice"

    def on_arrival(self, view, job_id):
        return (
            Fcfs().on_arrival(view, job_id)
            if job_id != "J4"
            else Decision(job_id, "PLACE", Placement(0, T0 + 4 * 1800))
        )

    def on_carbon_update(self, view):
        if view.now_s != T0 + 3600:
            return []
        return [
            Decision("J4", "MOVE", Placement(2, T0 + 5 * 1800)),
            Decision("J4", "MOVE", Placement(1, T0 + 6 * 1800)),
        ]


def test_stale_releases_ignored_r_sim_5(toy):
    res = Simulator(toy, _MoveTwice()).run()
    releases = [e for e in res.events if e.endswith(",JOB_RELEASE,J4")]
    assert releases == [r for r in releases if r.startswith(f"{T0 + 6 * 1800},")]
    assert len(releases) == 1
    j4 = next(j for j in res.jobs if j.job_id == "J4")
    assert (j4.dc_id, j4.start_s, j4.n_moves) == (1, T0 + 6 * 1800, 2)


def _random_scenario(rng: random.Random) -> Scenario:
    n_dc = rng.randint(1, 3)
    dcs = [DcConfig(d, d + 1, rng.choice([2, 4, 8]), 16, 64) for d in range(n_dc)]
    jobs = []
    for i in range(rng.randint(1, 12)):
        rt = rng.choice([60, 900, 1800, 4000])
        est = rng.choice([rt // 2 or 1, rt, rt * 2])
        jobs.append(
            Job(f"j{i:02d}", "u", T0 + rng.randrange(0, 7200, 300), rng.choice([0.5, 1, 2, 3]),
                rng.choice([0, 2]), 1, est, est, est, est, T0 + rng.randrange(1800, 30000), rt)
        )  # fmt: skip
    slots = range(T0, T0 + 20 * 1800, 1800)
    f = pd.DataFrame(
        [(d.region_id, k, T0, float(rng.randint(50, 400))) for d in dcs for k in slots],
        columns=["region_id", "slot_utc", "capture_utc", "forecast_g_per_kwh"],
    )
    cov = pd.DataFrame([(T0, T0, slots[-1])], columns=["capture_utc", "window_first_utc",
                                                       "window_last_utc"])  # fmt: skip
    truth = f.rename(columns={"forecast_g_per_kwh": "truth_g_per_kwh"})
    return Scenario("rand", jobs, dcs, ForecastStore(f, cov, [d.region_id for d in dcs]),
                    Truth(truth), PowerModel(1, 0.01), T0, T0 + 10 * 86400)  # fmt: skip


@pytest.mark.parametrize("policy", ["fcfs", "place_once"])
def test_random_scenarios_no_overbooking_r_sim_3(policy):
    """R-SIM-3: invariants are checked after every event in debug mode; all jobs finish."""
    rng = random.Random(1234)
    for _ in range(250):
        sc = _random_scenario(rng)
        res = Simulator(sc, make_policy(policy), debug=True).run()
        for j in res.jobs:
            fits = any(j.request.fits_in(d.cap) for d in sc.dcs)
            assert (j.end_s is not None) == fits, j


def test_power_scale_does_not_change_placements_r_en_3(toy, tmp_path):
    """R-EN-3: scaling every power by 2 leaves placement decisions unchanged."""
    toy2 = copy.copy(toy)
    toy2.power = PowerModel(toy.power.p_gpu_kw * 2, toy.power.p_cpu_kw * 2)
    a = Simulator(toy, PlaceOnce()).run().decisions
    b = Simulator(toy2, PlaceOnce()).run().decisions
    strip = [{k: v for k, v in d.items() if k not in ("S_a", "S_b")} for d in a]
    assert strip == [{k: v for k, v in d.items() if k not in ("S_a", "S_b")} for d in b]


def test_outputs_are_lf_terminated(toy, tmp_path):
    write_run(Simulator(toy, Fcfs()).run(), tmp_path)
    data = (tmp_path / "jobs.csv").read_bytes()
    assert b"\r\n" not in data and hashlib.sha256(data).hexdigest()
