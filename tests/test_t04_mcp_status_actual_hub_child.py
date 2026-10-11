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
from local_ai_hub.process_utils import process_owner_state

client = mcp_server.CLIENT
assert client.auto_start is True
real_popen = real_subprocess.Popen
launches = []

def tracked_popen(argv, **kwargs):
    stdout_log = open(os.environ["T04_CHILD_STDOUT_FILE"], "ab")
    stderr_log = open(os.environ["T04_CHILD_STDERR_FILE"], "ab")
    kwargs["stdout"] = stdout_log
    kwargs["stderr"] = stderr_log
    child = real_popen(argv, **kwargs)
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
    Path(os.environ["T04_TRACKED_PID_FILE"]).write_text(str(child.pid), encoding="ascii")
    return child

client_module.subprocess = SimpleNamespace(
    Popen=tracked_popen,
    DEVNULL=real_subprocess.DEVNULL,
    TimeoutExpired=real_subprocess.TimeoutExpired,
)
ensure_calls = []
original_ensure = client.ensure_server

def tracked_ensure(timeout=None):
    ensure_calls.append(timeout)
    return original_ensure(timeout=timeout)

client.ensure_server = tracked_ensure
started_ids = {id(item) for item in client_module._DETACHED_CHILDREN}
children = []
timer = None

def stop_owned_children():
    for process, _record in launches:
        if process.poll() is None:
            client_module._stop_owned_child(process)

try:
    os.environ["T04_EXPECT_PARENT_PID"] = str(os.getpid())
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
    hub_pid = int((state_dir / "hub.pid").read_text(encoding="ascii").strip())
    hub_owner = json.loads((state_dir / "hub.owner.json").read_text(encoding="utf-8"))
    assert int(hub_owner["pid"]) == hub_pid
    assert process_owner_state(hub_owner, state_dir, "hub") == "owned"
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
    stop_owned_children()
    for process, _record in launches:
        process.wait(timeout=2)
        assert process.poll() is not None, f"owned Hub child {process.pid} survived shutdown"
        _record["stdout_log"].close()
        _record["stderr_log"].close()
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
        "site.addsitedir(os.environ['T04_TEST_SITE_PACKAGES'])\n"
        "from pathlib import Path\n"
        "expected = os.environ.get('T04_EXPECT_PARENT_PID')\n"
        "if expected and os.getppid() == int(expected):\n"
        "    import local_ai_hub\n"
        "    spec = importlib.util.find_spec('local_ai_hub.__main__')\n"
        "    Path(os.environ['T04_CHILD_SOURCE_FILE']).write_text(json.dumps({"
        "'package_file': str(Path(local_ai_hub.__file__).resolve()), "
        "'entrypoint_file': str(Path(spec.origin).resolve())}), encoding='utf-8')\n"
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
        "T04_TEST_SITE_PACKAGES": site.getusersitepackages(),
        "LOCAL_AI_CONFIG": str(config_path),
        "T04_CHILD_SOURCE_FILE": str(child_source_file),
        "T04_TRACKED_PID_FILE": str(tracked_pid_file),
        "T04_CHILD_STDOUT_FILE": str(child_stdout_file),
        "T04_CHILD_STDERR_FILE": str(child_stderr_file),
    }
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
        env["WINDIR"] = os.environ.get("WINDIR", env["SYSTEMROOT"])

    process = subprocess.Popen(
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
    try:
        stdout, stderr = process.communicate(timeout=18)
    except subprocess.TimeoutExpired:
        if tracked_pid_file.exists():
            pid = tracked_pid_file.read_text(encoding="ascii").strip()
            if pid.isdigit():
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", pid, "/T", "/F"],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        **_hidden_kwargs(),
                    )
                else:
                    try:
                        os.kill(int(pid), 15)
                    except ProcessLookupError:
                        pass
        process.kill()
        stdout, stderr = process.communicate(timeout=3)
        pytest.fail(f"isolated MCP autostart exceeded 18s; helper={stdout!r}; stderr={stderr!r}")

    assert process.returncode == 0, stdout + stderr
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
