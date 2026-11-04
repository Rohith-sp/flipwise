"""Re-planning policies: C3, C7, rescue limits, throttling, baselines (PRD §10, §11)."""

import pytest
from replan_toy import SLOT, T0, by_id, forced, forced_place_once, job, kinds, scenario

from flipwise import planner
from flipwise.errors import ConfigError, MigrationError
from flipwise.models import Placement
from flipwise.policies import (
    Decision,
    FixedSavings,
    Periodic,
    Pig,
    PlaceOnce,
    PredError,
    Replanner,
    make_policy,
)
from flipwise.simulator import OracleView, SchedulerView, Simulator

FLAT = {1: 100, 2: 110, 3: 110}


def _queue_scenario():
    """B runs on dc0 for an hour and fills it. Q and K (4 GPUs each) queue behind it, in that
    order: dc0 at 100 g/kWh beats starting now at 110. Q's deadline only works from its own
    place in the queue: 3600 + 3600 = 7200. Behind K it would finish at 10800."""
    return scenario(
        [
            job("B", gpu=4, deadline=7000),
            job("Q", gpu=4, deadline=7200),
            job("K", gpu=4, deadline=30000),
        ],
        {0: FLAT, 1800: FLAT},
    )


@pytest.mark.parametrize("policy", [PlaceOnce, FixedSavings])
def test_queued_job_keeps_its_place_when_scored_r_trig_9(policy):
    """C3: an unchanged forecast neither moves nor rescues a queued job."""
    res = Simulator(_queue_scenario(), policy()).run()
    jobs = by_id(res)
    assert jobs["Q"].dc_id == 0 and jobs["Q"].start_s == T0 + 3600
    assert jobs["Q"].n_moves == 0 and jobs["Q"].rescued == 0
    assert jobs["Q"].end_s <= jobs["Q"].deadline_s
    assert "RESCUE" not in kinds(res, "Q") and "MOVE" not in kinds(res, "Q")


def test_incumbent_wait_comes_from_own_queue_position_r_trig_9():
    """C3: staying costs Q's place, joining the same queue again costs the end of it."""
    seen = {}

    class Probe(PlaceOnce):
        def on_carbon_update(self, view):
            if view.now_s == T0:  # the first capture comes before any arrival (PRD §8.4)
                return []
            q = view.job("Q")
            seen["inc"] = planner.rescore(view, q)
            seen["rejoin"] = planner.evaluate(view, q, 0, T0 + SLOT)
            return []

    Simulator(_queue_scenario(), Probe()).run()
    assert seen["inc"].feasible and seen["inc"].s_q50 == T0 + 3600
    assert seen["rejoin"].s_q50 == T0 + 7200
    assert seen["rejoin"].reject_reason == planner.DEADLINE_RISK


def test_placed_job_keeps_its_place_ahead_of_later_plans_r_trig_9():
    """C3 (D44): X is planned for 2 h and K for 3 h on dc0. X's plan is not pushed behind K, which
    is only planned to start after it; a new candidate for the same slot does go behind K."""
    seen = {}

    class Probe(PlaceOnce):
        def on_carbon_update(self, view):
            if view.now_s == T0:
                return []
            x = view.job("X")
            seen["inc"] = planner.rescore(view, x)
            seen["same_slot_elsewhere"] = planner.evaluate(view, x, 0, T0 + 2 * 3600)
            return []

    jobs = [job("X", gpu=4, runtime=3 * 3600, deadline=5 * 3600), job("K", gpu=4, deadline=40000)]
    sc = scenario(jobs, {0: FLAT, SLOT: FLAT})
    Simulator(sc, forced(Probe(), {"X": (0, 2 * 3600), "K": (0, 3 * 3600)})).run()
    assert seen["inc"].feasible and seen["inc"].s_q50 == T0 + 2 * 3600
    assert seen["same_slot_elsewhere"].s_q50 == T0 + 4 * 3600


