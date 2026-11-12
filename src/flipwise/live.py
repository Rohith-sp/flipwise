"""Live demo mode (PRD §13.6, D60): the simulator paced by the wall clock, several policies side
by side, jobs submitted while it runs, and a JSON API for a UI.

It is for showing the system, never for results: submitted jobs and wall-clock pacing make a live
session unrepeatable, so nothing here writes to `results/` or feeds `compare`. The research path
(`Simulator.run`) is unchanged: live mode only decides *when* to call `Simulator.advance`, never
*what* an event does, and every policy still sees only its `SchedulerView` (§8.7).

One policy (the first) may drive real datacentre services (`--mode remote`): its messages to them
are the "communication" a UI can show. The others run their datacentres in-process, because each
service holds the state of one simulation.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
from collections import Counter, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pandas as pd

from flipwise.config import policy_params
from flipwise.datacentre import InProcDatacentre
from flipwise.errors import CarbonDataError, ConfigError
from flipwise.models import SLOT_S, Job, JobState, floor_to_slot
from flipwise.policies import make_policy
from flipwise.scenario import build_replicate, dev_replicate, load_scenario
from flipwise.simulator import Scenario, Simulator, job_outcome
from flipwise.webstatic import read_static

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
REGION_NAMES = {1: "Delhi NCR (Northern grid)", 2: "Mumbai (Western grid)",
                3: "Chennai (Southern grid)", 4: "Eastern grid"}  # fmt: skip
MAX_SKIP_H = 7 * 24
MESSAGE_LOG = 200
LANE_CAP = 60
_CHECK_KINDS = {"KEEP", "MOVE", "SCREEN_FAIL", "THROTTLED", "RESCUE", "RESCUE_NOOP"}
STREAM_BUFFER = 2000
LATENCY_WINDOW = 50
KEEPALIVE_S = 15.0
RESULTS_CSV = Path("docs/test_results/summary.csv")
# kgCO2 under the D58 power bracket for the same test runs (D59, F25); optional.
BRACKET_CSVS = {
    "kg_co2_measured": Path("docs/power_bracket/test_measured_summary.csv"),
    "kg_co2_nameplate": Path("docs/power_bracket/test_nameplate_summary.csv"),
}


def _ist(t_s: int) -> str:
    return dt.datetime.fromtimestamp(t_s, IST).strftime("%a %d %b %Y %H:%M IST")


def _truth(sc: Scenario, region_id: int, slot: int) -> float | None:
    """Display only: a slot past the end of the truth table shows as missing, not as an error."""
    try:
        return sc.truth.get(region_id, slot)
    except CarbonDataError:
        return None


def _round(x, nd: int = 4):
    return None if x is None else round(float(x), nd)


class _Feed:
    """Bounded, id-numbered event buffer for the SSE stream. A client remembers the last id it
    saw, so slow clients lose old events instead of slowing the simulation down."""

    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.events: deque = deque(maxlen=STREAM_BUFFER)
        self.last_id = 0

    def publish(self, kind: str, payload: dict) -> None:
        with self.cond:
            self.last_id += 1
            self.events.append((self.last_id, kind, payload))
            self.cond.notify_all()

    def after(self, last_id: int, timeout_s: float) -> list[tuple[int, str, dict]]:
        with self.cond:
            if self.last_id <= last_id:
                self.cond.wait(timeout_s)
            return [e for e in self.events if e[0] > last_id]


class _MessageSink(deque):
    """The message log shown in /status; every append is also pushed to the stream."""

    def __init__(self, feed: _Feed) -> None:
        super().__init__(maxlen=MESSAGE_LOG)
        self.feed = feed

    def append(self, m) -> None:  # type: ignore[override]
        super().append(m)
        self.feed.publish("message", {**m, "t_ist": _ist(m["t"])})


class TimedClient:
    """Counts calls and times them, for /health. Display only: the latencies never feed back
    into the simulation (wall time must not touch simulation logic)."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.url = getattr(inner, "url", None)
        self.requests = 0
        self.latencies_ms: deque = deque(maxlen=LATENCY_WINDOW)

    def _timed(self, name: str, *args):
        t0 = time.perf_counter()
        try:
            return getattr(self.inner, name)(*args)
        finally:
            self.requests += 1
            self.latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    def reset(self, cfg, scenario_hash):
        return self._timed("reset", cfg, scenario_hash)

    def enqueue(self, t_s, job_id, req, runtime_actual_s):
        return self._timed("enqueue", t_s, job_id, req, runtime_actual_s)

    def remove(self, t_s, job_id):
        return self._timed("remove", t_s, job_id)

    def dispatch(self, t_s):
        return self._timed("dispatch", t_s)

    def complete(self, t_s, job_id):
        return self._timed("complete", t_s, job_id)

    def state(self):
        return self._timed("state")


