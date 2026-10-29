from __future__ import annotations

import importlib.util
import json
import sys
import subprocess
import os
import tomllib
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("local_ai_hub_setup", ROOT / "tools" / "setup.py")
assert SPEC and SPEC.loader
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


@pytest.mark.skipif(os.name != 'nt', reason='Windows batch executable lookup')
def test_run_resolves_windows_batch_executables(tmp_path, monkeypatch):
    script = tmp_path / 'hub-test-command.cmd'
    script.write_text('@echo off\necho batch-ok\n')
    monkeypatch.setenv('PATH', str(tmp_path) + os.pathsep + os.environ['PATH'])
    result = setup.run(['hub-test-command'], capture=True)
    assert result.stdout.strip() == 'batch-ok'


def test_setup_skip_service_still_restarts_hub_without_registering_service(tmp_path, monkeypatch):
    config_source = tmp_path / "config.toml"
    config_source.write_text("[hardware]\nprofile = \"auto\"\n", encoding="utf-8")
    install_dir = tmp_path / "install"
    config = {
        "setup": {
            "install_agent_configs": False,
            "install_optional_tools": False,
            "install_service": True,
        },
        "hardware": {"profile": "cpu"},
        "_hardware": {"gpus": [], "npus": [], "profile": "cpu", "os": "Windows", "arch": "AMD64"},
        "features": {
            "rag": False,
            "reranker": False,
            "install_local_nlp_dependencies": False,
            "install_openvino_dependencies": False,
            "pull_models_during_setup": False,
        },
        "models": {"embedding_backend": "none", "reranker_backend": "none"},
        "code_intelligence": {"serena_enabled": False},
        "headless": {"enabled": True},
        "ollama": {"enabled": False},
        "llama_cpp": {"mode": "off"},
        "tools": {},
    }
    commands = []

    monkeypatch.setattr(setup, "select_config_source", lambda _path: (config_source, config, install_dir))

    def copy_install_tree(destination, _source, *, before_commit=None):
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "config.toml").write_text("[hardware]\nprofile = \"auto\"\n", encoding="utf-8")
        return True

    monkeypatch.setattr(setup, "copy_install_tree", copy_install_tree)
    monkeypatch.setattr(setup, "load_hub_config", lambda _path: config)
    monkeypatch.setattr(setup, "ensure_venv", lambda _path: tmp_path / "python.exe")
    monkeypatch.setattr(setup, "install_requirements", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(setup, "write_generated_agent_manifests", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "ensure_ollama_for_setup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "pull_ollama_models", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "ensure_llama_cpp_for_setup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "run", lambda command, **_kwargs: commands.append([str(part) for part in command]))
    monkeypatch.setattr(sys, "argv", [
        "setup.py", "--config", str(config_source), "--profile", "cpu", "--skip-service",
        "--skip-tools", "--skip-agent-config", "--skip-token-economy", "--skip-model-pull",
        "--skip-local-nlp-preload", "--skip-ollama-install", "--skip-companion-skills",
    ])

    assert setup.main() == 0
    assert sum(
        command[-1:] == ["restart"] and any(part.endswith("tools/hubctl.py") or part.endswith("tools\\hubctl.py") for part in command)
        for command in commands
    ) == 1
    assert not any(command[-1:] == ["install"] and any(part.endswith("tools/service.py") or part.endswith("tools\\service.py") for part in command) for command in commands)


def test_setup_stop_failure_skips_runtime_setup_and_service_start(tmp_path, monkeypatch):
    config_source = tmp_path / "config.toml"
    config_source.write_text("[hardware]\nprofile = \"auto\"\n", encoding="utf-8")
    install_dir = tmp_path / "install"
    config = {"setup": {}}
    events = []
    stop_attempts = []

    monkeypatch.setattr(setup, "select_config_source", lambda _path: (config_source, config, install_dir))

    def fail_to_stop(*_args, **_kwargs):
        stop_attempts.append(True)
        return False, "stop outcome unknown"

    monkeypatch.setattr(setup, "stop_existing_runtime", fail_to_stop)

    def copy_install_tree(_destination, _source, *, before_commit=None):
        assert before_commit is not None
        stopped, _detail = before_commit()
        return stopped

    monkeypatch.setattr(setup, "copy_install_tree", copy_install_tree)
    monkeypatch.setattr(setup, "ensure_venv", lambda _path: events.append("venv"))
    monkeypatch.setattr(setup, "run", lambda command, **_kwargs: events.append(command))
    monkeypatch.setattr(sys, "argv", ["setup.py", "--config", str(config_source)])

    assert setup.main() == 1
    assert stop_attempts == [True]
    assert events == []


def test_token_economy_launchers_and_trim_run_allowlist(tmp_path, monkeypatch):
    scripts = tmp_path / '.venv' / ('Scripts' if setup.os.name == 'nt' else 'bin')
    scripts.mkdir(parents=True)
    registered = []
    monkeypatch.setattr(setup, "persist_token_economy_path", registered.append)
    setup.install_token_economy_suite(tmp_path, Path(sys.executable), allow_external_tools=False)
    assert registered == [scripts]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    for tool in ('tokcount', 'trim-run', 'repo-map'):
        launcher = scripts / (tool + '.cmd' if setup.os.name == 'nt' else tool)
        assert len(launcher.read_text().splitlines()) == 2
        if setup.os.name != 'nt':
            assert launcher.stat().st_mode & 0o111
        if tool == 'trim-run':
            unsafe = subprocess.run(
                [str(launcher), 'python', '-c', 'print(12345)'],
                capture_output=True, text=True, timeout=15, env=env,
            )
            assert unsafe.returncode == 2
            assert "not in the safe" in unsafe.stderr
            args = ['tokcount', '--help']
        else:
            args = ['--help']
        cp = subprocess.run([str(launcher), *args], capture_output=True, text=True, timeout=15, env=env)
        assert cp.returncode == 0, cp.stderr
        assert 'usage:' in cp.stdout.lower()



def test_token_economy_path_is_persisted_idempotently(tmp_path: Path):
    scripts = tmp_path / ".local-ai-hub" / ".venv" / "bin"
    setup.persist_token_economy_path(scripts, home=tmp_path, windows=False, shell="bash")
    setup.persist_token_economy_path(scripts, home=tmp_path, windows=False, shell="bash")

    profile = (tmp_path / ".profile").read_text(encoding="utf-8")
    assert profile.count("# BEGIN LOCAL AI HUB TOKEN TOOLS PATH") == 1
    assert str(scripts) in profile


def test_token_economy_path_merge_preserves_existing_entries(tmp_path: Path):
    scripts = tmp_path / "bin"
    existing = os.pathsep.join(["existing-tool-dir", str(scripts)])
    assert setup._merge_path_entry(existing, scripts, windows=os.name == "nt") == existing


def test_token_economy_path_merge_deduplicates_case_insensitively(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(setup.os, "pathsep", ":")
    scripts = Path(r"C:\Users\Test\TokenTools")
    existing = r"C:\Users\Test\tokentools;D:\Existing"
    assert setup._merge_path_entry(existing, scripts, windows=True) == existing


def test_compact_agent_config_is_default(tmp_path: Path):
    install = tmp_path / "install"
    py = tmp_path / "python"
    serena = tmp_path / "serena"
    cfg = {"code_intelligence": {"direct_agent_mcp": False, "serena_enabled": True}}
    entries = setup.build_mcp_entries(install, py, serena, "codex", cfg)
    assert set(entries) == {"local-ai"}
    assert entries["local-ai"]["env"]["LOCAL_AI_AGENT"] == "codex"
    assert entries["local-ai"]["args"] == ["-m", "local_ai_hub.mcp_server"]
    assert entries["local-ai"]["env"]["PYTHONPATH"] == str(install / "src")
    # Global MCP adapters launch from the Hub install. Repository-scoped
    # operations must still receive the caller's explicit root.
    assert entries["local-ai"]["cwd"] == str(install)


def test_global_policy_has_explicit_read_only_and_fallback_contract() -> None:
    policy = setup.GLOBAL_POLICY

    for phrase in (
        "READ-ONLY AUDIT CONTRACT",
        "git worktree add",
        "terminal=true",
        "retryable=false",
        "sandbox",
        "allow_write",
        "Codex controls each subagent's scope",
        "Native `multi_agent_v1__spawn_agent` is used only for useful independent bounded work",
    ):
        assert phrase in policy


@pytest.mark.parametrize("relative_path", ["docs/INSTALL_PROMPT.md", "docs/UPDATE_PROMPT.md"])
def test_instruction_policy_blocks_match_generated_policy_sources(relative_path: str) -> None:
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    expected_agent = setup.generate_global_policy({})
    expected_token = setup.generate_token_economy_policy({})

    def block(begin: str, end: str) -> str:
        start = text.find(begin)
        assert start >= 0, f"{relative_path} missing {begin}"
        assert text.find(begin, start + len(begin)) < 0, f"{relative_path} repeats {begin}"
        finish = text.find(end, start + len(begin))
        assert finish >= 0, f"{relative_path} missing {end}"
        return text[start:finish + len(end)]

    assert block(setup.GLOBAL_POLICY_BEGIN, setup.GLOBAL_POLICY_END) == expected_agent
    assert block(setup.TOKEN_ECONOMY_POLICY_BEGIN, setup.TOKEN_ECONOMY_POLICY_END) == expected_token


def test_direct_serena_is_explicit_opt_in(tmp_path: Path):
    cfg = {"code_intelligence": {"direct_agent_mcp": True, "serena_enabled": True}}
    entries = setup.build_mcp_entries(tmp_path, tmp_path / "python", tmp_path / "serena", "codex", cfg)
    assert set(entries) == {"local-ai", "serena"}
    assert "--project-from-cwd" in entries["serena"]["args"]


def test_direct_agent_serena_context_matches_gemini(tmp_path: Path):
    cfg = {"code_intelligence": {"direct_agent_mcp": True, "serena_enabled": True}}
    entries = setup.build_mcp_entries(tmp_path, tmp_path / "python", tmp_path / "serena", "gemini", cfg)
    assert entries["serena"]["args"][1:3] == ["--context", "gemini"]


def test_antigravity_mcp_sync_uses_gemini_and_prunes_stale_backends(tmp_path: Path):
    path = tmp_path / "mcp_config.json"
    serena = tmp_path / "serena.exe"
    path.write_text(json.dumps({"mcpServers": {
        "user-server": {"command": "keep"},
        "serena": {"command": str(serena), "args": ["start-mcp-server"]},
    }}), encoding="utf-8")

    setup.sync_antigravity_mcp_config(
        path, tmp_path / "install", tmp_path / "python", serena,
        {"code_intelligence": {"direct_agent_mcp": False}}, False,
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["mcpServers"]) == {"user-server", "local-ai"}
    local_ai = data["mcpServers"]["local-ai"]
    assert local_ai["cwd"] == str(tmp_path / "install")
    assert local_ai["env"]["LOCAL_AI_AGENT"] == "gemini"
    assert local_ai["env"]["LOCAL_AI_AGENT_PROFILE"] == "gemini"


def test_mcp_merge_preserves_existing_isolated_hub_launch(tmp_path: Path):
    import json
    import tomllib

    entry = {"command": "new-python", "args": ["-m", "local_ai_hub.mcp_server"], "cwd": "new-root"}
    isolated = ["-I", "-m", "local_ai_hub.mcp_server"]
    codex = tmp_path / "config.toml"
    codex.write_text(
        setup.MARKER_BEGIN + '\n[mcp_servers.local-ai]\ncommand = "old-python"\n'
        'args = ["-I", "-m", "local_ai_hub.mcp_server"]\n' + setup.MARKER_END + '\n',
        encoding="utf-8",
    )
    gemini = tmp_path / "settings.json"
    gemini.write_text(json.dumps({"mcpServers": {"local-ai": {"args": isolated}, "other": {"command": "keep"}}}), encoding="utf-8")
    for _ in range(2):
        setup.codex_mcp_merge(codex, {"local-ai": entry}, False)
        setup.json_mcp_merge(gemini, {"local-ai": entry}, False)
    codex_server = tomllib.loads(codex.read_text(encoding="utf-8"))["mcp_servers"]["local-ai"]
    gemini_servers = json.loads(gemini.read_text(encoding="utf-8"))["mcpServers"]
    for server in (codex_server, gemini_servers["local-ai"]):
        assert server["args"] == isolated
        assert server["command"] == "new-python"
        assert server["cwd"] == "new-root"
    assert gemini_servers["other"] == {"command": "keep"}
    assert setup.preserve_isolated_hub_args("local-ai", {"args": isolated + ["stale"]}, entry) == entry


def test_codex_mcp_merge_writes_stable_working_directory(tmp_path: Path):
    path = tmp_path / "config.toml"
    setup.codex_mcp_merge(
        path,
        {"local-ai": {"command": "python", "args": ["-m", "hub"], "cwd": str(tmp_path / "hub")}},
        False,
    )
    text = path.read_text(encoding="utf-8")
    assert f"cwd = {setup.toml_quote(str(tmp_path / 'hub'))}" in text


def test_config_mergers_preserve_user_content(tmp_path: Path):
    json_path = tmp_path / "settings.json"
    json_path.write_text(json.dumps({"other": 1, "mcpServers": {"user": {"command": "keep"}}}), encoding="utf-8")
    setup.json_mcp_merge(json_path, {"local-ai": {"command": "python", "args": ["hub.py"]}}, False)
    json_first = json_path.read_text(encoding="utf-8")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["other"] == 1
    assert data["mcpServers"]["user"]["command"] == "keep"
    assert data["mcpServers"]["local-ai"]["command"] == "python"
    setup.json_mcp_merge(json_path, {"local-ai": {"command": "python", "args": ["hub.py"]}}, False)
    assert json_path.read_text(encoding="utf-8") == json_first

    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        '[model]\nprovider="x"\n\n[mcp_servers.foreign]\ncommand="keep"\n\n'
        '[mcp_servers.local-ai]\ncommand="user-managed"\n',
        encoding="utf-8",
    )
    setup.codex_mcp_merge(toml_path, {"local-ai": {"command": "should-not-overwrite", "args": []}}, False)
    toml_first = toml_path.read_text(encoding="utf-8")
    data = tomllib.loads(toml_first)
    assert data["model"]["provider"] == "x"
    assert data["mcp_servers"]["foreign"]["command"] == "keep"
    assert data["mcp_servers"]["local-ai"]["command"] == "user-managed"
    assert "should-not-overwrite" not in toml_first
    setup.codex_mcp_merge(toml_path, {"local-ai": {"command": "should-not-overwrite", "args": []}}, False)
    assert toml_path.read_text(encoding="utf-8") == toml_first


@pytest.mark.parametrize(
    ("host", "manifest_format", "entry_agent"),
    [
        ("codex", "toml", "codex"),
        ("claude", "json", "claude"),
        ("gemini", "json", "gemini"),
        ("antigravity", "antigravity", "gemini"),
        ("cursor", "json", "cursor"),
        ("windsurf", "json", "windsurf"),
        ("copilot", "vscode", "copilot"),
        ("generic", "json", "generic"),
        ("vscode", "vscode", "generic"),
    ],
)
def test_supported_host_mcp_manifests_parse(tmp_path: Path, host: str, manifest_format: str, entry_agent: str):
    path = tmp_path / f"{host}.{'toml' if manifest_format == 'toml' else 'json'}"
    install_dir = tmp_path / "install"
    hub_python = tmp_path / "python"
    cfg = {"code_intelligence": {"direct_agent_mcp": False}}
    entries = setup.build_mcp_entries(install_dir, hub_python, None, entry_agent, cfg)

    if manifest_format == "toml":
        setup.codex_mcp_merge(path, entries, False)
        manifest = tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]
    elif manifest_format == "antigravity":
        setup.sync_antigravity_mcp_config(path, install_dir, hub_python, None, cfg, False)
        manifest = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
    elif manifest_format == "vscode":
        setup.vscode_mcp_merge(path, entries, False)
        manifest = json.loads(path.read_text(encoding="utf-8"))["servers"]
    else:
        setup.json_mcp_merge(path, entries, False)
        manifest = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]

    assert manifest["local-ai"]["env"]["LOCAL_AI_AGENT"] == entry_agent
    if manifest_format == "vscode":
        assert manifest["local-ai"]["type"] == "stdio"
    assert manifest["local-ai"]["command"] == str(hub_python)


