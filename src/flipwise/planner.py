"""Candidates, feasibility and scoring (PRD §9). Shared by every policy (PRD §11)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from flipwise.carbon import lead_bucket as lead_bucket
from flipwise.models import PENDING, SLOT_S, Candidate, ceil_to_slot, floor_to_slot

if TYPE_CHECKING:
    from flipwise.simulator import JobInfo, SchedulerView

EPS_TIE_KG = 1e-9

NO_FIT = "NO_FIT"
OUT_OF_RANGE = "OUT_OF_RANGE"
NO_START = "NO_START"
DEADLINE_RISK = "DEADLINE_RISK"
NO_CARBON = "NO_CARBON"
QUANTILES = ("q05", "q50", "q95")
INTERVAL_MALFORMED = "INTERVAL_MALFORMED"
INTERVAL_TOO_WIDE = "INTERVAL_TOO_WIDE"
LB_ROUNDING_GUARD = 1 - 1e-12


@dataclass(frozen=True)
class PlannerParams:
    h_defer_s: int = 24 * 3600
    feasibility: str = "conservative"  # or "point" (ablation, PRD §9.5)


def release_range(job: JobInfo, now_s: int, params: PlannerParams) -> tuple[int, int]:
    slot0 = ceil_to_slot(now_s)
    latest = min(slot0 + params.h_defer_s, floor_to_slot(job.deadline_s - job.r_q90_s))
    return slot0, max(latest, slot0)


def evaluate(
    view: SchedulerView,
    job: JobInfo,
    dc_id: int,
    release_slot: int,
    incumbent: bool = False,
    intervals: bool = True,
    known_starts: dict[str, int | None] | None = None,
) -> Candidate:
    """Score one candidate and run the feasibility checks of PRD §9.5 in order.

    With `incumbent`, the candidate is the job's current plan: the job then keeps its own place
    in the projected order (§9.3, C3) and a past release is exempt from the Range check (§9.5).
    `intervals=False` skips `L` and `U`, which only the chosen candidates need; `known_starts`
    carries starts between ascending slots of one datacentre (see `_projected_starts`).
    """
    c = Candidate(dc_id, release_slot)
    dc = view.dcs[dc_id]
    if not job.request.fits_in(dc.cap):
        c.reject_reason = NO_FIT
        return c
    slot0, latest = release_range(job, view.now_s, view.params)
    if incumbent and job.state in PENDING:
        starts = {q: view.own_start(job, q) for q in QUANTILES}
    else:
        starts = _projected_starts(view, job, dc_id, release_slot, known_starts)
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
        p = table.point(release_slot + c.w_mid, job.r_q50_s)
        if p is not None:
            c.s_hat, c.extrapolated = k_kg * p[0], p[1]
        if intervals:
            add_interval(view, job, c)
    # A placed incumbent past `latest` can only be past it through the deadline term, so the
    # Deadline check below catches it with the reason that rescue acts on.
    if not incumbent and not slot0 <= release_slot <= latest:
        c.reject_reason = OUT_OF_RANGE
    elif _finish(c, job, view.params) > job.deadline_s:
        c.reject_reason = DEADLINE_RISK
    elif c.s_hat is None:
        c.reject_reason = NO_CARBON
    else:
        c.feasible = True
    return c


def _projected_starts(
    view: SchedulerView,
    job: JobInfo,
    dc_id: int,
    release_slot: int,
    known: dict[str, int | None] | None,
) -> dict[str, int | None]:
    """Projected start per runtime quantile. The earliest fit never moves back as the release gets
    later, so a start already found from an earlier slot still holds if it is not before this one.
    """
    if known is None:
        return {q: view.projected_start(dc_id, job, release_slot, q) for q in QUANTILES}
    starts = {}
    for q in QUANTILES:
        if q in known and (known[q] is None or known[q] >= release_slot):
            starts[q] = known[q]
        else:
            starts[q] = known[q] = view.projected_start(dc_id, job, release_slot, q)
    return starts


def add_interval(view: SchedulerView, job: JobInfo, c: Candidate) -> None:
    """`L_c` and `U_c` of PRD §9.4. Left as None when any needed slot is unknown."""
    if view.forecast is None or c.w_lo is None:
        return
    dc = view.dcs[c.dc_id]
    table = view.carbon_table(dc.region_id)
    k_kg = dc.pue * job.power_kw / 3600 / 1000
    lo = table.integrate(c.release_slot + c.w_lo, job.r_q05_s)
    hi = table.integrate(c.release_slot + c.w_hi, job.r_q95_s)
    if lo is not None and hi is not None:
        c.lower, c.upper = k_kg * lo[1], k_kg * hi[2]


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
        known: dict[str, int | None] = {}
        for s in range(slot0, latest + 1, SLOT_S):
            out.append(evaluate(view, job, dc_id, s, intervals=False, known_starts=known))
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


def rescore(view: SchedulerView, job: JobInfo) -> Candidate:
    """The job's current plan, scored now (PRD §10.3). One candidate."""
    return evaluate(view, job, job.dc_id, job.release_slot, incumbent=True, intervals=False)  # type: ignore[arg-type]