class LoggedClient:
    """Records every call a simulation makes to one datacentre, so the UI can show the messages
    between scheduler and datacentres. Only for display; it changes nothing it forwards."""

    def __init__(self, inner, dc_id: int, sink: deque, clock) -> None:
        self.inner, self.dc_id, self.sink, self.clock = inner, dc_id, sink, clock

    def _log(self, op: str, job_id: str | None = None, detail: str | None = None) -> None:
        self.sink.append({"t": self.clock(), "dc_id": self.dc_id, "op": op, "job_id": job_id,
                          "detail": detail})  # fmt: skip

    def reset(self, cfg, scenario_hash):
        return self.inner.reset(cfg, scenario_hash)

    def enqueue(self, t_s, job_id, req, runtime_actual_s):
        self._log("enqueue", job_id)
        return self.inner.enqueue(t_s, job_id, req, runtime_actual_s)

    def remove(self, t_s, job_id):
        self._log("remove", job_id)
        return self.inner.remove(t_s, job_id)

    def dispatch(self, t_s):
        started = self.inner.dispatch(t_s)
        if started:
            self._log("dispatch", detail="started " + ",".join(s.job_id for s in started))
        return started

    def complete(self, t_s, job_id):
        self._log("complete", job_id)
        return self.inner.complete(t_s, job_id)

    def state(self):
        return self.inner.state()


