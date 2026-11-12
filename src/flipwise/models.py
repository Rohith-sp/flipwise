"""Core data model (PRD §8.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

SLOT_S = 1800  # NESO settlement period (PRD §8.5)


def ceil_to_slot(t_s: int) -> int:
    return -(-t_s // SLOT_S) * SLOT_S


def floor_to_slot(t_s: int) -> int:
    return (t_s // SLOT_S) * SLOT_S


class JobState(StrEnum):
    NOT_ARRIVED = "NOT_ARRIVED"
    PLACED = "PLACED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


PENDING = (JobState.PLACED, JobState.QUEUED)
QUANTILE_FIELD = {"q05": "r_q05_s", "q50": "r_q50_s", "q90": "r_q90_s", "q95": "r_q95_s"}


class Priority(IntEnum):
    """Same-time event order (PRD §8.4)."""

    CARBON_UPDATE = 1
    JOB_COMPLETE = 2
    JOB_ARRIVAL = 3
    JOB_RELEASE = 4
    PERIODIC_TICK = 5
    DEADLINE = 6
    SIM_END = 7


@dataclass(frozen=True)
class Request:
    gpu: float
    cpu: float
    mem_gb: float

    def fits_in(self, free: Request, eps: float = 1e-9) -> bool:
        return (
            self.gpu <= free.gpu + eps
            and self.cpu <= free.cpu + eps
            and (self.mem_gb <= free.mem_gb + eps)
        )


@dataclass
class Job:
    job_id: str
    user: str
    arrival_s: int
    gpu_req: float
    cpu_req: float
    mem_req_gb: float
    r_q05_s: int
    r_q50_s: int
    r_q90_s: int
    r_q95_s: int
    deadline_s: int
    # Hidden from policies (PRD §8.7): only the datacentre and the evaluator read it.
    runtime_actual_s: int
    gpu_type: str = "NONE"  # sets the evaluator's datasheet power per GPU (§7.2, D58)
    # Measured use (GPUs, cores), for the evaluator's `measured` power only (D58); hidden.
    gpu_used: float | None = None
    cpu_used: float | None = None
    # Dynamic state.
    state: JobState = JobState.NOT_ARRIVED
    dc_id: int | None = None
    release_slot: int | None = None
    placed_at_s: int | None = None
    plan_capture_utc: int | None = None
    plan_score: float | None = None
    n_moves: int = 0
    version: int = 0
    start_s: int | None = None
    end_s: int | None = None
    rescued: int = 0
    deadline_risk: int = 0
    on_fallback: bool = False  # current plan is a no-feasible fallback (PRD §10.2)
    # Wait interval of the last placement, for wait coverage (PRD §14.1).
    plan_w_lo_s: int | None = None
    plan_w_hi_s: int | None = None

    @property
    def request(self) -> Request:
        return Request(self.gpu_req, self.cpu_req, self.mem_req_gb)

    def r_q(self, q: str) -> int:
        return getattr(self, QUANTILE_FIELD[q])


@dataclass(frozen=True)
class DcConfig:
    dc_id: int
    region_id: int
    cap_gpu: float
    cap_cpu: float
    cap_mem_gb: float
    pue: float = 1.0

    @property
    def cap(self) -> Request:
        return Request(self.cap_gpu, self.cap_cpu, self.cap_mem_gb)


@dataclass(frozen=True)
class RunningInfo:
    """What the scheduler may see of a running job: no end time, no actual runtime."""

    job_id: str
    start_s: int
    gpu_req: float
    cpu_req: float
    mem_req_gb: float


@dataclass(frozen=True)
class DcState:
    t_s: int
    cap: Request
    used: Request
    queue: tuple[str, ...]
    running: tuple[RunningInfo, ...]


@dataclass(frozen=True)
class Placement:
    dc_id: int
    release_slot: int


@dataclass(slots=True)
class Candidate:
    dc_id: int
    release_slot: int
    s_q05: int | None = None
    s_q50: int | None = None
    s_q95: int | None = None
    w_lo: int | None = None
    w_mid: int | None = None
    w_hi: int | None = None
    s_hat: float | None = None  # estimated emissions Ŝ, kg
    lower: float | None = None  # L, kg
    upper: float | None = None  # U, kg
    feasible: bool = False
    reject_reason: str | None = None
    extrapolated: bool = False

    @property
    def placement(self) -> Placement:
        return Placement(self.dc_id, self.release_slot)


@dataclass(order=True)
class Event:
    time_s: int
    priority: int
    seq: int
    kind: str = field(compare=False)
    job_id: str | None = field(default=None, compare=False)
    version: int = field(default=0, compare=False)
    payload: int | None = field(default=None, compare=False)
