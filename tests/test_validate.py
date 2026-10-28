import copy

import yaml

from flipwise.validate import check_splits

BASE = yaml.safe_load(open("configs/base.yaml"))


def test_base_splits_are_separated():
    assert check_splits(BASE) == []


def test_overlapping_windows_rejected():
    """PRD §14.3: validate refuses overlapping calibration/validation/test windows."""
    cfg = copy.deepcopy(BASE)
    cfg["splits"]["validation"]["carbon_period"] = ["2023-06-01", "2023-08-31"]
    cfg["splits"]["test"]["trace_days"] = [30, 70]
    errs = check_splits(cfg)
    assert any("carbon periods overlap" in e for e in errs)
    assert any("trace-day windows overlap" in e for e in errs)


def test_non_monday_and_horizon_overflow_rejected():
    cfg = copy.deepcopy(BASE)
    cfg["splits"]["validation"]["carbon_mondays"] = ["2023-07-04", "2023-08-28"]
    errs = check_splits(cfg)
    assert any("not a Monday" in e for e in errs)
    assert any("leaves its carbon period" in e for e in errs)
