"""Scheduling policies (PRD §11). They differ only in trigger and acceptance; everything else
(candidates, feasibility, scoring, dispatch, rescue) is shared."""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from flipwise import planner
from flipwise.errors import ConfigError
from flipwise.models import Candidate, JobState, Placement

if TYPE_CHECKING:
    from flipwise.simulator import JobInfo, SchedulerView, Simulator


@dataclass(frozen=True)
class Decision:
    """One row of decisions.csv (PRD §16.1). `to` is the placement to apply, if any."""

    job_id: str
    kind: str
    to: Placement | None = None
    s_a: float | None = None  # incumbent score
    s_b: float | None = None  # chosen / best alternative score
    reason: str = ""
    deadline_risk: bool = False
    lb: float | None = None  # Stage-1 lower bound
    w_ab: float | None = None  # noise width of the comparison
    g_min: float | None = None  # benefit gate
    theta_eff: float | None = None  # θ actually applied, after the §10.7 fallbacks
    w_lo: int | None = None  # wait interval of the plan being applied (PRD §14.1)
    w_hi: int | None = None


@dataclass
class PolicyStats:
    """Work counters for `metrics.json` (PRD §14.1). Timings use `perf_counter` and never reach
    the byte-identical logs, so they cannot affect determinism (R-SIM-1)."""

    stage2_calls: int = 0
    screened: int = 0
    rescues: int = 0
    arrival_s: float = 0.0
    screen_s: float = 0.0
    rescore_s: float = 0.0
    rescue_s: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


def _to_candidate(job_id: str, kind: str, c: Candidate, **kw) -> Decision:
    return Decision(job_id, kind, c.placement, s_b=c.s_hat, w_lo=c.w_lo, w_hi=c.w_hi, **kw)


class Policy:
    name = "base"
    uses_oracle = False
    tick_s: int | None = None  # interval of PERIODIC_TICK events, if the policy wants them

    def __init__(self) -> None:
        self.stats = PolicyStats()

    def make_view(self, sim: Simulator) -> SchedulerView:
        from flipwise.simulator import SchedulerView

        return SchedulerView(sim)

    def on_arrival(self, view: SchedulerView, job_id: str) -> Decision:
        raise NotImplementedError

    def on_carbon_update(self, view: SchedulerView) -> Iterable[Decision]:
        """Re-planning policies are generators: the simulator applies each decision before the
        policy resumes, so the next job sees the new congestion (PRD §10.6, R-TRIG-8)."""
        return []

    def on_tick(self, view: SchedulerView) -> Iterable[Decision]:
        """Same contract as `on_carbon_update`; only called when `tick_s` is set."""
        return []

    def on_release(self, view: SchedulerView, job_id: str) -> Decision | None:
        """Last check before a job joins the queue. A decision with `to` set replaces the release
        (rescue, PRD §10.2); one without is only logged; None means nothing to log."""
        return None


class Fcfs(Policy):
    """Non-carbon-aware reference: earliest projected start, never deferred or re-planned."""

    name = "fcfs"

    def __init__(self) -> None:
        super().__init__()
        self._arrivals = 0

    def on_arrival(self, view: SchedulerView, job_id: str) -> Decision:
        job = view.job(job_id)
        t0 = time.perf_counter()
        c = planner.earliest_start(view, job, self._arrivals)
        self.stats.arrival_s += time.perf_counter() - t0
        self._arrivals += 1
        if c is None:
            return Decision(job_id, "REJECT", reason="NO_START")
        return _to_candidate(job_id, "PLACE", c)


def initial_placement(view: SchedulerView, job_id: str) -> Decision:
    """Best feasible candidate, else the no-feasible fallback (PRD §9.5)."""
    job = view.job(job_id)
    cands = planner.candidates(view, job)
    best = planner.best_candidate(cands)
    if best is not None:
        return _to_candidate(job_id, "PLACE", best)
    fb = planner.fallback(cands, job, view.params)
    if fb is None:
        return Decision(job_id, "REJECT", reason="NO_START")
    return _to_candidate(
        job_id, "FALLBACK", fb, reason="FALLBACK_EARLIEST_FINISH", deadline_risk=True
    )


