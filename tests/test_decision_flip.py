"""Decision-flip: screen, noise width, fallbacks, and P1 (PRD §10, R-TRIG-1 to 6)."""

import math
import random

import pytest
from replan_toy import SLOT, T0, by_id, forced, job, kinds, scenario, state_changes

from flipwise import planner
from flipwise.carbon import CarbonTable, ForecastVintage, Residuals, fit_residuals
from flipwise.errors import CarbonDataError, ConfigError, SimulationInvariantError
from flipwise.estimates import fit_runtime
from flipwise.models import Candidate, JobState
from flipwise.policies import DecisionFlip, FixedSavings, Policy
from flipwise.reporting import write_run
from flipwise.simulator import Simulator

WIDE = Residuals(e05=(-50.0,) * 4, e95=(50.0,) * 4)
STATE_COLUMNS = ("time_s", "job_id", "kind", "from_dc", "from_slot", "to_dc", "to_slot", "S_a")
STATE_COLUMNS += ("S_b", "g_min", "reason")


def _table(series, first=T0, n=None, tail_known=True):
    n = n if n is not None else len(series)
    values = {k: v for k, v in zip(range(first, first + n * SLOT, SLOT), series, strict=True)}
    values = {k: v for k, v in values.items() if v is not None}
    last = first + n * SLOT - SLOT
    vintage = ForecastVintage(first, last, {1: values} if tail_known else {1: {}})
    return CarbonTable(vintage, 1, (0.0,) * 4, (0.0,) * 4)


def _brute_min(table, lo, hi, dur, step=60):
    best = math.inf
    for x in range(lo, hi + 1, step):
        p = table.integrate(x, dur)
        if p is not None:
            best = min(best, p[0])
    return None if best == math.inf else best


def test_min_window_matches_brute_force_r_trig_1():
    rng = random.Random(1)
    for _ in range(200):
        n = rng.randint(1, 20)
        series = [rng.uniform(0, 900) for _ in range(n)]
        if rng.random() < 0.4 and n > 8:  # a gap too long for the persistence rule
            at = rng.randrange(0, n - 5)
            series[at : at + 4] = [None] * 4
            series[0] = 700.0
        table = _table(series)
        lo = T0 + rng.randrange(0, 1800 * n, 60)
        hi = lo + rng.randrange(0, 1800 * 6, 60)
        dur = rng.randrange(60, 1800 * 5, 60)
        got, want = table.min_window(lo, hi, dur), _brute_min(table, lo, hi, dur)
        if want is None:
            assert got is None
        else:
            assert got == pytest.approx(want, rel=1e-9, abs=1e-6)


def test_min_window_finds_a_start_between_slot_boundaries():
    """Cheap slot 1 of two: a 40-minute run sits best when its end is on a boundary."""
    table = _table([1000.0, 10.0, 1000.0, 1000.0])
    got = table.min_window(T0, T0 + 3 * SLOT, 2400)
    assert got == pytest.approx(1800 * 10 + 600 * 1000)


def test_lower_bound_is_infinite_when_no_start_can_meet_the_deadline():
    seen = {}

    class Probe(Policy):
        name = "probe"

        def on_arrival(self, view, job_id):
            seen["lb"] = planner.lower_bound(view, view.job(job_id))
            return planner_place(view, job_id)

    def planner_place(view, job_id):
        from flipwise.policies import initial_placement

        return initial_placement(view, job_id)

    sc = scenario([job("X", runtime=7200, deadline=3600)], {0: {1: 100, 2: 100, 3: 100}})
    Simulator(sc, Probe()).run()
    assert seen["lb"] == math.inf


