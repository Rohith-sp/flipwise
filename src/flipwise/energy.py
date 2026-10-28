"""Power, energy and emissions (PRD §7.1). Units: kW, kWh, gCO2/kWh, kgCO2."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from flipwise.models import SLOT_S, floor_to_slot


@dataclass(frozen=True)
class PowerModel:
    p_gpu_kw: float  # per GPU
    p_cpu_kw: float  # per core

    def power_kw(self, gpu_req: float, cpu_req: float) -> float:
        return gpu_req * self.p_gpu_kw + cpu_req * self.p_cpu_kw


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