class LiveSession:
    """Several policies stepped together on one simulated clock."""

    def __init__(
        self,
        scenario_factory,
        cfg: dict | None,
        policies: list[str],
        speed: float = 1800.0,
        remote_clients: list | None = None,
        replicates: list[tuple[str, object]] | None = None,
    ) -> None:
        """`replicates` is a list of (name, build) for a validation session: each `build()` gives
        the next shared scenario and is called outside the lock (it takes seconds)."""
        if not policies:
            raise ConfigError("live: give at least one policy")
        if replicates and remote_clients:
            raise ConfigError("live: --split validation cannot drive remote services")
        self.lock = threading.RLock()
        self.cfg = cfg
        self.policies = policies
        self.feed = _Feed()
        self.messages: deque = _MessageSink(self.feed)
        self.remote_clients = remote_clients
        self.remote_policy = policies[0] if remote_clients else None
        self.replicates = replicates or []
        self.rep_index = 0
        self.building = False
        self.notes: list[str] = []
        self.speed = float(speed)
        self.paused = False
        self.closed = threading.Event()  # ends open SSE streams on shutdown
        scenario = self.replicates[0][1]() if self.replicates else scenario_factory()
        self._load(scenario)

    def _load(self, scenario: Scenario) -> None:
        """Install a (new) shared scenario: fresh simulators for every policy and cleared
        per-run caches. Called at start and when a validation replicate ends."""
        self.timed: list[TimedClient] = []
        self.history: dict[str, list[dict]] = {p: [] for p in self.policies}
        self._pending: dict[str, list[str]] = {}  # jobs not yet completed, per policy
        self._outcome: dict[str, dict[str, tuple[int, float, bool]]] = {
            p: {} for p in self.policies
        }
        self._seen_decisions: dict[str, int] = {p: 0 for p in self.policies}
        self._act: dict[str, dict[int, Counter]] = {p: {} for p in self.policies}
        self._act_seen: dict[str, int] = {p: 0 for p in self.policies}
        self.sims: dict[str, Simulator] = {}
        for i, name in enumerate(self.policies):
            params = policy_params(self.cfg, name) if self.cfg is not None else {}
            inner = self.remote_clients if (i == 0 and self.remote_clients) else None
            inner = inner or [InProcDatacentre() for _ in scenario.dcs]
            clients = inner
            if i == 0:  # the messages and health shown are those of the first policy
                self.timed = [TimedClient(c) for c in inner]
                clients = [LoggedClient(c, d.dc_id, self.messages, self._now)
                           for c, d in zip(self.timed, scenario.dcs, strict=True)]  # fmt: skip
            sim = Simulator(scenario, make_policy(name, **params), clients, debug=False)
            sim.keep_running = True
            sim.start()
            self.sims[name] = sim
            self._pending[name] = list(sim.jobs)
        self.start_s, self.end_s = scenario.start_s, scenario.end_s
        self._sim_base = float(self.start_s)
        self._wall_base = time.monotonic()
        if self.user_jobs_list():
            self.notes.append(f"user jobs cleared when replicate {self.rep_index + 1} started")
        self.user_jobs: list[str] = []
        self.submitted: dict[str, dict] = {}
        self._next_snap_s = floor_to_slot(self.start_s) + SLOT_S
        self._snapshot(self.start_s)

    def user_jobs_list(self) -> list[str]:
        return getattr(self, "user_jobs", [])

    # ---- clock -----------------------------------------------------------------------------
    def _now(self) -> int:
        return self.sims[self.policies[0]].now_s

    def target_s(self) -> float:
        if self.paused:
            return self._sim_base
        return self._sim_base + (time.monotonic() - self._wall_base) * self.speed

    def _rebase(self) -> None:
        self._sim_base = min(self.target_s(), float(self.end_s))
        self._wall_base = time.monotonic()

    def step(self) -> bool:
        """Advance every policy to the paced target time; True once all have finished."""
        with self.lock:
            # One slot at a time: when the simulation runs slower than the paced clock, the
            # worker must not hold the lock for minutes and starve the API.
            goal = min(self.target_s(), float(self.end_s))
            done = self._advance_all(min(goal, float(self._next_snap_s)))
            done = done and goal >= self.end_s
            more = done and self.rep_index + 1 < len(self.replicates) and not self.building
            if more:
                self.building = True
        if more:
            self._next_replicate()
            return False
        return done and self.rep_index + 1 >= len(self.replicates)

    def _next_replicate(self) -> None:
        try:
            scenario = self.replicates[self.rep_index + 1][1]()  # seconds; the lock is free
            with self.lock:
                self.rep_index += 1
                self._load(scenario)
        finally:
            self.building = False

    def _advance_all(self, target: float) -> bool:
        """Advance every policy to `target`, stopping at each slot boundary on the way so a long
        skip still yields one history snapshot per half hour."""
        while self._next_snap_s <= target:
            for sim in self.sims.values():
                sim.advance(self._next_snap_s)
            self._snapshot(self._next_snap_s)
            self._next_snap_s += SLOT_S
        done = all([sim.advance(target) for sim in self.sims.values()])
        self._publish_decisions()
        return done

    def control(self, body: dict) -> dict:
        with self.lock:
            self._rebase()
            if "speed" in body:
                speed = float(body["speed"])
                if speed <= 0:
                    raise ValueError("speed must be > 0 (simulated seconds per real second)")
                self.speed = speed
            if "paused" in body:
                self.paused = bool(body["paused"])
            if "skip_hours" in body:
                hours = float(body["skip_hours"])
                if not 0 < hours <= MAX_SKIP_H:
                    raise ValueError(f"skip_hours must be in (0, {MAX_SKIP_H}]")
                # The time skip: replay history up to the new time as fast as possible.
                self._sim_base = min(self._sim_base + hours * 3600, float(self.end_s))
                self._advance_all(self._sim_base)
            return self.clock()

    def clock(self) -> dict:
        now = self._now()
        return {"sim_time_s": now, "sim_time": _ist(now), "start": _ist(self.start_s),
                "end": _ist(self.end_s), "speed": self.speed, "paused": self.paused,
                "finished": all(s.finished for s in self.sims.values())
                and self.rep_index + 1 >= len(self.replicates),
                "replicate": self.replicate_info()}  # fmt: skip

    def replicate_info(self) -> dict | None:
        if not self.replicates:
            return None
        return {"name": self.replicates[self.rep_index][0], "index": self.rep_index + 1,
                "total": len(self.replicates), "building": self.building,
                "notes": self.notes[-5:]}  # fmt: skip

    # ---- jobs ------------------------------------------------------------------------------
    def submit(self, body: dict) -> dict:
        """A user job, given to every policy at the same simulated moment."""
        try:
            gpus = float(body.get("gpus", 1))
            cpus = float(body.get("cpus", 4))
            mem = float(body.get("mem_gb", 16))
            runtime_h = float(body["runtime_h"])
            actual_h = float(body.get("actual_runtime_h", runtime_h))
            deadline_h = float(body.get("deadline_h", 4 + 2 * runtime_h))
            gpu_type = str(body.get("gpu_type", "V100"))
            util = float(body.get("gpu_util", 1.0))
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"bad job: {e}") from None
        if min(gpus, cpus, mem) < 0 or runtime_h <= 0 or actual_h <= 0 or deadline_h <= 0:
            raise ValueError("gpus, cpus and mem_gb must be >= 0; times must be > 0")
        if not 0 <= util <= 1:
            raise ValueError("gpu_util must be between 0 and 1")
        with self.lock:
            dc0 = self.sims[self.policies[0]].scenario.dcs[0]
            if gpus > dc0.cap_gpu or cpus > dc0.cap_cpu or mem > dc0.cap_mem_gb:
                raise ValueError(f"job too large: a datacentre has {dc0.cap_gpu:.0f} GPUs, "
                                 f"{dc0.cap_cpu:.0f} cores, {dc0.cap_mem_gb:.0f} GB")  # fmt: skip
            job_id = f"USER-{len(self.user_jobs) + 1}"
            now = self._now()
            r = int(runtime_h * 3600)
            for sim in self.sims.values():
                sim.add_job(Job(
                    job_id=job_id, user="__live__", arrival_s=now, gpu_req=gpus, cpu_req=cpus,
                    mem_req_gb=mem, r_q05_s=r, r_q50_s=r, r_q90_s=r, r_q95_s=r,
                    deadline_s=now + int(deadline_h * 3600),
                    runtime_actual_s=int(actual_h * 3600), gpu_type=gpu_type,
                    gpu_used=gpus * util, cpu_used=cpus,
                ))  # fmt: skip
            for name in self.sims:
                self._pending[name].append(job_id)
            self.user_jobs.append(job_id)
            self.submitted[job_id] = {"submitted_at": _ist(now), **body}
            return {"job_id": job_id, "submitted_at": _ist(now)}

    def _job_view(self, sim: Simulator, job_id: str) -> dict:
        job = sim.jobs[job_id]
        out = {"state": str(job.state), "dc_id": job.dc_id,
               "datacentre": self._dc_name(sim, job.dc_id),
               "release": None if job.release_slot is None else _ist(job.release_slot),
               "start": None if job.start_s is None else _ist(job.start_s),
               "end": None if job.end_s is None or job.state != JobState.COMPLETED
               else _ist(job.end_s),
               "deadline": _ist(job.deadline_s), "moves": job.n_moves,
               "estimated_kg": _round(job.plan_score)}  # fmt: skip
        if job.state == JobState.COMPLETED:
            o = job_outcome(job, sim.scenario)
            out["kg_co2"] = _round(o["kg_co2"])
            out["deadline_missed"] = bool(job.end_s > job.deadline_s)  # type: ignore[operator]
        out["decisions"] = [self._decision(sim, d) for d in sim.decisions if d["job_id"] == job_id]
        return out

    def job(self, job_id: str) -> dict:
        with self.lock:
            if job_id not in self.sims[self.policies[0]].jobs:
                raise KeyError(job_id)
            return {"job_id": job_id, "submitted": self.submitted.get(job_id),
                    "by_policy": {p: self._job_view(s, job_id)
                                  for p, s in self.sims.items()}}  # fmt: skip

    # ---- history and stream ----------------------------------------------------------------
    def _publish_decisions(self) -> None:
        for name, sim in self.sims.items():
            seen = self._seen_decisions[name]
            for d in sim.decisions[seen:]:
                self.feed.publish("decision", {"policy": name, **self._decision(sim, d)})
            self._seen_decisions[name] = len(sim.decisions)

    def _settle(self, name: str) -> None:
        """Cache the outcome of each newly completed job once, so a snapshot costs a scan of
        the not-yet-completed jobs, not a re-evaluation of every finished one."""
        sim, cache = self.sims[name], self._outcome[name]
        still = []
        for jid in self._pending[name]:
            j = sim.jobs[jid]
            if j.state == JobState.COMPLETED:
                kg = job_outcome(j, sim.scenario)["kg_co2"]
                cache[jid] = (j.dc_id, kg, bool(j.end_s > j.deadline_s))  # type: ignore[operator]
            else:
                still.append(jid)
        self._pending[name] = still

    def _snapshot(self, t_s: float) -> None:
        for name, sim in self.sims.items():
            self._settle(name)
            cache = self._outcome[name]
            kinds = Counter(d["kind"] for d in sim.decisions)
            stats = getattr(sim.policy, "stats", None)
            per_dc_kg: Counter = Counter()
            for dc_id, kg, _ in cache.values():
                per_dc_kg[dc_id] += kg
            slot = floor_to_slot(int(t_s))
            dcs = []
            for d in sim.scenario.dcs:
                st = sim.clients[d.dc_id].state()
                f = sim.vintage.get(d.region_id, slot) if sim.vintage is not None else None
                dcs.append({"dc_id": d.dc_id, "gpus_used": _round(st.used.gpu, 1),
                            "running": len(st.running), "queued": len(st.queue),
                            "kg_co2": _round(per_dc_kg[d.dc_id], 3),
                            "forecast_g_per_kwh": _round(f.g_per_kwh if f else None, 1),
                            "actual_g_per_kwh": _round(_truth(sim.scenario, d.region_id, slot), 1)
                            })  # fmt: skip
            self.history[name].append({
                "t": int(t_s), "time": _ist(int(t_s)),
                "kg_co2": _round(sum(v[1] for v in cache.values()), 3),
                "moves": kinds.get("MOVE", 0), "full_rescores": getattr(stats, "stage2_calls", 0),
                "screen_skips": kinds.get("SCREEN_FAIL", 0), "jobs_completed": len(cache),
                "deadline_misses": sum(1 for v in cache.values() if v[2]), "dcs": dcs,
            })  # fmt: skip

    def get_history(self, since_s: int | None = None) -> dict:
        with self.lock:
            lo = -1 if since_s is None else since_s
            return {
                "since": since_s,
                "policies": {p: [h for h in hs if h["t"] > lo] for p, hs in self.history.items()},
            }

    def health(self) -> dict:
        with self.lock:
            return {"policy": self.policies[0], "datacentres": [
                {"dc_id": i, "url": c.url or "in-process", "remote": c.url is not None,
                 "requests": c.requests,
                 "mean_latency_ms": _round(sum(c.latencies_ms) / len(c.latencies_ms), 3)
                 if c.latencies_ms else None}
                for i, c in enumerate(self.timed)]}  # fmt: skip

    # ---- views -----------------------------------------------------------------------------
    @staticmethod
    def _dc_name(sim: Simulator, dc_id: int | None) -> str | None:
        if dc_id is None:
            return None
        region = {d.dc_id: d.region_id for d in sim.scenario.dcs}[dc_id]
        return REGION_NAMES.get(region, f"region {region}")

    def _decision(self, sim: Simulator, d: dict) -> dict:
        return {"time": _ist(d["time_s"]), "time_s": d["time_s"],
                "job_id": d["job_id"], "kind": d["kind"],
                "from": self._dc_name(sim, d["from_dc"]), "to": self._dc_name(sim, d["to_dc"]),
                "to_slot": None if d["to_slot"] is None else _ist(d["to_slot"]),
                "S_a_kg": _round(d["S_a"]), "S_b_kg": _round(d["S_b"]), "LB_kg": _round(d["LB"]),
                "w_ab_kg": _round(d["w_ab"]), "g_min_kg": _round(d["g_min"]),
                "theta": d["theta_eff"], "reason": d["reason"]}  # fmt: skip

    def _totals(self, sim: Simulator) -> dict:
        done = [j for j in sim.jobs.values() if j.state == JobState.COMPLETED]
        kg = sum(job_outcome(j, sim.scenario)["kg_co2"] for j in done)
        missed = sum(1 for j in done if j.end_s > j.deadline_s)  # type: ignore[operator]
        kinds = Counter(d["kind"] for d in sim.decisions)
        stats = getattr(sim.policy, "stats", None)
        return {"kg_co2_so_far": _round(kg, 3), "jobs_arrived": sum(
                    1 for j in sim.jobs.values() if j.state != JobState.NOT_ARRIVED),
                "jobs_completed": len(done), "deadline_misses": missed,
                "moves": kinds.get("MOVE", 0), "full_rescores": getattr(stats, "stage2_calls", 0),
                "screen_skips": kinds.get("SCREEN_FAIL", 0), "decisions": dict(kinds)}  # fmt: skip

    def _carbon_now(self, sim: Simulator) -> list[dict]:
        now, sc = sim.now_s, sim.scenario
        slot = floor_to_slot(now)
        out = []
        for d in sc.dcs:
            f = sim.vintage.get(d.region_id, slot) if sim.vintage is not None else None
            out.append({"dc_id": d.dc_id, "region": REGION_NAMES.get(d.region_id),
                        "forecast_g_per_kwh": _round(f.g_per_kwh if f else None, 1),
                        "actual_g_per_kwh": _round(_truth(sc, d.region_id, slot), 1),
                        "forecast_next_6h": [_round(v.g_per_kwh, 1) if v else None for v in (
                            sim.vintage.get(d.region_id, slot + i * SLOT_S)
                            if sim.vintage is not None else None for i in range(12))]})  # fmt: skip
        return out

    def status(self) -> dict:
        with self.lock:
            main = self.sims[self.policies[0]]
            return {"clock": self.clock(), "policies": self.policies,
                    "replicate": self.replicate_info(),
                    "remote_policy": self.remote_policy, "carbon": self._carbon_now(main),
                    "compare": {p: self._totals(s) for p, s in self.sims.items()},
                    "user_jobs": self.user_jobs,
                    "recent_decisions": {p: [self._decision(s, d) for d in s.decisions[-15:]]
                                         for p, s in self.sims.items()},
                    "recent_messages": [{**m, "t": _ist(m["t"])}
                                        for m in list(self.messages)[-30:]]}  # fmt: skip

    def dc(self, dc_id: int, policy: str | None = None) -> dict:
        with self.lock:
            name = policy or self.policies[0]
            if name not in self.sims:
                raise KeyError(name)
            sim = self.sims[name]
            if dc_id not in sim.clients:
                raise KeyError(dc_id)
            st = sim.clients[dc_id].state()  # remote mode: a real request to the service
            dcfg = {d.dc_id: d for d in sim.scenario.dcs}[dc_id]
            here = [j for j in sim.jobs.values() if j.dc_id == dc_id]
            done = [j for j in here if j.state == JobState.COMPLETED]
            carbon = next(c for c in self._carbon_now(sim) if c["dc_id"] == dc_id)
            return {"dc_id": dc_id, "name": self._dc_name(sim, dc_id), "policy": name,
                    "remote": name == self.remote_policy, "time": _ist(sim.now_s),
                    "capacity": {"gpus": _round(st.cap.gpu, 1), "cpus": _round(st.cap.cpu, 1),
                                 "mem_gb": _round(st.cap.mem_gb, 1)},
                    "used": {"gpus": _round(st.used.gpu, 1), "cpus": _round(st.used.cpu, 1),
                             "mem_gb": _round(st.used.mem_gb, 1)},
                    "gpu_utilisation": _round(st.used.gpu / dcfg.cap_gpu if dcfg.cap_gpu else 0, 3),
                    "running": len(st.running), "queue_length": len(st.queue),
                    "queue_head": list(st.queue[:10]),
                    "planned_not_released": sum(1 for j in here if j.state == JobState.PLACED),
                    "completed": len(done),
                    "kg_co2_so_far": _round(sum(job_outcome(j, sim.scenario)["kg_co2"]
                                                for j in done), 3),
                    "carbon": carbon,
                    "user_jobs_here": [j.job_id for j in here
                                       if j.job_id in self.submitted]}  # fmt: skip

    # ---- re-plan activity and per-datacentre job lists -----------------------------------------
    def activity(self, policy: str, since_s: int | None = None) -> list[dict]:
        """Re-plan work per forecast update (CARBON_UPDATE), grouped from the decision log. The
        grouping is cached and extended incrementally; only new decisions are read."""
        with self.lock:
            if policy not in self.sims:
                raise KeyError(policy)
            sim, cache = self.sims[policy], self._act[policy]
            caps = {c for c in sim.scenario.forecast.captures if self.start_s <= c <= self.end_s}
            for d in sim.decisions[self._act_seen[policy] :]:
                if d["time_s"] in caps and d["kind"] in _CHECK_KINDS:
                    kind = d["kind"]
                    if kind == "KEEP" and d["S_b"] is None:
                        kind = "OTHER"  # kept without a re-score (no carbon incumbent)
                    elif kind.startswith("RESCUE"):
                        kind = "RESCUE"
                    cache.setdefault(d["time_s"], Counter())[kind] += 1
            self._act_seen[policy] = len(sim.decisions)
            lo = -1 if since_s is None else since_s
            out = []
            for t in sorted(c for c in caps if lo < c <= sim.now_s):
                c = cache.get(t, Counter())
                out.append({"t": t, "time": _ist(t), "checked": sum(c.values()),
                            "screen_skipped": c["SCREEN_FAIL"], "rescored_kept": c["KEEP"],
                            "moved": c["MOVE"], "rescued": c["RESCUE"],
                            "throttled": c["THROTTLED"]})  # fmt: skip
            return out

    def lanes(self, policy: str | None = None) -> dict:
        """Planned, queued and running jobs at every datacentre, for one policy."""
        with self.lock:
            name = policy or self.policies[0]
            if name not in self.sims:
                raise KeyError(name)
            sim = self.sims[name]

            def chip(job_id: str) -> dict:
                j = sim.jobs[job_id]
                return {"job_id": job_id[:8], "gpus": j.gpu_req,
                        "user_job": job_id in self.submitted, "moved": j.n_moves > 0}  # fmt: skip

            def cap(ids: list[str]) -> dict:
                return {"total": len(ids), "jobs": [chip(i) for i in ids[:LANE_CAP]]}

            planned: dict[int, list[str]] = {d.dc_id: [] for d in sim.scenario.dcs}
            for j in sim.jobs.values():
                if j.state == JobState.PLACED and j.dc_id in planned:
                    planned[j.dc_id].append(j.job_id)
            out = []
            for d in sim.scenario.dcs:
                st = sim.clients[d.dc_id].state()
                out.append({"dc_id": d.dc_id, "name": self._dc_name(sim, d.dc_id),
                            "planned": cap(sorted(planned[d.dc_id])),
                            "queued": cap(list(st.queue)),
                            "running": cap([r.job_id for r in st.running]),
                            "completed": sum(1 for j in sim.jobs.values()
                                             if j.dc_id == d.dc_id
                                             and j.state == JobState.COMPLETED)})  # fmt: skip
            return {"policy": name, "time": _ist(sim.now_s), "datacentres": out}


