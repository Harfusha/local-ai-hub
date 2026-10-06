from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from queue import Queue
import time
from pathlib import Path

from local_ai_hub.operation_contracts import (
    OPERATION_CONTRACTS,
    operation_tool_input_schema,
    operation_tool_output_schema,
)


def test_stdio_handshake_publishes_all_registry_input_and_output_schemas() -> None:
    from local_ai_hub import mcp_server

    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(root / "src"), env.get("PYTHONPATH", "")) if value
    )
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "contract-test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]

    process = subprocess.Popen(
        [sys.executable, "-B", "-m", "local_ai_hub.mcp_server"],
        cwd=root,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    stdout_lines: Queue[str | None] = Queue()
    stderr_lines: list[str] = []

    def read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            stdout_lines.put(line)
        stdout_lines.put(None)

    def read_stderr() -> None:
        assert process.stderr is not None
        stderr_lines.extend(process.stderr)

    stdout_reader = threading.Thread(target=read_stdout, daemon=True)
    stderr_reader = threading.Thread(target=read_stderr, daemon=True)
    stdout_reader.start()
    stderr_reader.start()

    def send(message: dict[str, object]) -> None:
        assert process.stdin is not None
        process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()

    def receive(response_id: int) -> dict[str, object]:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                line = stdout_lines.get(timeout=max(0.01, deadline - time.monotonic()))
            except Exception as exc:
                raise AssertionError(
                    f"stdio MCP response {response_id} timed out; stderr={''.join(stderr_lines)[-2000:]}"
                ) from exc
            if line is None:
                raise AssertionError(
                    f"stdio MCP exited before response {response_id}; stderr={''.join(stderr_lines)[-2000:]}"
                )
            if not line.strip():
                continue
            response = json.loads(line)
            if response.get("id") == response_id:
                return response
        raise AssertionError(
            f"stdio MCP response {response_id} timed out; stderr={''.join(stderr_lines)[-2000:]}"
        )

    try:
        send(messages[0])
        initialize = receive(1)
        send(messages[1])
        send(messages[2])
        tool_list = receive(2)
    finally:
        if process.stdin is not None:
            process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        stdout_reader.join(timeout=1)
        stderr_reader.join(timeout=1)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

    assert process.returncode == 0, "".join(stderr_lines)[-2000:]
    assert initialize.get("result", {}).get("protocolVersion") == "2025-06-18"
    wire_tools = {tool["name"]: tool for tool in tool_list["result"]["tools"]}
    assert set(wire_tools) == set(OPERATION_CONTRACTS)

    for name in OPERATION_CONTRACTS:
        assert wire_tools[name]["inputSchema"] == operation_tool_input_schema(
            name, mcp_server.FEATURES
        ), name
        assert wire_tools[name]["outputSchema"] == operation_tool_output_schema(
            name, mcp_server.FEATURES
        ), name


def _isolated_config(tmp_path: Path) -> tuple[Path, Path, int]:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    state_dir = tmp_path / "hub-state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[server]\n"
        'bind = "127.0.0.1"\n'
        f"port = {port}\n"
        f'state_dir = "{state_dir.as_posix()}"\n'
        "[client]\n"
        "startup_wait_seconds = 20.0\n"
        "startup_poll_seconds = 0.1\n"
        "health_timeout_seconds = 0.5\n"
        "max_request_timeout_seconds = 40.0\n"
        "[features]\n"
        "status = true\n"
        "repo = true\n"
        "tasks = true\n"
        "vision = true\n"
        "rag = true\n"
        "commands = true\n"
        "coord = true\n"
        "artifacts = true\n"
        "agent_os = true\n"
        "work_orchestrator = true\n",
        encoding="utf-8",
    )
    return config_path, state_dir, port


