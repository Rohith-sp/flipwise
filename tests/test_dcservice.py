"""The datacentre service and its client (PRD §13.5, R-DEP-1, R-DEP-3, R-DEP-4, R-DEP-7)."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from flipwise.datacentre import InProcDatacentre
from flipwise.dcservice import PROTOCOL_VERSION, HttpDatacentre, make_server
from flipwise.errors import DeploymentError, MigrationError, SimulationInvariantError
from flipwise.experiment import ALL_POLICIES
from flipwise.models import DcConfig, Request
from flipwise.policies import make_policy
from flipwise.reporting import write_run
from flipwise.simulator import Simulator

CFG = DcConfig(0, 1, 4.0, 32.0, 100.0)
SMALL = Request(1.0, 2.0, 3.0)
BIG = Request(4.0, 2.0, 3.0)


class Running:
    """A service on a free local port, in a thread of this process."""

    def __init__(self, dc_id=0):
        self.server = make_server(dc_id, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


@pytest.fixture
def service():
    running = Running()
    yield running
    running.stop()


@pytest.fixture
def client(service):
    c = HttpDatacentre(service.url)
    c.reset(CFG, "h")
    return c


def _status(url, path, method="POST", body=None):
    data = json.dumps(body or {}).encode()
    request = urllib.request.Request(url + path, data=data, method=method)
    try:
        with urllib.request.urlopen(request) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _enqueue_body(t, job_id, runtime=100):
    return {
        "t": t,
        "job_id": job_id,
        "gpu_req": 1.0,
        "cpu_req": 1.0,
        "mem_req_gb": 1.0,
        "runtime_actual_s": runtime,
    }


def test_health_reports_identity_and_protocol(service):
    assert HttpDatacentre(service.url).health() == {
        "status": "ok",
        "dc_id": 0,
        "protocol_version": PROTOCOL_VERSION,
    }


def _script(dc):
    """One sequence touching every call. Returns everything a caller could observe."""
    seen = [
        dc.enqueue(0, "a", BIG, 100),
        dc.enqueue(0, "b", BIG, 50),
        dc.enqueue(0, "c", SMALL, 10),
    ]
    seen += [dc.dispatch(0), dc.state()]
    dc.remove(10, "c")
    seen.append(dc.state())
    dc.complete(100, "a")
    seen += [dc.dispatch(100), dc.state()]
    dc.complete(150, "b")
    seen += [dc.dispatch(150), dc.state()]
    return seen


def test_client_conforms_to_in_process_datacentre_r_dep_7(client):
    assert _script(client) == _script(InProcDatacentre(CFG, "h"))


def test_fractional_requests_survive_the_round_trip_r_dep_7(client):
    """§13.5 rule 3: floats keep their exact value, or capacity sums could diverge."""
    tiny = Request(0.1, 0.2, 0.30000000000000004)
    local = InProcDatacentre(CFG, "h")
    for dc in (client, local):
        dc.enqueue(0, "a", tiny, 10)
        dc.enqueue(0, "b", tiny, 10)
        dc.enqueue(0, "c", tiny, 10)
        dc.dispatch(0)
    assert client.state() == local.state()
    assert client.state().used.gpu == 0.1 + 0.1 + 0.1


@pytest.mark.parametrize("policy", ALL_POLICIES)
def test_simulation_over_http_is_byte_identical_r_dep_1(toy, policy, tmp_path):
    """Every policy on the toy, services in threads. The CLI form comes with `--mode remote`."""
    local = write_run(Simulator(toy, make_policy(policy)).run(), tmp_path / "local")
    services = [Running(d.dc_id) for d in toy.dcs]
    try:
        clients = [HttpDatacentre(s.url) for s in services]
        remote = write_run(Simulator(toy, make_policy(policy), clients).run(), tmp_path / "remote")
    finally:
        for s in services:
            s.stop()
    assert remote == local


def test_removing_a_running_job_is_409_migration_r_dep_4(client, service):
    client.enqueue(0, "a", SMALL, 100)
    client.dispatch(0)
    status, body = _status(service.url, "/remove", body={"t": 1, "job_id": "a"})
    assert (status, body["error"]) == (409, "MIGRATION")
    with pytest.raises(MigrationError):
        dc = InProcDatacentre(CFG, "h")
        dc.enqueue(0, "a", SMALL, 100)
        dc.dispatch(0)
        dc.remove(1, "a")


def test_time_going_backwards_is_409_r_dep_4(client, service):
    client.dispatch(100)
    for path, body in (
        ("/dispatch", {"t": 99}),
        ("/enqueue", _enqueue_body(99, "a")),
        ("/remove", {"t": 99, "job_id": "a"}),
    ):
        status, reply = _status(service.url, path, body=body)
        assert (status, reply["error"]) == (409, "TIME_BACKWARDS"), path


def test_duplicate_job_is_409_r_dep_4(client, service):
    client.enqueue(0, "a", SMALL, 100)
    status, body = _status(service.url, "/enqueue", body=_enqueue_body(0, "a"))
    assert (status, body["error"]) == (409, "DUPLICATE_JOB")


def test_removing_an_unqueued_job_is_404(client, service):
    assert _status(service.url, "/remove", body={"t": 0, "job_id": "ghost"})[0] == 404


@pytest.mark.parametrize("t", [99, 101])
def test_completing_at_the_wrong_time_is_409(client, service, t):
    client.enqueue(0, "a", SMALL, 100)
    client.dispatch(0)
    assert _status(service.url, "/complete", body={"t": t, "job_id": "a"})[0] == 409


def test_completing_a_job_that_is_not_running_is_409(client, service):
    client.enqueue(0, "a", BIG, 100)
    assert _status(service.url, "/complete", body={"t": 0, "job_id": "a"})[0] == 409


def test_state_hides_end_times_and_runtimes_r_dep_4(client, service):
    client.enqueue(0, "a", SMALL, 100)
    client.dispatch(0)
    client.enqueue(0, "b", BIG, 100)
    status, body = _status(service.url, "/state", method="GET")
    assert status == 200
    text = json.dumps(body)
    assert "end_s" not in text and "runtime" not in text
    assert set(body["running"][0]) == {"job_id", "start_s", "gpu_req", "cpu_req", "mem_req_gb"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"dc_id": 0},
        {
            "dc_id": 0,
            "region_id": 1,
            "cap_gpu": "x",
            "cap_cpu": 1,
            "cap_mem_gb": 1,
            "pue": 1,
            "scenario_hash": "h",
        },
    ],
)
def test_invalid_reset_is_400(service, body):
    assert _status(service.url, "/reset", body=body)[0] == 400


def test_reset_for_another_datacentre_is_refused(service):
    with pytest.raises(DeploymentError, match="HTTP 400"):
        HttpDatacentre(service.url).reset(DcConfig(2, 3, 4.0, 32.0, 100.0), "h")


def test_reset_clears_all_state(client):
    client.enqueue(0, "a", SMALL, 100)
    client.dispatch(50)
    client.reset(CFG, "h")
    st = client.state()
    assert st.queue == () and st.running == () and st.used.gpu == 0.0


def test_calls_before_reset_are_refused(service):
    assert _status(service.url, "/state", method="GET")[0] == 409
    assert _status(service.url, "/dispatch", body={"t": 0})[0] == 409


def test_bad_requests_are_400_not_a_crash(client, service):
    assert _status(service.url, "/enqueue", body={"t": 0})[0] == 400
    assert _status(service.url, "/nope")[0] == 404
    request = urllib.request.Request(service.url + "/dispatch", data=b"{not json", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(request)
    assert e.value.code == 400
    assert client.state().t_s < 2**62  # still serving


def test_service_rule_violation_aborts_the_client_r_dep_4(client):
    client.dispatch(100)
    with pytest.raises(DeploymentError, match="TIME_BACKWARDS"):
        client.dispatch(99)
    with pytest.raises(SimulationInvariantError):
        dc = InProcDatacentre(CFG, "h")
        dc.dispatch(100)
        dc.dispatch(99)


def test_dead_service_raises_deployment_error_and_no_retry_r_dep_3():
    running = Running()
    client = HttpDatacentre(running.url, timeout_s=2)
    client.reset(CFG, "h")
    before = client.rpc_count
    running.stop()
    with pytest.raises(DeploymentError):
        client.dispatch(0)
    assert client.rpc_count == before + 1


def test_service_dying_mid_run_aborts_the_simulation_r_dep_3(toy):
    services = [Running(d.dc_id) for d in toy.dcs]
    clients = [HttpDatacentre(s.url, timeout_s=2) for s in services]

    class KillAtFirstPlacement:
        name = "kill"
        uses_oracle = False
        tick_s = None
        stats = None

        def make_view(self, sim):
            from flipwise.simulator import SchedulerView

            return SchedulerView(sim)

        def on_arrival(self, view, job_id):
            services[0].stop()
            return make_policy("fcfs").on_arrival(view, job_id)

        def on_carbon_update(self, view):
            return []

        def on_release(self, view, job_id):
            return None

    try:
        with pytest.raises(DeploymentError):
            Simulator(toy, KillAtFirstPlacement(), clients).run()
    finally:
        for s in services[1:]:
            s.stop()


def test_service_module_never_reads_the_wall_clock():
    """§13.5: datacentre services take their time from each request."""
    import inspect

    import flipwise.datacentre as dc
    import flipwise.dcservice as svc

    for module in (svc, dc):
        source = inspect.getsource(module)
        assert "import time" not in source and "datetime" not in source


ERROR_CASES = {
    "time_backwards": ("TIME_BACKWARDS", lambda dc: (dc.dispatch(100), dc.dispatch(99))),
    "duplicate": (
        "DUPLICATE_JOB",
        lambda dc: (dc.enqueue(0, "a", SMALL, 9), dc.enqueue(0, "a", SMALL, 9)),
    ),
    "remove_running": (
        "MIGRATION",
        lambda dc: (dc.enqueue(0, "a", SMALL, 9), dc.dispatch(0), dc.remove(1, "a")),
    ),
    "remove_unknown": ("NOT_QUEUED", lambda dc: dc.remove(0, "ghost")),
    "complete_early": (
        "NOT_RUNNING",
        lambda dc: (dc.enqueue(0, "a", SMALL, 9), dc.dispatch(0), dc.complete(1, "a")),
    ),
}


@pytest.mark.parametrize("case", sorted(ERROR_CASES))
def test_every_error_case_fails_on_both_clients_r_dep_7(client, case):
    """Both refuse and neither changes state. The HTTP client reports the rule's code, because
    §13.5 rule 4 turns any non-2xx into `DeploymentError`."""
    code, call = ERROR_CASES[case]
    local = InProcDatacentre(CFG, "h")
    with pytest.raises((SimulationInvariantError, MigrationError, KeyError)):
        call(local)
    with pytest.raises(DeploymentError, match=code):
        call(client)
    assert client.state() == local.state()


def test_cli_dc_serve_runs_as_its_own_process(tmp_path):
    """`flipwise dc-serve` answers from a separate process, then stops cleanly when killed."""
    import socket
    import subprocess
    import sys
    import time

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        [sys.executable, "-m", "flipwise.cli", "dc-serve", "--dc-id", "2", "--port", str(port)],
        stdout=subprocess.DEVNULL,
    )
    try:
        client = HttpDatacentre(f"http://127.0.0.1:{port}", timeout_s=2)
        deadline = time.monotonic() + 20
        while True:
            try:
                assert client.health()["dc_id"] == 2
                break
            except DeploymentError:
                assert time.monotonic() < deadline, "service did not come up"
                time.sleep(0.1)
        client.reset(DcConfig(2, 3, 4.0, 32.0, 100.0), "h")
        assert client.dispatch(0) == []
    finally:
        proc.kill()
        proc.wait()
    with pytest.raises(DeploymentError):
        client.dispatch(1)
