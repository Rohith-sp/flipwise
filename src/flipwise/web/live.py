"""Live sessions: every selected policy runs in its own OS process on the unchanged simulator,
paced to one shared demo clock, and streams what happens back for the browser to animate.

Processes, not threads: the planners are CPU-bound, so threads would share one core and their
`perf_counter` planner timings would include waiting for the interpreter lock. Each lane process
gets its own core, so the timings shown are the policy's own.

Pacing only delays when an event is handled; it never changes the order or the outcome, so a
live lane makes exactly the decisions of a normal `flipwise run` on the same scenario
(`tests/test_web.py`).
"""

from __future__ import annotations

import collections
import multiprocessing as mp
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ALL = ("fcfs", "place_once", "periodic", "pred_error", "fixed_savings", "decision_flip", "pig")
DC_PORT_BASE = 8301
LOCKSTEP_S = 1800  # a lane handles an event only within one slot of the slowest lane
LAG_MAX_S = 3600  # the clock never runs more than this ahead of the slowest lane
FLUSH_S = 0.1  # how often a lane process ships its new records
_CTX = mp.get_context("spawn")  # same behaviour on Linux and Windows

# shared clock slots
_ANCHOR_SIM, _ANCHOR_WALL, _SPEED, _PAUSED, _STOPPED = range(5)


class Stopped(Exception):
    """Raised inside a lane to unwind the simulator when the session stops."""


class SharedClock:
    """Simulated time advancing at `speed` simulated seconds per wall second, in shared memory
    so every lane process reads the same clock. `time.monotonic` is system-wide on Linux and
    Windows, so a wall anchor taken in one process is valid in the others."""

    def __init__(self, start_s: float, speed: float, n_lanes: int) -> None:
        self.lock = _CTX.Lock()
        self.v = _CTX.Array("d", [float(start_s), time.monotonic(), float(speed), 1.0, 0.0],
                            lock=False)  # fmt: skip
        self.pos = _CTX.Array("d", [float(start_s)] * n_lanes, lock=False)

    def _now(self) -> float:
        v = self.v
        if v[_PAUSED]:
            return v[_ANCHOR_SIM]
        return v[_ANCHOR_SIM] + (time.monotonic() - v[_ANCHOR_WALL]) * v[_SPEED]

    def now(self) -> float:
        with self.lock:
            return self._now()

    def _set(self, sim: float | None = None, **kw) -> None:
        with self.lock:
            v = self.v
            v[_ANCHOR_SIM] = self._now() if sim is None else sim
            v[_ANCHOR_WALL] = time.monotonic()
            for k, x in kw.items():
                v[{"speed": _SPEED, "paused": _PAUSED}[k]] = x

    @property
    def speed(self) -> float:
        return self.v[_SPEED]

    @property
    def paused(self) -> bool:
        return bool(self.v[_PAUSED])

    @property
    def stopped(self) -> bool:
        return bool(self.v[_STOPPED])

    def play(self) -> None:
        self._set(paused=0.0)

    def pause(self) -> None:
        self._set(paused=1.0)

    def set_speed(self, speed: float) -> None:
        self._set(speed=float(speed))

    def jump(self, delta_s: float) -> None:
        self._set(self.now() + delta_s)

    def stop(self) -> None:
        self.v[_STOPPED] = 1.0

    def hold_at_most(self, t_s: float) -> None:
        """Pull the clock back to `t_s` if it ran ahead: the slowest lane sets the pace."""
        with self.lock:
            if self._now() > t_s:
                self.v[_ANCHOR_SIM] = t_s
                self.v[_ANCHOR_WALL] = time.monotonic()

    def min_pos(self) -> float:
        return min(self.pos)