def _mcp_env(root: Path, config_path: Path, extra_pythonpath: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["LOCAL_AI_CONFIG"] = str(config_path)
    parts = [str(root / "src")]
    if extra_pythonpath is not None:
        parts.insert(0, str(extra_pythonpath))
    if env.get("PYTHONPATH"):
        parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def test_mcp_sdk_absence_keeps_importable_fallback(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    config_path, _state_dir, _port = _isolated_config(tmp_path)
    script = r"""
import builtins
real_import = builtins.__import__
def without_mcp(name, *args, **kwargs):
    if name == "mcp" or name.startswith("mcp."):
        raise ImportError("MCP SDK deliberately unavailable")
    return real_import(name, *args, **kwargs)
builtins.__import__ = without_mcp
from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import OPERATION_CONTRACTS
assert mcp_server.FastMCP is None
registered = {tool.__name__ for tool in mcp_server.mcp.tools}
assert "local_ai_status" in registered
assert registered <= set(OPERATION_CONTRACTS)
try:
    mcp_server.mcp.run()
except SystemExit as exc:
    assert "Missing MCP dependency" in str(exc)
else:
    raise AssertionError("missing SDK fallback unexpectedly ran")
print("fallback-ok")
"""
    env = _mcp_env(root, config_path)
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert "fallback-ok" in completed.stdout


def test_stdio_status_call_cold_starts_isolated_hub_and_cleans_up(tmp_path: Path) -> None:
    from local_ai_hub.process_utils import pid_alive, terminate_tree

    root = Path(__file__).resolve().parents[1]
    config_path, state_dir, port = _isolated_config(tmp_path)
    child_log = tmp_path / "children.txt"
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(
        "import os, subprocess\n"
        "_popen = subprocess.Popen\n"
        "class _TrackedPopen(_popen):\n"
        "    def __init__(self, *args, **kwargs):\n"
        "        super().__init__(*args, **kwargs)\n"
        "        command = kwargs.get('args', args[0] if args else ())\n"
        "        if isinstance(command, str):\n"
        "            command = command.split()\n"
        "        command = list(command or ())\n"
        "        if '-m' in command and any(part.startswith('local_ai_hub') for part in command):\n"
        "            with open(os.environ['LOCAL_AI_TEST_CHILD_LOG'], 'a', encoding='ascii') as stream:\n"
        "                stream.write(str(self.pid) + '\\n')\n"
        "subprocess.Popen = _TrackedPopen\n",
        encoding="utf-8",
    )
    env = _mcp_env(root, config_path, tmp_path)
    env["LOCAL_AI_TEST_CHILD_LOG"] = str(child_log)
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "cold-start-test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "local_ai_status",
                "arguments": {"action": "status", "detail": "brief"},
            },
        },
    ]
    assert not (state_dir / "hub.pid").exists()
    with socket.socket() as probe:
        assert probe.connect_ex(("127.0.0.1", port)) != 0
    completed = None
    try:
        completed = subprocess.run(
            [sys.executable, "-B", "-m", "local_ai_hub.mcp_server"],
            cwd=root,
            env=env,
            input="".join(json.dumps(item, separators=(",", ":")) + "\n" for item in messages),
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr[-2000:]
        responses = [
            json.loads(line) for line in completed.stdout.splitlines() if line.strip()
        ]
        response = next(item for item in responses if item.get("id") == 2)
        result = response.get("result", {})
        payload = result.get("structuredContent")
        if not isinstance(payload, dict):
            payload = next(
                json.loads(block["text"])
                for block in result.get("content", [])
                if block.get("type") == "text"
            )
        assert payload.get("success") is True, payload
        assert (state_dir / "hub.pid").is_file()
        assert child_log.is_file()
    finally:
        pids: set[int] = set()
        if child_log.is_file():
            pids.update(int(line) for line in child_log.read_text(encoding="ascii").splitlines() if line.strip())
        for name in ("supervisor.pid", "hub.pid"):
            try:
                pids.add(int((state_dir / name).read_text(encoding="utf-8").strip()))
            except (OSError, ValueError):
                pass
        for pid in pids:
            terminate_tree(pid, grace_seconds=2.0)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and any(pid_alive(pid) for pid in pids):
            time.sleep(0.1)
        alive = sorted(pid for pid in pids if pid_alive(pid))
        assert not alive, f"orphan Hub processes remain: {alive}; stderr={getattr(completed, 'stderr', '')[-1000:]}"
