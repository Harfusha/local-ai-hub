from __future__ import annotations

import ast
import importlib.util
import plistlib
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


setup = _load_module("local_ai_hub_setup_rollout_contract", ROOT / "tools" / "setup.py")
rollback = _load_module("local_ai_hub_rollback_rollout_contract", ROOT / "tools" / "rollback_snapshot.py")


def _load_service(tmp_path: Path, monkeypatch):
    from local_ai_hub import config as hub_config

    state = tmp_path / "service-state"
    monkeypatch.setattr(
        hub_config,
        "load_config",
        lambda *_args, **_kwargs: {"server": {"state_dir": str(state)}},
    )
    return _load_module("local_ai_hub_service_rollout_contract", ROOT / "tools" / "service.py")


def test_codex_global_entry_reconciles_one_stdio_adapter(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[model]\nprovider = "keep"\n\n[mcp_servers.external]\ncommand = "keep"\nargs = []\n',
        encoding="utf-8",
    )
    cfg = {"code_intelligence": {"direct_agent_mcp": False}}
    first_install = tmp_path / "hub-v1"
    first_python = first_install / ".venv" / "Scripts" / "python.exe"
    first_entry = setup.build_mcp_entries(first_install, first_python, None, "codex", cfg)

    assert set(first_entry) == {"local-ai"}
    assert first_entry["local-ai"] == {
        "command": str(first_python),
        "args": ["-m", "local_ai_hub.mcp_server"],
        "cwd": str(first_install),
        "env": {
            "LOCAL_AI_AGENT": "codex",
            "LOCAL_AI_AGENT_PROFILE": "codex",
            "LOCAL_AI_CONFIG": str(first_install / "config.toml"),
            "PYTHONPATH": str(first_install / "src"),
        },
    }
    assert not {key for key in first_entry["local-ai"]["env"] if "ROOT" in key or "PROJECT" in key}

    setup.codex_mcp_merge(config, first_entry, backup_enabled=False)
    second_install = tmp_path / "hub-v2"
    second_python = second_install / ".venv" / "Scripts" / "python.exe"
    second_entry = setup.build_mcp_entries(second_install, second_python, None, "codex", cfg)
    setup.codex_mcp_merge(config, second_entry, backup_enabled=False)

    text = config.read_text(encoding="utf-8")
    payload = tomllib.loads(text)
    assert text.count("[mcp_servers.local-ai]") == 1
    assert payload["model"]["provider"] == "keep"
    assert payload["mcp_servers"]["external"]["command"] == "keep"
    assert payload["mcp_servers"]["local-ai"]["command"] == str(second_python)
    assert payload["mcp_servers"]["local-ai"]["cwd"] == str(second_install)
    assert set(payload["mcp_servers"]) == {"external", "local-ai"}


def test_windows_service_config_is_one_logon_supervisor(tmp_path: Path, monkeypatch) -> None:
    service = _load_service(tmp_path, monkeypatch)
    calls: list[list[str]] = []
    monkeypatch.setattr(service.shutil, "which", lambda _: "powershell.exe")
    monkeypatch.setattr(
        service,
        "run",
        lambda command, **_: calls.append([str(item) for item in command]) or subprocess.CompletedProcess(command, 0),
    )
    startup = []
    monkeypatch.setattr(service, "set_windows_user_startup", lambda enabled: startup.append(enabled) or True)

    assert service.install_windows() == "windows-logon-task"
    assert service.install_windows() == "windows-logon-task"
    registrations = [" ".join(command) for command in calls if "Register-ScheduledTask" in " ".join(command)]
    assert len(registrations) == 2
    assert all("LocalAIHubSupervisor" in registration for registration in registrations)
    assert all("New-ScheduledTaskTrigger -AtLogOn" in registration for registration in registrations)
    assert all("-MultipleInstances IgnoreNew" in registration for registration in registrations)
    assert calls[1][-3:] == ["/Run", "/TN", "LocalAIHubSupervisor"]
    assert startup == [False, False]


def test_macos_service_config_reuses_one_user_launch_agent(tmp_path: Path, monkeypatch) -> None:
    service = _load_service(tmp_path, monkeypatch)
    calls: list[list[str]] = []
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(service.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(
        service,
        "run",
        lambda command, **_: calls.append([str(item) for item in command]) or subprocess.CompletedProcess(command, 0),
    )

    assert service.install_macos() == "launchd"
    assert service.install_macos() == "launchd"
    service_file = tmp_path / "Library" / "LaunchAgents" / "com.localai.hub.plist"
    with service_file.open("rb") as stream:
        payload = plistlib.load(stream)
    assert payload["Label"] == "com.localai.hub"
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is True
    assert payload["ProgramArguments"][-2:] == ["-m", "local_ai_hub.supervisor"]
    assert [call[1] for call in calls] == ["bootout", "bootstrap", "bootout", "bootstrap"]
    assert all("com.localai.hub.plist" in call[-1] for call in calls)


def test_linux_service_config_reuses_one_user_unit(tmp_path: Path, monkeypatch) -> None:
    service = _load_service(tmp_path, monkeypatch)
    calls: list[list[str]] = []
    monkeypatch.setattr(service.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(service.shutil, "which", lambda _: "systemctl")
    monkeypatch.setattr(
        service,
        "run",
        lambda command, **_: calls.append([str(item) for item in command]) or subprocess.CompletedProcess(command, 0),
    )

    assert service.install_linux() == "systemd-user"
    assert service.install_linux() == "systemd-user"
    service_file = tmp_path / ".config" / "systemd" / "user" / "local-ai-hub.service"
    unit = service_file.read_text(encoding="utf-8")
    assert "ExecStart=" in unit and "-m local_ai_hub.supervisor" in unit
    assert "WantedBy=default.target" in unit
    assert "Restart=always" in unit
    assert calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "local-ai-hub.service"],
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "local-ai-hub.service"],
    ]


