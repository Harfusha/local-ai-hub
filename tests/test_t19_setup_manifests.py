from __future__ import annotations

import importlib.util
import json
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("local_ai_hub_setup", ROOT / "tools" / "setup.py")
assert SPEC and SPEC.loader
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def _entries(tmp_path: Path, agent: str) -> dict[str, dict[str, object]]:
    config = {"code_intelligence": {"direct_agent_mcp": False}}
    return setup.build_mcp_entries(tmp_path / "install", tmp_path / "python", None, agent, config)


@pytest.mark.parametrize("agent", ["claude", "gemini", "cursor", "windsurf"])
def test_json_host_manifests_parse_preserve_and_merge_idempotently(tmp_path: Path, agent: str):
    path = tmp_path / f"{agent}.json"
    path.write_text(
        json.dumps({"custom_setting": "preserve", "mcpServers": {"user-server": {"command": "user-command"}}}),
        encoding="utf-8",
    )
    entries = _entries(tmp_path, agent)

    setup.json_mcp_merge(path, entries, False)
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["custom_setting"] == "preserve"
    assert parsed["mcpServers"]["user-server"]["command"] == "user-command"
    assert parsed["mcpServers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == agent

    first_merge = path.read_bytes()
    setup.json_mcp_merge(path, entries, False)
    assert path.read_bytes() == first_merge


def test_copilot_manifest_parses_as_stdio_and_merge_is_idempotent(tmp_path: Path):
    path = tmp_path / "copilot.json"
    path.write_text(
        json.dumps({"custom_setting": "preserve", "servers": {"user-server": {"command": "user-command"}}}),
        encoding="utf-8",
    )
    entries = _entries(tmp_path, "copilot")

    setup.vscode_mcp_merge(path, entries, False)
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["custom_setting"] == "preserve"
    assert parsed["servers"]["user-server"]["command"] == "user-command"
    assert parsed["servers"]["local-ai"]["type"] == "stdio"
    assert parsed["servers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == "copilot"

    first_merge = path.read_bytes()
    setup.vscode_mcp_merge(path, entries, False)
    assert path.read_bytes() == first_merge


def test_codex_manifest_parses_preserves_unmanaged_tables_and_merges_idempotently(tmp_path: Path):
    path = tmp_path / "codex.toml"
    path.write_text('[model]\nprovider="preserve"\n\n[mcp_servers.user-server]\ncommand="user-command"\n', encoding="utf-8")
    entries = _entries(tmp_path, "codex")

    setup.codex_mcp_merge(path, entries, False)
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["model"]["provider"] == "preserve"
    assert parsed["mcp_servers"]["user-server"]["command"] == "user-command"
    assert parsed["mcp_servers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == "codex"

    first_merge = path.read_bytes()
    setup.codex_mcp_merge(path, entries, False)
    assert path.read_bytes() == first_merge


def test_antigravity_manifest_parses_preserves_user_servers_and_merges_idempotently(tmp_path: Path):
    path = tmp_path / "antigravity.json"
    path.write_text(
        json.dumps({"custom_setting": "preserve", "mcpServers": {"user-server": {"command": "user-command"}}}),
        encoding="utf-8",
    )
    install_dir = tmp_path / "install"
    python = tmp_path / "python"
    config = {"code_intelligence": {"direct_agent_mcp": False}}

    setup.sync_antigravity_mcp_config(path, install_dir, python, None, config, False)
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["custom_setting"] == "preserve"
    assert parsed["mcpServers"]["user-server"]["command"] == "user-command"
    assert parsed["mcpServers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == "gemini"

    first_merge = path.read_bytes()
    setup.sync_antigravity_mcp_config(path, install_dir, python, None, config, False)
    assert path.read_bytes() == first_merge
