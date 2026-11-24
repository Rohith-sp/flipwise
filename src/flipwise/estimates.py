"""Runtime quantiles (PRD §6.5) and queue-wait estimates from usage profiles (PRD §9.3)."""

from __future__ import annotations

import bisect
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from flipwise.models import Request

PROFILE_HORIZON_S = 9 * 86400
OVERRUN_MIN_S = 60  # a job past its estimate is assumed to need at least one more minute
CHECKPOINT_EVERY = 8  # profile state is copied before every 8th job, for `without`
RUNTIME_QUANTILES = (0.05, 0.50, 0.90, 0.95)
N_MIN_USER_JOBS = 20  # PRD §6.5

type RuntimeQuantiles = tuple[int, int, int, int]  # q05, q50, q90, q95 in seconds


def gpu_class(gpu_req: float) -> int:
    """GPU-request class of PRD §6.5: {0}, (0, 1], (1, 8], > 8."""
    if gpu_req <= 0:
        return 0
    return 1 if gpu_req <= 1 else 2 if gpu_req <= 8 else 3


def _quantiles(runtimes: np.ndarray) -> RuntimeQuantiles:
    q = np.quantile(runtimes, RUNTIME_QUANTILES, method="linear")
    return tuple(max(1, int(np.rint(x))) for x in q)  # type: ignore[return-value]


@dataclass(frozen=True)
class RuntimeModel:
    """Frozen after calibration; the fallback chain is user → GPU class → global (PRD §10.7)."""

    by_user: dict[str, RuntimeQuantiles]
    by_class: dict[int, RuntimeQuantiles]
    overall: RuntimeQuantiles

    def estimate(self, user: str, gpu_req: float) -> tuple[RuntimeQuantiles, str]:
        """The quantiles and which level supplied them: `user`, `class` or `global`."""
        q = self.by_user.get(user)
        if q is not None:
            return q, "user"
        q = self.by_class.get(gpu_class(gpu_req))
        return (q, "class") if q is not None else (self.overall, "global")


def fit_runtime(calibration: pd.DataFrame, n_min: int = N_MIN_USER_JOBS) -> RuntimeModel:
    """Fit from calibration jobs with columns `user, gpu_req, runtime_actual_s` (PRD §6.5)."""
    by_user = {
        str(user): _quantiles(group.to_numpy())
        for user, group in calibration.groupby("user", sort=True)["runtime_actual_s"]
        if len(group) >= n_min
    }
    classes = calibration["gpu_req"].map(gpu_class)
    by_class = {
        int(c): _quantiles(group.to_numpy())
        for c, group in calibration.groupby(classes, sort=True)["runtime_actual_s"]
    }
    return RuntimeModel(by_user, by_class, _quantiles(calibration["runtime_actual_s"].to_numpy()))


@dataclass(frozen=True)
class ProfileJob:
    """One job in a projected profile; `release_s` is when it may start at the earliest."""

    job_id: str
    req: Request
    release_s: int
    duration_s: int


