"""Carbon views: forecast by vintage (scheduler) and truth (evaluator only). PRD §6.2, §6.7."""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass
from itertools import accumulate

import numpy as np
import pandas as pd

from flipwise.errors import CarbonDataError
from flipwise.models import SLOT_S, floor_to_slot

MAX_PERSIST_SLOTS = 2  # PRD §6.2 missing-slot rule
LEAD_BUCKETS_S = (6 * 3600, 12 * 3600, 24 * 3600)  # [0,6h) [6,12h) [12,24h) [24h,∞)
WIDEST_BUCKET = len(LEAD_BUCKETS_S)
MIN_RESIDUALS_PER_REGION_BUCKET = 500  # PRD §6.8


def lead_bucket(slot_utc: int, capture_utc: int) -> int:
    lead = slot_utc - capture_utc
    for b, edge in enumerate(LEAD_BUCKETS_S):
        if lead < edge:
            return b
    return WIDEST_BUCKET


@dataclass(frozen=True)
class Residuals:
    """Per lead-bucket residual quantiles e05(b), e95(b) in g/kWh (PRD §6.8): pooled, or per
    region in `by_region` when every region has enough residuals in every bucket."""

    e05: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0)
    e95: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0)
    by_region: dict[int, tuple[tuple[float, ...], tuple[float, ...]]] | None = None

    def for_region(self, region_id: int) -> tuple[tuple[float, ...], tuple[float, ...]]:
        if self.by_region is not None:
            return self.by_region[region_id]
        return self.e05, self.e95


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

    def items(self, region_id: int) -> list[tuple[int, float]]:
        """The `(slot, g/kWh)` pairs this capture holds, without persistence or extrapolation."""
        return sorted(self._values.get(region_id, {}).items())

    def _last_slot(self, region_id: int) -> int | None:
        vals = self._values.get(region_id, {})
        for k in range(floor_to_slot(self.window_last_utc), self.capture_utc - 3 * SLOT_S, -SLOT_S):
            if k in vals:
                return k
        return None


