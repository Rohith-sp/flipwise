"""Power, energy and emissions (PRD §7.1). Units: kW, kWh, gCO2/kWh, kgCO2."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field

from flipwise.models import SLOT_S, floor_to_slot

POWER_MODES = ("nameplate", "measured")


@dataclass(frozen=True)
class PowerModel:
    """Allocated power per job (PRD §7.2, D58).

    `nameplate`: requested GPUs at datasheet power per type, plus requested cores. `measured`:
    datasheet power scaled by the job's measured GPU use, plus measured cores; it leaves out idle
    draw, so the two bracket real consumption. The scheduler always uses `power_kw` (nameplate):
    it may know the request and GPU type, never how hard a job will use them (§8.7).
    """

    p_gpu_kw: float  # per GPU, for any type not in gpu_kw_by_type (the toy uses only this)
    p_cpu_kw: float  # per core
    gpu_kw_by_type: Mapping[str, float] = field(default_factory=dict)
    mode: str = "nameplate"

    def __post_init__(self) -> None:
        if self.mode not in POWER_MODES:
            raise ValueError(f"power mode must be one of {POWER_MODES}, got {self.mode!r}")

    def gpu_kw(self, gpu_type: str | None) -> float:
        return float(self.gpu_kw_by_type.get(gpu_type or "", self.p_gpu_kw))

    def power_kw(self, gpu_req: float, cpu_req: float, gpu_type: str | None = None) -> float:
        """Nameplate power: what the scheduler scores with."""
        return gpu_req * self.gpu_kw(gpu_type) + cpu_req * self.p_cpu_kw

    def actual_kw(
        self,
        gpu_req: float,
        cpu_req: float,
        gpu_type: str | None,
        gpu_used: float | None,
        cpu_used: float | None,
    ) -> float:
        """Evaluator power. In `measured` mode a missing measurement is an error, not a guess:
        `ingest usage` already filled every job (D58)."""
        if self.mode == "nameplate":
            return self.power_kw(gpu_req, cpu_req, gpu_type)
        if gpu_used is None or cpu_used is None:
            raise ValueError("measured power needs gpu_used and cpu_used for every job")
        share = min(1.0, gpu_used / gpu_req) if gpu_req > 0 else 0.0
        return gpu_req * self.gpu_kw(gpu_type) * share + cpu_used * self.p_cpu_kw


def slot_overlaps(start_s: int, duration_s: int) -> Iterator[tuple[int, int]]:
    """Yield `(slot_utc, overlap_s)` for every slot overlapped by `[start, start + duration)`."""
    if duration_s < 0:
        raise ValueError(f"negative duration {duration_s}")
    end = start_s + duration_s
    k = floor_to_slot(start_s)
    while k < end:
        tau = min(end, k + SLOT_S) - max(start_s, k)
        if tau > 0:
            yield k, tau
        k += SLOT_S


def energy_kwh(power_kw: float, duration_s: int, pue: float = 1.0) -> float:
    if duration_s < 0:
        raise ValueError(f"negative duration {duration_s}")
    return pue * power_kw * duration_s / 3600


def emissions_kg(
    power_kw: float,
    start_s: int,
    duration_s: int,
    intensity: Callable[[int], float],
    pue: float = 1.0,
) -> float:
    """M = Σ_k PUE · P · (τ_k / 3600) · I(k) / 1000, with `intensity(slot) -> g/kWh`."""
    total_g = 0.0
    for k, tau in slot_overlaps(start_s, duration_s):
        g = intensity(k)
        if g < 0:
            raise ValueError(f"negative intensity {g} at slot {k}")
        total_g += pue * power_kw * tau / 3600 * g
    return total_g / 1000