class Replanner(Policy):
    """Shared by everything except FCFS: placement at arrival, rescue, throttling (PRD §10.2,
    §10.4). Subclasses say only when to re-score and what to accept."""

    def __init__(self, cooldown_s: int = 1800, max_moves: int = 3) -> None:
        super().__init__()
        self.cooldown_s = int(cooldown_s)
        self.max_moves = int(max_moves)
        self.last_rescore: dict[str, int] = {}

    def on_arrival(self, view: SchedulerView, job_id: str) -> Decision:
        t0 = time.perf_counter()
        d = initial_placement(view, job_id)
        self.stats.arrival_s += time.perf_counter() - t0
        self.after_placement(view, d)
        return d

    def after_placement(self, view: SchedulerView, d: Decision) -> None:
        """Hook for policies that remember what a plan looked like when it was made."""

    def rescue(self, view: SchedulerView, job: JobInfo, inc: Candidate) -> Decision:
        """The incumbent is infeasible (PRD §10.2): re-plan, bypassing the acceptance rule."""
        s_a = inc.s_hat
        # Missing data is not an operational violation, so the plan stands (D28).
        if inc.reject_reason == planner.NO_CARBON:
            return Decision(job.job_id, "KEEP", s_a=s_a, reason="NO_CARBON_INCUMBENT")
        # Without this limit an at-risk job would give up its place at every update (D28).
        if job.on_fallback:
            return Decision(job.job_id, "RESCUE_NOOP", s_a=s_a, reason="ON_FALLBACK")
        cands = planner.alternatives(view, job)
        best = planner.best_candidate(cands)
        if best is not None:
            self.stats.rescues += 1
            return _to_candidate(job.job_id, "RESCUE", best, s_a=s_a, reason=inc.reject_reason)
        if job.state == JobState.QUEUED:
            return Decision(job.job_id, "RESCUE_NOOP", s_a=s_a, reason="NO_FEASIBLE_ALTERNATIVE")
        fb = planner.fallback(cands, job, view.params)
        finish_now = planner.finish_estimate(inc, job, view.params)
        finish_fb = None if fb is None else planner.finish_estimate(fb, job, view.params)
        # A fallback that finishes no earlier gives up nothing but also gains nothing (D42).
        if finish_fb is None or (finish_now is not None and finish_fb >= finish_now):
            return Decision(job.job_id, "RESCUE_NOOP", s_a=s_a, reason="NOT_EARLIER")
        self.stats.rescues += 1
        return _to_candidate(
            job.job_id, "RESCUE", fb, s_a=s_a, reason="FALLBACK_EARLIEST_FINISH", deadline_risk=True
        )

    def on_release(self, view: SchedulerView, job_id: str) -> Decision | None:
        job = view.job(job_id)
        inc = planner.rescore(view, job)
        return None if inc.feasible else self._rescue_logged(view, job, inc)

    def _rescue_logged(self, view: SchedulerView, job: JobInfo, inc: Candidate) -> Decision:
        t0 = time.perf_counter()
        d = self.rescue(view, job, inc)
        self.stats.rescue_s += time.perf_counter() - t0
        self.after_placement(view, d)
        return d

    def _replan_all(
        self, view: SchedulerView, trigger: bool = True, rescue: bool = True
    ) -> Iterator[Decision]:
        """One pass over pending jobs in tie order: rescue first, then the policy's re-planning."""
        for job in view.pending_jobs():
            t0 = time.perf_counter()
            inc = planner.rescore(view, job)
            self.stats.screen_s += time.perf_counter() - t0
            if not inc.feasible:
                if rescue:
                    yield self._rescue_logged(view, job, inc)
            elif trigger:
                yield from self.replan(view, job, inc)

    def replan(self, view: SchedulerView, job: JobInfo, inc: Candidate) -> Iterator[Decision]:
        """Re-plan one job whose incumbent is feasible. Rescue-only policies do nothing."""
        return iter(())

    def on_carbon_update(self, view: SchedulerView) -> Iterable[Decision]:
        return self._replan_all(view)

    def _throttled(self, view: SchedulerView, job: JobInfo) -> bool:
        last = self.last_rescore.get(job.job_id)
        return job.n_moves >= self.max_moves or (
            last is not None and view.now_s < last + self.cooldown_s
        )

    def _best_for_replan(self, view: SchedulerView, job: JobInfo) -> Candidate | None:
        self.stats.stage2_calls += 1
        t0 = time.perf_counter()
        b = planner.best_alternative(view, job)
        self.stats.rescore_s += time.perf_counter() - t0
        self.last_rescore[job.job_id] = view.now_s
        return b