def test_ollama_setup_skips_exclusive_llama_cpp_configuration(monkeypatch, tmp_path: Path, capsys):
    cfg = {
        "ollama": {"enabled": False},
        "server": {"auto_start_ollama": True},
        "llama_cpp": {"mode": "on", "fallback_to_ollama": False},
    }
    monkeypatch.setattr(setup, "find_ollama_executable", lambda: pytest.fail("Ollama lookup must be skipped"))

    assert setup.ollama_setup_required(cfg) is False
    assert setup.ensure_ollama_for_setup(cfg, tmp_path, allow_install=True) is True
    setup.pull_ollama_models(cfg)
    assert "Skipping Ollama setup" in capsys.readouterr().out


@pytest.mark.parametrize(
    "cfg",
    [
        {"server": {"auto_start_ollama": False}, "llama_cpp": {"fallback_to_ollama": True}},
        {"server": {"auto_start_ollama": True}, "llama_cpp": {"fallback_to_ollama": False}},
    ],
)
def test_ollama_setup_requires_auto_start_and_fallback(cfg):
    assert setup.ollama_setup_required(cfg) is False


def test_ollama_setup_remains_enabled_for_fallback_configuration():
    assert setup.ollama_setup_required(
        {"ollama": {"enabled": True}, "server": {"auto_start_ollama": True}, "llama_cpp": {"mode": "auto", "fallback_to_ollama": True}}
    ) is True


