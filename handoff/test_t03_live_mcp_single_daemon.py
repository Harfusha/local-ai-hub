from __future__ import annotations

import json
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from local_ai_hub.process_utils import find_listening_pid, pid_alive, terminate_tree


def _daemon_pids(config_path: Path, timeout: float = 8) -> list[int]:
    if os.name == "nt":
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            raise RuntimeError("PowerShell unavailable for process count")
        script = (
            "$needle = [Console]::In.ReadToEnd(); "
            "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and "
            "$_.CommandLine.Contains($needle) -and $_.CommandLine -match '-m local_ai_hub(\\s|$)' } | "
            "ForEach-Object { $_.ProcessId }"
        )
        result = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", script],
            input=str(config_path), capture_output=True, text=True, timeout=timeout, check=False,
        )
        if result.returncode or result.stderr.strip():
            raise RuntimeError(f"process count failed: {result.stderr[-500:]}")
        return sorted(int(line) for line in result.stdout.splitlines() if line.strip().isdigit())
    if sys.platform == "linux":
        expected = os.fsencode(str(config_path))
        found = []
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit():
                try:
                    cmdline = (entry / "cmdline").read_bytes()
                except OSError:
                    continue
                if b"-m\x00local_ai_hub\x00" in cmdline and expected in cmdline:
                    found.append(int(entry.name))
        return sorted(found)
    raise RuntimeError(f"process count unsupported on {sys.platform}")


def _process_metrics(pid: int) -> dict[str, object]:
    if os.name == "nt":
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            raise RuntimeError("PowerShell unavailable for process metrics")
        script = (
            "$target = [Console]::In.ReadToEnd(); "
            "Get-Process -Id ([int]$target) -ErrorAction Stop | "
            "Select-Object Id,WorkingSet64,CPU | ConvertTo-Json -Compress"
        )
        result = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", script],
            input=str(pid), capture_output=True, text=True, timeout=6, check=False,
        )
        if result.returncode or result.stderr.strip():
            raise RuntimeError(f"process metrics failed: {result.stderr[-300:]}")
        item = json.loads(result.stdout)
        return {
            "pid": int(item["Id"]),
            "rss_bytes": int(item["WorkingSet64"]),
            "cpu_seconds": float(item["CPU"]) if item.get("CPU") is not None else None,
            "sampled_monotonic": time.monotonic(),
        }
    if sys.platform == "linux":
        proc = Path("/proc") / str(pid)
        status = (proc / "status").read_text(encoding="ascii")
        rss_kib = next(
            int(line.split()[1]) for line in status.splitlines() if line.startswith("VmRSS:")
        )
        stat = (proc / "stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()
        cpu_ticks = int(stat[11]) + int(stat[12])
        return {
            "pid": pid,
            "rss_bytes": rss_kib * 1024,
            "cpu_seconds": cpu_ticks / os.sysconf("SC_CLK_TCK"),
            "sampled_monotonic": time.monotonic(),
        }
    raise RuntimeError(f"process metrics unsupported on {sys.platform}")


def _wait(predicate, timeout: float, label: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timeout waiting for {label}")


def _messages(index: int) -> str:
    items = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": f"t03-client-{index}", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "local_ai_status", "arguments": {"detail": "brief"}}},
    ]
    return "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in items)


def _write_messages(stdin, index: int) -> None:
    stdin.write(_messages(index))
    stdin.flush()


def _safe_scalar(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:128]
    return None


def _response_summary(line: str) -> dict[str, object]:
    encoded = line.encode("utf-8", errors="replace")
    summary: dict[str, object] = {
        "line_bytes": len(encoded),
        "line_sha256": hashlib.sha256(encoded).hexdigest(),
    }
    try:
        item = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        summary.update(json_type="invalid", parse_error=True)
        return summary
    if isinstance(item, dict):
        error = item.get("error")
        error_code = error.get("code") if isinstance(error, dict) else item.get("error_code")
        request_id = item.get("id")
        summary.update(
            json_type="object",
            method=_safe_scalar(item.get("method")),
            id_type=type(request_id).__name__ if "id" in item else None,
            id_value=_safe_scalar(request_id),
            error_code=_safe_scalar(error_code),
        )
    elif isinstance(item, list):
        summary.update(json_type="array")
    elif item is None:
        summary.update(json_type="null")
    else:
        summary.update(json_type=type(item).__name__)
    return summary


def test_concurrent_stdio_clients_receive_batch_before_stdin_eof() -> None:
    worker = (
        "import json,sys\n"
        "for line in sys.stdin:\n"
        " message=json.loads(line)\n"
        " if 'id' in message:\n"
        "  print(json.dumps({'jsonrpc':'2.0','id':message['id'],'result':{}}),flush=True)\n"
    )
    clients = [subprocess.Popen(
        [sys.executable, "-B", "-c", worker], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
    ) for _ in range(8)]
    output = [[] for _ in clients]
    readers = []
    try:
        for index, client in enumerate(clients):
            assert client.stdin is not None
            _write_messages(client.stdin, index)
            reader = threading.Thread(
                target=lambda stream=client.stdout, lines=output[index]: lines.extend(stream),
                daemon=True,
            )
            reader.start()
            readers.append(reader)

        def received_all_ids(lines) -> bool:
            ids = set()
            for line in lines:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict) and isinstance(message.get("id"), int):
                    ids.add(message["id"])
            return {1, 2, 3} <= ids

        _wait(
            lambda: all(received_all_ids(lines) for lines in output),
            10,
            "JSON-RPC responses 1, 2, and 3 while all echo-client stdin pipes stay open",
        )
        for client in clients:
            assert client.stdin is not None
            client.stdin.close()
            client.stdin = None
        for client in clients:
            assert client.wait(timeout=10) == 0
        for reader in readers:
            reader.join(timeout=2)
        for client in clients:
            if client.stdout is not None:
                client.stdout.close()
                client.stdout = None
            assert not reader.is_alive(), "echo-client output reader did not finish after stdin EOF"
        assert all(received_all_ids(lines) for lines in output)
    finally:
        for client in clients:
            if client.stdin is not None:
                client.stdin.close()
                client.stdin = None
            if client.poll() is None:
                client.terminate()
        for client in clients:
            if client.poll() is None:
                client.wait(timeout=2)
        for reader in readers:
            reader.join(timeout=2)
        for client in clients:
            if client.stdout is not None:
                client.stdout.close()
                client.stdout = None


