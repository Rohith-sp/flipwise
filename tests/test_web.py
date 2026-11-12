"""The live dashboard drives the unchanged simulator: pacing must not change any decision."""

from __future__ import annotations

from conftest import TOY

from flipwise.policies import make_policy
from flipwise.simulator import Simulator
from flipwise.web.live import ALL, Session


def _run_live(toy, policies, timeout_s: float = 120):
    session = Session(("dir", str(TOY)), toy.start_s, list(policies), "inproc", 1e12,
                      n_dcs=len(toy.dcs), return_logs=True)  # fmt: skip
    session.clock.play()
    session.start()
    assert session.wait(timeout_s), "live lanes did not finish"
    return session


def test_live_lanes_match_plain_runs_r_sim_1(toy):
    """R-SIM-1 holds through the dashboard: each live lane, in its own process and in lock-step
    with the others, logs exactly the events and decisions of `Simulator.run`."""
    session = _run_live(toy, ALL)
    for policy in ALL:
        lane = session.lanes[policy]
        assert lane.error is None, lane.error
        plain = Simulator(toy, make_policy(policy), debug=False).run()
        events, decisions = lane.logs
        assert events == plain.events, policy
        assert decisions == plain.decisions, policy


def test_live_records_cover_every_job(toy):
    """Every job is recorded arriving and, when it completes in the plain run, completing."""
    lane = _run_live(toy, ["decision_flip"]).lanes["decision_flip"]
    arrived = {r["j"] for r in lane.records if r["k"] == "arr"}
    done = {r["j"] for r in lane.records if r["k"] == "done"}
    assert arrived == {j.job_id for j in toy.jobs}
    plain = Simulator(toy, make_policy("decision_flip"), debug=False).run()
    assert done == {j.job_id for j in plain.jobs if j.state == "COMPLETED"}
    assert lane.summary()["done"] == len(done)


def test_stopped_session_unwinds(toy):
    """A paused session waits at its first event; stopping it unwinds the lane cleanly (the
    lane reports its end, with no error and no events handled). `stop` reaps the process."""
    session = Session(("dir", str(TOY)), toy.start_s, ["fixed_savings"], "inproc", 1.0,
                      n_dcs=len(toy.dcs))  # fmt: skip
    session.start()
    session.stop()
    assert session.wait(30)
    lane = session.lanes["fixed_savings"]
    assert lane.finished and lane.error is None
    assert lane.summary()["arrived"] == 0