def test_profile_for_a_new_candidate_never_contains_the_job_r_trig_9():
    """C3: "a job is never in its own wait profile" when scored for anywhere else."""
    seen = {}

    class Probe(PlaceOnce):
        def on_carbon_update(self, view):
            if view.now_s > T0:
                seen["start"] = planner.evaluate(view, view.job("X"), 0, T0 + 2 * SLOT).s_q50
            return []

    sc = scenario([job("X", gpu=4)], {0: FLAT, SLOT: FLAT})
    Simulator(sc, forced(Probe(), {"X": (0, 4 * SLOT)})).run()
    assert seen["start"] == T0 + 2 * SLOT


def _deferred_zero_power():
    return scenario([job("Z", gpu=0.0, cpu=0.0)], {0: FLAT, SLOT: FLAT, 2 * SLOT: FLAT})


@pytest.mark.parametrize("policy", [FixedSavings, Periodic, PredError])
def test_zero_gain_is_never_accepted_r_trig_9(policy):
    """C7: a zero-power job has Ŝ = 0 and g_min = 0 everywhere; without `gain > 0` it would move
    at every update."""
    res = Simulator(_deferred_zero_power(), forced(policy(), {"Z": (1, 4 * SLOT)})).run()
    assert by_id(res)["Z"].n_moves == 0
    assert "MOVE" not in kinds(res, "Z")


def test_c7_applies_at_fixed_savings_zero_gate():
    d = FixedSavings(g_rel=0.0)
    assert d.gate(job("x"), 0.0) == 0.0


def test_gate_formula_prd_10_3():
    p = FixedSavings(g_rel=0.1, g_abs=0.5, kappa_switch=0.01, kappa_queue=0.02, lambda_ovh=0.03)
    placed = job("x")
    assert p.gate(placed, 2.0) == pytest.approx(0.5 + 0.01 + 0.03)
    assert p.gate(placed, 10.0) == pytest.approx(1.0 + 0.01 + 0.03)
    queued = job("x")
    queued.state = "QUEUED"
    assert p.gate(queued, 10.0) == pytest.approx(1.0 + 0.01 + 0.02 + 0.03)


def _blocked_incumbent():
    """X is planned for dc0 at 3600 with a 7200 deadline. Y then fills dc0 for 4 hours from 1800,
    so X can no longer finish there, but dc1 and dc2 are free."""
    return [job("X", gpu=4, deadline=7200), job("Y", gpu=4, runtime=14400, arrival=SLOT)]


def test_rescue_at_carbon_update_r_trig_7():
    sc = scenario(_blocked_incumbent(), {0: FLAT, 3600: FLAT})
    res = Simulator(sc, forced_place_once({"X": (0, 3600), "Y": (0, SLOT)})).run()
    x = by_id(res)["X"]
    assert (x.rescued, x.n_moves) == (1, 0) and x.dc_id != 0
    assert x.end_s <= x.deadline_s
    row = next(d for d in res.decisions if d["kind"] == "RESCUE")
    assert row["time_s"] == T0 + 3600 and row["reason"] == planner.DEADLINE_RISK


def test_rescue_at_release_when_no_update_comes_r_trig_7():
    sc = scenario(_blocked_incumbent(), {0: FLAT})
    res = Simulator(sc, forced_place_once({"X": (0, 3600), "Y": (0, SLOT)})).run()
    x = by_id(res)["X"]
    assert x.rescued == 1 and x.dc_id != 0 and x.start_s == T0 + 3600
    assert kinds(res, "X").count("RESCUE") == 1


def test_missing_carbon_keeps_incumbent_r_trig_7():
    """D28: no carbon data for dc0's region from slot 2 on is not a rescue reason."""
    gap = {1: {0: 100, 2: None}, 2: 110, 3: 110}
    sc = scenario([job("X", gpu=4)], {0: gap, SLOT: gap})
    res = Simulator(sc, forced_place_once({"X": (0, 4 * SLOT)})).run()
    x = by_id(res)["X"]
    assert (x.dc_id, x.rescued) == (0, 0)
    assert any(d["reason"] == "NO_CARBON_INCUMBENT" for d in res.decisions)