def test_thirty_real_stdio_clients_share_one_live_hub_process(tmp_path: Path) -> None:
    client_count = 30
    repo = Path(__file__).resolve().parents[1]
    src = repo / "src"
    run_root = tmp_path / "t03-live-mcp-30"
    assert not run_root.exists(), run_root
    run_root.mkdir()
    state = run_root / "state"
    state.mkdir()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = run_root / "hub.toml"
    config.write_text(
        "[server]\n"
        f'bind="127.0.0.1"\nport={port}\nstate_dir="{state.as_posix()}"\n'
        "auto_start_ollama=false\nmax_request_body_bytes=1048576\n"
        "[hardware]\nprofile=\"cpu\"\nauto_tune=false\n"
        "[prewarm]\nenabled=false\n"
        "[preprocessing]\nenabled=false\n"
        "[code_intelligence]\nenabled=false\n"
        "[background_gpu]\nenabled=false\n"
        "[observability]\nenabled=false\n"
        "[resilience]\nwatchdog_enabled=false\n"
        "[features]\nrag=false\ncommands=false\nrepo=false\n",
        encoding="utf-8",
    )
    ready = run_root / "ready"
    ready.mkdir()
    gate = run_root / "go"
    worker = r'''import sys, time
from pathlib import Path
src, ready_name, gate_name = sys.argv[1:]
sys.path.insert(0, src)
from local_ai_hub import mcp_server
Path(ready_name).touch()
gate = Path(gate_name)
deadline = time.monotonic() + 15
while not gate.exists() and time.monotonic() < deadline:
    time.sleep(.01)
if not gate.exists():
    raise SystemExit("client barrier timeout")
mcp_server.main()'''
    env = os.environ.copy()
    env["LOCAL_AI_CONFIG"] = str(config)
    env["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(src), env.get("PYTHONPATH", "")) if item
    )
    clients: list[subprocess.Popen[str]] = []
    server_pids: list[int] = []
    client_output: list[dict[str, list[str]]] = []
    readers: list[threading.Thread] = []
    client_runs: list[dict[str, object]] = []
    diagnostic_path = repo / "handoff" / "T03-live-mcp-30-client-acceptance-20261005.json"
    assert not diagnostic_path.exists(), diagnostic_path
    started = time.monotonic()
    timings: dict[str, float] = {}
    resource_samples: list[dict[str, object]] = []
    pre_server_pids: list[int] = []
    pre_pid_file_exists = False
    hub_pid: int | None = None
    failure: str | None = None
    diagnostic: dict[str, object] = {
        "execution_scope": "one bounded live MCP acceptance; isolated temporary Hub state",
        "client_count_expected": client_count,
        "config_path": str(config),
        "state_path": str(state),
        "shared_hub_state_touched": False,
        "timings_seconds": timings,
        "resource_samples": resource_samples,
    }
    try:
        pre_server_pids = _daemon_pids(config)
        pre_pid_file_exists = (state / "hub.pid").exists()
        diagnostic["preflight"] = {
            "config_matched_server_pids": pre_server_pids,
            "hub_pid_file_exists": pre_pid_file_exists,
        }
        assert not pre_server_pids and not pre_pid_file_exists, diagnostic["preflight"]
        for index in range(client_count):
            clients.append(subprocess.Popen(
                [sys.executable, "-B", "-c", worker, str(src), str(ready / f"{index}"), str(gate)],
                cwd=repo, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding="utf-8",
            ))
            client_output.append({"stdout": [], "stderr": []})
        _wait(
            lambda: len(list(ready.iterdir())) == client_count,
            25,
            f"{client_count} independent MCP clients",
        )
        timings["clients_ready"] = round(time.monotonic() - started, 3)
        for index, client in enumerate(clients):
            assert client.stdin is not None
            _write_messages(client.stdin, index)
            output = client_output[index]
            stdout_reader = threading.Thread(
                target=lambda stream=client.stdout, lines=output["stdout"]: lines.extend(stream),
                daemon=True,
            )
            stderr_reader = threading.Thread(
                target=lambda stream=client.stderr, chunks=output["stderr"]: chunks.append(stream.read()),
                daemon=True,
            )
            stdout_reader.start()
            stderr_reader.start()
            readers.extend((stdout_reader, stderr_reader))
        gate.touch()

        timings["gate_released"] = round(time.monotonic() - started, 3)

        def received_call_response(output) -> bool:
            found_ids = set()
            for line in output["stdout"]:
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(message, dict) and isinstance(message.get("id"), int):
                    found_ids.add(message["id"])
            if found_ids and "first_response" not in timings:
                timings["first_response"] = round(time.monotonic() - started, 3)
            return {1, 2, 3} <= found_ids

        _wait(
            lambda: (state / "hub.pid").exists(),
            25,
            "isolated Hub PID file after client startup",
        )
        hub_pid = int((state / "hub.pid").read_text(encoding="ascii").strip())
        server_pids = _daemon_pids(config, timeout=5)
        timings["hub_ready"] = round(time.monotonic() - started, 3)
        resource_samples.append(_process_metrics(hub_pid))
        diagnostic["daemon_count_at_startup"] = len(server_pids)
        diagnostic["daemon_pids_at_startup"] = server_pids
        assert server_pids == [hub_pid], {"server_pids": server_pids, "hub_pid": hub_pid}

        _wait(
            lambda: all(received_call_response(output) for output in client_output),
            60,
            f"responses 1, 2, and 3 from all {client_count} clients before stdin EOF",
        )
        timings["all_responses"] = round(time.monotonic() - started, 3)
        resource_samples.append(_process_metrics(hub_pid))
        server_pids = _daemon_pids(config, timeout=5)
        diagnostic["daemon_count_after_responses"] = len(server_pids)
        diagnostic["daemon_pids_after_responses"] = server_pids
        assert server_pids == [hub_pid], server_pids

        for client in clients:
            assert client.stdin is not None
            client.stdin.close()
            client.stdin = None
        for client in clients:
            client.wait(timeout=12)
        for reader in readers:
            reader.join(timeout=5)
            assert not reader.is_alive(), "client output reader did not finish after stdin EOF"
        assert all(client.returncode == 0 for client in clients), [
            {"pid": client.pid, "returncode": client.returncode} for client in clients
        ]

        assert find_listening_pid(port) == hub_pid
        print(
            f"measurement: mcp_clients={client_count} responses={client_count}/{client_count} "
            f"live_hub_processes={len(server_pids)} pid={hub_pid} "
            f"startup_seconds={timings['hub_ready']} total_seconds={timings['all_responses']}"
        )
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        diagnostic["failure"] = failure
    finally:
        for client in clients:
            if client.stdin is not None:
                try:
                    client.stdin.close()
                except OSError:
                    pass
                client.stdin = None
        for client in clients:
            if client.poll() is None:
                try:
                    client.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    client.terminate()
                    try:
                        client.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        client.kill()
                        client.wait(timeout=3)
        for reader in readers:
            reader.join(timeout=5)
        for client, output in zip(clients, client_output):
            lines = [line.rstrip("\r\n") for line in output["stdout"] if line.strip()]
            stderr = "".join(output["stderr"])
            responses = [_response_summary(line) for line in lines]
            client_runs.append({
                "client_index": len(client_runs),
                "pid": client.pid,
                "returncode": client.returncode,
                "stdout_nonempty_line_count": len(lines),
                "response_ids": [item.get("id_value") for item in responses if item.get("id_type")],
                "error_codes": [item.get("error_code") for item in responses if item.get("error_code") is not None],
                "response_shapes": responses,
                "stderr_line_count": len(stderr.splitlines()),
                "stderr_sha256": hashlib.sha256(stderr.encode("utf-8", errors="replace")).hexdigest(),
            })
        for client in clients:
            for stream in (client.stdout, client.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass

        pid_file = state / "hub.pid"
        try:
            server_pids = _daemon_pids(config, timeout=5)
        except Exception as exc:
            diagnostic["cleanup_enumeration_error"] = f"{type(exc).__name__}: {exc}"
            server_pids = []
        pid_value = None
        if pid_file.exists():
            try:
                pid_value = int(pid_file.read_text(encoding="ascii").strip())
            except (OSError, ValueError):
                diagnostic["cleanup_pid_file_read_error"] = True
        owned_pids = sorted(set(server_pids) - set(pre_server_pids))
        diagnostic["daemon_pids_before_cleanup"] = server_pids
        diagnostic["hub_pid_file_before_cleanup"] = {
            "exists": pid_file.exists(),
            "value": pid_value,
        }
        cleanup_actions = []
        owner_match = (
            not pre_server_pids
            and bool(owned_pids)
            and (not pid_file.exists() or pid_value in owned_pids)
        )
        cleanup_errors = []
        if owner_match:
            for pid in owned_pids:
                try:
                    terminate_tree(pid, grace_seconds=0.5)
                    cleanup_actions.append({"action": "terminate_tree", "pid": pid})
                except Exception as exc:
                    cleanup_errors.append(f"terminate {pid}: {type(exc).__name__}: {exc}")
            for pid in owned_pids:
                try:
                    _wait(lambda pid=pid: not pid_alive(pid), 5, f"owned Hub process {pid} cleanup")
                except Exception as exc:
                    cleanup_errors.append(f"wait {pid}: {type(exc).__name__}: {exc}")
            if pid_value in owned_pids and not pid_alive(pid_value) and pid_file.exists():
                pid_file.unlink()
                cleanup_actions.append({"action": "remove_dead_owned_pid_file", "pid": pid_value})
        try:
            post_server_pids = _daemon_pids(config, timeout=5)
        except Exception as exc:
            diagnostic["post_cleanup_enumeration_error"] = f"{type(exc).__name__}: {exc}"
            post_server_pids = [*owned_pids]
        cleanup_ok = (
            not post_server_pids
            and not pid_file.exists()
            and all(client.poll() is not None for client in clients)
        )
        cleanup = {
            "pre_config_matched_pids": pre_server_pids,
            "pre_pid_file_exists": pre_pid_file_exists,
            "owned_server_pids": owned_pids,
            "pid_file_value_before_cleanup": pid_value,
            "actions": cleanup_actions,
            "post_config_matched_pids": post_server_pids,
            "post_pid_file_exists": pid_file.exists(),
            "client_pids": [client.pid for client in clients],
            "client_returncodes": [client.returncode for client in clients],
            "cleanup_errors": cleanup_errors,
            "clean": cleanup_ok and not cleanup_errors and all(not pid_alive(pid) for pid in owned_pids),
        }
        cleanup_ok = cleanup["clean"]
        if cleanup_ok:
            shutil.rmtree(run_root)
            cleanup["temp_run_root_removed"] = not run_root.exists()
        else:
            cleanup["temp_run_root_left_for_ownership_safety"] = str(run_root)
        diagnostic["cleanup"] = cleanup
        diagnostic["clients"] = client_runs
        diagnostic["client_count_started"] = len(clients)
        diagnostic["resource_samples"] = resource_samples
        diagnostic["timings_seconds"] = timings
        diagnostic["test_status"] = "PASS" if failure is None and cleanup_ok else "FAIL"
        diagnostic_path.write_text(json.dumps(diagnostic, indent=2) + "\n", encoding="utf-8")

    if failure is not None:
        raise AssertionError(failure)
    assert cleanup["clean"], cleanup