class PlaceOnce(Replanner):
    """Best Ŝ among feasible candidates at arrival; after that, rescue only."""

    name = "place_once"

    def on_carbon_update(self, view: SchedulerView) -> Iterable[Decision]:
        return self._replan_all(view, trigger=False)


class Periodic(Replanner):
    """Timer re-optimisation: every `T_s`, all pending jobs; rescue still runs at every update."""

    name = "periodic"

    def __init__(self, T_s: int = 1800, cooldown_s: int = 1800, max_moves: int = 3) -> None:
        super().__init__(cooldown_s, max_moves)
        self.tick_s = int(T_s)

    def on_carbon_update(self, view: SchedulerView) -> Iterable[Decision]:
        return self._replan_all(view, trigger=False)

    def on_tick(self, view: SchedulerView) -> Iterable[Decision]:
        # Rescue runs on updates and releases for every policy alike, never on this policy's timer.
        return self._replan_all(view, rescue=False)

    def replan(self, view: SchedulerView, job: JobInfo, inc: Candidate) -> Iterator[Decision]:
        yield from _accept_any_gain(self, view, job, inc)


def _accept_any_gain(
    policy: Replanner, view: SchedulerView, job: JobInfo, inc: Candidate
) -> Iterator[Decision]:
    """Acceptance `Ŝ_a − Ŝ_b > ε_tie`, shared by `periodic` and `pred_error` (PRD §11)."""
    if policy._throttled(view, job):
        yield Decision(job.job_id, "THROTTLED", s_a=inc.s_hat)
        return
    b = policy._best_for_replan(view, job)
    if b is None:
        yield Decision(job.job_id, "NO_ALTERNATIVE", s_a=inc.s_hat)
    elif inc.s_hat - b.s_hat > planner.EPS_TIE_KG:
        yield _to_candidate(job.job_id, "MOVE", b, s_a=inc.s_hat)
    else:
        yield Decision(job.job_id, "KEEP", s_a=inc.s_hat, s_b=b.s_hat)


class PredError(Replanner):
    """Re-plans when the inputs of the current plan drift by more than `epsilon` (PRD §11)."""

    name = "pred_error"

    def __init__(self, epsilon: float = 0.1, cooldown_s: int = 1800, max_moves: int = 3) -> None:
        super().__init__(cooldown_s, max_moves)
        self.epsilon = float(epsilon)
        self._plan: dict[str, tuple[float | None, int | None]] = {}  # job -> (mean forecast, w_mid)

    def _remember(self, view: SchedulerView, job: JobInfo, c: Candidate) -> None:
        self._plan[job.job_id] = (planner.window_mean_forecast(view, job, c), c.w_mid)

    def after_placement(self, view: SchedulerView, d: Decision) -> None:
        if d.to is not None:
            job = view.job(d.job_id)
            c = planner.evaluate(view, job, d.to.dc_id, d.to.release_slot)
            self._remember(view, job, c)

    def _drifted(self, view: SchedulerView, job: JobInfo, inc: Candidate) -> bool:
        mean0, w_mid0 = self._plan.get(job.job_id, (None, None))
        mean = planner.window_mean_forecast(view, job, inc)
        if mean0 is not None and mean is not None and abs(mean - mean0) > self.epsilon * mean0:
            return True
        planned_start = inc.release_slot + inc.w_mid  # type: ignore[operator]
        horizon = max(planned_start - view.now_s, 0)
        return w_mid0 is not None and abs(inc.w_mid - w_mid0) > self.epsilon * horizon  # type: ignore[operator]

    def replan(self, view: SchedulerView, job: JobInfo, inc: Candidate) -> Iterator[Decision]:
        if not self._drifted(view, job, inc):
            return
        # The drift is measured from the last time the plan was examined, whatever the outcome:
        # otherwise one past drift would fire this job at every update from then on (D43).
        self._remember(view, job, inc)
        decisions = list(_accept_any_gain(self, view, job, inc))
        yield from decisions
        for d in decisions:
            self.after_placement(view, d)