def scenario_factory(cfg: dict | None, scenario_dir: Path | None, seed: int = 0):
    """The scenario every policy runs on, built once and shared: a simulation copies the jobs
    it changes and reads the rest, as consecutive runs in `compare` already do (R-FAIR-1)."""
    if scenario_dir is None and cfg is None:
        raise ConfigError("live: give --config or --scenario")
    built: list[Scenario] = []

    def factory() -> Scenario:
        if not built:
            if scenario_dir is not None:
                built.append(load_scenario(scenario_dir))
            else:
                built.append(build_replicate(cfg, dev_replicate(cfg), seed))  # type: ignore[arg-type]
        return built[0]

    return factory


def results_summary(path: Path | None = None) -> tuple[int, dict]:
    """Test-period results per policy (D57), for the dashboard's reference panel."""
    csv_path = path or RESULTS_CSV
    if not csv_path.is_file():
        return 404, {
            "error": "NOT_FOUND",
            "message": f"{csv_path} not found: run from the "
            "repository root after the test results exist (docs/test_results/)",
        }
    df = pd.read_csv(csv_path)
    cols = [c for c in ("kg_co2", "miss_rate", "stage2_calls", "moves") if c in df.columns]
    agg = df.groupby("policy")[cols].mean()
    agg["replicates"] = df.groupby("policy").size()
    for key, bracket_path in BRACKET_CSVS.items():
        if path is None and bracket_path.is_file():
            agg[key] = pd.read_csv(bracket_path).groupby("policy")["kg_co2"].mean()
    return 200, {"source": str(csv_path), "aggregate": "mean over replicates",
                 "policies": {p: {k: _round(v, 6) for k, v in row.items()}
                              for p, row in agg.iterrows()}}  # fmt: skip