def _everything_full():
    """Every datacentre is full for 4 hours, so X cannot meet its deadline anywhere."""
    fillers = [job(f"F{d}", gpu=4, runtime=14400, deadline=90000) for d in range(3)]
    plans = {f"F{d}": (d, 0) for d in range(3)}
    return fillers + [job("X", gpu=4, arrival=SLOT, deadline=7200)], plans


def test_no_repeat_rescue_on_a_fallback_placement_r_trig_7():
    jobs, plans = _everything_full()
    sc = scenario(jobs, {0: FLAT, 3600: FLAT, 7200: FLAT})
    res = Simulator(sc, forced_place_once(plans)).run()
    x = by_id(res)["X"]
    assert kinds(res, "X")[0] == "FALLBACK" and x.deadline_risk == 1
    assert x.rescued == 0
    noops = [d for d in res.decisions if d["job_id"] == "X" and d["kind"] == "RESCUE_NOOP"]
    assert noops and all(d["reason"] == "ON_FALLBACK" for d in noops)


def test_queued_job_needs_a_feasible_alternative_r_trig_7():
    """X is queued behind an estimate that was wrong: it stops being feasible, nothing else is,
    and rescuing would only cost its place in the queue."""
    jobs = [
        job("R", gpu=4, runtime=14400, q=(1800, 1800, 1800, 1800), deadline=7100),
        job("X", gpu=4, deadline=7200),
        job("F1", gpu=4, runtime=14400, deadline=90000),
        job("F2", gpu=4, runtime=14400, deadline=90000),
    ]
    plans = {"R": (0, 0), "X": (0, 0), "F1": (1, 0), "F2": (2, 0)}
    sc = scenario(jobs, {0: FLAT, 3600: FLAT, 5400: FLAT})
    res = Simulator(sc, forced_place_once(plans)).run()
    x = by_id(res)["X"]
    assert x.dc_id == 0 and x.rescued == 0
    assert any(
        d["job_id"] == "X" and d["reason"] == "NO_FEASIBLE_ALTERNATIVE" for d in res.decisions
    )


def test_placed_job_takes_earlier_fallback_once_then_stays_r_trig_7():
    """A placed job with no feasible option moves to the earliest finish once, flagged at risk,
    and is then left alone (D28, D42)."""
    jobs = [
        job("F0", gpu=4, runtime=28800, deadline=90000),
        job("F1", gpu=4, runtime=10800, deadline=90000, arrival=SLOT),
        job("F2", gpu=4, runtime=10800, deadline=90000, arrival=SLOT),
        job("X", gpu=4, deadline=9000),
    ]
    plans = {"F0": (0, 0), "F1": (1, SLOT), "F2": (2, SLOT), "X": (0, 3 * SLOT)}
    sc = scenario(jobs, {0: FLAT, 2 * SLOT: FLAT, 3 * SLOT: FLAT})
    res = Simulator(sc, forced_place_once(plans)).run()
    x = by_id(res)["X"]
    assert x.rescued == 1 and x.deadline_risk == 1 and x.dc_id != 0
    assert kinds(res, "X").count("RESCUE") == 1


def test_rescue_does_not_count_as_a_move_r_trig_7():
    sc = scenario(_blocked_incumbent(), {0: FLAT, 3600: FLAT})
    policy = forced_place_once({"X": (0, 3600), "Y": (0, SLOT)})
    res = Simulator(sc, policy).run()
    assert by_id(res)["X"].n_moves == 0 and policy.stats.rescues == 1


def _flip_forecast():
    """Plan on dc0, then dc0's forecast doubles: dc1 becomes clearly cheaper."""
    before = {1: 100, 2: 150, 3: 200}
    after = {1: 200, 2: 150, 3: 200}
    return before, after


def test_fixed_savings_moves_when_gain_clears_gate():
    before, after = _flip_forecast()
    sc = scenario([job("X", deadline=30000)], {0: before, SLOT: after})
    res = Simulator(sc, forced(FixedSavings(), {"X": (0, 4 * SLOT)})).run()
    x = by_id(res)["X"]
    assert x.dc_id == 1 and x.n_moves == 1
    row = next(d for d in res.decisions if d["kind"] == "MOVE")
    assert row["S_a"] == pytest.approx(0.2) and row["S_b"] == pytest.approx(0.15)
    assert row["g_min"] == pytest.approx(0.05 * 0.2)


