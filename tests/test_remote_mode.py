"""`flipwise run --mode remote` against separate `dc-serve` processes (PRD §13.5, DT1 step 7).

The services here are real processes, as `local_cluster.sh` starts them, not threads: this is the
CLI form of R-DEP-1 that `test_dcservice.py` checks in-process.
"""

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from flipwise.cli import main
from flipwise.dcservice import HttpDatacentre
from flipwise.errors import ConfigError, DeploymentError
from flipwise.experiment import ALL_POLICIES

TOY = Path(__file__).parent / "fixtures" / "toy"
COMPARED = ("jobs.csv", "decisions.csv", "events.log")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_healthy(url: str, timeout_s: float = 20) -> None:
    client = HttpDatacentre(url, timeout_s=2)
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            client.health()
            return
        except DeploymentError:
            assert time.monotonic() < deadline, f"{url} did not come up"
            time.sleep(0.1)


@pytest.fixture(scope="module")
def cluster():
    """Three `flipwise dc-serve` processes on free local ports, in dc_id order."""
    ports = [_free_port() for _ in range(3)]
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "flipwise.cli", "dc-serve", "--dc-id", str(i), "--port", str(p)],
            stdout=subprocess.DEVNULL,
        )
        for i, p in enumerate(ports)
    ]
    urls = [f"http://127.0.0.1:{p}" for p in ports]
    try:
        for u in urls:
            _wait_healthy(u)
        yield urls
    finally:
        for p in procs:
            p.kill()
            p.wait()


def _run(out: Path, policy: str, *extra: str) -> Path:
    assert main(["run", "--scenario", str(TOY), "--policy", policy, "--out", str(out), *extra]) == 0
    (run_dir,) = [d for d in out.iterdir() if d.is_dir()]
    return run_dir


@pytest.mark.parametrize("policy", ALL_POLICIES)
def test_cli_remote_run_is_byte_identical_r_dep_1(cluster, policy, tmp_path):
    """Every policy on the toy: the three compared files match `--mode inproc` byte for byte."""
    local = _run(tmp_path / "inproc", policy)
    remote = _run(tmp_path / "remote", policy, "--mode", "remote", "--dc-urls", ",".join(cluster))
    for name in COMPARED:
        assert (remote / name).read_bytes() == (local / name).read_bytes(), name
    manifest = json.loads((remote / "manifest.json").read_text())
    assert manifest["mode"] == "remote" and manifest["dc_urls"] == cluster
    # R-DEP-5: both modes report overhead, and make the same calls to each datacentre
    local_calls = json.loads((local / "manifest.json").read_text())["overhead"]["per_dc"]
    remote_calls = manifest["overhead"]["per_dc"]
    assert [d["calls"] for d in remote_calls] == [d["calls"] for d in local_calls]
    assert all(d["calls"] > 0 and d["seconds"] >= 0 for d in remote_calls)
    assert remote.name != local.name  # a remote run is never served from a saved in-process run


def test_wrong_number_of_urls_is_a_config_error(cluster, tmp_path):
    with pytest.raises(ConfigError, match="3 datacentres"):
        _run(tmp_path, "fcfs", "--mode", "remote", "--dc-urls", ",".join(cluster[:2]))


def test_urls_in_the_wrong_order_are_refused(cluster, tmp_path):
    swapped = [cluster[1], cluster[0], cluster[2]]
    with pytest.raises(ConfigError, match="another datacentre"):
        _run(tmp_path, "fcfs", "--mode", "remote", "--dc-urls", ",".join(swapped))


def test_dc_urls_need_remote_mode(cluster, tmp_path):
    with pytest.raises(ConfigError, match="only for --mode remote"):
        _run(tmp_path, "fcfs", "--dc-urls", ",".join(cluster))


def test_no_service_fails_before_the_run_r_dep_3(tmp_path):
    """Nothing listening: `DeploymentError`, and no run is left looking complete."""
    urls = ",".join(f"http://127.0.0.1:{_free_port()}" for _ in range(3))
    with pytest.raises(DeploymentError):
        main(["run", "--scenario", str(TOY), "--policy", "fcfs", "--out", str(tmp_path),
              "--mode", "remote", "--dc-urls", urls])  # fmt: skip
    assert not list(tmp_path.rglob("metrics.json"))
