"""Dashboard server (standard library only).

uv run python -m flipwise.web                # http://127.0.0.1:8000
uv run python -m flipwise.web --port 8080 --open
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import signal
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from flipwise.config import policy_params
from flipwise.web import data
from flipwise.web.live import ALL, Session
from flipwise.web.scenarios import PRESETS, REGION_NAMES, config, demo_scenario

STATIC = Path(__file__).parent / "static"
MAX_PROCESS_LANES = 3  # 3 datacentre processes per lane


class App:
    def __init__(self) -> None:
        self.cfg = config()
        self.lock = threading.Lock()
        self.scenarios: dict = {}
        self.sessions: dict[str, Session] = {}
        self.results_cache: dict = {}

    def scenario(self, preset: str):
        with self.lock:
            if preset not in self.scenarios:
                self.scenarios[preset] = demo_scenario(self.cfg, preset)
            return self.scenarios[preset]

    def results(self, split: str) -> dict:
        if split not in self.results_cache:
            self.results_cache[split] = data.results(split)
        return self.results_cache[split]

    def carbon(self, preset: str) -> dict:
        """Data page: truth over the run, one forecast vintage against truth, the job mix."""
        sc = self.scenario(preset)
        t_fc = sc.start_s + 2 * 86400
        return {
            "start_s": sc.start_s, "end_s": sc.end_s, "carbon": data.carbon_curves(sc),
            "forecast": data.forecast_at(sc, t_fc, 48 * 3600), "forecast_t": t_fc,
            "jobs": [[j.arrival_s, j.gpu_req, j.runtime_actual_s, j.r_q50_s, j.r_q90_s]
                     for j in sc.jobs],
            "dcs": [{"id": d.dc_id, "region": d.region_id, "cap_gpu": d.cap_gpu} for d in sc.dcs],
        }  # fmt: skip

    def new_session(self, body: dict) -> dict:
        preset = body.get("preset", "medium")
        if preset not in PRESETS:
            raise ValueError(f"unknown preset {preset!r}")
        policies = [p for p in ALL if p in set(body.get("policies") or ALL)]
        if not policies:
            raise ValueError("select at least one policy")
        mode = body.get("mode", "inproc")
        if mode == "process" and len(policies) > MAX_PROCESS_LANES:
            raise ValueError(f"process mode runs at most {MAX_PROCESS_LANES} policies "
                             f"(3 datacentre processes each)")  # fmt: skip
        for s in self.sessions.values():  # one live session at a time keeps the laptop free
            s.stop()
        self.sessions.clear()
        sc = self.scenario(preset)
        sess = Session(("preset", preset), sc.start_s, policies, mode,
                       float(body.get("speed", 3600)), n_dcs=len(sc.dcs))  # fmt: skip
        sess.scenario = sc
        sess.start()
        self.sessions[sess.id] = sess
        power = sc.power
        jobs = [
            [j.job_id, j.user, j.arrival_s, j.gpu_req, j.cpu_req, round(j.mem_req_gb, 1),
             j.r_q50_s, j.r_q90_s, j.deadline_s, round(power.power_kw(j.gpu_req, j.cpu_req), 4),
             j.runtime_actual_s]
            for j in sc.jobs
        ]  # fmt: skip
        return {
            "sid": sess.id, "preset": preset, "mode": mode, "policies": policies,
            "params": {p: policy_params(self.cfg, p) for p in policies},
            "start_s": sc.start_s, "end_s": sc.end_s,
            "last_arrival_s": max(j.arrival_s for j in sc.jobs),
            "dcs": [{"id": d.dc_id, "region": d.region_id, "name": REGION_NAMES[d.region_id][0],
                     "grid": REGION_NAMES[d.region_id][1], "cap_gpu": d.cap_gpu,
                     "cap_cpu": d.cap_cpu, "cap_mem": d.cap_mem_gb} for d in sc.dcs],
            "job_cols": ["id", "user", "arrival", "gpu", "cpu", "mem", "q50", "q90", "deadline",
                         "kw", "actual"],
            "jobs": jobs,
            "carbon": data.carbon_curves(sc),
            "h_defer_s": sc.params.h_defer_s,
        }  # fmt: skip

    def session(self, sid: str) -> Session:
        s = self.sessions.get(sid)
        if s is None:
            raise LookupError("session ended; start a new one")
        return s


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload, status: int = 200) -> None:
            self._send(status, json.dumps(payload, allow_nan=False).encode(), "application/json")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def _static(self, rel: str) -> None:
            path = (STATIC / rel).resolve()
            if STATIC.resolve() not in path.parents or not path.is_file():
                self._json({"error": "not found"}, 404)
                return
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.suffix == ".js":
                ctype = "text/javascript"
            self._send(200, path.read_bytes(), ctype + "; charset=utf-8")

        def _route(self, method: str) -> None:
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if method == "GET" and u.path in ("/", "/index.html"):
                    return self._static("index.html")
                if method == "GET" and u.path.startswith("/static/"):
                    return self._static(u.path.removeprefix("/static/"))
                if method == "GET" and u.path == "/api/results":
                    return self._json(app.results(q.get("split", "test")))
                if method == "GET" and u.path == "/api/scale":
                    return self._json(data.scale())
                if method == "GET" and u.path == "/api/presets":
                    return self._json({k: {"days": v[0], "sampling": v[1], "label": v[2]}
                                       for k, v in PRESETS.items()})  # fmt: skip
                if method == "GET" and u.path == "/api/carbon":
                    return self._json(app.carbon(q.get("preset", "medium")))
                if method == "POST" and u.path == "/api/session":
                    return self._json(app.new_session(self._body()))
                if method == "GET" and u.path == "/api/poll":
                    s = app.session(q["sid"])
                    watched = set(filter(None, q.get("watch", "").split(",")))
                    cursors = {}
                    for item in filter(None, q.get("cur", "").split(",")):
                        p, _, n = item.partition(":")
                        cursors[p] = int(n or 0)
                    return self._json(s.poll(cursors, watched))
                if method == "POST" and u.path == "/api/clock":
                    b = self._body()
                    s = app.session(b["sid"])
                    act = b.get("action")
                    if act == "play":
                        s.clock.play()
                    elif act == "pause":
                        s.clock.pause()
                    elif act == "speed":
                        s.clock.set_speed(float(b["value"]))
                    elif act == "jump":
                        s.clock.jump(float(b["value"]))
                    return self._json({"now": s.clock.now(), "paused": s.clock.paused})
                if method == "GET" and u.path == "/api/forecast":
                    s = app.session(q["sid"])
                    return self._json(data.forecast_at(s.scenario, float(q["t"])))
                if method == "POST" and u.path == "/api/stop":
                    s = app.sessions.pop(self._body().get("sid", ""), None)
                    if s:
                        s.stop()
                    return self._json({"ok": True})
                return self._json({"error": "not found"}, 404)
            except (ValueError, KeyError, LookupError) as e:
                return self._json({"error": str(e)}, 400)

        def do_GET(self) -> None:  # noqa: N802 (http.server's naming)
            self._route("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._route("POST")

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            pass  # polling would flood the terminal

    return Handler


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Flipwise live dashboard")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--open", action="store_true", help="open a browser tab")
    args = ap.parse_args(argv)
    app = App()

    def _terminate(*_args) -> None:
        raise KeyboardInterrupt  # SIGTERM cleans up like Ctrl+C

    signal.signal(signal.SIGTERM, _terminate)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    server.daemon_threads = True
    url = f"http://{args.host}:{args.port}/"
    print(f"Flipwise dashboard on {url}  (Ctrl+C to stop)", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for s in app.sessions.values():
            s.stop(wait=True)  # no dc-serve process may outlive the server