def make_handler(session: LiveSession):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict | list) -> None:
            data = json.dumps(body, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")  # the UI may be on another port
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self) -> None:  # noqa: N802 (http.server's naming)
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _static(self, rel: str) -> None:
            found = read_static(rel)
            if found is None:
                self._send(404, {"error": "NOT_FOUND", "path": self.path})
                return
            data, ctype = found
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            last = session.feed.last_id  # follow from the newest event
            quiet_since = time.monotonic()
            try:
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while not session.closed.is_set():
                    events = session.feed.after(last, 1.0)
                    for eid, kind, payload in events:
                        data = json.dumps(payload, default=str)
                        self.wfile.write(f"id: {eid}\nevent: {kind}\ndata: {data}\n\n".encode())
                        last = eid
                    if events:
                        quiet_since = time.monotonic()
                    elif time.monotonic() - quiet_since >= KEEPALIVE_S:
                        self.wfile.write(b": keep-alive\n\n")
                        quiet_since = time.monotonic()
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return  # the browser went away

        def do_GET(self) -> None:  # noqa: N802
            url = urlsplit(self.path)
            parts = [p for p in url.path.split("/") if p]
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if parts == []:
                    self._static("index.html")
                elif parts[0] == "static" and len(parts) > 1:
                    self._static("/".join(parts[1:]))
                elif parts == ["status"]:
                    self._send(200, session.status())
                elif parts == ["clock"]:
                    self._send(200, session.clock())
                elif parts == ["health"]:
                    self._send(200, session.health())
                elif parts == ["history"]:
                    since = query.get("since")
                    self._send(200, session.get_history(int(since) if since else None))
                elif parts == ["stream"]:
                    self._stream()
                elif parts == ["results"]:
                    code, body = results_summary()
                    self._send(code, body)
                elif parts == ["activity"]:
                    since = query.get("since")
                    self._send(
                        200,
                        session.activity(
                            query.get("policy") or session.policies[0],
                            int(since) if since else None,
                        ),
                    )
                elif parts == ["lanes"]:
                    self._send(200, session.lanes(query.get("policy")))
                elif len(parts) == 2 and parts[0] == "dc":
                    self._send(200, session.dc(int(parts[1]), query.get("policy")))
                elif parts == ["jobs"]:
                    self._send(200, {"user_jobs": session.user_jobs})
                elif len(parts) == 2 and parts[0] == "jobs":
                    self._send(200, session.job(parts[1]))
                else:
                    self._send(404, {"error": "NOT_FOUND", "path": self.path})
            except (KeyError, ValueError) as e:
                self._send(404, {"error": "NOT_FOUND", "message": str(e)})

        def do_POST(self) -> None:  # noqa: N802
            try:
                body = self._body()
                if self.path == "/jobs":
                    self._send(201, session.submit(body))
                elif self.path == "/control":
                    self._send(200, session.control(body))
                else:
                    self._send(404, {"error": "NOT_FOUND", "path": self.path})
            except (ValueError, json.JSONDecodeError) as e:
                self._send(400, {"error": "BAD_REQUEST", "message": str(e)})

        def log_message(self, *args) -> None:  # quiet: the UI polls often
            pass

    return Handler


def serve(session: LiveSession, host: str = "127.0.0.1", port: int = 8100) -> None:
    """Run the paced simulation in a thread and the API in the foreground until Ctrl-C."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            session.step()
            time.sleep(0.05)

    worker = threading.Thread(target=loop, daemon=True)
    worker.start()
    server = ThreadingHTTPServer((host, port), make_handler(session))
    print(
        f"live: {', '.join(session.policies)} at {session.speed:g}x on http://{host}:{port}",
        flush=True,
    )
    print("  GET /, /status, /history, /stream, /health, /results, /dc/<id>, /activity, /lanes,"
          " /jobs/<id>;"
          " POST /jobs, /control", flush=True)  # fmt: skip
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        session.closed.set()
        server.server_close()
