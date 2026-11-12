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
