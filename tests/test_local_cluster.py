"""`scripts/local_cluster.sh` and `.ps1`, run for real (PRD §13.5 DT1; R-DEP-1, R-DEP-3).

Each test starts three `dc-serve` processes through the script on ports no other test uses. The
scripts are the demo, so they are tested as a teammate runs them: bash on Linux, and on Windows
both PowerShell and Git Bash when it is installed.
"""

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from flipwise.cli import main

ROOT = Path(__file__).parent.parent
TOY = ROOT / "tests" / "fixtures" / "toy"
COMPARED = ("jobs.csv", "decisions.csv", "events.log")


def _git_bash() -> str | None:
    """Git Bash on Windows (never WSL's bash.exe, which runs in another OS); bash elsewhere."""
    if sys.platform != "win32":
        return shutil.which("bash")
    git = shutil.which("git")
    if git is None:
        return None
    candidate = Path(git).resolve().parents[1] / "bin" / "bash.exe"
    return str(candidate) if candidate.exists() else None


def _runners() -> list:
    found = []
    if sys.platform == "win32":
        found.append(pytest.param("ps1", id="powershell"))
    if _git_bash():
        found.append(pytest.param("sh", id="bash"))
    return found


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _free_base(n: int = 3) -> int:
    for base in range(18100, 19000, 10):
        if all(_port_free(base + i) for i in range(n)):
            return base
    raise RuntimeError("no free ports for the cluster")


def _cluster(runner: str, base: int, *args: str) -> subprocess.CompletedProcess:
    extra = ["--base-port", str(base), *args]
    if runner == "ps1":
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               str(ROOT / "scripts" / "local_cluster.ps1"), *extra]  # fmt: skip
    else:
        cmd = [_git_bash(), str(ROOT / "scripts" / "local_cluster.sh"), *extra]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    # Output to a file, not a pipe: a service the script failed to stop would keep a pipe open
    # and hang this test, whereas with a file it fails on the free-port check instead.
    log = Path(os.environ.get("TMP", "/tmp")) / f"local_cluster_{runner}_{base}.log"
    with open(log, "w+", encoding="utf-8", errors="replace") as out:
        code = subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, timeout=180,
                              env=env).returncode  # fmt: skip
        out.seek(0)
        text = out.read()
    return subprocess.CompletedProcess(cmd, code, text, "")


def _only_run_dir(out: Path) -> Path:
    (run_dir,) = [d for d in out.iterdir() if d.is_dir()]
    return run_dir


@pytest.mark.parametrize("runner", _runners())
def test_cluster_run_matches_inproc_and_keeps_logs_r_dep_1(runner, tmp_path):
    base = _free_base()
    done = _cluster(runner, base, "--scenario", str(TOY), "--policy", "decision_flip",
                    "--out", str(tmp_path / "remote"))  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    remote = _only_run_dir(tmp_path / "remote")
    assert main(["run", "--scenario", str(TOY), "--policy", "decision_flip",
                 "--out", str(tmp_path / "inproc")]) == 0  # fmt: skip
    local = _only_run_dir(tmp_path / "inproc")
    for name in COMPARED:
        assert (remote / name).read_bytes() == (local / name).read_bytes(), name
    assert sorted(p.name for p in remote.glob("dc-*.log")) == ["dc-0.log", "dc-1.log", "dc-2.log"]
    assert all(_port_free(base + i) for i in range(3)), "a service outlived the script"


@pytest.mark.parametrize("runner", _runners())
def test_a_crashed_service_aborts_the_run_cleanly_r_dep_3(runner, tmp_path):
    """Exit non-zero with `DeploymentError`, no `metrics.json`, and no service left running."""
    base = _free_base()
    done = _cluster(runner, base, "--crash", "1:5", "--scenario", str(TOY),
                    "--policy", "decision_flip", "--out", str(tmp_path))  # fmt: skip
    assert done.returncode != 0
    assert "DeploymentError" in done.stdout + done.stderr
    assert not list(tmp_path.rglob("metrics.json"))
    assert all(_port_free(base + i) for i in range(3)), "a service outlived the script"


@pytest.mark.parametrize("runner", _runners())
def test_a_busy_port_starts_nothing_and_kills_nothing(runner, tmp_path):
    """The script must never stop a process it did not start, here this test's own socket."""
    base = _free_base()
    with socket.socket() as other:
        other.bind(("127.0.0.1", base + 1))
        other.listen()
        done = _cluster(runner, base, "--scenario", str(TOY), "--policy", "fcfs",
                        "--out", str(tmp_path))  # fmt: skip
        assert done.returncode == 2, done.stdout + done.stderr
        assert other.fileno() != -1
    assert _port_free(base) and _port_free(base + 2)
    assert not list(tmp_path.rglob("metrics.json"))
