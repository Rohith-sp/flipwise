"""Datacentre state and FIFO first-fit dispatch (PRD §8.3, §13.5).

The simulator talks to every datacentre through `DatacentreClient`, so the same simulation can
run in-process or against HTTP services (deployment track) without changing any logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from flipwise.errors import MigrationError, SimulationInvariantError
from flipwise.models import DcConfig, DcState, Request, RunningInfo


@dataclass(frozen=True)
class Started:
    job_id: str
    start_s: int
    end_s: int


class DatacentreClient(Protocol):
    def reset(self, cfg: DcConfig, scenario_hash: str) -> None: ...

    def enqueue(self, t_s: int, job_id: str, req: Request, runtime_actual_s: int) -> int: ...

    def remove(self, t_s: int, job_id: str) -> None: ...

    def dispatch(self, t_s: int) -> list[Started]: ...

    def complete(self, t_s: int, job_id: str) -> None: ...

    def state(self) -> DcState: ...


@dataclass
class _Entry:
    req: Request
    runtime_actual_s: int
    start_s: int | None = None


class InProcDatacentre:
    """Plain-Python datacentre. Never reads the wall clock: time arrives with every call."""

    def __init__(self, cfg: DcConfig | None = None, scenario_hash: str = "") -> None:
        if cfg is not None:
            self.reset(cfg, scenario_hash)

    def reset(self, cfg: DcConfig, scenario_hash: str = "") -> None:
        self.cfg = cfg
        self.scenario_hash = scenario_hash
        self.t_s = -(2**62)
        self.queue: list[str] = []
        self.running: dict[str, _Entry] = {}  # insertion order == start order
        self.jobs: dict[str, _Entry] = {}
        self.used = Request(0.0, 0.0, 0.0)

    def _advance(self, t_s: int) -> None:
        if t_s < self.t_s:
            raise SimulationInvariantError(
                f"TIME_BACKWARDS: dc {self.cfg.dc_id} got t={t_s} after t={self.t_s}"
            )
        self.t_s = t_s

    def enqueue(self, t_s: int, job_id: str, req: Request, runtime_actual_s: int) -> int:
        self._advance(t_s)
        if job_id in self.jobs:
            raise SimulationInvariantError(f"DUPLICATE_JOB: {job_id} at dc {self.cfg.dc_id}")
        self.jobs[job_id] = _Entry(req, runtime_actual_s)
        self.queue.append(job_id)
        return len(self.queue)

    def remove(self, t_s: int, job_id: str) -> None:
        self._advance(t_s)
        if job_id in self.running:
            raise MigrationError(f"job {job_id} is running at dc {self.cfg.dc_id}")
        if job_id not in self.queue:
            raise KeyError(f"job {job_id} not queued at dc {self.cfg.dc_id}")
        self.queue.remove(job_id)
        del self.jobs[job_id]

    def _free(self) -> Request:
        c, u = self.cfg.cap, self.used
        return Request(c.gpu - u.gpu, c.cpu - u.cpu, c.mem_gb - u.mem_gb)

    def dispatch(self, t_s: int) -> list[Started]:
        """Scan the queue front to back and start every job that fits (first-fit, FIFO)."""
        self._advance(t_s)
        started: list[Started] = []
        remaining: list[str] = []
        for job_id in self.queue:
            e = self.jobs[job_id]
            if e.req.fits_in(self._free()):
                e.start_s = t_s
                self.running[job_id] = e
                u = self.used
                self.used = Request(u.gpu + e.req.gpu, u.cpu + e.req.cpu, u.mem_gb + e.req.mem_gb)
                started.append(Started(job_id, t_s, t_s + e.runtime_actual_s))
            else:
                remaining.append(job_id)
        self.queue = remaining
        self._check_capacity()
        return started

    def complete(self, t_s: int, job_id: str) -> None:
        self._advance(t_s)
        e = self.running.get(job_id)
        if e is None or e.start_s is None or e.start_s + e.runtime_actual_s != t_s:
            raise SimulationInvariantError(f"complete({job_id}) at {t_s} is not its end time")
        del self.running[job_id]
        del self.jobs[job_id]
        u = self.used
        self.used = Request(u.gpu - e.req.gpu, u.cpu - e.req.cpu, u.mem_gb - e.req.mem_gb)
        if not self.running:
            # Avoid float drift accumulating across the run once the datacentre is idle.
            self.used = Request(0.0, 0.0, 0.0)

    def _check_capacity(self) -> None:
        if not self.used.fits_in(self.cfg.cap):
            raise SimulationInvariantError(
                f"overbooking at dc {self.cfg.dc_id}: used {self.used} > cap {self.cfg.cap}"
            )

    def state(self) -> DcState:
        return DcState(
            t_s=self.t_s,
            cap=self.cfg.cap,
            used=self.used,
            queue=tuple(self.queue),
            running=tuple(
                RunningInfo(j, e.start_s, e.req.gpu, e.req.cpu, e.req.mem_gb)  # type: ignore[arg-type]
                for j, e in self.running.items()
            ),
        )
