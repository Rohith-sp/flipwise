"""`flipwise live --services local`: start the datacentre services as child processes.

A convenience for the demo (PRD §13.6): the same `dc-serve` processes `scripts/local_cluster.sh`
starts, owned by the live command so one command runs everything and nothing is left behind.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager

from flipwise.errors import DeploymentError

HEALTH_WAIT_S = 20.0
STOP_WAIT_S = 5.0


def _wait_healthy(proc: subprocess.Popen, dc_id: int, port: int) -> None:
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + HEALTH_WAIT_S  # real time: waiting for a process, not simulation
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise DeploymentError(
                f"datacentre {dc_id} exited with code {proc.returncode} on port {port};"
                " is the port already in use? Try --base-port"
            )
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                health = json.loads(response.read())
        except (OSError, ValueError):
            time.sleep(0.2)  # not up yet
            continue
        if health.get("dc_id") != dc_id:
            raise DeploymentError(f"{url} answers as dc {health.get('dc_id')}, not dc {dc_id}")
        return
    raise DeploymentError(
        f"datacentre {dc_id} gave no /health on port {port} in {HEALTH_WAIT_S:g} s"
    )


def _stop(procs: list[subprocess.Popen]) -> None:
    for p in procs:
        if p.poll() is None:
            p.terminate()  # Windows has no SIGTERM handler; terminate() works on both systems
    for p in procs:
        try:
            p.wait(timeout=STOP_WAIT_S)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()


@contextmanager
def local_services(count: int, base_port: int = 8101) -> Iterator[list[str]]:
    """Yield the service URLs in dc_id order; always stops the children on exit."""
    procs: list[subprocess.Popen] = []

    def on_sigterm(_signum, _frame) -> None:
        raise SystemExit(143)  # unwinds through `finally`, so the children are stopped too

    try:
        previous = signal.signal(signal.SIGTERM, on_sigterm)
    except ValueError:  # not the main thread (tests, embedding): Ctrl-C and errors still clean up
        previous = None
    try:
        for i in range(count):
            cmd = [sys.executable, "-m", "flipwise", "dc-serve", "--dc-id", str(i),
                   "--host", "127.0.0.1", "--port", str(base_port + i)]  # fmt: skip
            procs.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL))
        for i, p in enumerate(procs):
            _wait_healthy(p, i, base_port + i)
        yield [f"http://127.0.0.1:{base_port + i}" for i in range(count)]
    finally:
        _stop(procs)
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)
