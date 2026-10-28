"""Scheduling policies (PRD §11). They differ only in trigger and acceptance; everything else
(candidates, feasibility, scoring, dispatch) is shared."""

from __future__ import annotations

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


class Policy:
    name = "base"
    uses_oracle = False

    def on_arrival(self, view: SchedulerView, job_id: str) -> Decision:
        raise NotImplementedError

    def on_carbon_update(self, view: SchedulerView) -> list[Decision]:
        return []


class Fcfs(Policy):
    """Non-carbon-aware reference: earliest projected start, never deferred or re-planned."""

    name = "fcfs"

    def on_arrival(self, view: SchedulerView, job_id: str) -> Decision:
        job = view.job(job_id)
        c = planner.earliest_start(view, job)
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
