import pytest

from flipwise.energy import PowerModel, emissions_kg, energy_kwh, slot_overlaps


def test_hand_example_r_en_1():
    """R-EN-1: 2 GPUs at 1 kW, start 00:15, 90 min, slots 100/200/300/400 g/kWh."""
    pm = PowerModel(p_gpu_kw=1.0, p_cpu_kw=0.01)
    p = pm.power_kw(gpu_req=2, cpu_req=0)
    start, dur = 900, 5400
    per_slot = {0: 100.0, 1800: 200.0, 3600: 300.0, 5400: 400.0}
    kwh = [p * tau / 3600 for _, tau in slot_overlaps(start, dur)]
    assert kwh == pytest.approx([0.5, 1.0, 1.0, 0.5], abs=1e-9)
    assert energy_kwh(p, dur) == pytest.approx(3.0, abs=1e-9)
    assert emissions_kg(p, start, dur, per_slot.__getitem__) == pytest.approx(0.75, abs=1e-9)


def test_static_factor_r_en_4():
    """R-EN-4: with a constant intensity c, M / E == c / 1000 for any start and duration."""
    p = PowerModel(1.0, 0.01).power_kw(3, 7)
    for start, dur in [(0, 1), (17, 1800), (1799, 7201), (12345, 98765)]:
        m = emissions_kg(p, start, dur, lambda _k: 250.0)
        assert m / energy_kwh(p, dur) == pytest.approx(0.25, rel=1e-12)


def test_negative_inputs_raise():
    with pytest.raises(ValueError):
        energy_kwh(1.0, -1)
    with pytest.raises(ValueError):
        emissions_kg(1.0, 0, 60, lambda _k: -1.0)
