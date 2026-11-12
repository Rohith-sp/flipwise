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


def test_power_bracket_d58():
    """D58: nameplate charges datasheet power per GPU type; measured scales GPU power by the
    measured share (capped at 1) and charges the cores actually used."""
    pm = PowerModel(0.3, 0.01, {"T4": 0.07, "P100": 0.25}, mode="measured")
    assert pm.nameplate_kw(2, 4, "T4") == pytest.approx(2 * 0.07 + 4 * 0.01)
    assert pm.nameplate_kw(1, 0, "MISSING") == pytest.approx(0.3)  # unknown type: p_gpu_kw
    # The scheduler's scale ignores type and measurement (F24): decisions stay as frozen.
    assert pm.power_kw(2, 4) == pytest.approx(2 * 0.3 + 4 * 0.01)
    # 2 P100 requested, 0.5 GPU in use on average, 3 cores used.
    assert pm.actual_kw(2, 8, "P100", 0.5, 3) == pytest.approx(2 * 0.25 * 0.25 + 3 * 0.01)
    assert pm.actual_kw(1, 0, "P100", 4.0, 0) == pytest.approx(0.25)  # share capped at 1
    assert pm.actual_kw(0, 2, "NONE", 0.0, 1.5) == pytest.approx(0.015)  # CPU-only job
    nameplate = PowerModel(0.3, 0.01, {"P100": 0.25})
    assert nameplate.actual_kw(2, 8, "P100", 0.5, 3) == nameplate.nameplate_kw(2, 8, "P100")
    assert nameplate.actual_kw(2, 8, "P100", None, None) == nameplate.nameplate_kw(2, 8, "P100")


def test_measured_power_refuses_missing_usage_d58():
    with pytest.raises(ValueError, match="gpu_used"):
        PowerModel(0.3, 0.01, mode="measured").actual_kw(1, 1, "T4", None, 1.0)
    with pytest.raises(ValueError, match="power mode"):
        PowerModel(0.3, 0.01, mode="typo")
