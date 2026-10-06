from __future__ import annotations

import asyncio
import json
import os
import atexit
from pathlib import Path
import socket
import sys
import time

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from local_ai_hub.process_utils import pid_alive, process_identity


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _config(tmp_path: Path, *, startup_wait: float) -> tuple[Path, Path]:
    state_dir = tmp_path / "state"
    config_path = tmp_path / "isolated-hub.toml"
    config_path.write_text(
        f'[server]\nbind="127.0.0.1"\nport={_free_port()}\n'
        f'state_dir={json.dumps(state_dir.as_posix())}\nmax_concurrent_requests=8\n'
        f'[client]\nstartup_wait_seconds={startup_wait}\nstartup_poll_seconds=0.05\n'
        'health_timeout_seconds=0.25\nmax_request_timeout_seconds=10\n'
        '[features]\nstatus=true\n'
        '[hardware]\nprofile="cpu"\nauto_tune=false\n'
        '[ollama]\nenabled=false\n[smart_ollama]\nenabled=false\n'
        '[llama_cpp]\nmode="off"\n'
        '[code_intelligence]\nenabled=false\nserena_enabled=false\npreprocess_serena=false\n'
        '[preprocessing]\nenabled=false\n[background_gpu]\nenabled=false\n'
        '[agent_state]\nenabled=false\n',
        encoding="utf-8",
    )
    return config_path, state_dir


def _stdio_parameters(
    source_root: Path,
    probe_dir: Path,
    config_path: Path,
    child_log: Path,
    *,
    delay_child_seconds: float = 0,
) -> StdioServerParameters:
    env = os.environ.copy()
    env.update({
        "LOCAL_AI_CONFIG": str(config_path),
        "LOCAL_AI_AGENT": "t04-stdio-acceptance",
        "PYTHONPATH": os.pathsep.join((str(source_root), str(probe_dir))),
        "PYTHONDONTWRITEBYTECODE": "1",
        "T04_TRACKED_CHILD_FILE": str(child_log),
    })
    (probe_dir / "sitecustomize.py").write_text(
        "import atexit, json, os, subprocess, time\n"
        "from local_ai_hub.process_utils import process_identity\n"
        "_Popen = subprocess.Popen\n"
        "_owned = []\n"
        "class _TrackedPopen(_Popen):\n"
        "    def __init__(self, args, *pos, **kw):\n"
        "        argv = args if isinstance(args, (list, tuple)) else []\n"
        "        if '-m' in argv and 'local_ai_hub' in argv and '--config' in argv:\n"
        "            env = kw.get('env')\n"
        f"            if env is not None and {delay_child_seconds!r} > 0:\n"
        f"                env['T04_DELAY_HUB_CHILD_SECONDS'] = {str(delay_child_seconds)!r}\n"
        "        super().__init__(args, *pos, **kw)\n"
        "        if '-m' in argv and 'local_ai_hub' in argv and '--config' in argv:\n"
        "            identity = process_identity(self.pid)\n"
        "            row = {'pid': self.pid, 'identity': identity}\n"
        "            _owned.append(self)\n"
        "            with open(os.environ['T04_TRACKED_CHILD_FILE'], 'a', encoding='utf-8') as stream:\n"
        "                stream.write(json.dumps(row) + '\\n')\n"
        "subprocess.Popen = _TrackedPopen\n"
        "def _cleanup_owned():\n"
        "    for child in _owned:\n"
        "        if child.poll() is None:\n"
        "            child.terminate()\n"
        "            try:\n"
        "                child.wait(timeout=0.5)\n"
        "            except subprocess.TimeoutExpired:\n"
        "                child.kill()\n"
        "                child.wait(timeout=0.5)\n"
        "atexit.register(_cleanup_owned)\n"
        "if os.environ.get('T04_DELAY_HUB_CHILD_SECONDS'):\n"
        "    time.sleep(float(os.environ['T04_DELAY_HUB_CHILD_SECONDS']))\n",
        encoding="utf-8",
    )
    return StdioServerParameters(
        command=sys.executable,
        args=["-B", "-m", "local_ai_hub.mcp_server"],
        env=env,
        cwd=str(source_root.parent),
    )


def _launches(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _same_process(row: dict[str, object]) -> bool:
    pid = int(row["pid"])
    expected = row.get("identity")
    current = process_identity(pid)
    return bool(
        isinstance(expected, dict)
        and current
        and current.get("creation_identity_type") == expected.get("creation_identity_type")
        and current.get("creation_identity") == expected.get("creation_identity")
    )


def _stop_recorded_children(rows: list[dict[str, object]]) -> None:
    for row in rows:
        pid = int(row["pid"])
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and _same_process(row):
            time.sleep(0.05)
        assert not _same_process(row), f"isolated Hub child {pid} survived test cleanup"


async def _mcp_status(parameters: StdioServerParameters) -> dict[str, object]:
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert any(tool.name == "local_ai_status" for tool in tools.tools)
            result = await session.call_tool("local_ai_status", {"detail": "brief"})
            assert not result.isError
            assert result.content and hasattr(result.content[0], "text")
            return json.loads(result.content[0].text)


def test_stdio_handshake_starts_one_hub_for_simultaneous_cold_clients(tmp_path: Path) -> None:
    source_root = Path(__file__).resolve().parents[1] / "src"
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    child_log = tmp_path / "children.jsonl"
    config_path, state_dir = _config(tmp_path, startup_wait=8)
    parameters = [
        _stdio_parameters(source_root, probe_dir, config_path, child_log)
        for _ in range(2)
    ]

    async def call_both() -> list[dict[str, object]]:
        return await asyncio.gather(*(_mcp_status(item) for item in parameters))

    try:
        results = asyncio.run(asyncio.wait_for(call_both(), timeout=25))
        assert all(result["success"] is True for result in results)
        rows = _launches(child_log)
        assert len(rows) == 1, f"simultaneous cold MCP clients started {len(rows)} Hub children"
        assert pid_alive(int(rows[0]["pid"]))
        assert (state_dir / "hub.pid").exists()
        assert not (state_dir / "hub.start.lock").exists()
    finally:
        _stop_recorded_children(_launches(child_log))


def test_stdio_handshake_timeout_reaps_owned_hub_child(tmp_path: Path) -> None:
    source_root = Path(__file__).resolve().parents[1] / "src"
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    child_log = tmp_path / "children.jsonl"
    config_path, state_dir = _config(tmp_path, startup_wait=1)
    parameters = _stdio_parameters(
        source_root, probe_dir, config_path, child_log, delay_child_seconds=5,
    )

    try:
        result = asyncio.run(asyncio.wait_for(_mcp_status(parameters), timeout=12))
        assert result["success"] is False
        rows = _launches(child_log)
        assert len(rows) == 1
        pid = int(rows[0]["pid"])
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and _same_process(rows[0]):
            time.sleep(0.05)
        assert not _same_process(rows[0]), f"timed-out Hub child {pid} was orphaned"
        assert not (state_dir / "hub.start.lock").exists()
    finally:
        _stop_recorded_children(_launches(child_log))
