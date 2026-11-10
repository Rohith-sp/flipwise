"""One datacentre as an HTTP service, and the client that talks to it (PRD §13.5, protocol 1).

A transport and nothing more: every rule lives in `datacentre.py`, so `--mode remote` can match
`--mode inproc` byte for byte (R-DEP-1). Standard library only. The simulated time arrives with
each request; nothing here reads the wall clock.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

from flipwise.datacentre import InProcDatacentre, Started
from flipwise.errors import DeploymentError, MigrationError, SimulationInvariantError
from flipwise.models import DcConfig, DcState, Request, RunningInfo

PROTOCOL_VERSION = 1
DEFAULT_TIMEOUT_S = 30.0
TIME_BACKWARDS = "TIME_BACKWARDS"
DUPLICATE_JOB = "DUPLICATE_JOB"
MIGRATION = "MIGRATION"
NOT_READY = "NOT_READY"
INVALID_CONFIG = "INVALID_CONFIG"
BAD_REQUEST = "BAD_REQUEST"
NOT_QUEUED = "NOT_QUEUED"
NOT_RUNNING = "NOT_RUNNING"


class _ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code = status, code


class DatacentreService:
    """The API of §13.5 as plain methods, so the routing can be tested without sockets."""

    def __init__(self, dc_id: int) -> None:
        self.dc_id = dc_id
        self.dc: InProcDatacentre | None = None
        # The coordinator sends one request at a time (§13.5 rule 1); this keeps a stray second
        # client from interleaving with it.
        self.lock = threading.Lock()

    def _ready(self) -> InProcDatacentre:
        if self.dc is None:
            raise _ApiError(409, NOT_READY, "POST /reset first")
        return self.dc

    def health(self, _body: dict) -> dict:
        return {"status": "ok", "dc_id": self.dc_id, "protocol_version": PROTOCOL_VERSION}

    def reset(self, body: dict) -> dict:
        try:
            cfg = DcConfig(
                dc_id=int(body["dc_id"]),
                region_id=int(body["region_id"]),
                cap_gpu=float(body["cap_gpu"]),
                cap_cpu=float(body["cap_cpu"]),
                cap_mem_gb=float(body["cap_mem_gb"]),
                pue=float(body["pue"]),
            )
            scenario_hash = str(body["scenario_hash"])
        except (KeyError, TypeError, ValueError) as e:
            raise _ApiError(400, INVALID_CONFIG, f"invalid config: {e!r}") from None
        if cfg.dc_id != self.dc_id:
            raise _ApiError(400, INVALID_CONFIG, f"this is dc {self.dc_id}, not dc {cfg.dc_id}")
        self.dc = InProcDatacentre(cfg, scenario_hash)
        return {"ok": True}

    def enqueue(self, body: dict) -> dict:
        req = Request(body["gpu_req"], body["cpu_req"], body["mem_req_gb"])
        n = self._ready().enqueue(body["t"], body["job_id"], req, body["runtime_actual_s"])
        return {"queue_len": n}

    def remove(self, body: dict) -> dict:
        self._ready().remove(body["t"], body["job_id"])
        return {"ok": True}

    def dispatch(self, body: dict) -> dict:
        started = self._ready().dispatch(body["t"])
        return {
            "started": [
                {"job_id": s.job_id, "start_s": s.start_s, "end_s": s.end_s} for s in started
            ]
        }

    def complete(self, body: dict) -> dict:
        self._ready().complete(body["t"], body["job_id"])
        return {"ok": True}

    def state(self, _body: dict) -> dict:
        st = self._ready().state()
        # Only what the scheduler may see: no end time, no runtime (§8.7, R-DEP-4).
        return {
            "t": st.t_s,
            "cap": _request_json(st.cap),
            "used": _request_json(st.used),
            "queue": list(st.queue),
            "running": [
                {
                    "job_id": r.job_id,
                    "start_s": r.start_s,
                    "gpu_req": r.gpu_req,
                    "cpu_req": r.cpu_req,
                    "mem_req_gb": r.mem_req_gb,
                }
                for r in st.running
            ],
        }

    ROUTES: ClassVar[dict[tuple[str, str], str]] = {
        ("GET", "/health"): "health",
        ("POST", "/reset"): "reset",
        ("POST", "/enqueue"): "enqueue",
        ("POST", "/remove"): "remove",
        ("POST", "/dispatch"): "dispatch",
        ("POST", "/complete"): "complete",
        ("GET", "/state"): "state",
    }

    def handle(self, method: str, path: str, body: dict) -> tuple[int, dict]:
        """Run one request; returns `(status, JSON body)`. Violations become the §13.5 codes."""
        name = self.ROUTES.get((method, path))
        if name is None:
            return 404, {"error": "NOT_FOUND", "message": f"{method} {path}"}
        try:
            with self.lock:
                return 200, getattr(self, name)(body)
        except _ApiError as e:
            return e.status, {"error": e.code, "message": str(e)}
        except MigrationError as e:
            return 409, {"error": MIGRATION, "message": str(e)}
        except SimulationInvariantError as e:
            return 409, {"error": _invariant_code(str(e)), "message": str(e)}
        except KeyError as e:
            # `remove` raises this for a job not in the queue; a missing field raises it too.
            if name == "remove" and "job_id" in body and "t" in body:
                return 404, {"error": NOT_QUEUED, "message": str(e)}
            return 400, {"error": BAD_REQUEST, "message": f"missing field {e}"}
        except TypeError as e:
            return 400, {"error": BAD_REQUEST, "message": str(e)}


def _invariant_code(message: str) -> str:
    for code in (TIME_BACKWARDS, DUPLICATE_JOB):
        if message.startswith(code):
            return code
    return NOT_RUNNING


def _request_json(r: Request) -> dict:
    return {"gpu": r.gpu, "cpu": r.cpu, "mem_gb": r.mem_gb}


def make_server(
    dc_id: int, host: str = "127.0.0.1", port: int = 8101, crash_at_request: int | None = None
) -> ThreadingHTTPServer:
    """A bound, not yet serving, server for one datacentre. Port 0 picks a free port.

    `crash_at_request` is fault injection for R-DEP-3: the process exits, without answering, on
    that simulation request (1-based; `/health` does not count). Counting requests, not seconds,
    makes the failure land at the same point of every run.
    """
    service = DatacentreService(dc_id)
    seen = {"n": 0}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _serve(self, method: str) -> None:
            if crash_at_request is not None and self.path != "/health":
                with lock:
                    seen["n"] += 1
                    if seen["n"] >= crash_at_request:
                        print(f"dc {dc_id}: crashing at request {seen['n']} (fault injection)",
                              flush=True)  # fmt: skip
                        os._exit(3)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError as e:
                self._reply(400, {"error": BAD_REQUEST, "message": f"not JSON: {e}"})
                return
            self._reply(*service.handle(method, self.path, body))

        def _reply(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 (http.server's naming)
            self._serve("GET")

        def do_POST(self) -> None:  # noqa: N802 (http.server's naming)
            self._serve("POST")

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            pass  # one line per RPC would swamp the service log on a real run

    return _Server((host, port), Handler)


class _Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second socket take a port that is already listening, so a
    # service could silently share a port with another program; there, a busy port must fail.
    allow_reuse_address = sys.platform != "win32"


def serve(dc_id: int, host: str, port: int, crash_at_request: int | None = None) -> None:
    """`flipwise dc-serve`: runs until the process is stopped."""
    with make_server(dc_id, host, port, crash_at_request) as server:
        print(f"dc {dc_id} serving on {host}:{server.server_address[1]}", flush=True)
        server.serve_forever()


class HttpDatacentre:
    """`DatacentreClient` over HTTP. Any failure raises `DeploymentError` and is never retried,
    because retrying `/enqueue` could apply it twice (§13.5 rule 4)."""

    def __init__(self, url: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s
        self.rpc_count = 0

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        self.rpc_count += 1
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.url + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise DeploymentError(f"{method} {self.url}{path}: HTTP {e.code} {detail}") from None
        except (OSError, ValueError) as e:  # refused, reset, timed out, or not JSON
            raise DeploymentError(f"{method} {self.url}{path}: {e}") from None

    def health(self) -> dict:
        return self._call("GET", "/health")

    def reset(self, cfg: DcConfig, scenario_hash: str = "") -> None:
        health = self.health()
        if health.get("protocol_version") != PROTOCOL_VERSION:
            raise DeploymentError(f"{self.url}: protocol {health.get('protocol_version')}")
        self._call(
            "POST",
            "/reset",
            {
                "dc_id": cfg.dc_id,
                "region_id": cfg.region_id,
                "cap_gpu": cfg.cap_gpu,
                "cap_cpu": cfg.cap_cpu,
                "cap_mem_gb": cfg.cap_mem_gb,
                "pue": cfg.pue,
                "scenario_hash": scenario_hash,
            },
        )

    def enqueue(self, t_s: int, job_id: str, req: Request, runtime_actual_s: int) -> int:
        body = {
            "t": t_s,
            "job_id": job_id,
            "gpu_req": req.gpu,
            "cpu_req": req.cpu,
            "mem_req_gb": req.mem_gb,
            "runtime_actual_s": runtime_actual_s,
        }
        return self._call("POST", "/enqueue", body)["queue_len"]

    def remove(self, t_s: int, job_id: str) -> None:
        self._call("POST", "/remove", {"t": t_s, "job_id": job_id})

    def dispatch(self, t_s: int) -> list[Started]:
        started = self._call("POST", "/dispatch", {"t": t_s})["started"]
        return [Started(s["job_id"], s["start_s"], s["end_s"]) for s in started]

    def complete(self, t_s: int, job_id: str) -> None:
        self._call("POST", "/complete", {"t": t_s, "job_id": job_id})

    def state(self) -> DcState:
        st = self._call("GET", "/state")
        return DcState(
            t_s=st["t"],
            cap=Request(**{k: st["cap"][k] for k in ("gpu", "cpu", "mem_gb")}),
            used=Request(**{k: st["used"][k] for k in ("gpu", "cpu", "mem_gb")}),
            queue=tuple(st["queue"]),
            running=tuple(
                RunningInfo(r["job_id"], r["start_s"], r["gpu_req"], r["cpu_req"], r["mem_req_gb"])
                for r in st["running"]
            ),
        )
