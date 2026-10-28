"""Discrete-event simulator (PRD §8). Owns the simulated clock and the event heap; talks to
datacentres only through `DatacentreClient`; hands policies a `SchedulerView` (PRD §8.7)."""

from __future__ import annotations

import copy
import heapq
from dataclasses import dataclass, field

from flipwise.carbon import ForecastStore, ForecastVintage, Truth
from flipwise.datacentre import DatacentreClient, InProcDatacentre
from flipwise.energy import PowerModel, emissions_kg, energy_kwh
from flipwise.errors import MigrationError, SimulationInvariantError
from flipwise.estimates import ProfileJob, UsageProfile, build_profile
from flipwise.models import (
    PENDING,
    DcConfig,
    DcState,
    Event,
    Job,
    JobState,
    Placement,
    Priority,
    Request,
)
from flipwise.planner import PlannerParams, Residuals
from flipwise.policies import Decision, Policy


@dataclass
class Scenario:
    name: str
    jobs: list[Job]
    dcs: list[DcConfig]
    forecast: ForecastStore
    truth: Truth
    power: PowerModel
    start_s: int
    end_s: int  # SIM_END
    params: PlannerParams = field(default_factory=PlannerParams)
    residuals: Residuals = field(default_factory=Residuals)
    scenario_hash: str = ""


@dataclass(frozen=True)
class JobInfo:
    """Scheduler-visible copy of a job: no actual runtime, no end time (PRD §8.7)."""

    job_id: str
    user: str
    arrival_s: int
    gpu_req: float
    cpu_req: float
    mem_req_gb: float
    r_q05_s: int
    r_q50_s: int
    r_q90_s: int
    r_q95_s: int
    deadline_s: int
    power_kw: float
    state: JobState
    dc_id: int | None
    release_slot: int | None
    start_s: int | None
    n_moves: int
    plan_score: float | None

    @property
    def request(self) -> Request:
        return Request(self.gpu_req, self.cpu_req, self.mem_req_gb)

    def r_q(self, q: str) -> int:
        return {"q05": self.r_q05_s, "q50": self.r_q50_s, "q90": self.r_q90_s, "q95": self.r_q95_s}[
            q
        ]


class SchedulerView:
    """Everything a policy may read. Built from simulator state; hidden fields never copied."""

    def __init__(self, sim: Simulator) -> None:
        self._sim = sim
        self.dcs: dict[int, DcConfig] = {d.dc_id: d for d in sim.scenario.dcs}
        self.params = sim.scenario.params
        self.residuals = sim.scenario.residuals
        self._profiles: dict[tuple, UsageProfile] = {}

    @property
    def now_s(self) -> int:
        return self._sim.now_s

    @property
    def forecast(self) -> ForecastVintage | None:
        return self._sim.vintage

    def job(self, job_id: str) -> JobInfo:
        return self._sim.job_info(job_id)

    def pending_jobs(self) -> list[JobInfo]:
        """Pending jobs in the tie order `(deadline_s, arrival_s, job_id)`."""
        infos = [self.job(j) for j in self._sim.pending_ids]
        return sorted(infos, key=lambda j: (j.deadline_s, j.arrival_s, j.job_id))

    def dc_state(self, dc_id: int) -> DcState:
        return self._sim.dc_state(dc_id)

    def profile(self, dc_id: int, q: str, exclude: str | None = None) -> UsageProfile:
        key = (dc_id, q, exclude, self._sim.dc_version[dc_id], self.now_s)
        prof = self._profiles.get(key)
        if prof is None:
            prof = self._build_profile(dc_id, q, exclude)
            if len(self._profiles) > 64:
                self._profiles.clear()
            self._profiles[key] = prof
        return prof

    def _build_profile(self, dc_id: int, q: str, exclude: str | None) -> UsageProfile:
        st = self.dc_state(dc_id)
        t = self.now_s
        running = [
            (Request(r.gpu_req, r.cpu_req, r.mem_req_gb), r.start_s, self.job(r.job_id).r_q(q))
            for r in st.running
        ]
        pending: list[ProfileJob] = []
        for jid in st.queue:
            if jid != exclude:
                j = self.job(jid)
                pending.append(ProfileJob(jid, j.request, t, j.r_q(q)))
        placed = sorted(
            (self.job(j) for j in self._sim.placed_at[dc_id] if j != exclude),
            key=lambda j: (j.release_slot, j.deadline_s, j.job_id),
        )
        for j in placed:
            pending.append(ProfileJob(j.job_id, j.request, max(t, j.release_slot), j.r_q(q)))
        return build_profile(st.cap, t, running, pending)

    def projected_start(self, dc_id: int, job: JobInfo, release_s: int, q: str) -> int | None:
        prof = self.profile(dc_id, q, exclude=job.job_id)
        return prof.earliest_fit(release_s, job.r_q(q), job.request)


@dataclass
class RunResult:
    jobs: list[Job]
    events: list[str]
    decisions: list[dict]
    scenario: Scenario
    policy: str


