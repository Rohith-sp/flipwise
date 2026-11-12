"""Live demo mode (PRD §13.6, D60): refactor safety, submitted jobs, history, HTTP API."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from flipwise.live import LiveSession, make_handler, scenario_factory
from flipwise.policies import make_policy
from flipwise.simulator import Simulator

TOY = Path(__file__).parent / "fixtures" / "toy"
POLICIES = ["decision_flip", "fixed_savings", "periodic", "pred_error", "place_once"]


def _session(speed: float = 1800.0) -> LiveSession:
    session = LiveSession(scenario_factory(None, TOY), None, POLICIES, speed)
    session.paused = True  # tests drive the clock with skip_hours, not wall time
    return session


def test_live_run_equals_stepwise_advance():
    """Splitting `run` into start/advance/result must not change events or decisions."""
    sc = scenario_factory(None, TOY)()
    whole = Simulator(sc, make_policy("decision_flip")).run()
    sim = Simulator(sc, make_policy("decision_flip"))
    sim.start()
    t = sc.start_s
    while not sim.advance(t):
        t += 900
    parts = sim.result()
    assert parts.events == whole.events
    assert parts.decisions == whole.decisions


def test_live_submitted_job_placed_by_every_policy():
    s = _session()
    job_id = s.submit({"runtime_h": 1, "gpus": 1})["job_id"]
    s.control({"skip_hours": 6})
    story = s.job(job_id)
    assert set(story["by_policy"]) == set(POLICIES)
    for view in story["by_policy"].values():
        assert view["datacentre"] is not None
        assert view["decisions"]
    with pytest.raises(KeyError):
        s.job("USER-99")


def test_live_skip_hours_advances_clock_and_history():
    s = _session()
    before = len(s.get_history()["policies"]["decision_flip"])
    t0 = s.clock()["sim_time_s"]
    s.control({"skip_hours": 3})
    assert s.clock()["sim_time_s"] > t0
    hist = s.get_history()["policies"]["decision_flip"]
    assert len(hist) >= before + 5  # 3 h = 6 half hours
    assert {"kg_co2", "moves", "dcs"} <= set(hist[-1])
    assert len(hist[-1]["dcs"]) == 3
    newer = s.get_history(hist[2]["t"])["policies"]["decision_flip"]
    assert newer == hist[3:]


def _call(base: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), e.read()


def test_live_http_smoke():
    s = _session()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(s))
    base = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert _call(base, "/status")[0] == 200
        code, _, body = _call(base, "/jobs", {"runtime_h": 1})
        assert code == 201 and json.loads(body)["job_id"] == "USER-1"
        s.control({"skip_hours": 2})
        code, _, body = _call(base, "/jobs/USER-1")
        assert code == 200 and "by_policy" in json.loads(body)
        code, _, body = _call(base, "/health")
        dcs = json.loads(body)["datacentres"]
        assert code == 200 and dcs[0]["url"] == "in-process" and not dcs[0]["remote"]
        assert dcs[0]["requests"] > 0
        assert _call(base, "/history?since=0")[0] == 200
        code, ctype, body = _call(base, "/")
        assert code == 200 and ctype.startswith("text/html") and b"Flipwise live" in body
        for bad in (
            "/../../etc/passwd",
            "/static/../../../etc/passwd",
            "/static/..%2f..%2f..%2fetc/passwd",
            "/static/%2e%2e/%2e%2e/pyproject.toml",
        ):
            assert _call(base, bad)[0] == 404
    finally:
        server.shutdown()
        server.server_close()
        s.closed.set()
        thread.join(timeout=5)


def test_live_stream_feed_tags_decisions_with_policy():
    s = _session()
    last = s.feed.last_id
    s.submit({"runtime_h": 1})
    s.control({"skip_hours": 2})
    events = s.feed.after(last, 0.0)
    assert [e[0] for e in events] == sorted(e[0] for e in events)
    decisions = [e[2] for e in events if e[1] == "decision"]
    assert {d["policy"] for d in decisions} >= {"decision_flip", "place_once"}


def test_live_activity_groups_decisions_per_forecast_update():
    s = _session()
    s.control({"skip_hours": 6})
    for policy in ("decision_flip", "fixed_savings"):
        rows = s.activity(policy)
        assert rows and [r["t"] for r in rows] == sorted(r["t"] for r in rows)
        for r in rows:
            assert r["checked"] >= r["screen_skipped"] + r["moved"] + r["rescored_kept"]
        assert s.activity(policy, rows[-1]["t"]) == []
        assert s.activity(policy, rows[0]["t"]) == rows[1:]
    flip_kinds = sum(r["screen_skipped"] for r in s.activity("decision_flip"))
    log = sum(1 for d in s.sims["decision_flip"].decisions if d["kind"] == "SCREEN_FAIL")
    assert flip_kinds <= log
    with pytest.raises(KeyError):
        s.activity("nope")


def test_live_lanes_list_jobs_per_datacentre_capped():
    s = _session()
    s.submit({"runtime_h": 1, "gpus": 1})
    s.control({"skip_hours": 1})
    lanes = s.lanes("decision_flip")
    assert len(lanes["datacentres"]) == 3
    seen = [j for dc in lanes["datacentres"] for k in ("planned", "queued", "running")
            for j in dc[k]["jobs"]]  # fmt: skip
    assert seen and all(len(j["job_id"]) <= 8 and "moved" in j for j in seen)
    assert any(j["user_job"] for j in seen)
    for dc in lanes["datacentres"]:
        assert all(len(dc[k]["jobs"]) <= 60 for k in ("planned", "queued", "running"))
    with pytest.raises(KeyError):
        s.lanes("nope")


def test_live_validation_replicates_play_in_turn():
    """Replicates follow one another; user jobs are per replicate (live-mode design, D60)."""
    factory = scenario_factory(None, TOY)
    reps = [("rep_a", factory), ("rep_b", factory)]
    s = LiveSession(factory, None, ["decision_flip", "fixed_savings"], 1800.0, None, reps)
    s.paused = True
    assert s.clock()["replicate"] == {"name": "rep_a", "index": 1, "total": 2,
                                      "building": False, "notes": []}  # fmt: skip
    s.submit({"runtime_h": 1})
    s.control({"skip_hours": 7 * 24})
    assert s.step() is False  # all finished replicate 1: step builds replicate 2
    info = s.clock()["replicate"]
    assert (info["name"], info["index"]) == ("rep_b", 2)
    assert s.user_jobs == [] and info["notes"]
    assert s.clock()["finished"] is False
    s.control({"skip_hours": 7 * 24})
    assert s.step() is True and s.clock()["finished"] is True


def test_live_cli_refuses_test_split():
    import argparse

    from flipwise.cli import _cmd_live
    from flipwise.errors import ConfigError

    with pytest.raises(ConfigError, match="once only"):
        _cmd_live(argparse.Namespace(split="test"))