def test_managed_llama_setup_runs_only_when_selected(monkeypatch, capsys):
    class ManagedRuntime:
        def __init__(self, config):
            self.config = config

        def ensure_running(self):
            return True

        def status(self):
            return {"url": "http://127.0.0.1:12438", "mode": "none"}

    monkeypatch.setattr(setup, "LlamaCppManagedRuntime", ManagedRuntime)
    assert setup.ensure_llama_cpp_for_setup({"ollama": {"enabled": False}, "llama_cpp": {"mode": "on"}})
    assert "Managed llama.cpp is ready" in capsys.readouterr().out
    assert setup.ensure_llama_cpp_for_setup({"ollama": {"enabled": True}, "llama_cpp": {"mode": "on"}})
    assert "Skipping managed llama.cpp setup" in capsys.readouterr().out


def test_managed_llama_setup_fails_closed_when_server_never_becomes_healthy(monkeypatch):
    class ManagedRuntime:
        def __init__(self, config):
            pass

        def ensure_running(self):
            return False

        def status(self):
            return {"last_error": "llama-server did not become healthy"}

    monkeypatch.setattr(setup, "LlamaCppManagedRuntime", ManagedRuntime)
    with pytest.raises(RuntimeError, match="did not become healthy"):
        setup.ensure_llama_cpp_for_setup({"ollama": {"enabled": False}, "llama_cpp": {"mode": "on"}})