class CarbonTable:
    """Prefix sums of F, L and U for one `(vintage, region)`, so a score costs O(1) (PRD §9.4).

    Built from `ForecastVintage.get`, which stays the single source of the persistence and
    extrapolation rules. Plain Python floats keep the sums independent of numpy's build.
    """

    def __init__(
        self,
        vintage: ForecastVintage,
        region_id: int,
        e05: tuple[float, ...],
        e95: tuple[float, ...],
    ) -> None:
        self.first_s = floor_to_slot(vintage.capture_utc)
        self.n = max(0, (floor_to_slot(vintage.window_last_utc) - self.first_s) // SLOT_S + 1)
        self.stop_s = self.first_s + self.n * SLOT_S
        f: list[float] = []
        lo: list[float] = []
        hi: list[float] = []
        unknown: list[int] = []
        for i in range(self.n):
            k = self.first_s + i * SLOT_S
            sv = vintage.get(region_id, k)
            b = lead_bucket(k, vintage.capture_utc)
            unknown.append(int(sv is None))
            f.append(0.0 if sv is None else sv.g_per_kwh)
            lo.append(0.0 if sv is None else max(0.0, sv.g_per_kwh + e05[b]))
            hi.append(0.0 if sv is None else sv.g_per_kwh + e95[b])
        self._series = (f, lo, hi)
        self._prefix = tuple(list(accumulate(s, initial=0.0)) for s in self._series)
        self._unknown = list(accumulate(unknown, initial=0))
        tail = vintage.get(region_id, self.stop_s)
        self._tail = (
            None
            if tail is None
            else (
                tail.g_per_kwh,
                max(0.0, tail.g_per_kwh + e05[WIDEST_BUCKET]),
                tail.g_per_kwh + e95[WIDEST_BUCKET],
            )
        )

    def _cumulative(self, which: int, x_s: int) -> float:
        """∫ series from `first_s` to `x_s`, in s·g/kWh."""
        i, rem = divmod(x_s - self.first_s, SLOT_S)
        if i >= self.n:
            over = x_s - self.stop_s
            tail = self._tail[which] * over if over else 0.0  # type: ignore[index]
            return self._prefix[which][self.n] * SLOT_S + tail
        return self._prefix[which][i] * SLOT_S + rem * self._series[which][i]

    def point(self, start_s: int, dur_s: int) -> tuple[float, bool] | None:
        """`(Σ τ·F, extrapolated)`: `integrate` for the one series every candidate needs."""
        end_s = start_s + dur_s
        if start_s < self.first_s:
            return None
        extrapolated = end_s > self.stop_s
        if extrapolated and self._tail is None:
            return None
        i0 = min((start_s - self.first_s) // SLOT_S, self.n)
        i1 = min(-(-(end_s - self.first_s) // SLOT_S), self.n)
        if i1 > i0 and self._unknown[i1] != self._unknown[i0]:
            return None
        return self._cumulative(0, end_s) - self._cumulative(0, start_s), extrapolated

    def integrate(self, start_s: int, dur_s: int) -> tuple[float, float, float, bool] | None:
        """`(Σ τ·F, Σ τ·L, Σ τ·U, extrapolated)` over `[start, start + dur)`; None if unknown."""
        end_s = start_s + dur_s
        if start_s < self.first_s:
            return None
        extrapolated = end_s > self.stop_s
        if extrapolated and self._tail is None:
            return None
        i0 = min((start_s - self.first_s) // SLOT_S, self.n)
        i1 = min(-(-(end_s - self.first_s) // SLOT_S), self.n)
        if i1 > i0 and self._unknown[i1] != self._unknown[i0]:
            return None
        point, lo, hi = (
            self._cumulative(w, end_s) - self._cumulative(w, start_s) for w in (0, 1, 2)
        )
        return point, lo, hi, extrapolated


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

    def as_vintage(self, first_slot_utc: int) -> ForecastVintage:
        """Truth in the shape of a forecast, for the `pig` reference's `OracleView` only."""
        values: dict[int, dict[int, float]] = {}
        for (r, k), x in self._v.items():
            values.setdefault(r, {})[k] = x
        return ForecastVintage(first_slot_utc, max(k for _, k in self._v), values)


def fit_residuals(
    forecast: pd.DataFrame,
    coverage: pd.DataFrame,
    truth: pd.DataFrame,
    region_ids: list[int],
    lo_s: int,
    hi_s: int,
) -> tuple[Residuals, dict]:
    """Fit e05, e95 of `e = A − F` per lead bucket on the calibration period (PRD §6.8).

    Every `(r, k, v)` counts, so vintages are expanded: `forecast` is a change-log, and using its
    rows directly would drop the captures where a slot did not change. Slots must also lie inside
    `[lo_s, hi_s)`, because a late capture's window reaches into the validation period.
    """
    t = truth[truth["region_id"].isin(region_ids) & truth["slot_utc"].between(lo_s, hi_s - 1)]
    actual = {
        (int(r), int(k)): float(x)
        for r, k, x in zip(t["region_id"], t["slot_utc"], t["truth_g_per_kwh"], strict=True)
    }
    f = forecast[forecast["slot_utc"].between(lo_s, hi_s - 1)]
    cov = coverage[coverage["capture_utc"].between(lo_s, hi_s - 1)]
    store = ForecastStore(f, cov, region_ids)
    by_bucket: dict[tuple[int, int], list[float]] = defaultdict(list)
    for capture in store.captures:
        vintage = store.at(capture)
        for r in store.region_ids:
            for k, value in vintage.items(r):
                if k >= capture and (r, k) in actual:
                    by_bucket[(r, lead_bucket(k, capture))].append(actual[(r, k)] - value)

    buckets = range(WIDEST_BUCKET + 1)
    counts = {r: [len(by_bucket[(r, b)]) for b in buckets] for r in store.region_ids}
    if not all(all(counts[r]) for r in store.region_ids):
        raise CarbonDataError(f"no residuals in some lead bucket: {counts}")

    def quantiles(values_of) -> tuple[tuple[float, ...], tuple[float, ...]]:
        q = [np.quantile(values_of(b), [0.05, 0.95], method="linear") for b in buckets]
        return tuple(float(x[0]) for x in q), tuple(float(x[1]) for x in q)

    e05, e95 = quantiles(lambda b: np.concatenate([by_bucket[(r, b)] for r in store.region_ids]))
    per_region = all(
        n >= MIN_RESIDUALS_PER_REGION_BUCKET for r in store.region_ids for n in counts[r]
    )
    by_region = (
        {r: quantiles(lambda b, r=r: by_bucket[(r, b)]) for r in store.region_ids}
        if per_region
        else None
    )
    report = {"mode": "per_region" if per_region else "pooled", "counts": counts}
    return Residuals(e05, e95, by_region), report


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
