import pytest

from flipwise.datacentre import InProcDatacentre
from flipwise.errors import MigrationError, SimulationInvariantError
from flipwise.models import DcConfig, Request


@pytest.fixture
def dc():
    return InProcDatacentre(DcConfig(0, 1, cap_gpu=4, cap_cpu=8, cap_mem_gb=10))


def test_fifo_first_fit_skips_blocked_head(dc):
    dc.enqueue(0, "big", Request(5, 1, 1), 10)  # never fits
    dc.enqueue(0, "a", Request(3, 1, 1), 10)
    dc.enqueue(0, "b", Request(2, 1, 1), 10)
    dc.enqueue(0, "c", Request(1, 1, 1), 10)
    started = dc.dispatch(0)
    assert [s.job_id for s in started] == ["a", "c"]
    assert dc.state().queue == ("big", "b")


def test_remove_running_raises_migration_r_sim_4(dc):
    dc.enqueue(0, "a", Request(1, 1, 1), 10)
    dc.dispatch(0)
    with pytest.raises(MigrationError):
        dc.remove(1, "a")


def test_time_backwards_and_bad_complete(dc):
    dc.enqueue(5, "a", Request(1, 1, 1), 10)
    with pytest.raises(SimulationInvariantError, match="TIME_BACKWARDS"):
        dc.dispatch(4)
    dc.dispatch(5)
    with pytest.raises(SimulationInvariantError):
        dc.complete(14, "a")
    dc.complete(15, "a")
    assert dc.state().used == Request(0, 0, 0)


def test_state_hides_runtime_and_end():
    """R-DEP-4 (shape): visible running info has no end time or runtime."""
    from dataclasses import fields

    from flipwise.models import RunningInfo

    names = {f.name for f in fields(RunningInfo)}
    assert not names & {"end_s", "runtime_actual_s"}