def test_fixed_savings_keeps_when_gain_is_below_gate():
    before, after = _flip_forecast()
    sc = scenario([job("X", deadline=30000)], {0: before, SLOT: after})
    res = Simulator(sc, forced(FixedSavings(g_rel=0.5), {"X": (0, 4 * SLOT)})).run()
    assert by_id(res)["X"].dc_id == 0
    assert "KEEP" in kinds(res, "X") and "MOVE" not in kinds(res, "X")


def test_moves_apply_one_at_a_time_r_trig_8():
    """Two 4-GPU jobs, and dc1 is cheap for only one job's hour: exactly one takes it."""
    before = {1: 500, 2: 1000, 3: 1000}
    after = {1: 500, 2: {0: 1000, 6: 10, 8: 1000}, 3: 1000}
    jobs = [job(n, gpu=4, deadline=40000) for n in ("A", "B")]
    plans = {"A": (0, 8 * SLOT), "B": (0, 10 * SLOT)}
    sc = scenario(jobs, {0: before, SLOT: after})
    res = Simulator(sc, forced(FixedSavings(), plans)).run()
    in_cheap = [
        j for j in res.jobs if j.dc_id == 1 and j.start_s == T0 + 6 * SLOT and j.n_moves == 1
    ]
    assert len(in_cheap) == 1


def test_stale_release_after_two_moves_r_sim_5():
    a = {1: 100, 2: 300, 3: 300}
    b = {1: 400, 2: {0: 400, 6: 100}, 3: 300}
    c = {1: 400, 2: 400, 3: {0: 400, 7: 100}}
    sc = scenario([job("X", deadline=40000)], {0: a, SLOT: b, 2 * SLOT: c})
    res = Simulator(sc, forced(FixedSavings(), {"X": (0, 6 * SLOT)})).run()
    x = by_id(res)["X"]
    assert x.n_moves == 2 and x.dc_id == 2
    releases = [e for e in res.events if e.endswith(",JOB_RELEASE,X")]
    assert len(releases) == 1
    assert int(releases[0].split(",")[0]) == x.release_slot


def test_max_moves_freezes_a_job_r_trig_7():
    a = {1: 100, 2: 300, 3: 300}
    b = {1: 400, 2: {0: 400, 6: 100}, 3: 300}
    c = {1: 400, 2: 400, 3: {0: 400, 7: 100}}
    sc = scenario([job("X", deadline=40000)], {0: a, SLOT: b, 2 * SLOT: c})
    res = Simulator(sc, forced(FixedSavings(max_moves=1), {"X": (0, 6 * SLOT)})).run()
    assert by_id(res)["X"].n_moves == 1
    assert "THROTTLED" in kinds(res, "X")


def test_cooldown_skips_re_scoring():
    a = {1: 100, 2: 300, 3: 300}
    policy = FixedSavings(cooldown_s=7200)
    sc = scenario([job("X", deadline=40000)], {0: a, SLOT: a, 2 * SLOT: a, 6 * SLOT: a})
    res = Simulator(sc, forced(policy, {"X": (0, 8 * SLOT)})).run()
    assert kinds(res, "X").count("THROTTLED") == 1  # the update at 2 * SLOT
    assert policy.stats.stage2_calls == 2  # the updates at SLOT and 6 * SLOT


def test_periodic_re_scores_on_its_timer_only():
    a = {1: 100, 2: 300, 3: 300}
    policy = Periodic(T_s=2 * 3600)
    captures = {i * SLOT: a for i in range(10)}
    sc = scenario([job("X", deadline=40000)], captures)
    Simulator(sc, forced(policy, {"X": (0, 9 * SLOT)})).run()
    assert policy.stats.stage2_calls == 2  # ticks at 2 h and 4 h; the job is released at 4.5 h