# --------------------------------------------------------------------------- lane process side
class LiveClient:
    """Wraps a datacentre client (in-process or HTTP) and records what the local scheduler did:
    queue joins, removals and starts. Counts calls and their time, like `TimedClient`."""

    def __init__(self, inner, lane: LaneCore, dc_id: int) -> None:
        self.inner, self.lane, self.dc_id = inner, lane, dc_id
        self.calls = 0
        self.seconds = 0.0

    def _timed(self, fn, *a):
        t0 = time.perf_counter()
        try:
            return fn(*a)
        finally:
            self.calls += 1
            self.seconds += time.perf_counter() - t0

    def reset(self, cfg, scenario_hash: str = "") -> None:
        self._timed(self.inner.reset, cfg, scenario_hash)

    def enqueue(self, t_s, job_id, req, runtime_actual_s):
        n = self._timed(self.inner.enqueue, t_s, job_id, req, runtime_actual_s)
        self.lane.emit({"k": "q", "t": t_s, "j": job_id, "dc": self.dc_id})
        return n

    def remove(self, t_s, job_id):
        self._timed(self.inner.remove, t_s, job_id)
        self.lane.emit({"k": "rm", "t": t_s, "j": job_id, "dc": self.dc_id})

    def dispatch(self, t_s):
        started = self._timed(self.inner.dispatch, t_s)
        for s in started:
            self.lane.emit({"k": "run", "t": t_s, "j": s.job_id, "dc": self.dc_id, "end": s.end_s})
        return started

    def complete(self, t_s, job_id):
        self._timed(self.inner.complete, t_s, job_id)

    def state(self):
        return self._timed(self.inner.state)


def _live_simulator_class():
    from flipwise.simulator import Simulator, job_outcome

    class LiveSimulator(Simulator):
        """The simulator with two hooks: wait for the demo clock before each event, and record
        the event and the decisions it produced. The event loop and every rule are inherited."""

        def __init__(self, scenario, policy, lane: LaneCore, clients: list) -> None:
            self.lane = lane
            super().__init__(scenario, policy, clients=clients, debug=False)

        def _handle(self, ev) -> None:
            self.lane.wait_until(ev.time_s)
            n0 = len(self.decisions)
            super()._handle(ev)
            lane = self.lane
            if ev.kind == "JOB_ARRIVAL":
                lane.emit({"k": "arr", "t": ev.time_s, "j": ev.job_id})
            elif ev.kind == "CARBON_UPDATE":
                lane.emit({"k": "fc", "t": ev.time_s})
            elif ev.kind == "PERIODIC_TICK":
                lane.emit({"k": "tick", "t": ev.time_s})
            elif ev.kind == "JOB_COMPLETE":
                out = job_outcome(self.jobs[ev.job_id], self.scenario)
                lane.emit({"k": "done", "t": ev.time_s, "j": ev.job_id,
                           "kg": out["kg_co2"], "kwh": out["energy_kwh"]})  # fmt: skip
            for d in self.decisions[n0:]:
                lane.emit_decision(d)
            lane.sim_t = ev.time_s

    return LiveSimulator