def test_pull_ollama_models_includes_vision_when_enabled(monkeypatch):
    pulled = []
    monkeypatch.setattr(setup, "find_ollama_executable", lambda: "ollama")
    monkeypatch.setattr(setup, "run", lambda args, **kwargs: pulled.append(args))

    setup.pull_ollama_models(
        {
            "ollama": {"enabled": True},
            "features": {"pull_models_during_setup": True, "vision": True},
            "server": {"auto_start_ollama": True},
            "llama_cpp": {"fallback_to_ollama": True},
            "models": {"general": "qwen2.5-coder:7b", "vision": "qwen3-vl:4b"},
            "ollama_subagents": {"enabled": False},
        }
    )

    assert [args[-1] for args in pulled] == ["qwen2.5-coder:7b", "qwen3-vl:4b"]


def test_pull_ollama_models_skips_vision_when_disabled(monkeypatch):
    pulled = []
    monkeypatch.setattr(setup, "find_ollama_executable", lambda: "ollama")
    monkeypatch.setattr(setup, "run", lambda args, **kwargs: pulled.append(args))

    setup.pull_ollama_models(
        {
            "ollama": {"enabled": True},
            "features": {"pull_models_during_setup": True, "vision": False},
            "server": {"auto_start_ollama": True},
            "llama_cpp": {"fallback_to_ollama": True},
            "models": {"general": "qwen2.5-coder:7b", "vision": "qwen3-vl:4b"},
            "ollama_subagents": {"enabled": False},
        }
    )

    assert [args[-1] for args in pulled] == ["qwen2.5-coder:7b"]