def _random_scenario(rng):
    forecast = {}
    series = {r: {0: rng.uniform(50, 900)} for r in (1, 2, 3)}
    for r in series:
        for k in range(2, 40, rng.randint(2, 6)):
            series[r][k] = rng.uniform(50, 900)
    forecast[0] = {r: dict(v) for r, v in series.items()}
    captures = rng.sample(range(1, 12), rng.randint(2, 4))
    for c in sorted(captures):
        for r in series:
            for k in rng.sample(list(series[r]), max(1, len(series[r]) // 2)):
                series[r][k] = rng.uniform(50, 900)
        forecast[c * SLOT] = {r: dict(v) for r, v in series.items()}
    jobs = []
    for i in range(rng.randint(4, 9)):
        q50 = rng.randrange(600, 10800, 60)
        q = (max(60, q50 // 2), q50, q50 * 2, q50 * 3)
        jobs.append(
            job(
                f"J{i}",
                gpu=rng.choice([1.0, 2.0, 3.0, 4.0]),
                runtime=rng.choice([q50 // 2, q50, q50 * 2, q50 * 4]),
                arrival=rng.randrange(0, 5 * SLOT, 300),
                deadline=rng.randrange(6 * SLOT, 40 * SLOT, 300),
                q=q,
            )
        )
    jobs.sort(key=lambda j: j.job_id)
    return scenario(jobs, forecast)


def test_bound_never_exceeds_a_feasible_score_r_trig_1():
    """Random forecasts, jobs and queue states; includes non-slot starts from completions."""
    rng = random.Random(7)
    checks = 0
    violations = []

    class Check(FixedSavings):
        def replan(self, view, job_, inc):
            nonlocal checks
            lb = planner.lower_bound(view, job_)
            for c in planner.candidates(view, job_):
                if c.feasible:
                    checks += 1
                    if c.s_hat < lb:
                        violations.append((job_.job_id, view.now_s, c, lb))
            return iter(())

    for _ in range(60):
        Simulator(_random_scenario(rng), Check()).run()
    assert not violations
    assert checks >= 2000


def test_debug_assertion_catches_an_unsound_bound_r_trig_1():
    a = {1: 100, 2: 300, 3: 300}
    b = {1: 400, 2: 100, 3: 300}

    class Broken(DecisionFlip):
        def screen_fails(self, view, job_, inc, g):
            return False, inc.s_hat * 10

    sc = scenario([job("X", deadline=40000)], {0: a, SLOT: b})
    with pytest.raises(SimulationInvariantError):
        Simulator(sc, forced(Broken(), {"X": (0, 6 * SLOT)})).run()


def _state(res):
    return [{k: d[k] for k in STATE_COLUMNS} for d in state_changes(res)]


@pytest.mark.parametrize("seed", range(25))
def test_screen_changes_no_decision_p1_r_trig_2(seed, tmp_path):
    """P1: at θ = 0 decision-flip and fixed-savings write identical logs, for less work."""
    sc = _random_scenario(random.Random(seed))
    fixed = FixedSavings()
    flip = DecisionFlip(theta=0.0)
    a = Simulator(sc, fixed).run()
    b = Simulator(sc, flip).run()
    ha = write_run(a, tmp_path / "a")
    hb = write_run(b, tmp_path / "b")
    assert ha["jobs.csv"] == hb["jobs.csv"] and ha["events.log"] == hb["events.log"]
    assert _state(a) == _state(b)
    assert flip.stats.stage2_calls <= fixed.stats.stage2_calls


def test_p1_on_the_toy_r_trig_2(toy, tmp_path):
    a = Simulator(toy, FixedSavings()).run()
    b = Simulator(toy, DecisionFlip(theta=0.0)).run()
    ha = write_run(a, tmp_path / "a")
    hb = write_run(b, tmp_path / "b")
    assert ha["jobs.csv"] == hb["jobs.csv"] and ha["events.log"] == hb["events.log"]
    assert _state(a) == _state(b)


def test_screen_saves_work_when_nothing_can_clear_the_gate_p2():
    a = {1: 100, 2: 101, 3: 102}
    sc = scenario([job("X", deadline=40000)], {i * SLOT: a for i in range(4)})
    flip = DecisionFlip(theta=0.0)
    res = Simulator(sc, forced(flip, {"X": (0, 8 * SLOT)})).run()
    assert flip.stats.screened == 3 and flip.stats.stage2_calls == 0
    assert kinds(res, "X").count("SCREEN_FAIL") == 3


def test_flip_moves_when_another_dc_becomes_clearly_better_r_trig_3():
    """Hour-long 1-GPU job: dc0 goes 100 -> 400, dc1 stays 150, so the gain is 0.25 kg against a
    gate of 0.05 * 0.4 = 0.02 kg. With zero residuals, w_ab = 0, so θ adds nothing."""
    before = {1: 100, 2: 150, 3: 300}
    after = {1: 400, 2: 150, 3: 300}
    sc = scenario([job("X", deadline=40000)], {0: before, SLOT: after})
    res = Simulator(sc, forced(DecisionFlip(), {"X": (0, 6 * SLOT)})).run()
    assert by_id(res)["X"].dc_id == 1
    row = next(d for d in res.decisions if d["kind"] == "MOVE")
    assert row["S_a"] == pytest.approx(0.4) and row["S_b"] == pytest.approx(0.15)
    assert row["g_min"] == pytest.approx(0.02) and row["w_ab"] == pytest.approx(0.0)
    assert row["theta_eff"] == pytest.approx(0.1) and row["LB"] == pytest.approx(0.15)


def test_uniform_shift_does_not_flip_r_trig_4():
    """Every region rises by the same amount: the ranking is unchanged, so no move."""
    before = {1: 100, 2: 150, 3: 300}
    after = {1: 200, 2: 250, 3: 400}
    sc = scenario([job("X", deadline=40000)], {0: before, SLOT: after})
    res = Simulator(sc, forced(DecisionFlip(), {"X": (0, 6 * SLOT)})).run()
    assert by_id(res)["X"].n_moves == 0
    assert "SCREEN_FAIL" in kinds(res, "X")


def test_small_gain_does_not_move_r_trig_5():
    """Gain 0.1 kg clears a 0.2 * 0.3 = 0.06 kg gate, but not gate + θ w_ab.

    With residuals ±50 g/kWh and exact waits and runtimes, U' − L' is 100 g/kWh × 1 h = 0.1 kg for
    each option, so w_ab = 0.1; θ = 0.5 needs a gain of at least 0.06 + 0.05 = 0.11 kg."""
    before = {1: 100, 2: 200, 3: 900}
    after = {1: 300, 2: 200, 3: 900}
    sc = scenario([job("X", deadline=40000)], {0: before, SLOT: after}, residuals=WIDE)
    res = Simulator(sc, forced(DecisionFlip(g_rel=0.2, theta=0.5), {"X": (0, 6 * SLOT)})).run()
    assert by_id(res)["X"].n_moves == 0
    row = next(d for d in res.decisions if d["kind"] == "KEEP")
    assert row["w_ab"] == pytest.approx(0.1)
    sc = scenario([job("X", deadline=40000)], {0: before, SLOT: after}, residuals=WIDE)
    res = Simulator(sc, forced(DecisionFlip(g_rel=0.2, theta=0.0), {"X": (0, 6 * SLOT)})).run()
    assert by_id(res)["X"].n_moves == 1  # the margin alone held it back


def test_screen_off_changes_no_decision_a2():
    sc = _random_scenario(random.Random(3))
    on = Simulator(sc, DecisionFlip(theta=0.25)).run()
    off_policy = DecisionFlip(theta=0.25, screen=False)
    off = Simulator(sc, off_policy).run()
    assert _state(on) == _state(off)
    assert off_policy.stats.screened == 0


def _cand(s_hat=1.0, lower=0.5, upper=1.5):
    return Candidate(0, T0, s_hat=s_hat, lower=lower, upper=upper)


@pytest.mark.parametrize(
    "lower,upper",
    [(math.nan, 1.5), (0.5, math.inf), (None, 1.5), (0.5, None), (1.2, 1.5), (0.5, 0.9)],
)
def test_malformed_interval_detected_r_trig_6(lower, upper):
    bad = _cand(lower=lower, upper=upper)
    assert planner.interval_problem(bad, _cand(), 0.1, 2.0) == planner.INTERVAL_MALFORMED
    assert planner.interval_problem(_cand(), bad, 0.1, 2.0) == planner.INTERVAL_MALFORMED


def test_unknown_width_is_malformed_r_trig_6():
    assert planner.interval_problem(_cand(), _cand(), None, 2.0) == planner.INTERVAL_MALFORMED


def test_too_wide_interval_detected_r_trig_6():
    assert planner.interval_problem(_cand(), _cand(), 2.5, 2.0) == planner.INTERVAL_TOO_WIDE
    assert planner.interval_problem(_cand(), _cand(), 2.0, 2.0) == ""


def test_too_wide_interval_turns_theta_off_r_trig_6():
    """w_ab = 0.2 is above w_max × Ŝ_a = 0.03, so θ = 5 is ignored and the plain gate decides."""
    before = {1: 100, 2: 300, 3: 900}
    after = {1: 200, 2: 100, 3: 900}
    wide = Residuals(e05=(-100.0,) * 4, e95=(100.0,) * 4)
    sc = scenario([job("X", deadline=40000)], {0: before, SLOT: after}, residuals=wide)
    policy = DecisionFlip(theta=5.0, w_max=0.15)
    res = Simulator(sc, forced(policy, {"X": (0, 6 * SLOT)})).run()
    row = next(d for d in res.decisions if d["kind"] == "MOVE")
    assert row["reason"] == planner.INTERVAL_TOO_WIDE and row["theta_eff"] == 0.0
    assert policy.stats.fallbacks == {planner.INTERVAL_TOO_WIDE: 1}


def test_residual_fallback_uses_widest_bucket_r_trig_6():
    """Lead buckets with no residuals borrow the widest bucket's quantiles (§10.7)."""
    import pandas as pd

    far = T0 + 30 * 3600  # 30 h ahead of the only capture: widest bucket only
    f = pd.DataFrame(
        [(1, far + i * SLOT, T0, 100.0, "toy") for i in range(3)],
        columns=["region_id", "slot_utc", "capture_utc", "forecast_g_per_kwh", "source"],
    )
    c = pd.DataFrame(
        [(T0, "regional", T0, far + 2 * SLOT)],
        columns=["capture_utc", "endpoint", "window_first_utc", "window_last_utc"],
    )
    t = pd.DataFrame(
        [(1, far + i * SLOT, 100.0 + 10 * i) for i in range(3)],
        columns=["region_id", "slot_utc", "truth_g_per_kwh"],
    )
    res, report = fit_residuals(f, c, t, [1], T0, far + 3 * SLOT)
    assert res.e05[0] == res.e05[3] and res.e95[1] == res.e95[3]
    assert report["residual_fallback_buckets"] == [0, 1, 2]


def test_no_residuals_at_all_is_an_error():
    import pandas as pd

    f = pd.DataFrame(
        columns=["region_id", "slot_utc", "capture_utc", "forecast_g_per_kwh", "source"]
    )
    c = pd.DataFrame(
        [(T0, "regional", T0, T0)],
        columns=["capture_utc", "endpoint", "window_first_utc", "window_last_utc"],
    )
    t = pd.DataFrame(columns=["region_id", "slot_utc", "truth_g_per_kwh"])
    with pytest.raises(CarbonDataError):
        fit_residuals(f, c, t, [1], T0, T0 + SLOT)


def test_runtime_fallback_chain_r_trig_6():
    import pandas as pd

    cal = pd.DataFrame(
        {"user": ["a"] * 30 + ["b"], "gpu_req": [1.0] * 31, "runtime_actual_s": range(100, 131)}
    )
    model = fit_runtime(cal, n_min=20)
    assert model.estimate("a", 1.0)[1] == "user"
    assert model.estimate("new", 1.0)[1] == "class"
    assert model.estimate("new", 8.0)[1] == "global"


def test_missing_carbon_for_incumbent_never_moves_r_trig_6():
    gap = {1: {0: 100, 2: None}, 2: 110, 3: 110}
    sc = scenario([job("X", gpu=4)], {0: gap, SLOT: gap})
    res = Simulator(sc, forced(DecisionFlip(), {"X": (0, 4 * SLOT)})).run()
    assert by_id(res)["X"].n_moves == 0
    assert any(d["reason"] == "NO_CARBON_INCUMBENT" for d in res.decisions)


def test_paired_width_only_counts_runtime_through_the_difference():
    """Runtime spread cancels when both options see the same intensity at every time."""
    seen = {}

    class Probe(FixedSavings):
        def replan(self, view, job_, inc):
            b = planner.best_alternative(view, job_)
            seen["w"] = planner.paired_width(view, job_, inc, b)
            return iter(())

    flat = {1: 200, 2: 200, 3: 200}
    sc = scenario([job("X", q=(600, 3600, 7200, 14400), deadline=60000)], {0: flat, SLOT: flat})
    Simulator(sc, forced(Probe(), {"X": (0, 6 * SLOT)})).run()
    assert seen["w"] == pytest.approx(0.0)


def test_paired_width_counts_runtime_that_differs_between_options():
    """Δ(r_q95) − Δ(r_q05): a long run reaches dc0's dirty hours but dc1 stays flat.

    a = dc0 from slot 6: 100 until slot 8, then 1000. b = dc1: 200 throughout. r_q05 = 1800 s and
    r_q95 = 7200 s. Δ(r_q05) = (100 − 200) × 0.5 h / 1000 = −0.05 kg. Δ(r_q95) = 1 h × (100 − 200)
    + 1 h × (1000 − 200), over 1000 = 0.7 kg. Half the difference is 0.375 kg."""
    seen = {}

    class Probe(FixedSavings):
        def replan(self, view, job_, inc):
            b = planner.evaluate(view, job_, 1, T0 + 6 * SLOT, intervals=True)
            seen["w"] = planner.paired_width(view, job_, inc, b)
            return iter(())

    f = {1: {0: 100, 8: 1000}, 2: 200, 3: 200}
    sc = scenario([job("X", q=(1800, 3600, 5400, 7200), deadline=60000)], {0: f, SLOT: f})
    Simulator(sc, forced(Probe(), {"X": (0, 6 * SLOT)})).run()
    assert seen["w"] == pytest.approx(0.375)


def test_ablations_change_the_width():
    seen = {}

    class Probe(FixedSavings):
        def replan(self, view, job_, inc):
            b = planner.evaluate(view, job_, 1, T0 + 6 * SLOT, intervals=True)
            for mode in ("full", "no_wait", "carbon_only"):
                seen[mode] = planner.paired_width(view, job_, inc, b, mode)
            return iter(())

    f = {1: {0: 100, 8: 1000}, 2: 200, 3: 200}
    sc = scenario(
        [job("X", q=(1800, 3600, 5400, 7200), deadline=60000)],
        {0: f, SLOT: f},
        residuals=WIDE,
    )
    Simulator(sc, forced(Probe(), {"X": (0, 6 * SLOT)})).run()
    assert seen["carbon_only"] == pytest.approx(0.1)  # ±50 g/kWh × 1 h, at each option
    assert seen["no_wait"] == pytest.approx(0.1 + 0.375)
    with pytest.raises(ConfigError):
        DecisionFlip(width="nope")


def test_kappa_queue_only_gates_queued_jobs_a6():
    p = DecisionFlip(g_rel=0.0, kappa_queue=0.5)
    placed = job("x")
    queued = job("y")
    queued.state = JobState.QUEUED
    assert p.gate(placed, 1.0) == 0.0 and p.gate(queued, 1.0) == 0.5


def test_outputs_are_byte_identical_r_sim_1(toy, tmp_path):
    a = write_run(Simulator(toy, DecisionFlip()).run(), tmp_path / "a")
    b = write_run(Simulator(toy, DecisionFlip()).run(), tmp_path / "b")
    assert a == b
