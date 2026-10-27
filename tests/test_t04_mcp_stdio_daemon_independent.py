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

from local_ai_hub.process_utils import pid_alive, process_identity, terminate_owned_process


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
        'health_timeout_seconds=0.25\nmax_request_timeout_seconds=40\n'
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
    keep_hub_after_client_exit: bool = False,
) -> StdioServerParameters:
    env = os.environ.copy()
    env.update({
        "LOCAL_AI_CONFIG": str(config_path),
        "LOCAL_AI_AGENT": "t04-stdio-acceptance",
        "PYTHONPATH": os.pathsep.join((str(source_root), str(probe_dir))),
        "PYTHONDONTWRITEBYTECODE": "1",
        "T04_TRACKED_CHILD_FILE": str(child_log),
        "T04_KEEP_HUB_AFTER_CLIENT_EXIT": "1" if keep_hub_after_client_exit else "0",
    })
    (probe_dir / "sitecustomize.py").write_text(
        "import atexit, json, os, subprocess, time\n"
        "from local_ai_hub.process_utils import process_identity, process_owner_record\n"
        "_Popen = subprocess.Popen\n"
        "_owned = []\n"
        "class _TrackedPopen(_Popen):\n"
        "    def __init__(self, args, *pos, **kw):\n"
        "        argv = args if isinstance(args, (list, tuple)) else []\n"
        "        with open(os.environ['T04_TRACKED_CHILD_FILE'] + '.all', 'a', encoding='utf-8') as stream:\n"
        "            stream.write(json.dumps({'argv': [str(item) for item in argv]}) + '\\n')\n"
        "        if '-m' in argv and any(item == 'local_ai_hub' or item.startswith('local_ai_hub.') for item in argv) and '--config' in argv:\n"
        "            env = kw.get('env')\n"
        f"            if env is not None and {delay_child_seconds!r} > 0:\n"
        f"                env['T04_DELAY_HUB_CHILD_SECONDS'] = {str(delay_child_seconds)!r}\n"
        "        super().__init__(args, *pos, **kw)\n"
        "        if '-m' in argv and any(item == 'local_ai_hub' or item.startswith('local_ai_hub.') for item in argv) and '--config' in argv:\n"
        "            identity = process_identity(self.pid)\n"
        "            row = {'pid': self.pid, 'identity': identity, 'keep_hub': os.environ.get('T04_KEEP_HUB_AFTER_CLIENT_EXIT')}\n"
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
        "if os.environ.get('T04_KEEP_HUB_AFTER_CLIENT_EXIT') != '1':\n"
        "    atexit.register(_cleanup_owned)\n"
        "if os.environ.get('T04_DELAY_HUB_CHILD_SECONDS'):\n"
        "    state_dir = os.path.dirname(os.environ['LOCAL_AI_CONFIG'])\n"
        "    owner = process_owner_record(os.getpid(), state_dir, 't04-delayed-worker')\n"
        "    with open(os.environ['T04_TRACKED_CHILD_FILE'] + '.workers', 'a', encoding='utf-8') as stream:\n"
        "        stream.write(json.dumps({'pid': os.getpid(), 'identity': process_identity(os.getpid()), 'owner': owner}) + '\\n')\n"
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


def _stop_recorded_children(rows: list[dict[str, object]], state_dir: Path) -> None:
    for row in rows:
        pid = int(row["pid"])
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and _same_process(row):
            time.sleep(0.05)
        if _same_process(row):
            owner_path = state_dir / "hub.owner.json"
            assert owner_path.is_file(), "live test Hub has no owner receipt"
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
            assert owner.get("pid") == pid, (
                f"test child {pid} differs from recorded Hub owner {owner.get('pid')}; "
                "refusing to terminate a different process"
            )
            assert terminate_owned_process(owner, state_dir, "hub", grace_seconds=1.0)
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
    config_path, state_dir = _config(tmp_path, startup_wait=30)
    parameters = [
        _stdio_parameters(
            source_root, probe_dir, config_path, child_log,
            keep_hub_after_client_exit=True,
        )
        for _ in range(2)
    ]

    async def call_both() -> list[dict[str, object]]:
        return await asyncio.gather(*(_mcp_status(item) for item in parameters))

    try:
        results = asyncio.run(asyncio.wait_for(call_both(), timeout=45))
        state_files = sorted(path.name for path in state_dir.iterdir()) if state_dir.exists() else []
        assert all(
            result.get("hub_online") is True
            and (result.get("success") is True or (
                result.get("degraded") is True
                and result.get("retryable") is True
                and result.get("terminal") is False
                and result.get("error") == "status snapshot is warming"
            ) or (
                result.get("success") is False
                and result.get("degraded") is True
                and isinstance(result.get("dependency_status"), dict)
                and bool(result["dependency_status"])
                and all(isinstance(item, dict) and item.get("degraded") is True
                        for item in result["dependency_status"].values())
            ))
            for result in results
        ), (
            f"cold MCP failures: {[(item.get('error'), item.get('status_code')) for item in results]!r}; "
            f"results={results!r}; "
            f"launches={_launches(child_log)!r}; state_files={state_files!r}"
        )
        rows = _launches(child_log)
        assert len(rows) == 1, f"simultaneous cold MCP clients started {len(rows)} Hub children"
        assert (state_dir / "hub.pid").exists()
        assert (state_dir / "hub.start.lock").read_bytes() == b""
    finally:
        _stop_recorded_children(_launches(child_log), state_dir=state_dir)


def test_stdio_handshake_timeout_reaps_owned_hub_child(tmp_path: Path) -> None:
    source_root = Path(__file__).resolve().parents[1] / "src"
    probe_dir = tmp_path / "probe"
    probe_dir.mkdir()
    child_log = tmp_path / "children.jsonl"
    config_path, state_dir = _config(tmp_path, startup_wait=8)
    parameters = _stdio_parameters(
        source_root, probe_dir, config_path, child_log, delay_child_seconds=20,
        keep_hub_after_client_exit=True,
    )

    try:
        result = asyncio.run(asyncio.wait_for(_mcp_status(parameters), timeout=16))
        assert result["success"] is False
        rows = _launches(child_log)
        state_files = sorted(path.name for path in state_dir.iterdir()) if state_dir.exists() else []
        all_launches_path = Path(str(child_log) + ".all")
        all_launches = all_launches_path.read_text(encoding="utf-8") if all_launches_path.exists() else ""
        assert len(rows) == 1, (
            f"no owned Hub child was recorded; MCP result: {result!r}; "
            f"state_files={state_files!r}; subprocess_calls={all_launches!r}"
        )
        pid = int(rows[0]["pid"])
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and _same_process(rows[0]):
            time.sleep(0.05)
        assert not _same_process(rows[0]), f"timed-out Hub child {pid} was orphaned"
        workers = _launches(Path(str(child_log) + ".workers"))
        assert workers, "delayed supervisor interpreter never reached its startup marker"
        assert all(not _same_process(row) for row in workers), "timed-out supervisor interpreter survived owned tree cleanup"
        lock_owner = (state_dir / "hub.start.lock").read_text(encoding="ascii").split()
        assert len(lock_owner) >= 2
        assert int(lock_owner[0]) > 0
        assert float(lock_owner[1]) > 0
    finally:
        for worker in _launches(Path(str(child_log) + ".workers")):
            if _same_process(worker):
                assert terminate_owned_process(worker["owner"], config_path.parent, "t04-delayed-worker", grace_seconds=1.0)
        _stop_recorded_children(_launches(child_log), state_dir=state_dir)