class UsageProfile:
    """Step function of used capacity per dimension, built by first-fit list scheduling.

    Usage is kept as three parallel lists rather than one list of tuples: profiles are rebuilt
    for every candidate evaluation, and this is where a run spends most of its time.
    """

    def __init__(self, cap: Request, t_s: int) -> None:
        self.cap = cap
        self.t_s = t_s
        self.horizon_s = t_s + PROFILE_HORIZON_S
        self._times: list[int] = [t_s]
        # Used GPUs, cores and GB from `_times[i]` on.
        self._gpu: list[float] = [0.0]
        self._cpu: list[float] = [0.0]
        self._mem: list[float] = [0.0]
        self.starts: dict[str, int | None] = {}  # projected start of each scheduled job
        # Set by `build_profile`, for `without`: the jobs placed, in order, and copies of the
        # state before every `CHECKPOINT_EVERY`-th of them.
        self._pending: list[ProfileJob] = []
        self._checkpoints: list[tuple[list[int], list[float], list[float], list[float]]] = []

    def _state(self) -> tuple[list[int], list[float], list[float], list[float]]:
        return self._times.copy(), self._gpu.copy(), self._cpu.copy(), self._mem.copy()

    def without(self, job_id: str) -> UsageProfile:
        """The profile `build_profile` gives for the same jobs minus `job_id`.

        List scheduling places jobs in order, so the jobs before `job_id` land exactly where they
        did here; only the rest are placed again, from the last checkpoint before it. Reading
        the result, never placing more jobs on it, is all a caller may do.
        """
        k = next((i for i, j in enumerate(self._pending) if j.job_id == job_id), None)
        if k is None:
            return self
        c = k // CHECKPOINT_EVERY
        first = c * CHECKPOINT_EVERY
        prof = UsageProfile(self.cap, self.t_s)
        prof._times, prof._gpu, prof._cpu, prof._mem = (x.copy() for x in self._checkpoints[c])
        prof.starts = {j.job_id: self.starts[j.job_id] for j in self._pending[:first]}
        for job in self._pending[first:]:
            if job.job_id != job_id:
                prof.place(job)
        return prof

    def occupy(self, start_s: int, end_s: int, req: Request) -> None:
        if end_s <= start_s:
            return
        # Both ends become steps; a new step starts with the usage of the one it splits.
        # Written out twice rather than looped: this is the innermost code of a run.
        times, gpu, cpu, mem = self._times, self._gpu, self._cpu, self._mem
        x = start_s if start_s > self.t_s else self.t_s
        i = bisect.bisect_right(times, x) - 1
        if times[i] != x:
            i += 1
            times.insert(i, x)
            gpu.insert(i, gpu[i - 1])
            cpu.insert(i, cpu[i - 1])
            mem.insert(i, mem[i - 1])
        j = bisect.bisect_right(times, end_s) - 1
        if times[j] != end_s:
            j += 1
            times.insert(j, end_s)
            gpu.insert(j, gpu[j - 1])
            cpu.insert(j, cpu[j - 1])
            mem.insert(j, mem[j - 1])
        rg, rc, rm = req.gpu, req.cpu, req.mem_gb
        for k in range(i, j):
            gpu[k] += rg
            cpu[k] += rc
            mem[k] += rm

    def earliest_fit(self, after_s: int, duration_s: int, req: Request) -> int | None:
        """Earliest start ≥ `after_s` (and < horizon) where `req` fits for `duration_s`.

        Candidate starts are `after_s` and every later step. One sweep finds the first that fits:
        a step that is too full rules out every candidate up to it, so the next candidate is the
        step just after it.
        """
        cap = self.cap
        if not req.fits_in(cap):
            return None
        s = after_s if after_s > self.t_s else self.t_s
        horizon = self.horizon_s
        if s >= horizon:
            return None
        eps = 1e-9
        lim_g, lim_c, lim_m = cap.gpu + eps, cap.cpu + eps, cap.mem_gb + eps
        rg, rc, rm = req.gpu, req.cpu, req.mem_gb
        dur = duration_s if duration_s > 1 else 1
        times, gpu, cpu, mem = self._times, self._gpu, self._cpu, self._mem
        n = len(times)
        end = s + dur
        i = bisect.bisect_right(times, s) - 1
        while i < n and times[i] < end:
            if gpu[i] + rg > lim_g or cpu[i] + rc > lim_c or mem[i] + rm > lim_m:
                i += 1
                if i >= n:
                    return None
                s = times[i]
                if s >= horizon:
                    return None
                end = s + dur
            else:
                i += 1
        return s

    def place(self, job: ProfileJob) -> int | None:
        s = self.earliest_fit(job.release_s, job.duration_s, job.req)
        self.starts[job.job_id] = s
        if s is not None:
            self.occupy(s, s + job.duration_s, job.req)
        return s


def build_profile(
    cap: Request,
    t_s: int,
    running: Iterable[tuple[Request, int, int]],
    pending: Iterable[ProfileJob],
) -> UsageProfile:
    """`running`: `(req, start_s, r_q_s)`; `pending`: queued jobs in queue order, then
    placed-but-unreleased jobs in `(release_slot, deadline, job_id)` order (PRD §9.3)."""
    prof = UsageProfile(cap, t_s)
    for req, start_s, r_q_s in running:
        prof.occupy(t_s, start_s + max(r_q_s, (t_s - start_s) + OVERRUN_MIN_S), req)
    prof._pending = list(pending)
    for k, job in enumerate(prof._pending):
        if k % CHECKPOINT_EVERY == 0:
            prof._checkpoints.append(prof._state())
        prof.place(job)
    return prof