class Simulator:
    def __init__(
        self,
        scenario: Scenario,
        policy: Policy,
        clients: list[DatacentreClient] | None = None,
        debug: bool = True,
    ) -> None:
        self.scenario = scenario
        self.policy = policy
        self.debug = debug
        self.jobs: dict[str, Job] = {j.job_id: copy.copy(j) for j in scenario.jobs}
        if clients is None:
            clients = [InProcDatacentre() for _ in scenario.dcs]
        self.clients = {d.dc_id: c for d, c in zip(scenario.dcs, clients, strict=True)}
        for d in scenario.dcs:
            self.clients[d.dc_id].reset(d, scenario.scenario_hash)
        self.dc_version = {d.dc_id: 0 for d in scenario.dcs}
        self.placed_at: dict[int, set[str]] = {d.dc_id: set() for d in scenario.dcs}
        self.pending_ids: set[str] = set()
        self._states: dict[int, DcState] = {}
        self.now_s = scenario.start_s
        self.vintage: ForecastVintage | None = None
        self._heap: list[Event] = []
        self._seq = 0
        self.events: list[str] = []
        self.decisions: list[dict] = []
        self._touched: set[int] = set()
        self.view = SchedulerView(self)

    # ---- state helpers -------------------------------------------------------------------
    def job_info(self, job_id: str) -> JobInfo:
        j = self.jobs[job_id]
        return JobInfo(
            job_id=j.job_id,
            user=j.user,
            arrival_s=j.arrival_s,
            gpu_req=j.gpu_req,
            cpu_req=j.cpu_req,
            mem_req_gb=j.mem_req_gb,
            r_q05_s=j.r_q05_s,
            r_q50_s=j.r_q50_s,
            r_q90_s=j.r_q90_s,
            r_q95_s=j.r_q95_s,
            deadline_s=j.deadline_s,
            power_kw=self.scenario.power.power_kw(j.gpu_req, j.cpu_req),
            state=j.state,
            dc_id=j.dc_id,
            release_slot=j.release_slot,
            start_s=j.start_s if j.state in (JobState.RUNNING, JobState.COMPLETED) else None,
            n_moves=j.n_moves,
            plan_score=j.plan_score,
        )

    def dc_state(self, dc_id: int) -> DcState:
        st = self._states.get(dc_id)
        if st is None:
            st = self._states[dc_id] = self.clients[dc_id].state()
        return st

    def _touch(self, dc_id: int) -> None:
        self.dc_version[dc_id] += 1
        self._states.pop(dc_id, None)
        self._touched.add(dc_id)

    def _push(self, time_s: int, prio: Priority, job_id: str | None = None, **kw) -> None:
        heapq.heappush(self._heap, Event(time_s, int(prio), self._seq, prio.name, job_id, **kw))
        self._seq += 1

    # ---- placement -----------------------------------------------------------------------
    def _apply(self, d: Decision) -> None:
        job = self.jobs[d.job_id]
        rec = {
            "time_s": self.now_s,
            "job_id": d.job_id,
            "kind": d.kind,
            "from_dc": job.dc_id,
            "from_slot": job.release_slot,
            "to_dc": d.to.dc_id if d.to else None,
            "to_slot": d.to.release_slot if d.to else None,
            "S_a": d.s_a,
            "S_b": d.s_b,
            "reason": d.reason,
        }
        self.decisions.append(rec)
        if d.to is None:
            if d.kind == "REJECT":
                job.state = JobState.REJECTED
                self.pending_ids.discard(job.job_id)
            return
        self._place(job, d.to, d)

    def _place(self, job: Job, to: Placement, d: Decision) -> None:
        if job.state in (JobState.RUNNING, JobState.COMPLETED):
            raise MigrationError(f"job {job.job_id} is {job.state}; running jobs never move")
        if to.dc_id not in self.clients:
            raise SimulationInvariantError(f"unknown dc {to.dc_id}")
        if job.state == JobState.QUEUED:
            self.clients[job.dc_id].remove(self.now_s, job.job_id)  # type: ignore[index]
            self._touch(job.dc_id)  # type: ignore[arg-type]
        elif job.state == JobState.PLACED:
            self.placed_at[job.dc_id].discard(job.job_id)  # type: ignore[index]
            self._touch(job.dc_id)  # type: ignore[arg-type]
        if job.state in PENDING:
            job.n_moves += 1
        job.state = JobState.PLACED
        job.dc_id, job.release_slot = to.dc_id, to.release_slot
        job.placed_at_s = self.now_s
        job.plan_score = d.s_b
        job.plan_capture_utc = self.vintage.capture_utc if self.vintage else None
        job.deadline_risk = int(job.deadline_risk or d.deadline_risk)
        job.version += 1
        self.placed_at[to.dc_id].add(job.job_id)
        self.pending_ids.add(job.job_id)
        self._touch(to.dc_id)
        self._push(
            max(to.release_slot, self.now_s), Priority.JOB_RELEASE, job.job_id, version=job.version
        )

    # ---- event loop ----------------------------------------------------------------------
    def run(self) -> RunResult:
        sc = self.scenario
        for c in sc.forecast.captures:
            if sc.start_s <= c <= sc.end_s:
                self._push(c, Priority.CARBON_UPDATE, payload=c)
        order = sorted(self.jobs.values(), key=lambda j: (j.arrival_s, j.deadline_s, j.job_id))
        for j in order:
            self._push(j.arrival_s, Priority.JOB_ARRIVAL, j.job_id)
        for j in order:
            self._push(j.deadline_s, Priority.DEADLINE, j.job_id)
        self._push(sc.end_s, Priority.SIM_END)
        # Vintage visible at start: the latest capture at or before the start time.
        first = sc.forecast.latest_capture(sc.start_s - 1)
        if first is not None:
            self.vintage = sc.forecast.at(first)

        while self._heap:
            ev = heapq.heappop(self._heap)
            if ev.kind == "JOB_RELEASE" and ev.version != self.jobs[ev.job_id].version:
                continue  # stale after a re-placement (R-SIM-5)
            if ev.time_s < self.now_s:
                raise SimulationInvariantError(f"time went backwards at {ev}")
            self.now_s = ev.time_s
            self.events.append(f"{ev.time_s},{ev.priority},{ev.seq},{ev.kind},{ev.job_id or ''}")
            if ev.kind == "SIM_END":
                break
            self._handle(ev)
            self._dispatch()
            if self.debug:
                self._check_invariants()
            if all(j.state in (JobState.COMPLETED, JobState.REJECTED) for j in self.jobs.values()):
                break
        return RunResult(
            list(self.jobs.values()), self.events, self.decisions, sc, self.policy.name
        )

    def _handle(self, ev: Event) -> None:
        if ev.kind == "CARBON_UPDATE":
            self.vintage = self.scenario.forecast.at(ev.payload)  # type: ignore[arg-type]
            for d in self.policy.on_carbon_update(self.view):
                self._apply(d)
        elif ev.kind == "JOB_COMPLETE":
            job = self.jobs[ev.job_id]  # type: ignore[index]
            self.clients[job.dc_id].complete(self.now_s, job.job_id)  # type: ignore[index]
            job.state = JobState.COMPLETED
            self._touch(job.dc_id)  # type: ignore[arg-type]
        elif ev.kind == "JOB_ARRIVAL":
            d = self.policy.on_arrival(self.view, ev.job_id)  # type: ignore[arg-type]
            self._apply(
                Decision(
                    ev.job_id,
                    d.kind,
                    d.to,
                    d.s_a,
                    d.s_b,
                    d.reason,  # type: ignore[arg-type]
                    d.deadline_risk,
                )
            )
        elif ev.kind == "JOB_RELEASE":
            job = self.jobs[ev.job_id]  # type: ignore[index]
            self.placed_at[job.dc_id].discard(job.job_id)  # type: ignore[index]
            self.clients[job.dc_id].enqueue(  # type: ignore[index]
                self.now_s, job.job_id, job.request, job.runtime_actual_s
            )
            job.state = JobState.QUEUED
            self._touch(job.dc_id)  # type: ignore[arg-type]
        # DEADLINE is diagnostic only; PERIODIC_TICK arrives with the periodic policy.

    def _dispatch(self) -> None:
        for dc_id in sorted(self._touched):
            started = self.clients[dc_id].dispatch(self.now_s)
            if started:
                self._touch(dc_id)
            for s in started:
                job = self.jobs[s.job_id]
                job.state, job.start_s, job.end_s = JobState.RUNNING, s.start_s, s.end_s
                self.pending_ids.discard(job.job_id)
                self._push(s.end_s, Priority.JOB_COMPLETE, job.job_id)
        self._touched.clear()

    def _check_invariants(self) -> None:
        for dc_id in self.clients:
            st = self.dc_state(dc_id)
            if not st.used.fits_in(st.cap):
                raise SimulationInvariantError(f"overbooking at dc {dc_id} t={self.now_s}")
            for jid in st.queue:
                if self.jobs[jid].state != JobState.QUEUED or self.jobs[jid].dc_id != dc_id:
                    raise SimulationInvariantError(f"queue/state mismatch for {jid}")
            for r in st.running:
                if self.jobs[r.job_id].state != JobState.RUNNING:
                    raise SimulationInvariantError(f"running/state mismatch for {r.job_id}")


def job_outcome(job: Job, scenario: Scenario) -> dict:
    """Evaluator-side outcome: actual start and runtime against truth (R-EN-2)."""
    dc = {d.dc_id: d for d in scenario.dcs}.get(job.dc_id)  # type: ignore[arg-type]
    done = job.state == JobState.COMPLETED
    row: dict = {"energy_kwh": None, "kg_co2": None}
    if done and dc is not None:
        p = scenario.power.power_kw(job.gpu_req, job.cpu_req)
        row["energy_kwh"] = energy_kwh(p, job.runtime_actual_s, dc.pue)
        row["kg_co2"] = emissions_kg(
            p,
            job.start_s,  # type: ignore[arg-type]
            job.runtime_actual_s,
            lambda k: scenario.truth.get(dc.region_id, k),
            dc.pue,
        )
    return row
