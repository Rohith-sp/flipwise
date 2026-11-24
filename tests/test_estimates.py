"""Usage profiles (PRD §9.3): the sweep in `earliest_fit` must match the plain definition."""

import bisect
import random

from flipwise.estimates import PROFILE_HORIZON_S, ProfileJob, UsageProfile, build_profile
from flipwise.models import Request


class _ReferenceProfile:
    """The definition, written plainly: try every candidate start in order (R-SIM-1 guard)."""

    def __init__(self, cap: Request, t_s: int) -> None:
        self.cap, self.t_s, self.horizon_s = cap, t_s, t_s + PROFILE_HORIZON_S
        self.times = [t_s]
        self.used = [(0.0, 0.0, 0.0)]

    def _split(self, x: int) -> int:
        i = bisect.bisect_right(self.times, x) - 1
        if self.times[i] != x:
            self.times.insert(i + 1, x)
            self.used.insert(i + 1, self.used[i])
            i += 1
        return i

    def occupy(self, start_s: int, end_s: int, req: Request) -> None:
        if end_s <= start_s:
            return
        i, j = self._split(max(start_s, self.t_s)), self._split(end_s)
        for k in range(i, j):
            g, c, m = self.used[k]
            self.used[k] = (g + req.gpu, c + req.cpu, m + req.mem_gb)

    def _fits(self, s: int, d: int, req: Request, eps: float = 1e-9) -> bool:
        i = bisect.bisect_right(self.times, s) - 1
        while i < len(self.times) and self.times[i] < s + d:
            g, c, m = self.used[i]
            if (
                g + req.gpu > self.cap.gpu + eps
                or c + req.cpu > self.cap.cpu + eps
                or m + req.mem_gb > self.cap.mem_gb + eps
            ):
                return False
            i += 1
        return True

    def earliest_fit(self, after_s: int, d: int, req: Request) -> int | None:
        if not req.fits_in(self.cap):
            return None
        a = max(after_s, self.t_s)
        for s in [a] + self.times[bisect.bisect_right(self.times, a) :]:
            if s >= self.horizon_s:
                return None
            if self._fits(s, max(d, 1), req):
                return s
        return None


def _random_request(rng: random.Random) -> Request:
    return Request(rng.choice([0, 0.5, 1, 2, 4, 8]), rng.uniform(0, 40), rng.uniform(0, 200))


def test_earliest_fit_matches_reference_r_sim_1():
    """Byte-identical outputs rest on the sweep giving exactly the definition's starts."""
    rng = random.Random(7)
    for _ in range(300):
        cap = Request(8.0, 64.0, 512.0)
        t0 = rng.randrange(0, 10**6)
        fast, ref = UsageProfile(cap, t0), _ReferenceProfile(cap, t0)
        for _ in range(rng.randrange(1, 40)):
            req = _random_request(rng)
            after = t0 + rng.randrange(-3600, 5 * 86400)
            dur = rng.choice([0, 1, 60, 1800, 7200, rng.randrange(1, 5 * 86400)])
            s = fast.earliest_fit(after, dur, req)
            assert s == ref.earliest_fit(after, dur, req)
            if s is not None:
                fast.occupy(s, s + dur, req)
                ref.occupy(s, s + dur, req)
        assert fast._times == ref.times
        assert list(zip(fast._gpu, fast._cpu, fast._mem, strict=True)) == ref.used


def test_earliest_fit_respects_horizon_and_capacity():
    cap = Request(1.0, 1.0, 1.0)
    p = UsageProfile(cap, 0)
    assert p.earliest_fit(0, 10, Request(2.0, 0.0, 0.0)) is None  # larger than the datacentre
    assert p.earliest_fit(PROFILE_HORIZON_S, 10, Request(1.0, 1.0, 1.0)) is None
    p.occupy(0, PROFILE_HORIZON_S + 100, Request(1.0, 0.0, 0.0))
    assert p.earliest_fit(0, 10, Request(1.0, 0.0, 0.0)) is None  # next step is past horizon
    assert p.earliest_fit(0, 10, Request(0.0, 1.0, 1.0)) == 0


def test_build_profile_places_in_order():
    cap = Request(1.0, 10.0, 10.0)
    running = [(Request(1.0, 1.0, 1.0), -100, 200)]  # ends at 100
    pending = [
        ProfileJob("a", Request(1.0, 1.0, 1.0), 0, 50),
        ProfileJob("b", Request(0.0, 1.0, 1.0), 0, 50),
    ]
    prof = build_profile(cap, 0, running, pending)
    assert prof.starts == {"a": 100, "b": 0}


def test_without_matches_a_fresh_build_r_sim_1():
    """`without` resumes from a checkpoint; it must equal building without the job (PRD §9.3)."""
    rng = random.Random(11)
    cap = Request(8.0, 64.0, 512.0)
    for _ in range(100):
        t0 = rng.randrange(0, 10**6)
        running = [
            (_random_request(rng), t0 - rng.randrange(0, 7200), rng.randrange(1, 20000))
            for _ in range(rng.randrange(0, 5))
        ]
        pending = [
            ProfileJob(
                f"j{i}", _random_request(rng), t0 + rng.randrange(0, 86400), rng.randrange(1, 40000)
            )
            for i in range(rng.randrange(0, 30))
        ]
        full = build_profile(cap, t0, running, pending)
        for gone in [p.job_id for p in pending] + ["absent"]:
            fresh = build_profile(cap, t0, running, [p for p in pending if p.job_id != gone])
            cut = full.without(gone)
            assert cut._times == fresh._times
            assert (cut._gpu, cut._cpu, cut._mem) == (fresh._gpu, fresh._cpu, fresh._mem)
            assert cut.starts == fresh.starts
