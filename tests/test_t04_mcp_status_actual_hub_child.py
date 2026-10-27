from __future__ import annotations

import json
import os
import site
import socket
import subprocess
import sys
from pathlib import Path

import pytest


_MCP_CHILD_SCRIPT = r'''
import asyncio
import importlib.util
import json
import os
import platform
import subprocess as real_subprocess
import sys
import threading
import time
import psutil
from pathlib import Path
from types import SimpleNamespace

import local_ai_hub.hardware as hardware

def cpu_only(_requested="auto"):
    return {
        "platform": sys.platform,
        "os": platform.system().lower(),
        "arch": platform.machine().lower(),
        "cpu": {"name": "fixture-cpu", "logical_cores": 1},
        "ram": {"total_gb": 8.0, "available_gb": 4.0},
        "gpus": [], "npus": [], "openvino_devices": [],
        "openvino_gpu_devices": [], "profile": "cpu",
    }

hardware.detect_hardware = cpu_only
from local_ai_hub import client as client_module
from local_ai_hub import mcp_server
from local_ai_hub.process_utils import (
    _resume_suspended_process, assign_process_to_job, create_job_object_kill_on_close,
    close_job_object, pid_alive, process_identity, process_parent_pid, process_owner_state, terminate_tree,
)

def _read_published_owners(state_dir, *, deadline):
    while True:
        snapshot = {}
        try:
            pid_text = (state_dir / "hub.pid").read_text(encoding="ascii").strip()
            hub_owner = json.loads((state_dir / "hub.owner.json").read_text(encoding="utf-8"))
            supervisor_owner = json.loads((state_dir / "supervisor.owner.json").read_text(encoding="utf-8"))
            snapshot = {"pid_text": pid_text, "hub_owner": hub_owner, "supervisor_owner": supervisor_owner}
            if pid_text:
                hub_pid = int(pid_text)
                if int(hub_owner["pid"]) == hub_pid and process_owner_state(hub_owner, state_dir, "hub") == "owned" and process_owner_state(supervisor_owner, state_dir, "supervisor") == "owned":
                    return hub_pid, hub_owner, supervisor_owner
        except (PermissionError, FileNotFoundError) as exc:
            snapshot = {"read_error": repr(exc)}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"owner publication did not settle within startup deadline: {snapshot}")
        time.sleep(min(0.01, remaining))

client = mcp_server.CLIENT
assert client.auto_start is True
real_popen = real_subprocess.Popen
launches = []

def tracked_popen(argv, **kwargs):
    stdout_log = open(os.environ["T04_CHILD_STDOUT_FILE"], "ab")
    stderr_log = open(os.environ["T04_CHILD_STDERR_FILE"], "ab")
    kwargs["stdout"] = stdout_log
    kwargs["stderr"] = stderr_log
    if os.name == "nt":
        kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | 0x00000004
    child = real_popen(argv, **kwargs)
    child._local_ai_process_identity = process_identity(child.pid)
    if os.name == "nt":
        child._local_ai_job_handle = create_job_object_kill_on_close()
        assert child._local_ai_job_handle
        assert assign_process_to_job(child._local_ai_job_handle, child.pid)
        assert _resume_suspended_process(child)
    elif kwargs.get("start_new_session"):
        child._local_ai_process_group = child.pid
    env = kwargs["env"]
    info = kwargs.get("startupinfo")
    record = {
        "argv": [str(part) for part in argv],
        "local_ai_config": env.get("LOCAL_AI_CONFIG"),
        "pythonpath": env.get("PYTHONPATH", "").split(os.pathsep),
        "creationflags": int(kwargs.get("creationflags", 0)),
        "startupinfo_flags": int(getattr(info, "dwFlags", 0)),
        "startupinfo_show": int(getattr(info, "wShowWindow", -1)),
    }
    launches.append((child, record))
    record["stdout_log"] = stdout_log
    record["stderr_log"] = stderr_log
    Path(os.environ["T04_TRACKED_PID_FILE"]).write_text(json.dumps(child._local_ai_process_identity), encoding="ascii")
    return child

client_module.subprocess = SimpleNamespace(
    Popen=tracked_popen,
    DEVNULL=real_subprocess.DEVNULL,
    TimeoutExpired=real_subprocess.TimeoutExpired,
)
if os.name == "nt":
    client_module.popen_managed = tracked_popen
ensure_calls = []
original_ensure = client.ensure_server

def tracked_ensure(timeout=None):
    ensure_calls.append(timeout)
    return original_ensure(timeout=timeout)

client.ensure_server = tracked_ensure
started_ids = {id(item) for item in client_module._DETACHED_CHILDREN}
children = []
timer = None
owned_runtime_identities = []
owned_runtime_processes = []

def stop_owned_children():
    for process, _record in launches:
        if process.poll() is None:
            assert terminate_tree(process.pid, process_handle=process, grace_seconds=0.25)

try:
    os.environ["T04_EXPECT_PARENT_PID"] = str(os.getpid())
    os.environ["T04_EXPECT_PARENT_CREATION"] = str(process_identity(os.getpid())["creation_identity"])
    timer = threading.Timer(14.0, stop_owned_children)
    timer.daemon = True
    timer.start()
    started_at = time.monotonic()
    result = asyncio.run(mcp_server.mcp.call_tool("local_ai_status", {"detail": "brief"}))
    elapsed = time.monotonic() - started_at
    content = result[0] if isinstance(result, tuple) else result
    text = next(item.text for item in content if getattr(item, "type", None) == "text")
    status = json.loads(text)
    assert status.get("success") is True or (
        status.get("degraded") is True and status.get("ollama_online") is False
    ), {
        "status": status,
        "elapsed": elapsed,
        "children": [{"pid": process.pid, "poll": process.poll()} for process, _ in launches],
        "stdout": Path(os.environ["T04_CHILD_STDOUT_FILE"]).read_text(encoding="utf-8", errors="replace"),
        "stderr": Path(os.environ["T04_CHILD_STDERR_FILE"]).read_text(encoding="utf-8", errors="replace"),
    }
    assert ensure_calls, "first registered MCP status call skipped HubClient.ensure_server"
    assert elapsed < 15.0, elapsed
    children = [item for item in client_module._DETACHED_CHILDREN if id(item) not in started_ids]
    assert len(children) == 1, children
    child = children[0]
    assert len(launches) == 1
    assert launches[0][0] is child
    assert child.poll() is None
    state_dir = Path(client.config["server"]["state_dir"])
    hub_pid, hub_owner, supervisor_owner = _read_published_owners(state_dir, deadline=started_at + 12.0)
    assert int(hub_owner["pid"]) == hub_pid
    assert process_owner_state(hub_owner, state_dir, "hub") == "owned"
    assert process_owner_state(supervisor_owner, state_dir, "supervisor") == "owned"
    supervisor_pid = int(supervisor_owner["pid"])
    assert process_identity(child.pid) == child._local_ai_process_identity
    if os.name == "nt" and sys.prefix != sys.base_prefix:
        assert supervisor_pid != child.pid
    if supervisor_pid != child.pid:
        assert process_parent_pid(supervisor_pid) == child.pid
        assert process_identity(supervisor_pid)["creation_identity"] >= child._local_ai_process_identity["creation_identity"]
    owned_runtime_identities = [process_identity(supervisor_pid), process_identity(hub_pid)]
    assert all(owned_runtime_identities)
    owned_runtime_processes = [psutil.Process(identity["pid"]) for identity in owned_runtime_identities]
    argv = launches[0][1]["argv"]
    assert argv[1:] == ["-m", "local_ai_hub.supervisor", "--config", os.environ["LOCAL_AI_CONFIG"]], argv
    expected_executable = Path(sys.executable)
    if os.name == "nt":
        pythonw = expected_executable.parent / "pythonw.exe"
        if pythonw.exists():
            expected_executable = pythonw
    assert Path(argv[0]).resolve() == expected_executable.resolve(), argv[0]
    assert launches[0][1]["local_ai_config"] == os.environ["LOCAL_AI_CONFIG"]
    package_source = Path(importlib.util.find_spec("local_ai_hub").origin).resolve()
    entrypoint_source = Path(importlib.util.find_spec("local_ai_hub.__main__").origin).resolve()
    child_source = json.loads(Path(os.environ["T04_CHILD_SOURCE_FILE"]).read_text(encoding="utf-8"))
    assert child_source["runtime_pid"] == supervisor_pid
    assert child_source["runtime_identity"] == process_identity(supervisor_pid)
    source_root = Path(os.environ["PYTHONPATH"].split(os.pathsep)[0]).resolve()
    assert Path(launches[0][1]["pythonpath"][0]).resolve() == source_root
    assert package_source == source_root / "local_ai_hub" / "__init__.py", package_source
    assert entrypoint_source == source_root / "local_ai_hub" / "__main__.py", entrypoint_source
    assert Path(child_source["package_file"]).resolve() == package_source
    assert Path(child_source["entrypoint_file"]).resolve() == entrypoint_source
    if os.name == "nt":
        assert launches[0][1]["startupinfo_flags"] & real_subprocess.STARTF_USESHOWWINDOW
        assert launches[0][1]["startupinfo_show"] == 0
        assert launches[0][1]["creationflags"] & real_subprocess.CREATE_NO_WINDOW
        assert launches[0][1]["creationflags"] & real_subprocess.CREATE_NEW_PROCESS_GROUP
    launch_record = {key: value for key, value in launches[0][1].items()
                     if key not in {"stdout_log", "stderr_log"}}
    print(json.dumps({"status": status, "elapsed": elapsed, "argv": argv,
                      "launch": launch_record, "child_source": child_source,
                      "package_source": str(package_source), "entrypoint_source": str(entrypoint_source),
                      "child_pid": child.pid, "ensure_calls": len(ensure_calls)}))
finally:
    if timer is not None:
        timer.cancel()
    client._drop_connection()
    cleanup_deadline = time.monotonic() + 2
    stop_owned_children()
    for process, _record in launches:
        process.wait(timeout=max(0.01, cleanup_deadline - time.monotonic()))
        assert process.poll() is not None, f"owned Hub child {process.pid} survived shutdown"
        _record["stdout_log"].close()
        _record["stderr_log"].close()
    for runtime in owned_runtime_processes:
        try:
            runtime.wait(timeout=max(0.01, cleanup_deadline - time.monotonic()))
        except psutil.NoSuchProcess:
            pass
    assert all(not pid_alive(identity["pid"]) for identity in owned_runtime_identities)
'''


