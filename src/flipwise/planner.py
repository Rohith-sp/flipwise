"""Candidates, feasibility and scoring (PRD §9). Shared by every policy (PRD §11)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from flipwise.carbon import lead_bucket as lead_bucket
from flipwise.models import SLOT_S, Candidate, ceil_to_slot, floor_to_slot

if TYPE_CHECKING:
    from flipwise.simulator import JobInfo, SchedulerView

EPS_TIE_KG = 1e-9

NO_FIT = "NO_FIT"
OUT_OF_RANGE = "OUT_OF_RANGE"
NO_START = "NO_START"
DEADLINE_RISK = "DEADLINE_RISK"
NO_CARBON = "NO_CARBON"


@dataclass(frozen=True)
class PlannerParams:
    h_defer_s: int = 24 * 3600
    feasibility: str = "conservative"  # or "point" (ablation, PRD §9.5)


def release_range(job: JobInfo, now_s: int, params: PlannerParams) -> tuple[int, int]:
    slot0 = ceil_to_slot(now_s)
    latest = min(slot0 + params.h_defer_s, floor_to_slot(job.deadline_s - job.r_q90_s))
    return slot0, max(latest, slot0)


def evaluate(view: SchedulerView, job: JobInfo, dc_id: int, release_slot: int) -> Candidate:
    """Score one candidate and run the feasibility checks of PRD §9.5 in order."""
    c = Candidate(dc_id, release_slot)
    dc = view.dcs[dc_id]
    if not job.request.fits_in(dc.cap):
        c.reject_reason = NO_FIT
        return c
    slot0, latest = release_range(job, view.now_s, view.params)
    starts = {q: view.projected_start(dc_id, job, release_slot, q) for q in ("q05", "q50", "q95")}
    if any(s is None for s in starts.values()):
        c.reject_reason = NO_START
        return c
    c.s_q05, c.s_q50, c.s_q95 = starts["q05"], starts["q50"], starts["q95"]
    c.w_lo = min(starts.values()) - release_slot  # type: ignore[type-var,operator]
    c.w_mid = c.s_q50 - release_slot  # type: ignore[operator]
    c.w_hi = max(starts.values()) - release_slot  # type: ignore[type-var,operator]
    k_kg = dc.pue * job.power_kw / 3600 / 1000
    if view.forecast is not None:
        table = view.carbon_table(dc.region_id)
        p = table.integrate(release_slot + c.w_mid, job.r_q50_s)
        lo = table.integrate(release_slot + c.w_lo, job.r_q05_s)
        hi = table.integrate(release_slot + c.w_hi, job.r_q95_s)
        if p is not None:
            c.s_hat, c.extrapolated = k_kg * p[0], p[3]
        if lo is not None and hi is not None:
            c.lower, c.upper = k_kg * lo[1], k_kg * hi[2]
    if not slot0 <= release_slot <= latest:
        c.reject_reason = OUT_OF_RANGE
    elif _finish(c, job, view.params) > job.deadline_s:
        c.reject_reason = DEADLINE_RISK
    elif c.s_hat is None:
        c.reject_reason = NO_CARBON
    else:
        c.feasible = True
    return c


def _finish(c: Candidate, job: JobInfo, params: PlannerParams) -> int:
    if params.feasibility == "point":
        return c.release_slot + c.w_mid + job.r_q50_s  # type: ignore[operator]
    return c.release_slot + c.w_hi + job.r_q90_s  # type: ignore[operator]


def candidates(view: SchedulerView, job: JobInfo) -> list[Candidate]:
    """Every eligible datacentre × every release slot in range, in `(dc_id, slot)` order."""
    slot0, latest = release_range(job, view.now_s, view.params)
    out = []
    for dc_id in sorted(view.dcs):
        if not job.request.fits_in(view.dcs[dc_id].cap):
            continue
        for s in range(slot0, latest + 1, SLOT_S):
            out.append(evaluate(view, job, dc_id, s))
    return out


def _tie_key(c: Candidate) -> tuple:
    return (c.release_slot + c.w_mid, c.dc_id, c.release_slot)  # type: ignore[operator]


def best_candidate(cands: list[Candidate]) -> Candidate | None:
    """Minimum Ŝ among feasible candidates; ties within ε: earlier start, lower dc, earlier slot."""
    feas = [c for c in cands if c.feasible]
    if not feas:
        return None
    best_s = min(c.s_hat for c in feas)  # type: ignore[type-var]
    near = [c for c in feas if c.s_hat <= best_s + EPS_TIE_KG]  # type: ignore[operator]
    return min(near, key=_tie_key)


def fallback(cands: list[Candidate], job: JobInfo, params: PlannerParams) -> Candidate | None:
    """No feasible candidate: earliest conservative finish among those with a start (§9.5)."""
    usable = [c for c in cands if c.w_hi is not None]
    if not usable:
        return None
    return min(usable, key=lambda c: (_finish(c, job, params), *_tie_key(c)))


def earliest_start(view: SchedulerView, job: JobInfo, arrival_index: int = 0) -> Candidate | None:
    """FCFS: `(d, slot0)` with the earliest `s + w_mid`; carbon ignored (PRD §11).

    Ties go to datacentres in rotated order starting at `arrival_index mod N_dc`: always preferring
    dc0 would make this carbon-blind reference favour Delhi NCR's cleaner grid (PRD §11, v0.8).
    """
    slot0, _ = release_range(job, view.now_s, view.params)
    cands = [
        evaluate(view, job, d, slot0)
        for d in sorted(view.dcs)
        if job.request.fits_in(view.dcs[d].cap)
    ]
    usable = [c for c in cands if c.w_mid is not None]
    n_dc = len(view.dcs)

    def key(c: Candidate) -> tuple:
        return (c.release_slot + c.w_mid, (c.dc_id - arrival_index) % n_dc)  # type: ignore[operator]

    return min(usable, key=key) if usable else None
