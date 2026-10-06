from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from local_ai_hub import client as client_module


def test_concurrent_process_clients_have_one_supervisor_spawn_authority(tmp_path) -> None:
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
        "[client]\nstartup_wait_seconds=2\nstartup_poll_seconds=0.02\n",
        encoding="utf-8",
    )

    start_gate = tmp_path / "start.gate"
    release_gate = tmp_path / "release.gate"
    worker = r'''
import os, sys, time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[8])
from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient
from local_ai_hub.supervisor import Supervisor

config_path, ready_name, arrivals_name, starts_name, owners_name, start_name, release_name, source_root = sys.argv[1:9]
assert Path(client_module.__file__).resolve().is_relative_to(Path(source_root).resolve()), client_module.__file__
ready, arrivals, starts, owners = map(Path, (ready_name, arrivals_name, starts_name, owners_name))
start_gate, release_gate = Path(start_name), Path(release_name)
arrivals.joinpath(f"{os.getpid()}.ready").touch()
deadline = time.monotonic() + 5
while not start_gate.exists() and time.monotonic() < deadline:
    time.sleep(0.01)

def service_start(*_args, **_kwargs):
    starts.joinpath(f"{os.getpid()}.request").write_text("start", encoding="ascii")
    supervisor = Supervisor(config_path)
    if supervisor.acquire():
        owners.joinpath(f"{os.getpid()}.owner").write_text("spawn-authority", encoding="ascii")
        ready.touch()
        deadline = time.monotonic() + 5
        while not release_gate.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        supervisor.release_lock()
    return SimpleNamespace(returncode=0)

client_module.subprocess.run = service_start
client_module.find_listening_pid = lambda _port: None
client = HubClient(config_path=config_path, auto_start=True)
client._online = lambda _timeout=None: ready.exists()
print("ready" if client.ensure_server(timeout=2) else "failed")
'''
    python_root = str(Path(client_module.__file__).resolve().parents[1])
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (python_root, env.get("PYTHONPATH", "")) if value
    )

    def run_client(_index: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
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
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(run_client, index) for index in range(8)]
        try:
            deadline = time.monotonic() + 4
            while len(list(arrivals.glob("*.ready"))) < 8 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert len(list(arrivals.glob("*.ready"))) == 8
            start_gate.touch()
            deadline = time.monotonic() + 4
            while not list(daemon_owners.glob("*.owner")) and time.monotonic() < deadline:
                time.sleep(0.01)
            assert len(list(daemon_owners.glob("*.owner"))) == 1
            deadline = time.monotonic() + 4
            while sum(future.done() for future in futures) < 7 and time.monotonic() < deadline:
                time.sleep(0.01)
            assert sum(future.done() for future in futures) >= 7
        finally:
            start_gate.touch()
            release_gate.touch()
        results = [future.result(timeout=8) for future in futures]

    assert all(result.returncode == 0 for result in results), [
        result.stderr[-1000:] for result in results if result.returncode != 0
    ]
    assert [result.stdout.strip() for result in results] == ["ready"] * 8
    assert len(list(daemon_owners.glob("*.owner"))) == 1
    print(
        "measurement: clients=8 "
        f"service_start_requests={len(list(start_calls.glob('*.request')))} "
        "supervisor_spawn_authorities=1"
    )