def alternatives(view: SchedulerView, job: JobInfo) -> list[Candidate]:
    """Every candidate except the current plan. Leaving a queue, even for the same datacentre,
    means joining the end of it, so those remain real alternatives (PRD §10.6)."""
    return [
        c
        for c in candidates(view, job)
        if (c.dc_id, c.release_slot) != (job.dc_id, job.release_slot)
    ]


def best_alternative(view: SchedulerView, job: JobInfo) -> Candidate | None:
    """Best feasible `b ≠ a` (PRD §10.5), or None."""
    return best_candidate(alternatives(view, job))


def finish_estimate(c: Candidate, job: JobInfo, params: PlannerParams) -> int | None:
    """Conservative finish `s + w_hi + r_q90`; None when the candidate has no projected start."""
    return None if c.w_hi is None else _finish(c, job, params)


def window_mean_forecast(view: SchedulerView, job: JobInfo, c: Candidate) -> float | None:
    """Mean forecast g/kWh over a candidate's point-estimate window (`pred_error`, PRD §11)."""
    if view.forecast is None or c.w_mid is None:
        return None
    p = view.carbon_table(view.dcs[c.dc_id].region_id).integrate(
        c.release_slot + c.w_mid, job.r_q50_s
    )
    return None if p is None else p[0] / max(job.r_q50_s, 1)


def lower_bound(view: SchedulerView, job: JobInfo) -> float:
    """`LB_j` (PRD §10.4): no feasible alternative can score lower, whatever the queues do.

    Waits only move a feasible candidate's start inside `[slot0, deadline − r_q90]`, so taking the
    cheapest start in that window at every eligible datacentre gives a sound bound. The factor
    keeps floating-point rounding from turning a tie into a false screen failure (P1).
    """
    if view.forecast is None:
        return math.inf
    slot0 = ceil_to_slot(view.now_s)
    finish_s = job.r_q50_s if view.params.feasibility == "point" else job.r_q90_s
    x_max = job.deadline_s - finish_s
    if x_max < slot0:
        return math.inf
    best = math.inf
    for dc_id in sorted(view.dcs):
        dc = view.dcs[dc_id]
        if not job.request.fits_in(dc.cap):
            continue
        cost = view.carbon_table(dc.region_id).min_window(slot0, x_max, job.r_q50_s)
        if cost is not None:
            best = min(best, dc.pue * job.power_kw / 3600 / 1000 * cost)
    return best * LB_ROUNDING_GUARD


def paired_width(
    view: SchedulerView, job: JobInfo, a: Candidate, b: Candidate, width: str = "full"
) -> float | None:
    """`w_ab` (PRD §10.5): forecast and wait spread of each option with runtime held at `r_q50`,
    plus the runtime term in the difference of the two. None if a needed slot is unknown.

    `width` selects the ablations of §14.6: `no_wait` (A3) holds waits at `w_mid`; `carbon_only`
    (A4) also drops the runtime term.
    """
    total = 0.0
    for c in (a, b):
        dc = view.dcs[c.dc_id]
        table = view.carbon_table(dc.region_id)
        k_kg = dc.pue * job.power_kw / 3600 / 1000
        w_lo, w_hi = (c.w_mid, c.w_mid) if width != "full" else (c.w_lo, c.w_hi)
        lo = table.integrate(c.release_slot + w_lo, job.r_q50_s)
        hi = table.integrate(c.release_slot + w_hi, job.r_q50_s)
        if lo is None or hi is None:
            return None
        total += k_kg * (hi[2] - lo[1])
    width_s = total / 2
    if width == "carbon_only":
        return width_s
    d95, d05 = _score_difference(view, job, a, b, "q95"), _score_difference(view, job, a, b, "q05")
    if d95 is None or d05 is None:
        return None
    return width_s + abs(d95 - d05) / 2


def _score_difference(
    view: SchedulerView, job: JobInfo, a: Candidate, b: Candidate, q: str
) -> float | None:
    """`Δ(r) = Ŝ_a(r) − Ŝ_b(r)`: the point scores with the same runtime `r` at both options."""
    scores = []
    for c in (a, b):
        dc = view.dcs[c.dc_id]
        p = view.carbon_table(dc.region_id).point(c.release_slot + c.w_mid, job.r_q(q))
        if p is None:
            return None
        scores.append(dc.pue * job.power_kw / 3600 / 1000 * p[0])
    return scores[0] - scores[1]


def interval_problem(a: Candidate, b: Candidate, width: float | None, w_max: float) -> str:
    """Which §10.7 fallback, if any, applies to this comparison; empty when none does."""
    for c in (a, b):
        if c.lower is None or c.upper is None:
            return INTERVAL_MALFORMED
        if not (math.isfinite(c.lower) and math.isfinite(c.upper)):
            return INTERVAL_MALFORMED
        if c.lower > c.s_hat or c.upper < c.s_hat:  # type: ignore[operator]
            return INTERVAL_MALFORMED
    if width is None or not math.isfinite(width):
        return INTERVAL_MALFORMED
    return INTERVAL_TOO_WIDE if width > w_max * a.s_hat else ""  # type: ignore[operator]


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