def test_periodic_accepts_any_gain_above_tie():
    before = {1: 100, 2: 100.5, 3: 300}
    after = {1: 101, 2: 100.5, 3: 300}
    sc = scenario([job("X", deadline=40000)], {0: before, SLOT: after})
    res = Simulator(sc, forced(Periodic(T_s=2 * SLOT), {"X": (0, 6 * SLOT)})).run()
    assert by_id(res)["X"].dc_id == 1


def test_pred_error_quiet_when_inputs_do_not_change():
    a = {1: 100, 2: 300, 3: 300}
    policy = PredError(epsilon=0.1)
    sc = scenario([job("X", deadline=40000)], {i * SLOT: a for i in range(4)})
    Simulator(sc, policy).run()
    assert policy.stats.stage2_calls == 0


def test_pred_error_ignores_change_below_epsilon_and_fires_above_it():
    start = {1: 100, 2: 150, 3: 300}
    small = {1: 105, 2: 150, 3: 300}
    large = {1: 200, 2: 150, 3: 300}
    for after, calls, dc in ((small, 0, 0), (large, 1, 1)):
        policy = PredError(epsilon=0.1)
        sc = scenario([job("X", deadline=40000)], {0: start, SLOT: after})
        res = Simulator(sc, forced(policy, {"X": (0, 6 * SLOT)})).run()
        assert policy.stats.stage2_calls == calls
        assert by_id(res)["X"].dc_id == dc


def test_pred_error_measures_drift_from_last_examination():
    """D43: a job kept after a drift is not re-fired at every later update."""
    start = {1: 100, 2: 500, 3: 500}
    after = {1: 200, 2: 500, 3: 500}
    policy = PredError(epsilon=0.1)
    captures = {0: start, SLOT: after, 2 * SLOT: after, 3 * SLOT: after}
    sc = scenario([job("X", deadline=40000)], captures)
    Simulator(sc, forced(policy, {"X": (0, 10 * SLOT)})).run()
    assert policy.stats.stage2_calls == 1


def test_pig_alone_gets_the_oracle_view():
    a = {1: 100, 2: 300, 3: 300}
    seen = {}

    class Probe(Pig):
        def on_arrival(self, view, job_id):
            seen["view"] = view
            return super().on_arrival(view, job_id)

    sc = scenario([job("X", q=(1, 2, 3, 4), runtime=3600)], {0: a})
    res = Simulator(sc, Probe()).run()
    assert isinstance(seen["view"], OracleView) and res.uses_oracle
    assert Simulator(scenario([job("X")], {0: a}), PlaceOnce()).view.__class__ is SchedulerView


def test_pig_chooses_by_truth_not_forecast():
    forecast = {1: 100, 2: 300, 3: 300}
    truth = {1: 900, 2: 300, 3: 800}
    sc = scenario([job("X")], {0: forecast}, truth=truth)
    assert by_id(Simulator(sc, Pig()).run())["X"].dc_id == 1
    sc = scenario([job("X")], {0: forecast}, truth=truth)
    assert by_id(Simulator(sc, PlaceOnce()).run())["X"].dc_id == 0


def test_pig_keeps_reported_estimates_unchanged():
    a = {1: 100, 2: 300, 3: 300}
    sc = scenario([job("X", q=(600, 1200, 1800, 2400), runtime=3600)], {0: a})
    assert by_id(Simulator(sc, Pig()).run())["X"].r_q50_s == 1200


def test_running_jobs_cannot_be_moved_r_sim_4():
    class Bad(Replanner):
        name = "bad"

        def on_carbon_update(self, view):
            yield Decision("X", "MOVE", Placement(1, view.now_s))

    a = {1: 100, 2: 300, 3: 300}
    with pytest.raises(MigrationError):
        Simulator(scenario([job("X")], {0: a, SLOT: a}), Bad()).run()


def test_make_policy_rejects_unknown_names_and_parameters():
    with pytest.raises(ConfigError):
        make_policy("nope")
    with pytest.raises(ConfigError):
        make_policy("fcfs", theta=1)
