"""Datacentre dashboards and `flipwise live --services local` (PRD §13.6, D62).

All display only: the simulation API and its byte-identity (R-DEP-1) are checked in
`test_dcservice.py`; this file checks that the extra GET routes leave them alone.
"""

import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from flipwise.dcservice import HttpDatacentre, make_server
from flipwise.errors import ConfigError, DeploymentError
from flipwise.models import DcConfig, Request
from flipwise.policies import make_policy
from flipwise.simulator import Simulator

TOY = Path(__file__).parent / "fixtures" / "toy"


class Running:
    """A service on a free local port, in a thread of this process."""

    def __init__(self, dc_id=0):
        self.server = make_server(dc_id, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def _get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def test_live_before_any_config_reports_waiting():
    running = Running(1)
    try:
        status, headers, body = _get(running.url + "/live")
        data = json.loads(body)
        assert status == 200 and data["state"] == "waiting"
        assert data["name"] == "Mumbai" and data["grid"] == "Western grid"
        assert data["port"] == int(running.url.rsplit(":", 1)[1])
        assert headers["Access-Control-Allow-Origin"] == "*"
    finally:
        running.stop()


def test_live_counters_and_log_match_the_calls_made():
    running = Running(0)
    try:
        c = HttpDatacentre(running.url)
        c.reset(DcConfig(0, 0, 4.0, 32.0, 100.0), "h")
        for i, t in enumerate((0, 100, 2000)):
            c.enqueue(t, f"j{i}", Request(2.0, 2.0, 3.0), 500)
        started = c.dispatch(2000)  # two jobs of 2 GPUs fit in 4; the third waits
        c.complete(2500, started[0].job_id)
        c.remove(2600, "j2")
        data = json.loads(_get(running.url + "/live")[2])
        assert data["state"] == "ready" and data["t"] == 2600
        assert data["counters"] == {
            "enqueue": 3, "remove": 1, "dispatch": 1, "complete": 1,
            "started": len(started), "requests": 6,
        }  # fmt: skip
        assert [e["op"] for e in data["log"]] == ["enqueue"] * 3 + [
            "dispatch",
            "complete",
            "remove",
        ]
        assert data["log"][0]["gpu"] == 2.0 and data["log"][3]["started"]
        assert data["capacity"]["gpu"] == 4.0 and data["queue_len"] == len(data["queue"]) == 0
        assert len(data["running"]) == len(started) - 1
        assert [h["t"] for h in data["history"]] == [0, 2000]  # one sample per half hour
        assert data["starts"][0]["job_id"] == started[0].job_id
    finally:
        running.stop()


def test_log_is_bounded():
    running = Running(0)
    try:
        c = HttpDatacentre(running.url)
        c.reset(DcConfig(0, 0, 4.0, 32.0, 100.0), "h")
        for i in range(260):
            c.dispatch(i)
        data = json.loads(_get(running.url + "/live")[2])
        assert len(data["log"]) == 200 and data["counters"]["dispatch"] == 260
    finally:
        running.stop()


def test_root_is_html_and_static_serves_vendored_files():
    running = Running()
    try:
        status, headers, body = _get(running.url + "/")
        assert status == 200 and headers["Content-Type"].startswith("text/html")
        assert b"Waiting for the scheduler" in body
        assert _get(running.url + "/static/js/dc.js")[0] == 200
        assert _get(running.url + "/static/vendor/echarts.min.js")[0] == 200
    finally:
        running.stop()


@pytest.mark.parametrize(
    "path",
    ["/static/../dcservice.py", "/static/%2e%2e/dcservice.py", "/static/../../../etc/passwd"],
)
def test_static_traversal_is_refused(path):
    running = Running()
    try:
        host, port = running.url.removeprefix("http://").split(":")
        with socket.create_connection((host, int(port)), timeout=5) as s:
            # A raw request: urllib would normalise the ".." away before sending.
            s.sendall(f"GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n".encode())
            reply = b""
            while chunk := s.recv(4096):
                reply += chunk
        assert reply.startswith(b"HTTP/1.1 404")
        assert b"import" not in reply and b"root:" not in reply
    finally:
        running.stop()


def test_dashboard_gets_do_not_use_the_crash_budget():
    """R-DEP-3: `--crash-at-request` counts simulation requests only."""
    server = make_server(0, port=0, crash_at_request=3)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        c = HttpDatacentre(url)
        c.reset(DcConfig(0, 0, 4.0, 32.0, 100.0), "h")  # simulation request 1
        for _ in range(10):
            assert _get(url + "/live")[0] == 200
            assert _get(url + "/")[0] == 200
            assert _get(url + "/static/css/app.css")[0] == 200
        c.enqueue(0, "a", Request(1.0, 1.0, 1.0), 10)  # request 2: still alive
    finally:
        server.shutdown()
        server.server_close()
        t.join()


def test_dashboard_leaves_the_run_byte_identical_r_dep_1(toy, tmp_path):
    """Polling /live during a remote run must not change its outputs."""
    from flipwise.reporting import write_run

    local = write_run(Simulator(toy, make_policy("decision_flip")).run(), tmp_path / "local")
    services = [Running(d.dc_id) for d in toy.dcs]
    try:
        for s in services:
            _get(s.url + "/live")
        clients = [HttpDatacentre(s.url) for s in services]
        sim = Simulator(toy, make_policy("decision_flip"), clients)
        remote = write_run(sim.run(), tmp_path / "remote")
        live = [json.loads(_get(s.url + "/live")[2]) for s in services]
    finally:
        for s in services:
            s.stop()
    assert remote == local
    assert all(d["state"] == "ready" and d["counters"]["requests"] > 0 for d in live)


def _free_ports(n: int) -> int:
    """A base port whose next n-1 ports are free too."""
    for _ in range(50):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            base = s.getsockname()[1]
        try:
            for p in range(base, base + n):
                with socket.socket() as s:
                    s.bind(("127.0.0.1", p))
            return base
        except OSError:
            continue
    raise AssertionError("no free port range")


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def test_live_refuses_services_local_with_dc_urls():
    from flipwise.cli import main

    with pytest.raises(ConfigError, match="dc-urls"):
        main(["live", "--scenario", str(TOY), "--services", "local", "--dc-urls", "http://x:1"])


def test_local_services_reports_a_busy_port_as_deployment_error():
    from flipwise.localservices import local_services

    base = _free_ports(2)
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", base + 1))
        blocker.listen()
        with pytest.raises(DeploymentError, match="port"), local_services(2, base):
            pass
    assert not _port_open(base)  # the first child was stopped too


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM cannot unwind a Windows process")
def test_live_services_local_starts_four_listeners_and_stops_children():
    base, sched = _free_ports(3), _free_ports(1)
    proc = subprocess.Popen(
        [sys.executable, "-m", "flipwise", "live", "--scenario", str(TOY), "--services", "local",
         "--base-port", str(base), "--port", str(sched), "--policies", "decision_flip"],
        stdout=subprocess.PIPE, text=True,
    )  # fmt: skip
    try:
        deadline = time.monotonic() + 40
        urls = [f"http://127.0.0.1:{sched}/health"] + [
            f"http://127.0.0.1:{base + i}/" for i in range(3)
        ]
        for url in urls:
            while True:
                try:
                    assert _get(url)[0] == 200
                    break
                except OSError:
                    assert proc.poll() is None and time.monotonic() < deadline, url
                    time.sleep(0.2)
        health = json.loads(_get(urls[0])[2])
        assert [d["remote"] for d in health["datacentres"]] == [True] * 3
    finally:
        proc.terminate()
        proc.wait(timeout=30)
    deadline = time.monotonic() + 10
    while any(_port_open(base + i) for i in range(3)) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not any(_port_open(base + i) for i in range(3)) and not _port_open(sched)
