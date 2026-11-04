import random

import pandas as pd
import pytest

from flipwise.carbon import (
    CarbonTable,
    ForecastStore,
    Residuals,
    fit_residuals,
    interpolate_truth,
)
from flipwise.errors import CarbonDataError

S = 1800


def _store():
    # Change-log: slot 0 is 100 from capture 0, 150 from capture 2S; slot S is 200 from 0;
    # slot 2S appears only at capture 2S. Slot 3S never appears.
    f = pd.DataFrame(
        [(1, 0, 0, 100.0), (1, 0, 2 * S, 150.0), (1, S, 0, 200.0), (1, 2 * S, 2 * S, 300.0)],
        columns=["region_id", "slot_utc", "capture_utc", "forecast_g_per_kwh"],
    )
    cov = pd.DataFrame(
        [(0, 0, 2 * S), (S, 0, 3 * S), (2 * S, 0, 6 * S)],
        columns=["capture_utc", "window_first_utc", "window_last_utc"],
    )
    return ForecastStore(f, cov, [1])


def test_vintage_reconstruction_r_ing_3():
    st = _store()
    assert st.latest_capture(S + 5) == S
    v1 = st.at(S)
    assert v1.get(1, 0).g_per_kwh == 100.0  # last change with capture ≤ v
    assert v1.get(1, S).g_per_kwh == 200.0
    assert v1.get(1, 2 * S).g_per_kwh == 200.0  # missing → persistence from slot S
    v2 = st.at(2 * S)
    assert v2.get(1, 0).g_per_kwh == 150.0
    assert v2.get(1, 2 * S).g_per_kwh == 300.0
    assert v2.get(1, 4 * S).g_per_kwh == 300.0  # 2 slots back: still persisted
    assert v2.get(1, 5 * S) is None  # 3 slots back: unknown
    ex = v2.get(1, 7 * S)  # beyond the window: extrapolated from the last known slot
    assert ex.extrapolated and ex.g_per_kwh == 300.0


def test_unknown_capture_raises():
    with pytest.raises(CarbonDataError):
        _store().at(123)


def test_truth_interpolation_and_gap_r_ing_4():
    s = pd.Series([100.0, 400.0], index=[0, 3 * S])  # 2-slot gap: interpolated
    out = interpolate_truth(s)
    assert list(out["truth_g_per_kwh"]) == [100.0, 200.0, 300.0, 400.0]
    assert list(out["interpolated"]) == [0, 1, 1, 0]
    with pytest.raises(CarbonDataError):
        interpolate_truth(pd.Series([1.0, 2.0], index=[0, 4 * S]))  # 3-slot gap


def _slow_integrate(vintage, region, e05, e95, start, dur):
    """The slot-by-slot definition of PRD §9.4 that `CarbonTable` must reproduce."""
    from flipwise.carbon import WIDEST_BUCKET, lead_bucket
    from flipwise.energy import slot_overlaps

    point = lo = hi = 0.0
    extrapolated = False
    for k, tau in slot_overlaps(start, dur):
        sv = vintage.get(region, k)
        if sv is None:
            return None
        extrapolated |= sv.extrapolated
        b = WIDEST_BUCKET if sv.extrapolated else lead_bucket(k, vintage.capture_utc)
        point += tau * sv.g_per_kwh
        lo += tau * max(0.0, sv.g_per_kwh + e05[b])
        hi += tau * (sv.g_per_kwh + e95[b])
    return point, lo, hi, extrapolated


def test_carbon_table_matches_slot_by_slot_definition():
    """Prefix sums, persistence, unknown slots and extrapolation all agree with the loop."""
    rng = random.Random(7)
    e05, e95 = (-200.0, -150.0, -100.0, -50.0), (10.0, 20.0, 30.0, 40.0)
    for _ in range(50):
        first = 96 * S
        n = rng.randint(2, 60)
        kept = [i for i in range(n) if i == 0 or rng.random() > 0.2]
        f = pd.DataFrame(
            [(1, first + i * S, first, float(rng.randint(0, 900))) for i in kept],
            columns=["region_id", "slot_utc", "capture_utc", "forecast_g_per_kwh"],
        )
        cov = pd.DataFrame(
            [(first, first, first + (n - 1) * S)],
            columns=["capture_utc", "window_first_utc", "window_last_utc"],
        )
        vintage = ForecastStore(f, cov, [1]).at(first)
        table = CarbonTable(vintage, 1, e05, e95)
        for _ in range(40):
            start, dur = first + rng.randrange(0, (n + 4) * S), rng.randrange(1, 12 * S)
            got = table.integrate(start, dur)
            want = _slow_integrate(vintage, 1, e05, e95, start, dur)
            if want is None:
                assert got is None
            else:
                assert got[:3] == pytest.approx(want[:3], abs=1e-6)
                assert got[3] == want[3]


def _residual_inputs(regions=(1,)):
    # Two captures, F = 100 everywhere; A rises with the slot, and the slot past `hi` is huge.
    rows, truth = [], []
    for r in regions:
        for c in (0, S):
            rows += [(r, k * S, c, 100.0) for k in range(c // S, 100)]
        truth += [(r, k * S, 100.0 + k) for k in range(100)]
    f = pd.DataFrame(rows, columns=["region_id", "slot_utc", "capture_utc", "forecast_g_per_kwh"])
    cov = pd.DataFrame(
        [(0, 0, 99 * S), (S, S, 99 * S)],
        columns=["capture_utc", "window_first_utc", "window_last_utc"],
    )
    t = pd.DataFrame(truth, columns=["region_id", "slot_utc", "truth_g_per_kwh"])
    return f, cov, t


def test_fit_residuals_expands_vintages_and_stays_in_period():
    """PRD §6.8: a slot unchanged between captures still counts once per capture; slots at or
    past the end of the period are ignored, however large their error."""
    f, cov, t = _residual_inputs()
    t.loc[t.slot_utc >= 90 * S, "truth_g_per_kwh"] = 1e6
    # Only capture 0's rows: the change-log says nothing changed at capture S.
    res, report = fit_residuals(f[f.capture_utc == 0], cov, t, [1], 0, 90 * S)
    assert report["mode"] == "pooled"  # far below 500 per bucket
    assert report["counts"][1][0] == 12 + 12  # bucket [0, 6 h): 12 slots at each capture
    assert max(res.e95) < 100.0  # errors are k <= 89 g/kWh here, never the 1e6 past the period
    assert Residuals(res.e05, res.e95).for_region(1) == (res.e05, res.e95)