def test_rollback_snapshot_restores_codex_adapter_and_service_config(tmp_path: Path) -> None:
    code = tmp_path / "hub"
    state = tmp_path / "state"
    codex_config = tmp_path / ".codex" / "config.toml"
    service_config = tmp_path / ".config" / "systemd" / "user" / "local-ai-hub.service"
    hub_config = tmp_path / "config.toml"
    code.mkdir()
    state.mkdir()
    codex_config.parent.mkdir(parents=True)
    service_config.parent.mkdir(parents=True)
    (code / "release.txt").write_text("old release", encoding="utf-8")
    hub_config.write_text("old Hub config", encoding="utf-8")
    codex_config.write_text('[mcp_servers.local-ai]\ncommand = "old-python"\n', encoding="utf-8")
    service_config.write_text("ExecStart=old-hub", encoding="utf-8")
    roots = {
        "code": code,
        "config": hub_config,
        "state": state,
        "agent-codex": codex_config,
        "service-registration": service_config,
    }
    snapshot = tmp_path / "rollback-snapshot"

    rollback.create_snapshot(snapshot, roots, coverage=("code", "config", "state"), service_stopped=True)
    codex_config.write_text('[mcp_servers.local-ai]\ncommand = "new-python"\n', encoding="utf-8")
    service_config.write_text("ExecStart=new-hub", encoding="utf-8")
    rollback.restore_snapshot(snapshot, roots, coverage=("code", "config", "state"), service_stopped=True)

    assert 'command = "old-python"' in codex_config.read_text(encoding="utf-8")
    assert service_config.read_text(encoding="utf-8") == "ExecStart=old-hub"


def test_rollout_docs_state_adapter_multiplicity_root_and_transport_gates() -> None:
    install_prompt = (ROOT / "docs" / "INSTALL_PROMPT.md").read_text(encoding="utf-8")
    update_prompt = (ROOT / "docs" / "UPDATE_PROMPT.md").read_text(encoding="utf-8")
    mcp_docs = (ROOT / "docs" / "MCP_AND_AGENTS.md").read_text(encoding="utf-8")
    operations = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")

    for document in (install_prompt, update_prompt, mcp_docs, operations):
        normalized = document.lower()
        assert "each active" in normalized and "mcp session" in normalized and "adapter process" in normalized
        assert "do not prove duplicate daemons" in normalized or "is not daemon count" in normalized
        assert "global codex" in normalized and "cwd=install_dir" in normalized and "project root" in normalized
        assert "repo/rag mcp actions" in normalized
        assert "root" in normalized and "runtime" in normalized and "proof" in normalized

    for prompt in (install_prompt, update_prompt):
        assert "Pinned source includes operational modes and client transport safeguards." in prompt
        assert "`outcome_unknown` means delivery may have occurred and must never be replayed automatically" in prompt
        assert "Service registration is external to the file snapshot; reconcile that same service once" in prompt
    assert "reconcile the existing single user-service registration with the matching restored release" in operations.lower()


def test_mcp_stdio_adapter_does_not_construct_hub_backend_app() -> None:
    source = (ROOT / "src" / "local_ai_hub" / "mcp_server.py").read_text(encoding="utf-8")
    assert "mcp.run()" in source
    module = ast.parse(source)
    client_assignment = next(
        node for node in module.body
        if isinstance(node, ast.Try) and any(
            isinstance(child, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "CLIENT" for target in child.targets)
            for child in node.body
        )
    )
    client_call = next(
        child.value for child in client_assignment.body
        if isinstance(child, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "CLIENT" for target in child.targets)
    )
    assert isinstance(client_call, ast.Call)
    assert isinstance(client_call.func, ast.Name) and client_call.func.id == "_build_mcp_client"
    module_level_calls = [
        node for statement in module.body if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        for node in ast.walk(statement) if isinstance(node, ast.Call)
    ]
    forbidden_constructors = {"LocalAIApp", "HubServices", "ProjectPreprocessor", "CodeIndex", "RAGStore", "ModelRouter"}
    assert not any(isinstance(call.func, ast.Name) and call.func.id in forbidden_constructors for call in module_level_calls)
