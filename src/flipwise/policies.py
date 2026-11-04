"""Scheduling policies (PRD §11). They differ only in trigger and acceptance; everything else
(candidates, feasibility, scoring, dispatch) is shared."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from flipwise import planner
from flipwise.errors import ConfigError
from flipwise.models import Placement

if TYPE_CHECKING:
    from flipwise.simulator import SchedulerView


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


class Policy:
    name = "base"
    uses_oracle = False
    tick_s: int | None = None  # interval of PERIODIC_TICK events, if the policy wants them

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
        self._arrivals = 0

    def on_arrival(self, view: SchedulerView, job_id: str) -> Decision:
        job = view.job(job_id)
        c = planner.earliest_start(view, job, self._arrivals)
        self._arrivals += 1
        if c is None:
            return Decision(job_id, "REJECT", reason="NO_START")
        return Decision(job_id, "PLACE", c.placement, s_b=c.s_hat)


class PlaceOnce(Policy):
    """Best Ŝ among feasible candidates at arrival; no re-planning (rescue arrives in phase 5)."""

    name = "place_once"

    def on_arrival(self, view: SchedulerView, job_id: str) -> Decision:
        return initial_placement(view, job_id)


def initial_placement(view: SchedulerView, job_id: str) -> Decision:
    """Best feasible candidate, else the no-feasible fallback (PRD §9.5)."""
    job = view.job(job_id)
    cands = planner.candidates(view, job)
    best = planner.best_candidate(cands)
    if best is not None:
        return Decision(job_id, "PLACE", best.placement, s_b=best.s_hat)
    fb = planner.fallback(cands, job, view.params)
    if fb is None:
        return Decision(job_id, "REJECT", reason="NO_START")
    return Decision(
        job_id,
        "FALLBACK",
        fb.placement,
        s_b=fb.s_hat,
        reason="FALLBACK_EARLIEST_FINISH",
        deadline_risk=True,
    )


POLICIES: dict[str, type[Policy]] = {"fcfs": Fcfs, "place_once": PlaceOnce}


def make_policy(name: str, **params) -> Policy:
    try:
        cls = POLICIES[name]
    except KeyError:
        raise ConfigError(f"unknown policy {name!r}; known: {sorted(POLICIES)}") from None
    return cls(**params)
