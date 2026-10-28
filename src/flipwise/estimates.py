"""Queue-wait estimates from projected usage profiles (PRD §9.3).

Runtime-quantile fitting (PRD §6.5) is added in build phase 5.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable
from dataclasses import dataclass

from flipwise.models import Request

QUANTILES = ("q05", "q50", "q95")
PROFILE_HORIZON_S = 9 * 86400
OVERRUN_MIN_S = 60  # a job past its estimate is assumed to need at least one more minute


@dataclass(frozen=True)
class ProfileJob:
    """One job in a projected profile; `release_s` is when it may start at the earliest."""

    job_id: str
    req: Request
    release_s: int
    duration_s: int


class UsageProfile:
    """Step function of used capacity per dimension, built by first-fit list scheduling."""

    def __init__(self, cap: Request, t_s: int) -> None:
        self.cap = cap
        self.t_s = t_s
        self.horizon_s = t_s + PROFILE_HORIZON_S
        self._times: list[int] = [t_s]
        self._used: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0)]  # from _times[i] on

    def _split(self, x: int) -> int:
        i = bisect.bisect_right(self._times, x) - 1
        if self._times[i] != x:
            self._times.insert(i + 1, x)
            self._used.insert(i + 1, self._used[i])
            i += 1
        return i

    def occupy(self, start_s: int, end_s: int, req: Request) -> None:
        if end_s <= start_s:
            return
        i, j = self._split(max(start_s, self.t_s)), self._split(end_s)
        for k in range(i, j):
            g, c, m = self._used[k]
            self._used[k] = (g + req.gpu, c + req.cpu, m + req.mem_gb)

    def _fits(self, start_s: int, duration_s: int, req: Request, eps: float = 1e-9) -> bool:
        end = start_s + duration_s
        i = bisect.bisect_right(self._times, start_s) - 1
        cap = self.cap
        while i < len(self._times) and self._times[i] < end:
            g, c, m = self._used[i]
            if (
                g + req.gpu > cap.gpu + eps
                or c + req.cpu > cap.cpu + eps
                or m + req.mem_gb > cap.mem_gb + eps
            ):
                return False
            i += 1
        return True

    def earliest_fit(self, after_s: int, duration_s: int, req: Request) -> int | None:
        """Earliest start ≥ `after_s` (and < horizon) where `req` fits for `duration_s`."""
        if not req.fits_in(self.cap):
            return None
        a = max(after_s, self.t_s)
        candidates = [a] + self._times[bisect.bisect_right(self._times, a) :]
        for s in candidates:
            if s >= self.horizon_s:
                return None
            if self._fits(s, max(duration_s, 1), req):
                return s
        return None

    def place(self, job: ProfileJob) -> int | None:
        s = self.earliest_fit(job.release_s, job.duration_s, job.req)
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
    for job in pending:
        prof.place(job)
    return prof
