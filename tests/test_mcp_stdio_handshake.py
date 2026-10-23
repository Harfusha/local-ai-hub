from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tomllib
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from local_ai_hub.config import load_config
from local_ai_hub.generator import generate_mcp_configs

ROOT = Path(__file__).resolve().parents[1]
SETUP_SPEC = importlib.util.spec_from_file_location("local_ai_hub_setup", ROOT / "tools" / "setup.py")
assert SETUP_SPEC and SETUP_SPEC.loader
setup = importlib.util.module_from_spec(SETUP_SPEC)
SETUP_SPEC.loader.exec_module(setup)
EXPECTED_TOOLS = {
    "local_ai_artifact",
    "local_ai_coord",
    "local_ai_rag",
    "local_ai_repo",
    "local_ai_status",
    "local_ai_task",
    "local_ai_work",
}


async def _handshake(manifest_entry: dict[str, object]) -> None:
    env = os.environ.copy()
    env.update(manifest_entry.get("env", {}))
    params = StdioServerParameters(
        command=manifest_entry["command"],
        args=manifest_entry["args"],
        env=env,
        cwd=manifest_entry["cwd"],
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await asyncio.wait_for(session.initialize(), timeout=20)
            assert initialized.serverInfo.name == "Local AI Hub (compact)"
            names: list[str] = []
            cursor: str | None = None
            pages = 0
            while True:
                page = await asyncio.wait_for(session.list_tools(cursor=cursor), timeout=20)
                names.extend(tool.name for tool in page.tools)
                pages += 1
                if not page.nextCursor:
                    break
                assert page.nextCursor != cursor
                assert pages < 4
                cursor = page.nextCursor
            assert set(names) == EXPECTED_TOOLS
            assert len(names) == len(EXPECTED_TOOLS)


@pytest.mark.parametrize(
    "agent",
    ["generic", "claude", "gemini", "cursor", "windsurf", "copilot", "codex", "antigravity"],
)
def test_generated_stdio_manifest_performs_initialize_and_complete_tools_list(tmp_path: Path, agent: str):
    config = tmp_path / "config.toml"
    state_dir = json.dumps(str(tmp_path / "state" / agent))
    config.write_text(
        "[server]\n"
        f"state_dir = {state_dir}\n"
        "port = 21435\n"
        "auto_start_ollama = true\n\n"
        "[ollama]\n"
        "enabled = true\n",
        encoding="utf-8",
    )
    cfg = load_config(str(config))
    entry = generate_mcp_configs(cfg, tmp_path, Path(sys.executable), agent=agent)["local-ai"]
    assert entry["env"]["LOCAL_AI_AGENT"] == agent
    assert entry["env"]["LOCAL_AI_AGENT_PROFILE"] == agent
    entry["env"]["PYTHONPATH"] = str(ROOT / "src")
    manifest_path = tmp_path / "mcp-servers.json"
    manifest_path.write_text(json.dumps({"mcpServers": {"local-ai": entry}}), encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_entry = manifest["mcpServers"]["local-ai"]
    asyncio.run(asyncio.wait_for(_handshake(manifest_entry), timeout=45))


@pytest.mark.parametrize(
    "host,agent,manifest_kind",
    [
        ("claude", "claude", "json"),
        ("gemini", "gemini", "json"),
        ("cursor", "cursor", "json"),
        ("windsurf", "windsurf", "json"),
        ("copilot", "copilot", "vscode"),
        ("codex", "codex", "toml"),
        ("antigravity", "gemini", "antigravity"),
    ],
)
def test_merged_host_manifest_entry_performs_initialize_and_complete_tools_list(
    tmp_path: Path, host: str, agent: str, manifest_kind: str,
):
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    config = install_dir / "config.toml"
    state_dir = json.dumps(str(tmp_path / "state"))
    config.write_text(
        "[server]\n"
        f"state_dir = {state_dir}\n"
        "port = 21435\n"
        "auto_start_ollama = true\n\n"
        "[ollama]\n"
        "enabled = true\n",
        encoding="utf-8",
    )
    servers = setup.build_mcp_entries(
        install_dir, Path(sys.executable), None, agent,
        {"code_intelligence": {"direct_agent_mcp": False}},
    )
    servers["local-ai"]["env"]["PYTHONPATH"] = str(ROOT / "src")

    if manifest_kind == "vscode":
        path = tmp_path / f"{host}.json"
        setup.vscode_mcp_merge(path, servers, False)
        manifest_entry = json.loads(path.read_text(encoding="utf-8"))["servers"]["local-ai"]
        assert manifest_entry["type"] == "stdio"
    elif manifest_kind == "toml":
        path = tmp_path / f"{host}.toml"
        setup.codex_mcp_merge(path, servers, False)
        manifest_entry = tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]["local-ai"]
    elif manifest_kind == "antigravity":
        path = tmp_path / f"{host}.json"
        setup.sync_antigravity_mcp_config(path, install_dir, Path(sys.executable), None,
                                          {"code_intelligence": {"direct_agent_mcp": False}}, False)
        manifest_entry = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["local-ai"]
        manifest_entry["env"]["PYTHONPATH"] = str(ROOT / "src")
    else:
        path = tmp_path / f"{host}.json"
        setup.json_mcp_merge(path, servers, False)
        manifest_entry = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["local-ai"]

    assert manifest_entry["command"] == str(sys.executable)
    assert manifest_entry["args"] == ["-m", "local_ai_hub.mcp_server"]
    assert manifest_entry["cwd"] == str(install_dir)
    assert manifest_entry["env"]["LOCAL_AI_CONFIG"] == str(config)
    assert manifest_entry["env"]["PYTHONPATH"] == str(ROOT / "src")
    assert manifest_entry["env"]["LOCAL_AI_AGENT"] == agent
    assert manifest_entry["env"]["LOCAL_AI_AGENT_PROFILE"] == agent
    asyncio.run(asyncio.wait_for(_handshake(manifest_entry), timeout=45))
