import pandas as pd
import pytest

from flipwise.carbon import ForecastStore, interpolate_truth
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