def test_setup_rerun_preserves_installed_config_without_explicit_override(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    install = tmp_path / "installed"
    source.mkdir(); install.mkdir()
    (source / "config.toml").write_text(f'[setup]\ninstall_dir="{install.as_posix()}"\n[hardware]\nprofile="cpu"\n', encoding="utf-8")
    installed = install / "config.toml"
    installed.write_text(f'[setup]\ninstall_dir="{install.as_posix()}"\n[hardware]\nprofile="high"\n', encoding="utf-8")
    monkeypatch.setattr(setup, "SOURCE_ROOT", source)
    selected, cfg, selected_install = setup.select_config_source(None)
    assert selected == installed.resolve()
    assert selected_install == install.resolve()
    assert cfg["hardware"]["profile"] == "high"


def test_setup_explicit_config_wins_over_installed_config(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    install = tmp_path / "installed"
    source.mkdir(); install.mkdir()
    explicit = source / "custom.toml"
    explicit.write_text(f'[setup]\ninstall_dir="{install.as_posix()}"\n[hardware]\nprofile="low"\n', encoding="utf-8")
    (install / "config.toml").write_text(f'[setup]\ninstall_dir="{install.as_posix()}"\n[hardware]\nprofile="high"\n', encoding="utf-8")
    monkeypatch.setattr(setup, "SOURCE_ROOT", source)
    selected, cfg, selected_install = setup.select_config_source(explicit)
    assert selected == explicit.resolve()
    assert selected_install == install.resolve()
    assert cfg["hardware"]["profile"] == "low"


def test_setup_clean_checkout_bootstraps_from_example_config(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    install = tmp_path / "installed"
    source.mkdir()
    example = source / "config.toml.example"
    example.write_text(
        f'[setup]\ninstall_dir="{install.as_posix()}"\n[hardware]\nprofile="cpu"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(setup, "SOURCE_ROOT", source)

    selected, cfg, selected_install = setup.select_config_source(None)

    assert selected == example.resolve()
    assert selected_install == install.resolve()
    assert cfg["hardware"]["profile"] == "cpu"


def test_skip_service_uses_hubctl_fallback_without_managed_service(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    install = tmp_path / "installed"
    source.mkdir()
    install.mkdir()
    config_text = (
        f'[setup]\ninstall_dir="{install.as_posix()}"\n'
        "install_agent_configs=false\ninstall_optional_tools=false\n"
        "[server]\nauto_start_ollama=false\n"
        "[features]\ninstall_local_nlp_dependencies=false\n"
        "install_openvino_dependencies=false\npull_models_during_setup=false\n"
    )
    source_config = source / "config.toml"
    source_config.write_text(config_text, encoding="utf-8")
    (install / "config.toml").write_text(config_text, encoding="utf-8")
    monkeypatch.setattr(setup, "SOURCE_ROOT", source)
    monkeypatch.setattr(setup, "copy_install_tree", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(setup, "ensure_venv", lambda _venv: tmp_path / "python.exe")
    monkeypatch.setattr(setup, "install_requirements", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(setup, "ensure_ollama_for_setup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "pull_ollama_models", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "ensure_llama_cpp_for_setup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "write_generated_agent_manifests", lambda *_args, **_kwargs: None)
    commands = []
    monkeypatch.setattr(setup, "run", lambda command, **_kwargs: commands.append(command))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "setup.py", "--profile", "cpu", "--skip-service", "--skip-model-pull",
            "--skip-tools", "--skip-agent-config", "--skip-ollama-install",
            "--skip-local-nlp-preload", "--skip-token-economy", "--skip-companion-skills",
        ],
    )

    assert setup.main() == 0
    assert sum(
        len(command) >= 2 and Path(command[-2]).name == "hubctl.py" and command[-1] == "restart"
        for command in commands
    ) == 1
    assert not any(
        len(command) >= 2 and Path(command[-2]).name == "service.py" and command[-1] == "install"
        for command in commands
    )


def test_copy_install_tree_copies_only_current_package_roots(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    for name in ("src", "skills", "tools"):
        (source / name).mkdir(parents=True)
        (source / name / "marker.txt").write_text(name, encoding="utf-8")
    for name in ("requirements-core.txt", "defaults.toml", "pyproject.toml", "README.md"):
        (source / name).write_text("x", encoding="utf-8")
    config = source / "config.toml"
    config.write_text("[hardware]\nprofile='cpu'\n", encoding="utf-8")
    monkeypatch.setattr(setup, "SOURCE_ROOT", source)
    monkeypatch.setattr(setup, "UPDATE_SOURCE_ROOT", source)
    target = tmp_path / "install"

    setup.copy_install_tree(target, config)

    assert (target / "src" / "marker.txt").read_text(encoding="utf-8") == "src"
    assert (target / "skills" / "marker.txt").read_text(encoding="utf-8") == "skills"
    assert (target / "tools" / "marker.txt").read_text(encoding="utf-8") == "tools"
    assert not (target / "mcp").exists()


def test_install_agent_skills_includes_companion_by_default(tmp_path: Path):
    source = tmp_path / "source"
    skills = source / "skills"
    for s in ["local-ai-orchestrator", "token-economizer", "caveman", "tool-orchestration", "ollama-quality-routing"]:
        d = skills / s
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"name: {s}", encoding="utf-8")

    target = tmp_path / "target_skills"
    setup.install_agent_skills(source, target, include_companion=True)

    for s in ["local-ai-orchestrator", "token-economizer", "caveman", "tool-orchestration", "ollama-quality-routing"]:
        assert (target / s / "SKILL.md").exists()
        assert (target / s / "SKILL.md").read_text(encoding="utf-8") == f"name: {s}"


def test_install_agent_skills_skip_companion(tmp_path: Path):
    source = tmp_path / "source"
    skills = source / "skills"
    for s in ["local-ai-orchestrator", "token-economizer", "caveman", "tool-orchestration", "ollama-quality-routing"]:
        d = skills / s
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"name: {s}", encoding="utf-8")

    target = tmp_path / "target_skills"
    setup.install_agent_skills(source, target, include_companion=False)

    assert (target / "local-ai-orchestrator" / "SKILL.md").exists()
    for s in ["token-economizer", "caveman", "tool-orchestration", "ollama-quality-routing"]:
        assert not (target / s).exists()


def test_install_agent_skills_accepts_generated_install_target(tmp_path: Path):
    install = tmp_path / "install"
    target = tmp_path / "target_skills"
    setup.write_all_generated({"models": {"fast_code": "qwen2.5-coder:7b"}}, install)

    setup.install_agent_skills(install, target, include_companion=False)

    assert (target / "local-ai-orchestrator" / "SKILL.md").exists()