class LaneCore:
    """One policy's run inside its lane process."""

    def __init__(self, idx: int, policy: str, clock: SharedClock, out) -> None:
        self.idx, self.policy, self.clock, self.out = idx, policy, clock, out
        self.buf: list = []
        self.counts: collections.Counter = collections.Counter()
        self.kg = self.kwh = 0.0
        self.sim_t = 0
        self.sim = None
        self.clients: list = []
        self.pids: list = []
        self.ports: list = []
        self.t0 = time.perf_counter()
        self._last_flush = time.monotonic()

    def wait_until(self, t_s: int) -> None:
        """Wait for the demo clock, and stay within `LOCKSTEP_S` of the slowest unfinished lane,
        so lanes show the same moment even when one policy computes much more than another.
        The lane holding the earliest event is never blocked by this rule, so it cannot stall."""
        clock = self.clock
        clock.pos[self.idx] = t_s
        while True:
            if clock.stopped:
                raise Stopped
            floor = clock.min_pos()
            clock.hold_at_most(floor + LAG_MAX_S)
            now = clock.now()
            if now >= t_s and t_s <= floor + LOCKSTEP_S:
                return
            self.flush()
            gap_wall = (t_s - now) / max(clock.speed, 1.0)
            time.sleep(0.05 if clock.paused else min(0.05, max(gap_wall, 0.002)))

    def emit(self, rec: dict) -> None:
        self.buf.append(rec)
        k = rec["k"]
        self.counts[k] += 1
        if k == "done":
            self.kg += rec["kg"] or 0.0
            self.kwh += rec["kwh"] or 0.0

    def emit_decision(self, d: dict) -> None:
        def r(x):
            return None if x is None else round(float(x), 5)

        self.emit({
            "k": "d", "t": d["time_s"], "j": d["job_id"], "kind": d["kind"],
            "fdc": d["from_dc"], "fslot": d["from_slot"], "tdc": d["to_dc"], "tslot": d["to_slot"],
            "sa": r(d["S_a"]), "sb": r(d["S_b"]), "lb": r(d["LB"]), "g": r(d["g_min"]),
            "w": r(d["w_ab"]), "th": r(d["theta_eff"]), "why": d["reason"],
        })  # fmt: skip
        self.counts["kind:" + d["kind"]] += 1

    def summary(self) -> dict:
        stats = self.sim.policy.stats.as_dict() if self.sim else {}
        keys = ("arrival_s", "screen_s", "rescore_s", "rescue_s")
        c = self.counts
        dcs = [{"calls": cl.calls, "ms": 1000 * cl.seconds / max(cl.calls, 1),
                "pid": self.pids[i] if self.pids else None,
                "port": self.ports[i] if self.ports else None}
               for i, cl in enumerate(self.clients)]  # fmt: skip
        return {
            "policy": self.policy, "t": self.sim_t, "kg": self.kg, "kwh": self.kwh,
            "done": c["done"], "arrived": c["arr"], "moves": c["kind:MOVE"],
            "rescues": c["kind:RESCUE"], "rescores": stats.get("stage2_calls", 0),
            "screened": stats.get("screened", 0), "screen_fail": c["kind:SCREEN_FAIL"],
            "keep": c["kind:KEEP"], "throttled": c["kind:THROTTLED"], "rejected": c["kind:REJECT"],
            "planner_s": sum(stats.get(k, 0.0) for k in keys),
            "wall_s": time.perf_counter() - self.t0, "dcs": dcs,
        }  # fmt: skip

    def flush(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._last_flush < FLUSH_S:
            return
        self._last_flush = time.monotonic()
        recs, self.buf = self.buf, []
        self.out.put(("recs", self.idx, recs, self.summary()))


def _load(spec: tuple):
    from flipwise.scenario import load_scenario
    from flipwise.web.scenarios import config, demo_scenario

    kind, value = spec
    cfg = config()
    if kind == "preset":
        return cfg, demo_scenario(cfg, value)
    return {}, load_scenario(Path(value))  # tests: a scenario directory, policy defaults


def _exit_with_parent() -> None:
    """A lane process is useless without the server; leave if it dies, even from SIGKILL."""
    parent = mp.parent_process()
    while parent is not None:
        parent.join(1.0)
        if not parent.is_alive():
            os._exit(0)


def lane_main(idx: int, policy: str, spec: tuple, ports: list, pids: list, clock: SharedClock,
              out, return_logs: bool = False) -> None:  # fmt: skip
    """Entry point of a lane process."""
    threading.Thread(target=_exit_with_parent, daemon=True).start()
    lane = LaneCore(idx, policy, clock, out)
    error = None
    logs = None
    try:
        from flipwise.config import policy_params
        from flipwise.datacentre import InProcDatacentre
        from flipwise.policies import make_policy

        cfg, sc = _load(spec)
        if ports:
            from flipwise.dcservice import HttpDatacentre
            from flipwise.errors import DeploymentError

            inner = []
            for port in ports:
                http = HttpDatacentre(f"http://127.0.0.1:{port}")
                for _ in range(150):  # the service needs a moment to import and bind
                    try:
                        http.health()
                        break
                    except DeploymentError:
                        time.sleep(0.1)
                inner.append(http)
            lane.pids, lane.ports = pids, ports
        else:
            inner = [InProcDatacentre() for _ in sc.dcs]
        lane.clients = [LiveClient(c, lane, d.dc_id) for c, d in zip(inner, sc.dcs, strict=True)]
        policy_obj = make_policy(policy, **policy_params(cfg, policy))
        lane.sim = _live_simulator_class()(sc, policy_obj, lane, lane.clients)
        lane.sim.run()
        if return_logs:
            logs = (lane.sim.events, lane.sim.decisions)
    except Stopped:
        pass
    except Exception as e:  # shown in the lane; the other lanes keep running
        error = f"{type(e).__name__}: {e}"
    finally:
        clock.pos[idx] = float("inf")
        lane.flush(force=True)
        out.put(("end", idx, error, logs))


# --------------------------------------------------------------------------- server side
class Lane:
    """What the server keeps of one lane: its records and latest summary."""

    def __init__(self, idx: int, policy: str) -> None:
        self.idx, self.policy = idx, policy
        self.records: list = []
        self.info: dict = {"policy": policy, "t": 0, "kg": 0.0, "kwh": 0.0, "done": 0,
                           "arrived": 0, "moves": 0, "rescues": 0, "rescores": 0, "screened": 0,
                           "screen_fail": 0, "keep": 0, "throttled": 0, "rejected": 0,
                           "planner_s": 0.0, "wall_s": 0.0, "dcs": []}  # fmt: skip
        self.finished = False
        self.error: str | None = None
        self.logs = None  # (events, decisions) when requested, for tests
        self.proc = None
        self.dc_procs: list = []

    def summary(self) -> dict:
        return {**self.info, "finished": self.finished, "error": self.error,
                "n": len(self.records)}  # fmt: skip


class Session:
    def __init__(self, spec: tuple, start_s: int, policies: list[str], mode: str, speed: float,
                 n_dcs: int = 3, return_logs: bool = False) -> None:  # fmt: skip
        self.id = uuid.uuid4().hex[:10]
        self.spec, self.mode, self.n_dcs, self.return_logs = spec, mode, n_dcs, return_logs
        self.clock = SharedClock(start_s, speed, len(policies))
        self.lanes = {p: Lane(i, p) for i, p in enumerate(policies)}
        self._by_idx = {lane.idx: lane for lane in self.lanes.values()}
        self.out = _CTX.Queue()
        self._collector: threading.Thread | None = None

    @property
    def stopped(self) -> bool:
        return self.clock.stopped

    def start(self) -> None:
        port = DC_PORT_BASE
        for lane in self.lanes.values():
            ports: list = []
            if self.mode == "process":
                # Each datacentre is its own `flipwise dc-serve` process (PRD §13.5, DT1). The
                # server starts them, so it can always clean them up.
                for dc_id in range(self.n_dcs):
                    # `dcwatch` runs the unchanged `dc-serve` and exits if the server dies.
                    cmd = [sys.executable, "-m", "flipwise.web.dcwatch", "--dc-id",
                           str(dc_id), "--port", str(port)]  # fmt: skip
                    lane.dc_procs.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL))
                    ports.append(port)
                    port += 1
            pids = [p.pid for p in lane.dc_procs]
            lane.proc = _CTX.Process(
                target=lane_main, daemon=True,
                args=(lane.idx, lane.policy, self.spec, ports, pids, self.clock, self.out,
                      self.return_logs),
            )  # fmt: skip
            lane.proc.start()
        self._collector = threading.Thread(target=self._collect, daemon=True)
        self._collector.start()

    def _collect(self) -> None:
        while not all(lane.finished for lane in self.lanes.values()):
            try:
                msg = self.out.get(timeout=0.5)
            except queue.Empty:
                for lane in self.lanes.values():  # a lane process that died without a word
                    if not lane.finished and lane.proc and lane.proc.exitcode not in (None, 0):
                        lane.error = f"lane process exited {lane.proc.exitcode}"
                        lane.finished = True
                continue
            lane = self._by_idx[msg[1]]
            if msg[0] == "recs":
                lane.records.extend(msg[2])
                lane.info = msg[3]
            else:
                lane.error, lane.logs, lane.finished = msg[2], msg[3], True
                for p in lane.dc_procs:
                    p.terminate()

    def wait(self, timeout: float) -> bool:
        if self._collector:
            self._collector.join(timeout)
        return all(lane.finished for lane in self.lanes.values())

    def stop(self, wait: bool = False) -> None:
        """Ask every lane to unwind, then reap the processes: in the background while the
        server keeps serving, or before returning when the server itself is shutting down."""
        self.clock.stop()
        if wait:
            self._reap()
        else:
            threading.Thread(target=self._reap, daemon=True).start()

    def _reap(self) -> None:
        for lane in self.lanes.values():
            if lane.proc:
                lane.proc.join(10)
                if lane.proc.is_alive():
                    lane.proc.terminate()
            for p in lane.dc_procs:
                p.terminate()

    # ---- what the browser reads ----------------------------------------------------------
    def poll(self, cursors: dict[str, int], watched: set[str]) -> dict:
        lanes = {}
        for p, lane in self.lanes.items():
            info = lane.summary()
            if p in watched:
                start = cursors.get(p, 0)
                end = min(len(lane.records), start + 20000)  # keep one reply small
                info["records"] = lane.records[start:end]
                info["cursor"] = end
            lanes[p] = info
        return {"now": self.clock.now(), "paused": self.clock.paused, "speed": self.clock.speed,
                "lanes": lanes}  # fmt: skip