class Pig(PlaceOnce):
    """Perfect-information greedy reference (PRD §11): placement and rescue as `place_once`, but
    through an `OracleView`. Greedy in arrival order, so not a bound on what is attainable."""

    name = "pig"
    uses_oracle = True

    def make_view(self, sim: Simulator) -> SchedulerView:
        from flipwise.simulator import OracleView

        return OracleView(sim)


class FixedSavings(Replanner):
    """Every update, every pending job: full re-score, then the benefit gate (PRD §11)."""

    name = "fixed_savings"

    def __init__(
        self,
        g_rel: float = 0.05,
        g_abs: float = 0.0,
        kappa_switch: float = 0.0,
        kappa_queue: float = 0.0,
        lambda_ovh: float = 0.0,
        cooldown_s: int = 1800,
        max_moves: int = 3,
    ) -> None:
        super().__init__(cooldown_s, max_moves)
        self.g_rel, self.g_abs = float(g_rel), float(g_abs)
        self.kappa_switch, self.kappa_queue = float(kappa_switch), float(kappa_queue)
        self.lambda_ovh = float(lambda_ovh)

    def gate(self, job: JobInfo, s_a: float) -> float:
        """`g_min(j)` (PRD §10.3)."""
        queued = self.kappa_queue if job.state == JobState.QUEUED else 0.0
        return max(self.g_abs, self.g_rel * s_a) + self.kappa_switch + queued + self.lambda_ovh

    def replan(self, view: SchedulerView, job: JobInfo, inc: Candidate) -> Iterator[Decision]:
        if self._throttled(view, job):
            yield Decision(job.job_id, "THROTTLED", s_a=inc.s_hat)
            return
        g = self.gate(job, inc.s_hat)
        b = self._best_for_replan(view, job)
        if b is None:
            yield Decision(job.job_id, "NO_ALTERNATIVE", s_a=inc.s_hat, g_min=g)
            return
        gain = inc.s_hat - b.s_hat
        # C7: `gain > 0` matters when the gate is 0, as for a zero-power job (PRD §10.5).
        if gain >= g and gain > 0:
            yield _to_candidate(job.job_id, "MOVE", b, s_a=inc.s_hat, g_min=g)
        else:
            yield Decision(job.job_id, "KEEP", s_a=inc.s_hat, s_b=b.s_hat, g_min=g)


POLICIES: dict[str, type[Policy]] = {
    "fcfs": Fcfs,
    "place_once": PlaceOnce,
    "periodic": Periodic,
    "pred_error": PredError,
    "fixed_savings": FixedSavings,
    "pig": Pig,
}


def make_policy(name: str, **params) -> Policy:
    try:
        cls = POLICIES[name]
    except KeyError:
        raise ConfigError(f"unknown policy {name!r}; known: {sorted(POLICIES)}") from None
    try:
        return cls(**params)
    except TypeError as e:
        raise ConfigError(f"policy {name}: bad parameters {sorted(params)}: {e}") from None
