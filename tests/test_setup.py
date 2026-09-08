from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("local_ai_hub_setup", ROOT / "tools" / "setup.py")
assert SPEC and SPEC.loader
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


def test_compact_agent_config_is_default(tmp_path: Path):
    install = tmp_path / "install"
    py = tmp_path / "python"
    serena = tmp_path / "serena"
    cgc = tmp_path / "cgc"
    cfg = {"code_intelligence": {"direct_agent_mcp": False, "serena_enabled": True, "codegraph_enabled": True}}
    entries = setup.build_mcp_entries(install, py, serena, cgc, "codex", cfg)
    assert set(entries) == {"local-ai"}
    assert entries["local-ai"]["env"]["LOCAL_AI_AGENT"] == "codex"
    assert entries["local-ai"]["args"] == ["-m", "local_ai_hub.mcp_server"]
    assert entries["local-ai"]["env"]["PYTHONPATH"] == str(install / "src")
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


def test_direct_agent_backends_are_explicit_opt_in(tmp_path: Path):
    cfg = {"code_intelligence": {"direct_agent_mcp": True, "serena_enabled": True, "codegraph_enabled": True}}
    entries = setup.build_mcp_entries(tmp_path, tmp_path / "python", tmp_path / "serena", tmp_path / "cgc", "codex", cfg)
    assert set(entries) == {"local-ai", "serena", "codegraph"}
    assert "--project-from-cwd" in entries["serena"]["args"]
    assert entries["codegraph"]["args"] == ["mcp", "start"]


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
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["other"] == 1
    assert data["mcpServers"]["user"]["command"] == "keep"
    assert data["mcpServers"]["local-ai"]["command"] == "python"

    toml_path = tmp_path / "config.toml"
    toml_path.write_text('[model]\nprovider="x"\n\n[mcp_servers.local-ai]\ncommand="user-managed"\n', encoding="utf-8")
    setup.codex_mcp_merge(toml_path, {"local-ai": {"command": "should-not-overwrite", "args": []}}, False)
    text = toml_path.read_text(encoding="utf-8")
    assert 'command="user-managed"' in text
    assert "should-not-overwrite" not in text


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


def test_copy_install_tree_uses_package_native_mcp(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    for name in ("src", "skills", "tools"):
        (source / name).mkdir(parents=True)
    (source / "src" / "marker.txt").write_text("src", encoding="utf-8")
    (source / "skills" / "marker.txt").write_text("skill", encoding="utf-8")
    (source / "tools" / "marker.txt").write_text("tool", encoding="utf-8")
    for name in ("requirements-core.txt", "defaults.toml", "pyproject.toml", "README.md"):
        (source / name).write_text("x", encoding="utf-8")
    config = source / "config.toml"
    config.write_text("[hardware]\nprofile='cpu'\n", encoding="utf-8")
    monkeypatch.setattr(setup, "SOURCE_ROOT", source)
    target = tmp_path / "install"
    (target / "mcp").mkdir(parents=True)
    (target / "mcp" / "legacy.py").write_text("legacy", encoding="utf-8")
    setup.copy_install_tree(target, config)
    assert (target / "src" / "marker.txt").read_text(encoding="utf-8") == "src"
    assert not (target / "mcp").exists()


def test_copy_install_tree_preserves_source_mcp_wrapper(tmp_path: Path, monkeypatch):
    source = tmp_path / "source"
    for name in ("src", "skills", "tools", "mcp"):
        (source / name).mkdir(parents=True)
    (source / "mcp" / "local_ai_mcp.py").write_text("wrapper", encoding="utf-8")
    for name in ("requirements-core.txt", "defaults.toml", "pyproject.toml", "README.md"):
        (source / name).write_text("x", encoding="utf-8")
    config = source / "config.toml"
    config.write_text("[hardware]\nprofile='cpu'\n", encoding="utf-8")
    monkeypatch.setattr(setup, "SOURCE_ROOT", source)

    setup.copy_install_tree(source, config)

    assert (source / "mcp" / "local_ai_mcp.py").read_text(encoding="utf-8") == "wrapper"
