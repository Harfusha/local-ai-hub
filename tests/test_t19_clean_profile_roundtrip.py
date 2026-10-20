"""Portable configuration/prompt lifecycle; not full installed-host acceptance."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tomllib
from unittest.mock import patch


def _roundtrip(source_root: Path, scratch: Path) -> dict:
    # A fresh interpreter prevents candidate conftest imports masking root imports.
    sys.path.insert(0, str(source_root / "src"))
    spec = importlib.util.spec_from_file_location("t19_portable_setup", source_root / "tools/setup.py")
    assert spec and spec.loader
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    from local_ai_hub import config, generator, hardware

    origins = {"setup": Path(setup.__file__).resolve()}
    for module in (config, generator, hardware):
        origins[module.__name__] = Path(module.__file__).resolve()
        assert origins[module.__name__].is_relative_to(source_root / "src")
    assert origins["setup"] == source_root / "tools/setup.py"
    source_files = [*origins.values(), source_root / "defaults.toml"]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
    home = scratch / "home"
    home.mkdir()
    assert not any(home.iterdir())
    install = home / ".local-ai-hub"
    codex = home / ".codex"
    bootstrap = scratch / "bootstrap.toml"
    bootstrap.write_text(
        '[hardware]\nprofile = "balanced"\nauto_tune = false\n'
        '[server]\nport = 11439\nauto_start_ollama = true\nstate_dir = "~/.local-ai-hub/state"\n'
        '[models]\ngeneral = "qwen2.5-coder:3b"\n'
        '[llama_cpp]\nmode = "off"\n'
        '[ollama]\nenabled = true\n'
        '[setup]\ninstall_dir = "~/.local-ai-hub"\nbackup_existing_configs = false\n'
        '[agents]\nagent_skills_standard = true\n'
        'codex = true\nclaude = true\ngemini = true\ncursor = true\n'
        'windsurf = true\ncopilot = true\nextra_mcp_json_paths = []\nextra_vscode_mcp_paths = []\n'
        '[tool_policy]\ninstall_global_instructions = true\n',
        encoding="utf-8",
    )
    forbidden = AssertionError("portable fixture must not start processes or connect sockets")
    # Only host discovery is substituted; config, copy, merge and generator execute.
    with (
        patch.object(Path, "home", return_value=home),
        # Windows USERNAME and MultiGravity discovery can escape a patched
        # HOME/USERPROFILE. This test owns exactly one synthetic home.
        patch.object(setup, "get_user_homes", return_value=[home]),
        patch.object(hardware, "detect_hardware", return_value={"profile": "balanced"}),
        patch.object(subprocess, "Popen", side_effect=forbidden),
        patch.object(socket, "socket", side_effect=forbidden),
    ):
        selected, cfg, target = setup.select_config_source(bootstrap)
        assert selected == bootstrap and target == install
        assert Path(cfg["server"]["state_dir"]) == install / "state"
        setup.copy_install_tree(target, selected)
        installed_config = install / "config.toml"
        cfg = config.load_config(installed_config)
        setup.configure_agents(install, Path(sys.executable), None, cfg, include_companion=False)
        docs = [codex / "AGENTS.md", home / ".claude/CLAUDE.md", home / ".gemini/GEMINI.md"]
        old_policy = (install / "generated/agent-policy.md").read_text(encoding="utf-8")
        assert "`qwen2.5-coder:3b` for ordinary tasks" not in old_policy
        user_prompt = "\nUser rule: preserve this fixture-owned instruction.\n"
        for doc in docs:
            assert generator.generate_global_policy(cfg) in doc.read_text(encoding="utf-8")
            with doc.open("a", encoding="utf-8") as stream:
                stream.write(user_prompt)
        # Operator changes after install: unmanaged host settings and runtime overlay.
        codex_config = codex / "config.toml"
        with codex_config.open("a", encoding="utf-8") as stream:
            stream.write('\n[user_fixture]\nnote = "keep"\n[mcp_servers.external]\ncommand = "keep"\n')
        claude_config = home / ".claude.json"
        claude = json.loads(claude_config.read_text(encoding="utf-8"))
        claude["user_fixture"] = {"keep": True}
        claude["mcpServers"]["external"] = {"command": "keep"}
        claude_config.write_text(json.dumps(claude), encoding="utf-8")
        installed_config.write_text(
            installed_config.read_text(encoding="utf-8") + '\n[operator_fixture]\nnote = "keep"\n',
            encoding="utf-8",
        )
        runtime = config.save_runtime_overrides(
            installed_config, {"models": {"general": "qwen3.5:9b"}, "server": {"port": 11437}},
        )
        retained = {path: path.read_bytes() for path in (installed_config, runtime)}
        stale_schema = install / "generated/schemas/retired-fixture.json"
        stale_schema.write_text("{}", encoding="utf-8")
        # Installed setup's no-explicit-config branch, without reading real user config.
        with patch.object(setup, "SOURCE_ROOT", install):
            selected, updated, target = setup.select_config_source(None)
        assert selected == installed_config and target == install
        assert updated["operator_fixture"]["note"] == "keep"
        assert updated["models"]["general"] == "qwen3.5:9b"
        assert updated["server"]["port"] == 11437
        assert updated["_defaults_path"] == str(install / "defaults.toml")
        setup.copy_install_tree(target, selected)
        updated = config.load_config(installed_config)
        setup.configure_agents(install, Path(sys.executable), None, updated, include_companion=False)
        assert all(path.read_bytes() == content for path, content in retained.items())
        assert not stale_schema.exists()
        new_policy = (install / "generated/agent-policy.md").read_text(encoding="utf-8")
        assert new_policy == old_policy
        assert "`qwen3.5:9b` for ordinary tasks" not in new_policy
        assert "`qwen2.5-coder:3b` for ordinary tasks" not in new_policy
        for doc in docs:
            text = doc.read_text(encoding="utf-8")
            assert generator.generate_global_policy(updated) in text
            assert text.count(setup.GLOBAL_POLICY_BEGIN) == 1
            assert text.count(setup.TOKEN_ECONOMY_POLICY_BEGIN) == 1
            assert text.count(user_prompt.strip()) == 1
        for host in (codex, home / ".agents", home / ".claude", home / ".gemini"):
            skill = host / "skills/local-ai-orchestrator/SKILL.md"
            assert skill.read_bytes() == (install / "skills/local-ai-orchestrator/SKILL.md").read_bytes()
        codex_data = tomllib.loads(codex_config.read_text(encoding="utf-8"))
        assert codex_data["user_fixture"] == {"note": "keep"}
        assert codex_data["mcp_servers"]["external"] == {"command": "keep"}
        entry = codex_data["mcp_servers"]["local-ai"]
        assert entry["env"]["LOCAL_AI_CONFIG"] == str(installed_config)
        assert entry["env"]["PYTHONPATH"] == str(install / "src")
        assert entry["cwd"] == str(install)
        hosts = {
            ".claude.json": "mcpServers", ".gemini/settings.json": "mcpServers",
            ".gemini/config/mcp_config.json": "mcpServers", ".cursor/mcp.json": "mcpServers",
            ".codeium/windsurf/mcp_config.json": "mcpServers", ".copilot/mcp-config.json": "servers",
        }
        for relative, container in hosts.items():
            payload = json.loads((home / relative).read_text(encoding="utf-8"))
            assert payload[container]["local-ai"]["env"]["LOCAL_AI_CONFIG"] == str(installed_config)
        claude = json.loads(claude_config.read_text(encoding="utf-8"))
        assert claude["user_fixture"] == {"keep": True}
        assert claude["mcpServers"]["external"] == {"command": "keep"}
        schemas = {path.stem: json.loads(path.read_text(encoding="utf-8"))
                   for path in (install / "generated/schemas").glob("*.json")}
        # Operation metadata uses tuples; persisted JSON necessarily uses arrays.
        assert schemas == json.loads(json.dumps(generator.generate_mcp_tool_schemas(updated)))
        snapshot = {path.relative_to(home): path.read_bytes() for path in home.rglob("*") if path.is_file()}
        # Deliberate idempotency assertion, not a retry of a failed operation.
        setup.configure_agents(install, Path(sys.executable), None, updated, include_companion=False)
        assert {path.relative_to(home): path.read_bytes() for path in home.rglob("*") if path.is_file()} == snapshot
        assert not (install / "state").exists()
        assert not (install / ".venv").exists()
    assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files} == before
    return {"source_root": str(source_root), "origins": {key: str(path) for key, path in origins.items()},
            "source_sha256": before, "schemas": len(schemas), "result": "portable fixture roundtrip passed"}


def test_clean_profile_install_update_configuration_and_prompt_roundtrip(tmp_path):
    source_root = Path(os.environ.get("T19_ROUNDTRIP_SOURCE_ROOT", Path(__file__).resolve().parents[1])).resolve()
    env = os.environ.copy()
    home = tmp_path / "home"
    for name in ("HOME", "USERPROFILE", "CODEX_HOME", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        env[name] = str(home / ".codex" if name == "CODEX_HOME" else home)
    env["LOCAL_AI_CONFIG"] = str(tmp_path / "bootstrap.toml")
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--fixture", str(source_root), str(tmp_path)],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-4000:]
    receipt = json.loads(result.stdout.splitlines()[-1])
    assert receipt["source_root"] == str(source_root)
    assert receipt["result"] == "portable fixture roundtrip passed"
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    assert len(sys.argv) == 4 and sys.argv[1] == "--fixture"
    print(json.dumps(_roundtrip(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()), sort_keys=True))