def _hidden_kwargs() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
    }


def test_first_mcp_status_starts_and_reaps_real_hub_entrypoint(tmp_path: Path) -> None:
    source_root = Path(os.environ.get("T04_SOURCE_ROOT", Path(__file__).resolve().parents[1] / "src")).resolve()
    state_dir = tmp_path / "state"
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    child_source_file = tmp_path / "child-source.json"
    child_stdout_file = tmp_path / "child.stdout.log"
    child_stderr_file = tmp_path / "child.stderr.log"
    tracked_pid_file = tmp_path / "tracked-child.pid"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    config_path = tmp_path / "isolated-hub.toml"
    config_path.write_text(
        f'[server]\nbind="127.0.0.1"\nport={port}\nstate_dir={json.dumps(state_dir.as_posix())}\n'
        "max_concurrent_requests=8\n"
        "[client]\nstartup_wait_seconds=12\nstartup_poll_seconds=0.05\n"
        "health_timeout_seconds=0.25\nmax_request_timeout_seconds=14\n"
        "[features]\nstatus=true\n"
        "[hardware]\nprofile=\"cpu\"\nauto_tune=false\n"
        "[ollama]\nenabled=false\n"
        "[smart_ollama]\nenabled=false\n"
        "[llama_cpp]\nmode=\"off\"\n"
        "[code_intelligence]\nenabled=false\nserena_enabled=false\npreprocess_serena=false\n"
        "[preprocessing]\nenabled=false\n"
        "[background_gpu]\nenabled=false\n"
        "[agent_state]\nenabled=false\n",
        encoding="utf-8",
    )
    (probe_dir / "sitecustomize.py").write_text(
        "import importlib.util, json, os, site\n"
        "for directory in os.environ['T04_TEST_SITE_PACKAGES'].split(os.pathsep): site.addsitedir(directory)\n"
        "import psutil\n"
        "from pathlib import Path\n"
        "from local_ai_hub.process_utils import process_identity\n"
        "expected = os.environ.get('T04_EXPECT_PARENT_PID')\n"
        "creation = os.environ.get('T04_EXPECT_PARENT_CREATION')\n"
        "ancestors = psutil.Process().parents()[:2] if expected else []\n"
        "if expected and creation and any(parent.pid == int(expected) and str(process_identity(parent.pid)['creation_identity']) == creation for parent in ancestors):\n"
        "    target = Path(os.environ['T04_CHILD_SOURCE_FILE'])\n"
        "    if not target.exists():\n"
        "        import local_ai_hub\n"
        "        spec = importlib.util.find_spec('local_ai_hub.__main__')\n"
        "        target.write_text(json.dumps({"
        "'package_file': str(Path(local_ai_hub.__file__).resolve()), "
        "'entrypoint_file': str(Path(spec.origin).resolve()), "
        "'runtime_pid': os.getpid(), 'runtime_identity': process_identity(os.getpid())}), encoding='utf-8')\n"
        "    import local_ai_hub.hardware as hardware\n"
        "    hardware.detect_hardware = lambda _requested='auto': {"
        "'platform': os.name, 'os': os.name, 'arch': 'fixture', "
        "'cpu': {'name': 'fixture-cpu', 'logical_cores': 1}, "
        "'ram': {'total_gb': 8.0, 'available_gb': 4.0}, "
        "'gpus': [], 'npus': [], 'openvino_devices': [], "
        "'openvino_gpu_devices': [], 'profile': 'cpu'}\n",
        encoding="utf-8",
    )

    env = {
        "PATH": os.environ.get("PATH", ""),
        "TEMP": str(tmp_path),
        "TMP": str(tmp_path),
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "APPDATA": str(tmp_path / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(tmp_path / "AppData" / "Local"),
        "PYTHONPATH": os.pathsep.join((str(source_root), str(probe_dir))),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
        "T04_TEST_SITE_PACKAGES": os.pathsep.join([*site.getsitepackages(), site.getusersitepackages()]),
        "LOCAL_AI_CONFIG": str(config_path),
        "T04_CHILD_SOURCE_FILE": str(child_source_file),
        "T04_TRACKED_PID_FILE": str(tracked_pid_file),
        "T04_CHILD_STDOUT_FILE": str(child_stdout_file),
        "T04_CHILD_STDERR_FILE": str(child_stderr_file),
    }
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
        env["WINDIR"] = os.environ.get("WINDIR", env["SYSTEMROOT"])

    from local_ai_hub.process_utils import popen_managed, process_identity, terminate_tree
    process = popen_managed(
        [sys.executable, "-B", "-c", _MCP_CHILD_SCRIPT],
        cwd=source_root.parent,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_hidden_kwargs(),
    )
    process._local_ai_process_identity = process_identity(process.pid)
    try:
        stdout, stderr = process.communicate(timeout=18)
    except subprocess.TimeoutExpired:
        if tracked_pid_file.exists():
            identity = json.loads(tracked_pid_file.read_text(encoding="ascii"))
            if identity and process_identity(identity["pid"]) == identity:
                terminate_tree(identity["pid"], expected_identity=identity, grace_seconds=0.25)
        terminate_tree(process.pid, process_handle=process, grace_seconds=0.25)
        stdout, stderr = process.communicate(timeout=3)
        pytest.fail(f"isolated MCP autostart exceeded 18s; helper={stdout!r}; stderr={stderr!r}")

    assert process.returncode == 0, stderr[-1600:]
    result = json.loads(stdout.strip().splitlines()[-1])
    assert result["status"]["success"] is True or (
        result["status"].get("degraded") is True
        and result["status"].get("ollama_online") is False
    )
    print("T04_REAL_HUB_PROOF " + json.dumps(result, sort_keys=True))
    assert result["ensure_calls"] >= 1
    assert result["elapsed"] < 15.0
    assert result["argv"][1:] == ["-m", "local_ai_hub.supervisor", "--config", str(config_path)]
    assert Path(result["package_source"]).resolve() == source_root / "local_ai_hub" / "__init__.py"
    assert Path(result["entrypoint_source"]).resolve() == source_root / "local_ai_hub" / "__main__.py"


@pytest.mark.parametrize("fault", ["sharing", "mismatch", "empty_pid", "permanent_sharing", "permanent_mismatch", "corrupt"])
def test_owner_observation_waits_for_coherent_publication_within_existing_deadline(fault):
    import ast
    from types import SimpleNamespace

    clock = [0.0]
    attempts = [0]

    def sleep(seconds):
        assert 0 < seconds <= 0.01
        clock[0] += seconds

    class StateDirectory:
        def __truediv__(self, name):
            class PublishedFile:
                def read_text(self, *, encoding):
                    if name == "hub.pid":
                        attempts[0] += 1
                        return "" if fault == "empty_pid" and attempts[0] == 1 else "11"
                    if name == "hub.owner.json":
                        if fault == "permanent_sharing" or (fault == "sharing" and attempts[0] == 1):
                            raise PermissionError("publication sharing denial")
                        if fault == "corrupt":
                            return "not JSON"
                        pid = 12 if fault == "permanent_mismatch" or (fault == "mismatch" and attempts[0] == 1) else 11
                        return json.dumps({"pid": pid})
                    assert name == "supervisor.owner.json"
                    return json.dumps({"pid": 22})
            return PublishedFile()

    namespace = {"json": json, "time": SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep), "process_owner_state": lambda *_: "owned"}
    function = next(node for node in ast.parse(_MCP_CHILD_SCRIPT).body if isinstance(node, ast.FunctionDef) and node.name == "_read_published_owners")
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<owner-publication-observation>", "exec"), namespace)
    observe = namespace["_read_published_owners"]
    if fault.startswith("permanent"):
        with pytest.raises(AssertionError, match="owner publication"):
            observe(StateDirectory(), deadline=0.03)
        assert clock[0] == pytest.approx(0.03) and attempts[0] <= 4
    elif fault == "corrupt":
        with pytest.raises(json.JSONDecodeError):
            observe(StateDirectory(), deadline=0.03)
        assert clock[0] == 0 and attempts[0] == 1
    else:
        assert observe(StateDirectory(), deadline=0.03) == (11, {"pid": 11}, {"pid": 22})
        assert attempts[0] == 2 and clock[0] == pytest.approx(0.01)
