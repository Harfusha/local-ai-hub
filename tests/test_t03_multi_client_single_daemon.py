from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import client as client_module
from local_ai_hub.process_utils import process_owner_record, process_owner_state, terminate_tree

SERVICE_SUBPROCESS_PATCH = (
    "client_module.subprocess = SimpleNamespace(**{**vars(client_module.subprocess), "
    "'run': service_start})"
)


def test_service_start_double_does_not_intercept_hardware_probes(monkeypatch) -> None:
    from local_ai_hub import hardware

    probes, starts = [], []

    def hardware_probe(command, **kwargs):
        probes.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="hardware", stderr="")

    def service_start(*args, **kwargs):
        starts.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="service", stderr="")

    monkeypatch.setattr(subprocess, "run", hardware_probe)
    monkeypatch.setattr(client_module, "subprocess", subprocess)
    exec(SERVICE_SUBPROCESS_PATCH, {"client_module": client_module,
                                  "service_start": service_start,
                                  "SimpleNamespace": SimpleNamespace})
    result = hardware._run(["fixture-hardware-probe"])
    assert starts == [], f"hardware probe entered service_start: {starts}"
    assert probes == [["fixture-hardware-probe"]]
    assert result.stdout == "hardware"


@pytest.mark.parametrize("setup_delay", [0, 2.1], ids=["normal", "slow-preparation"])
@pytest.mark.parametrize("client_count", [8, 30], ids=["8-clients", "30-clients"])
def test_concurrent_process_clients_have_one_supervisor_spawn_authority(tmp_path, setup_delay, client_count) -> None:
    config = tmp_path / "hub.toml"
    state_dir = tmp_path / "state"
    ready_file = state_dir / "ready"
    arrivals = tmp_path / "arrivals"
    start_calls = tmp_path / "start_calls"
    daemon_owners = tmp_path / "daemon_owners"
    for path in (arrivals, start_calls, daemon_owners):
        path.mkdir()
    config.write_text(
        f"[server]\nport=39123\nstate_dir='{state_dir.as_posix()}'\n"
        "[hardware]\nprofile='cpu'\nauto_tune=false\n"
        "[client]\nstartup_wait_seconds=2\nstartup_poll_seconds=0.02\n",
        encoding="utf-8",
    )

    start_gate = tmp_path / "start.gate"
    release_gate = tmp_path / "release.gate"
    worker = r'''
import json, os, sys, time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[8])
from local_ai_hub import client as client_module, hardware, operational_mode
from local_ai_hub.client import HubClient
from local_ai_hub.supervisor import Supervisor
from local_ai_hub.process_utils import process_owner_record, process_owner_state

config_path, ready_name, arrivals_name, starts_name, owners_name, start_name, release_name, source_root = sys.argv[1:9]
assert Path(client_module.__file__).resolve().is_relative_to(Path(source_root).resolve()), client_module.__file__
ready, arrivals, starts, owners = map(Path, (ready_name, arrivals_name, starts_name, owners_name))
start_gate, release_gate = Path(start_name), Path(release_name)
def event(stage, **fields):
    print(json.dumps({"pid": os.getpid(), "stage": stage, **fields}), file=sys.stderr, flush=True)

# Host profiling is unrelated to singleton ownership. Configuration and object
# construction finish before publishing arrival at the startup barrier.
hardware.detect_hardware = lambda profile: {"profile": "cpu", "gpus": []}
time.sleep(float(sys.argv[10]))
client = HubClient(tenant=f"t03-client-{sys.argv[11]}", config_path=config_path, auto_start=True)
supervisor = Supervisor(config_path)
assert Path(client.config["_config_path"]).resolve() == Path(config_path).resolve()
assert Path(client.config["server"]["state_dir"]).resolve() == ready.parent.resolve()
worker_owner = process_owner_record(os.getpid(), ready.parent, "fixture_client")
assert worker_owner is not None
worker_owner.pop("command", None)
assert process_owner_state(worker_owner, ready.parent, "fixture_client") == "owned"
event("constructed", tenant=client.tenant, owner=worker_owner)

def service_start(command, **_kwargs):
    assert len(command) == 3 and command[-1] == "start", command
    starts.joinpath(f"{os.getpid()}.request").write_text("start", encoding="ascii")
    acquired = supervisor.acquire()
    owner = None
    if acquired:
        owner = json.loads(supervisor.owner_path.read_text(encoding="utf-8"))
        owner.pop("command", None)
        assert process_owner_state(owner, ready.parent, "supervisor") == "owned"
    event("acquire", acquired=acquired,
          owner=owner,
          lock_exists=supervisor.lock_path.exists(), pid_exists=supervisor.pid_path.exists())
    if acquired:
        try:
            owners.joinpath(f"{os.getpid()}.owner").write_text("spawn-authority", encoding="ascii")
            ready.touch()
            deadline = time.monotonic() + 5
            while not release_gate.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert release_gate.exists(), "release gate timed out"
        finally:
            supervisor.release_lock()
            event("released", lock_exists=supervisor.lock_path.exists(),
                  pid_exists=supervisor.pid_path.exists())
    return SimpleNamespace(returncode=0)

exec(sys.argv[9])
client_module.find_listening_pid = lambda _port: None
operational_mode.load_operational_mode = lambda *_args, **_kwargs: operational_mode.OperationalModeSnapshot("active", 0, None)
client._online = lambda _timeout=None: ready.exists()
arrivals.joinpath(f"{os.getpid()}.ready").touch()
event("prepared")
deadline = time.monotonic() + 5
while not start_gate.exists() and time.monotonic() < deadline:
    time.sleep(0.01)
assert start_gate.exists(), "start gate timed out"
online = client.ensure_server(timeout=2)
event("ensure_server", ready=online)
client.close()
print("ready" if online else "failed")
'''
    python_root = str(Path(client_module.__file__).resolve().parents[1])
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (python_root, env.get("PYTHONPATH", "")) if value
    )

    launcher_owners = {}

    def run_client(index: int) -> subprocess.CompletedProcess[str]:
        command = [
                sys.executable,
                "-B",
                "-c",
                worker,
                str(config),
                str(ready_file),
                str(arrivals),
                str(start_calls),
                str(daemon_owners),
                str(start_gate),
                str(release_gate),
                python_root,
                SERVICE_SUBPROCESS_PATCH,
                str(setup_delay),
                str(index),
            ]
        from local_ai_hub.process_utils import hidden_run_kwargs

        with subprocess.Popen(
            command,
            cwd=tmp_path,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **hidden_run_kwargs(),
        ) as process:
            launcher_owner = process_owner_record(process.pid, state_dir, "fixture_launcher")
            if launcher_owner is not None:
                launcher_owner.pop("command", None)
            launcher_owners[index] = launcher_owner

            def stop_owned_process_tree():
                assert launcher_owner is not None, f"unverified owned launcher: {process.pid}"
                assert terminate_tree(
                    process.pid, expected_identity=launcher_owner,
                    process_handle=process, grace_seconds=1,
                ), f"identity-bound cleanup failed: {process.pid}"

            try:
                stdout, stderr = process.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                stop_owned_process_tree()
                stdout, stderr = process.communicate(timeout=2)
                stderr += "\nparent: worker exceeded 8-second budget\n"
            finally:
                if process.poll() is None:
                    stop_owned_process_tree()
                    process.wait(timeout=2)
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

    with ThreadPoolExecutor(max_workers=client_count) as pool:
        futures = [pool.submit(run_client, index) for index in range(client_count)]
        phases = {}
        try:
            deadline = time.monotonic() + 4
            while len(list(arrivals.glob("*.ready"))) < client_count and time.monotonic() < deadline:
                time.sleep(0.01)
            phases["prepared"] = len(list(arrivals.glob("*.ready")))
            phases["requests_before_gate"] = len(list(start_calls.glob("*.request")))
            start_gate.touch()
            deadline = time.monotonic() + 4
            while not list(daemon_owners.glob("*.owner")) and time.monotonic() < deadline:
                time.sleep(0.01)
            phases["owners_before_release"] = len(list(daemon_owners.glob("*.owner")))
            deadline = time.monotonic() + 4
            while sum(future.done() for future in futures) < client_count - 1 and time.monotonic() < deadline:
                time.sleep(0.01)
            phases["followers_done_before_release"] = sum(future.done() for future in futures)
        finally:
            start_gate.touch()
            release_gate.touch()
        results = [future.result(timeout=8) for future in futures]

    diagnostics = {
        "phases": phases,
        "start_requests": len(list(start_calls.glob("*.request"))),
        "owner_files": len(list(daemon_owners.glob("*.owner"))),
        "owner_status": {name: (state_dir / name).exists()
                         for name in ("supervisor.lock", "supervisor.pid", "supervisor.owner.json")},
        "children": [{"returncode": result.returncode, "stdout": result.stdout.strip(),
                      "stderr": result.stderr[-4000:]} for result in results],
    }
    assert phases["prepared"] == client_count, diagnostics
    assert phases["requests_before_gate"] == 0, diagnostics
    assert phases["owners_before_release"] == 1, diagnostics
    assert phases["followers_done_before_release"] >= client_count - 1, diagnostics
    assert all(result.returncode == 0 for result in results), diagnostics
    assert [result.stdout.strip() for result in results] == ["ready"] * client_count, diagnostics
    assert diagnostics["start_requests"] == 1, diagnostics
    assert diagnostics["owner_files"] == 1, diagnostics
    assert not any(diagnostics["owner_status"].values()), diagnostics
    start_lock_path = state_dir / "hub.start.lock"
    assert start_lock_path.read_bytes() == b"", diagnostics
    # The persistent empty inode is intentional; verify its OS lock was released.
    lock = client_module._acquire_start_lock(start_lock_path)
    assert lock is not None, diagnostics
    try:
        lock.seek(0)
        lock.truncate()
        lock.flush()
    finally:
        lock.close()
    assert start_lock_path.read_bytes() == b"", diagnostics
    events = [json.loads(line) for result in results for line in result.stderr.splitlines()]
    acquisitions = [event for event in events
                    if event["stage"] == "acquire" and event["acquired"]]
    assert len(acquisitions) == 1, diagnostics
    assert acquisitions[0]["lock_exists"] and acquisitions[0]["pid_exists"], diagnostics
    assert sum(event["stage"] == "prepared" for event in events) == client_count, diagnostics
    assert sum(event["stage"] == "released" for event in events) == 1, diagnostics
    constructed = [event for event in events if event["stage"] == "constructed"]
    assert len(constructed) == client_count, diagnostics
    assert {event["tenant"] for event in constructed} == {
        f"t03-client-{index}" for index in range(client_count)
    }, diagnostics
    assert len(launcher_owners) == client_count, diagnostics
    assert all(owner is not None for owner in launcher_owners.values()), diagnostics
    owners = [event["owner"] for event in constructed] + list(launcher_owners.values())
    for owner in owners:
        assert Path(owner["state_dir"]).resolve() == state_dir.resolve(), diagnostics
        assert process_owner_state(owner, state_dir, owner["role"]) == "stale", diagnostics
    assert acquisitions[0]["owner"]["pid"] in {event["pid"] for event in constructed}, diagnostics
    assert process_owner_state(acquisitions[0]["owner"], state_dir, "supervisor") == "stale", diagnostics
    print(
        f"measurement: clients={client_count} "
        f"service_start_requests={len(list(start_calls.glob('*.request')))} "
        "supervisor_spawn_authorities=1 "
        f"returncodes={[result.returncode for result in results]} "
        f"owner_status_after_close={diagnostics['owner_status']} "
        f"identity_verified_closed_clients={client_count} tenant_count={client_count} "
        f"stderr={client_count}-prepared,1-real-acquire,1-released"
    )
