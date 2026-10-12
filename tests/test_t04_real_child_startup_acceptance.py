from __future__ import annotations

import socket
import json
import os
import sys
import subprocess
import time
from types import SimpleNamespace
import psutil

from local_ai_hub.process_utils import (
    _resume_suspended_process, assign_process_to_job, create_job_object_kill_on_close,
    close_job_object, pid_alive, process_identity, process_parent_pid, process_owner_state, terminate_tree,
)

from local_ai_hub import client as client_module
from local_ai_hub.client import HubClient


def test_autostart_launches_real_hub_child_and_returns_http_search_result(tmp_path, monkeypatch):
    global_popen = subprocess.Popen
    if os.name == "nt":
        real_popen = client_module.subprocess.Popen

        class OwnedPopen(real_popen):
            def __init__(self, *args, **kwargs):
                kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | 0x00000004
                super().__init__(*args, **kwargs)
                self._local_ai_process_identity = process_identity(self.pid)
                self._local_ai_job_handle = None
                try:
                    assert self._local_ai_process_identity is not None
                    self._local_ai_job_handle = create_job_object_kill_on_close()
                    assert self._local_ai_job_handle
                    assert assign_process_to_job(self._local_ai_job_handle, self.pid)
                    assert _resume_suspended_process(self)
                except BaseException:
                    self.kill()
                    self.wait(timeout=2)
                    close_job_object(self._local_ai_job_handle)
                    raise

        monkeypatch.setattr(
            client_module,
            "subprocess",
            SimpleNamespace(**{**vars(client_module.subprocess), "Popen": OwnedPopen}),
        )
        assert subprocess.Popen is global_popen
        assert client_module.subprocess.Popen is OwnedPopen
        assert client_module.subprocess.run is subprocess.run
        assert client_module.subprocess.TimeoutExpired is subprocess.TimeoutExpired
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "needle.py").write_text(
        'def find_marker():\n    return "T04_REAL_CHILD_MARKER"\n',
        encoding="utf-8",
    )
    state_dir = tmp_path / "state"
    config_path = tmp_path / "real-child.toml"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {port}\nstate_dir = "{state_dir.as_posix()}"\n'
        "[client]\nstartup_wait_seconds = 15\nstartup_poll_seconds = 0.05\nhealth_timeout_seconds = 0.25\n"
        "[ollama]\nenabled = false\n"
        "[smart_ollama]\nenabled = false\n"
        "[llama_cpp]\nmode = \"off\"\n"
        "[code_intelligence]\nenabled = false\nserena_enabled = false\npreprocess_serena = false\n"
        "[preprocessing]\nenabled = false\n",
        encoding="utf-8",
    )
    client = HubClient(tenant="t04-real-child", config_path=str(config_path), auto_start=True)
    assert client.config["llama_cpp"]["mode"] == "off"
    assert client.config["ollama"]["enabled"] is False
    assert client.config["smart_ollama"]["enabled"] is False
    assert client.config["code_intelligence"]["enabled"] is False
    assert client.config["code_intelligence"]["serena_enabled"] is False
    assert client.config["code_intelligence"]["preprocess_serena"] is False
    assert client.config["preprocessing"]["enabled"] is False
    with client_module._DETACHED_CHILDREN_LOCK:
        existing_child_ids = {id(child) for child in client_module._DETACHED_CHILDREN}
    runtime_identities = []
    runtime_processes = []

    try:
        result = client.post(
            "/api/search",
            {"root": str(repo), "query": "T04_REAL_CHILD_MARKER", "top_k": 3},
            request_id="t04-real-child-search",
            timeout=30,
        )
        assert result["success"] is True
        assert any(
            hit.get("path") == "needle.py" and "T04_REAL_CHILD_MARKER" in hit.get("text", "")
            for hit in result.get("results", [])
        )
        with client_module._DETACHED_CHILDREN_LOCK:
            started_children = [
                child
                for child in client_module._DETACHED_CHILDREN
                if id(child) not in existing_child_ids
            ]
        assert len(started_children) == 1
        child = started_children[0]
        assert isinstance(child, client_module.subprocess.Popen)
        assert child.poll() is None
        hub_pid = int((state_dir / "hub.pid").read_text(encoding="utf-8").strip())
        supervisor_pid = int((state_dir / "supervisor.pid").read_text(encoding="utf-8").strip())
        supervisor_owner = json.loads((state_dir / "supervisor.owner.json").read_text(encoding="utf-8"))
        assert supervisor_owner["pid"] == supervisor_pid
        assert process_owner_state(supervisor_owner, state_dir, "supervisor") == "owned"
        assert process_identity(child.pid) == child._local_ai_process_identity
        runtime_identity = process_identity(supervisor_pid)
        assert runtime_identity is not None
        if os.name == "nt" and sys.prefix != sys.base_prefix:
            assert supervisor_pid != child.pid
        if supervisor_pid != child.pid:
            assert process_parent_pid(supervisor_pid) == child.pid
            assert runtime_identity["creation_identity"] >= child._local_ai_process_identity["creation_identity"]
        print("AUTOSTART_RUNTIME_PROOF " + json.dumps({"launcher_pid": child.pid, "supervisor_pid": supervisor_pid}))
        assert hub_pid != supervisor_pid
        hub_owner = json.loads((state_dir / "hub.owner.json").read_text(encoding="utf-8"))
        assert hub_owner["pid"] == hub_pid
        assert process_owner_state(hub_owner, state_dir, "hub") == "owned"
        runtime_identities = [runtime_identity, process_identity(hub_pid)]
        assert all(runtime_identities)
        runtime_processes = [psutil.Process(identity["pid"]) for identity in runtime_identities]
        assert (state_dir / "hub.start.lock").read_bytes() == b""
    finally:
        client._drop_connection()
        with client_module._DETACHED_CHILDREN_LOCK:
            started_children = [
                child
                for child in client_module._DETACHED_CHILDREN
                if id(child) not in existing_child_ids
            ]
        cleanup_deadline = time.monotonic() + 2
        for child in started_children:
            if child.poll() is None:
                assert terminate_tree(child.pid, process_handle=child, grace_seconds=0.25)
                child.wait(timeout=max(0.01, cleanup_deadline - time.monotonic()))
        for runtime in runtime_processes:
            try:
                runtime.wait(timeout=max(0.01, cleanup_deadline - time.monotonic()))
            except psutil.NoSuchProcess:
                pass
        assert all(child.poll() is not None for child in started_children), (
            "test-owned Hub child remained alive after exact-handle cleanup"
        )
        assert all(not pid_alive(identity["pid"]) for identity in runtime_identities)
