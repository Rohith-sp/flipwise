"""Carbon views: forecast by vintage (scheduler) and truth (evaluator only). PRD §6.2, §6.7."""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass

import pandas as pd

from flipwise.errors import CarbonDataError
from flipwise.models import SLOT_S, floor_to_slot

MAX_PERSIST_SLOTS = 2  # PRD §6.2 missing-slot rule


@dataclass(frozen=True)
class SlotValue:
    g_per_kwh: float
    extrapolated: bool = False


class ForecastVintage:
    """F(r, ·, v): the forecast as it stood at capture `v`."""

    def __init__(self, capture_utc: int, window_last_utc: int, values: dict[int, dict[int, float]]):
        self.capture_utc = capture_utc
        self.window_last_utc = window_last_utc
        self._values = values  # region -> slot -> g/kWh

    def get(self, region_id: int, slot_utc: int) -> SlotValue | None:
        """Value for one slot, applying persistence and extrapolation; None if unknown."""
        vals = self._values.get(region_id, {})
        if slot_utc > self.window_last_utc:
            last = self._last_slot(region_id)
            return None if last is None else SlotValue(vals[last], extrapolated=True)
        for back in range(MAX_PERSIST_SLOTS + 1):
            v = vals.get(slot_utc - back * SLOT_S)
            if v is not None:
                return SlotValue(v)
        return None

    def _last_slot(self, region_id: int) -> int | None:
        vals = self._values.get(region_id, {})
        for k in range(floor_to_slot(self.window_last_utc), self.capture_utc - 3 * SLOT_S, -SLOT_S):
            if k in vals:
                return k
        return None


class ForecastStore:
    """Reconstructs vintages from the change-log (R-ING-3).

    A row `(r, k, c, value)` means the forecast for slot `k` became `value` at capture `c` and
    stayed so until the next row for `(r, k)`. A vintage only covers slots in its capture window.
    """

    def __init__(self, forecast: pd.DataFrame, coverage: pd.DataFrame, region_ids: list[int]):
        self.region_ids = sorted(region_ids)
        hist: dict[tuple[int, int], tuple[list[int], list[float]]] = defaultdict(lambda: ([], []))
        f = forecast[forecast["region_id"].isin(self.region_ids)].sort_values(
            ["region_id", "slot_utc", "capture_utc"], kind="stable"
        )
        for r, k, c, val in zip(
            f["region_id"], f["slot_utc"], f["capture_utc"], f["forecast_g_per_kwh"], strict=True
        ):
            caps, vals = hist[(int(r), int(k))]
            caps.append(int(c))
            vals.append(float(val))
        self._hist = dict(hist)
        cov = coverage.sort_values("capture_utc", kind="stable")
        self.captures: list[int] = [int(c) for c in cov["capture_utc"]]
        self._window = dict(
            zip(
                (int(c) for c in cov["capture_utc"]),
                (int(w) for w in cov["window_last_utc"]),
                strict=True,
            )
        )
        self._first = dict(
            zip(
                (int(c) for c in cov["capture_utc"]),
                (int(w) for w in cov["window_first_utc"]),
                strict=True,
            )
        )
        self._cache: dict[int, ForecastVintage] = {}

    def latest_capture(self, t_s: int) -> int | None:
        i = bisect.bisect_right(self.captures, t_s)
        return self.captures[i - 1] if i else None

    def at(self, capture_utc: int) -> ForecastVintage:
        if capture_utc not in self._window:
            raise CarbonDataError(f"no recorded capture at {capture_utc}")
        v = self._cache.get(capture_utc)
        if v is None:
            v = self._build(capture_utc)
            self._cache = {capture_utc: v}  # vintages are used in time order; keep one
        return v

    def _build(self, capture_utc: int) -> ForecastVintage:
        first = floor_to_slot(self._first[capture_utc])
        last = self._window[capture_utc]
        values: dict[int, dict[int, float]] = {}
        for r in self.region_ids:
            rv: dict[int, float] = {}
            for k in range(first, last + 1, SLOT_S):
                h = self._hist.get((r, k))
                if h is None:
                    continue
                i = bisect.bisect_right(h[0], capture_utc)
                if i:
                    rv[k] = h[1][i - 1]
            values[r] = rv
        return ForecastVintage(capture_utc, last, values)


class Truth:
    """A(r, k): evaluator-only intensities. Never handed to a policy (PRD §8.7)."""

    def __init__(self, truth: pd.DataFrame):
        self._v = {
            (int(r), int(k)): float(x)
            for r, k, x in zip(
                truth["region_id"], truth["slot_utc"], truth["truth_g_per_kwh"], strict=True
            )
        }

    def get(self, region_id: int, slot_utc: int) -> float:
        try:
            return self._v[(region_id, slot_utc)]
        except KeyError:
            raise CarbonDataError(f"no truth for region {region_id} slot {slot_utc}") from None


def interpolate_truth(series: pd.Series, max_gap_slots: int = MAX_PERSIST_SLOTS) -> pd.DataFrame:
    """Fill gaps of ≤ `max_gap_slots` linearly (R-ING-4). `series` is indexed by slot_utc.

    Returns columns `slot_utc, truth_g_per_kwh, interpolated`; raises on longer gaps.
    """
    s = series.sort_index()
    full = range(int(s.index.min()), int(s.index.max()) + 1, SLOT_S)
    s = s.reindex(full)
    missing = s.isna()
    run = (missing != missing.shift()).cumsum()
    gap_len = missing.groupby(run).transform("sum")
    if (gap_len[missing] > max_gap_slots).any():
        bad = int(s.index[missing & (gap_len > max_gap_slots)][0])
        raise CarbonDataError(f"truth gap longer than {max_gap_slots} slots at slot {bad}")
    filled = s.interpolate(method="linear")
    return pd.DataFrame(
        {
            "slot_utc": list(full),
            "truth_g_per_kwh": filled.to_numpy(),
            "interpolated": missing.astype(int).to_numpy(),
        }
    )
