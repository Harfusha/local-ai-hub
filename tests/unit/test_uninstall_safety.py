from __future__ import annotations

import sys
import json
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import uninstall
from install_ownership import record_external_block, record_external_json_key, read_install_manifest, write_install_manifest
from tools import setup as setup_script


def test_uninstall_path_containment_normalizes_traversal(tmp_path: Path) -> None:
    root = tmp_path / "install"
    nested = root / "rollback" / "snapshot.json"
    escaped = root / "rollback" / ".." / ".." / "outside.json"

    assert uninstall._is_within(nested, root)
    assert not uninstall._is_within(escaped, root)


def test_json_cleanup_removes_only_install_references(tmp_path: Path) -> None:
    install = tmp_path / "installed-hub"
    install.mkdir()
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {
        "local-ai": {"command": "python", "cwd": str(install)},
        "serena-local": {"command": "third-party-serena"},
    }}), encoding="utf-8")
    write_install_manifest(install)
    record_external_json_key(
        install, path, container="mcpServers", key="local-ai", preimage=None,
        postimage={"command": "python", "cwd": str(install)},
    )

    uninstall.clean_json(path, install)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert "local-ai" not in data["mcpServers"]
    assert "serena-local" in data["mcpServers"]


@pytest.mark.parametrize(
    "provider",
    ["antigravity", "claude", "copilot", "cursor", "devin", "gemini_cli", "windsurf"],
)
def test_provider_mcp_setup_rolls_back_only_hub_route(tmp_path: Path, monkeypatch, provider: str) -> None:
    install = tmp_path / "installed-hub"
    install.mkdir()
    path = tmp_path / f"{provider}-mcp.json"
    other = {"command": "browser-mcp"}
    path.write_text(json.dumps({"mcpServers": {"browser-mcp": other}}), encoding="utf-8")
    write_install_manifest(install)
    monkeypatch.setattr(setup_script, "_ACTIVE_INSTALL_ROOT", install)

    setup_script.json_mcp_merge(path, {
        "local-ai": {"command": "python", "env": {"LOCAL_AI_AGENT": provider}},
    }, backup_enabled=False)
    after_setup = json.loads(path.read_text(encoding="utf-8"))
    assert after_setup["mcpServers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == provider
    assert after_setup["mcpServers"]["browser-mcp"] == other

    uninstall.clean_external_configurations(read_install_manifest(install)["external_ownership"], install)

    restored = json.loads(path.read_text(encoding="utf-8"))
    assert restored == {"mcpServers": {"browser-mcp": other}}


def test_codex_mcp_setup_rolls_back_only_hub_block(tmp_path: Path, monkeypatch) -> None:
    install = tmp_path / "installed-hub"
    install.mkdir()
    path = tmp_path / "config.toml"
    original = 'model_provider = "user-model"\n\n[mcp_servers.browser-mcp]\ncommand = "browser"\n'
    path.write_text(original, encoding="utf-8")
    write_install_manifest(install)
    monkeypatch.setattr(setup_script, "_ACTIVE_INSTALL_ROOT", install)

    setup_script.codex_mcp_merge(path, {
        "local-ai": {
            "command": "python", "args": ["-m", "local_ai_hub.mcp_server"],
            "env": {"LOCAL_AI_AGENT": "codex"},
        },
    }, backup_enabled=False)
    configured = tomllib.loads(path.read_text(encoding="utf-8"))
    assert configured["model_provider"] == "user-model"
    assert configured["mcp_servers"]["browser-mcp"]["command"] == "browser"
    assert configured["mcp_servers"]["local-ai"]["env"]["LOCAL_AI_AGENT"] == "codex"

    uninstall.clean_external_configurations(read_install_manifest(install)["external_ownership"], install)

    assert tomllib.loads(path.read_text(encoding="utf-8")) == tomllib.loads(original)


@pytest.mark.parametrize(
    ("container_key", "require_stdio_type", "initial", "provider"),
    [
        ("mcp.servers", False, {"mcp": {"servers": {"browser-mcp": {"type": "local"}}}}, "opencode"),
        ("servers", True, {"servers": {"browser-mcp": {"type": "stdio"}}}, "vscode"),
    ],
)
def test_provider_nested_mcp_setup_restores_only_hub_route(
    tmp_path: Path, monkeypatch, container_key: str, require_stdio_type: bool,
    initial: dict[str, object], provider: str,
) -> None:
    install = tmp_path / "installed-hub"
    install.mkdir()
    path = tmp_path / "provider-mcp.json"
    path.write_text(json.dumps(initial), encoding="utf-8")
    write_install_manifest(install)
    monkeypatch.setattr(setup_script, "_ACTIVE_INSTALL_ROOT", install)

    entry = {
        "command": "python", "args": ["-m", "local_ai_hub.mcp_server"],
        "env": {"LOCAL_AI_AGENT": provider},
    }
    if not require_stdio_type:
        entry["type"] = "local"
    setup_script.json_server_merge(
        path,
        {"local-ai": entry},
        backup_enabled=False,
        container_key=container_key,
        require_stdio_type=require_stdio_type,
    )
    configured = json.loads(path.read_text(encoding="utf-8"))
    container = configured
    for segment in container_key.split("."):
        container = container[segment]
    assert container["local-ai"]["type"] == ("stdio" if require_stdio_type else "local")
    assert container["local-ai"]["env"]["LOCAL_AI_AGENT"] == provider

    uninstall.clean_external_configurations(read_install_manifest(install)["external_ownership"], install)

    assert json.loads(path.read_text(encoding="utf-8")) == initial


def test_devin_hook_setup_rolls_back_only_hub_tool_entries(tmp_path: Path, monkeypatch) -> None:
    install = tmp_path / "installed-hub"
    hook_source = install / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed hook source\n", encoding="utf-8")
    write_install_manifest(install)
    monkeypatch.setattr(setup_script, "_ACTIVE_INSTALL_ROOT", install)
    path = tmp_path / "devin" / "config.json"
    user_hook = {"matcher": "read", "hooks": [{"type": "command", "command": "user-hook"}]}
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"theme": "dark", "hooks": {"PreToolUse": [user_hook]}}), encoding="utf-8")

    assert setup_script.sync_devin_pre_tool_hook(path, install, tmp_path / "python.exe", False) is False
    assert json.loads(path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"] == [user_hook]

    path.write_text(json.dumps({"theme": "dark", "hooks": {"SessionStart": [{"matcher": "", "hooks": []}]}}), encoding="utf-8")
    assert setup_script.sync_devin_pre_tool_hook(path, install, tmp_path / "python.exe", False)
    assert setup_script.sync_devin_post_tool_hook(path, install, tmp_path / "python.exe", False)
    owned_hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]
    assert owned_hooks["SessionStart"] == [{"matcher": "", "hooks": []}]
    assert owned_hooks["PreToolUse"][0]["matcher"] == "exec"
    assert owned_hooks["PostToolUse"][0]["matcher"] == "^(edit|write|apply_patch)$"

    uninstall.clean_external_configurations(read_install_manifest(install)["external_ownership"], install)

    restored = json.loads(path.read_text(encoding="utf-8"))
    assert restored == {"theme": "dark", "hooks": {"SessionStart": [{"matcher": "", "hooks": []}]}}


def test_copilot_hook_setup_removes_only_its_new_managed_file_on_uninstall(tmp_path: Path, monkeypatch) -> None:
    install = tmp_path / "installed-hub"
    hook_source = install / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed hook source\n", encoding="utf-8")
    write_install_manifest(install)
    monkeypatch.setattr(setup_script, "_ACTIVE_INSTALL_ROOT", install)
    path = tmp_path / "copilot" / "hooks" / "local-ai-hub.json"

    assert setup_script.sync_copilot_tool_hooks(path, install, tmp_path / "python.exe", False)
    configured = json.loads(path.read_text(encoding="utf-8"))
    assert set(configured["hooks"]) == {"preToolUse", "postToolUse"}

    uninstall.clean_external_configurations(read_install_manifest(install)["external_ownership"], install)

    assert not path.exists()


def test_copilot_hook_uninstall_preserves_user_edited_managed_file(tmp_path: Path, monkeypatch) -> None:
    install = tmp_path / "installed-hub"
    hook_source = install / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed hook source\n", encoding="utf-8")
    write_install_manifest(install)
    monkeypatch.setattr(setup_script, "_ACTIVE_INSTALL_ROOT", install)
    path = tmp_path / "copilot" / "hooks" / "local-ai-hub.json"

    assert setup_script.sync_copilot_tool_hooks(path, install, tmp_path / "python.exe", False)
    configured = json.loads(path.read_text(encoding="utf-8"))
    configured["operatorNote"] = "keep this edit"
    path.write_text(json.dumps(configured), encoding="utf-8")

    uninstall.clean_external_configurations(read_install_manifest(install)["external_ownership"], install)

    assert json.loads(path.read_text(encoding="utf-8"))["operatorNote"] == "keep this edit"


@pytest.mark.parametrize(
    ("provider", "setup_name", "source_name", "config_name"),
    [
        ("claude", "sync_claude_permission_request_hook", "repo_plan/host_hooks.py", "settings.json"),
        ("claude", "sync_claude_post_tool_hook", "repo_plan/host_hooks.py", "settings.json"),
        ("claude", "sync_claude_subagent_start_hook", "repo_plan/host_hooks.py", "settings.json"),
        ("gemini", "sync_gemini_cli_hooks", "repo_plan/host_hooks.py", "settings.json"),
        ("cursor", "sync_cursor_after_file_edit_hook", "repo_plan/host_hooks.py", "hooks.json"),
        ("windsurf", "sync_windsurf_policy_hooks", "windsurf_hook.py", "hooks.json"),
        ("devin", "sync_devin_post_tool_hook", "repo_plan/host_hooks.py", "config.json"),
    ],
)
def test_provider_new_hook_file_rolls_back_with_exact_written_bytes(
    tmp_path: Path, monkeypatch, provider: str, setup_name: str, source_name: str, config_name: str,
) -> None:
    install = tmp_path / "installed-hub"
    hook_source = install / "src" / "local_ai_hub" / source_name
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed hook source\n", encoding="utf-8")
    write_install_manifest(install)
    monkeypatch.setattr(setup_script, "_ACTIVE_INSTALL_ROOT", install)
    path = tmp_path / provider / config_name

    setup = getattr(setup_script, setup_name)
    assert setup(path, install, tmp_path / "python.exe", False)
    assert path.exists()

    uninstall.clean_external_configurations(read_install_manifest(install)["external_ownership"], install)

    assert not path.exists()


@pytest.mark.parametrize(
    ("provider", "setup_name", "source_name", "config_name", "foreign_event"),
    [
        ("claude", "sync_claude_permission_request_hook", "repo_plan/host_hooks.py", "settings.json", "SessionStart"),
        ("claude", "sync_claude_post_tool_hook", "repo_plan/host_hooks.py", "settings.json", "SessionStart"),
        ("gemini", "sync_gemini_cli_hooks", "repo_plan/host_hooks.py", "settings.json", "BeforeAgent"),
        ("cursor", "sync_cursor_after_file_edit_hook", "repo_plan/host_hooks.py", "hooks.json", "beforeSubmitPrompt"),
        ("windsurf", "sync_windsurf_policy_hooks", "windsurf_hook.py", "hooks.json", "post_mcp_tool_use"),
    ],
)
def test_provider_hook_rollback_preserves_foreign_event_list(
    tmp_path: Path, monkeypatch, provider: str, setup_name: str, source_name: str,
    config_name: str, foreign_event: str,
) -> None:
    install = tmp_path / "installed-hub"
    hook_source = install / "src" / "local_ai_hub" / source_name
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed hook source\n", encoding="utf-8")
    write_install_manifest(install)
    monkeypatch.setattr(setup_script, "_ACTIVE_INSTALL_ROOT", install)
    path = tmp_path / provider / config_name
    original = {"hooks": {foreign_event: [{"type": "command", "command": "user-hook"}]}}
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(original), encoding="utf-8")

    setup = getattr(setup_script, setup_name)
    assert setup(path, install, tmp_path / "python.exe", False)
    assert foreign_event in json.loads(path.read_text(encoding="utf-8"))["hooks"]

    uninstall.clean_external_configurations(read_install_manifest(install)["external_ownership"], install)

    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_antigravity_hook_rollback_preserves_existing_user_configuration(tmp_path: Path, monkeypatch) -> None:
    install = tmp_path / "installed-hub"
    source = install / "src" / "local_ai_hub" / "antigravity_hook.py"
    source.parent.mkdir(parents=True)
    source.write_text("# managed hook source\n", encoding="utf-8")
    write_install_manifest(install)
    monkeypatch.setattr(setup_script, "_ACTIVE_INSTALL_ROOT", install)
    path = tmp_path / "antigravity" / "config" / "hooks.json"
    original = {"custom": {"enabled": True}}
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(original), encoding="utf-8")

    setup_script.sync_antigravity_hooks_json(path, install, tmp_path / "python.exe", False)
    assert "local-ai-hub" in json.loads(path.read_text(encoding="utf-8"))

    uninstall.clean_external_configurations(read_install_manifest(install)["external_ownership"], install)

    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert not (path.parent / "local-ai-hook.cmd").exists()


def test_windsurf_hook_setup_preserves_unowned_overlap_for_manual_merge(tmp_path: Path, monkeypatch) -> None:
    install = tmp_path / "installed-hub"
    hook_source = install / "src" / "local_ai_hub" / "windsurf_hook.py"
    hook_source.parent.mkdir(parents=True)
    hook_source.write_text("# managed hook source\n", encoding="utf-8")
    write_install_manifest(install)
    monkeypatch.setattr(setup_script, "_ACTIVE_INSTALL_ROOT", install)
    path = tmp_path / "windsurf" / "hooks.json"
    original = {"hooks": {"pre_mcp_tool_use": [{"command": "user-hook"}]}}
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(original), encoding="utf-8")
    before = path.read_bytes()

    assert not setup_script.sync_windsurf_policy_hooks(path, install, tmp_path / "python.exe", False)
    assert path.read_bytes() == before


def test_json_cleanup_preserves_edited_owned_entry_and_unowned_entry(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    path = tmp_path / "mcp.json"
    original = {"command": "python", "cwd": str(install)}
    data = {"mcpServers": {"local-ai": original, "other": {"command": "foreign"}}}
    path.write_text(json.dumps(data), encoding="utf-8")
    write_install_manifest(install)
    record_external_json_key(
        install, path, container="mcpServers", key="local-ai", preimage=None, postimage=original,
    )
    data["mcpServers"]["local-ai"]["args"] = ["user-added-flag"]
    path.write_text(json.dumps(data), encoding="utf-8")

    uninstall.clean_json(path, install)

    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["mcpServers"]["local-ai"]["args"] == ["user-added-flag"]
    assert result["mcpServers"]["other"] == {"command": "foreign"}


def test_uninstall_plan_rejects_home_before_mutation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(ValueError, match="unsafe uninstall path"):
        uninstall.build_uninstall_plan(home, source_root=source, home=home)


def test_uninstall_plan_requires_install_ownership_marker(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = tmp_path / "source"
    install = home / ".local-ai-hub"
    home.mkdir()
    source.mkdir()
    install.mkdir()

    with pytest.raises(ValueError, match="ownership marker"):
        uninstall.build_uninstall_plan(install, source_root=source, home=home)


def test_uninstall_plan_accepts_owned_install_and_lists_managed_files(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = tmp_path / "source"
    install = tmp_path / "install"
    home.mkdir()
    source.mkdir()
    install.mkdir()
    write_install_manifest(install, ["tools/setup.py"])

    plan = uninstall.build_uninstall_plan(install, source_root=source, home=home)

    assert plan["install_dir"] == str(install)
    assert plan["managed_paths"] == ["tools/setup.py"]
    assert plan["owned_paths"] == [str(install), str(install / "tools" / "setup.py")]


def test_uninstall_plan_rejects_source_overlap(tmp_path: Path) -> None:
    source = tmp_path / "source"
    install = source / "installed-child"
    source.mkdir()
    install.mkdir()
    write_install_manifest(install)

    with pytest.raises(ValueError, match="unsafe uninstall path"):
        uninstall.build_uninstall_plan(install, source_root=source, home=tmp_path / "home")


def test_uninstall_plan_rejects_symlink_component(tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = tmp_path / "source"
    real_install = tmp_path / "real-install"
    linked_parent = tmp_path / "linked-parent"
    home.mkdir()
    source.mkdir()
    real_install.mkdir()
    write_install_manifest(real_install)
    try:
        linked_parent.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(ValueError, match="symlink or junction"):
        uninstall.build_uninstall_plan(linked_parent / "real-install", source_root=source, home=home)


def test_main_stops_before_cleanup_when_hub_stop_is_unconfirmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = tmp_path / "install"
    install.mkdir()
    write_install_manifest(install)
    monkeypatch.setattr(uninstall, "configured_install_dir", lambda: install)
    monkeypatch.setattr(uninstall, "stop_hub", lambda _install: "unconfirmed")
    monkeypatch.setattr(sys, "argv", ["uninstall.py"])

    cleanup_calls: list[str] = []
    monkeypatch.setattr(uninstall, "clean_codex", lambda _path: cleanup_calls.append("codex"))
    monkeypatch.setattr(uninstall, "clean_json", lambda _path: cleanup_calls.append("json"))
    monkeypatch.setattr(uninstall, "clean_policy", lambda _path: cleanup_calls.append("policy"))
    monkeypatch.setattr(uninstall.shutil, "rmtree", lambda *_args, **_kwargs: cleanup_calls.append("rmtree"))

    assert uninstall.main() == 1
    assert cleanup_calls == []
    assert install.is_dir()


def test_policy_cleanup_requires_manifest_and_preserves_outside_edits(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    target = tmp_path / "AGENTS.md"
    begin, end = uninstall.POLICY_BEGIN, uninstall.POLICY_END
    owned_block = f"{begin}\nHub policy v1\n{end}"
    target.write_text(f"User intro\n{owned_block}\nUser tail\n", encoding="utf-8")
    write_install_manifest(install)
    record_external_block(
        install, target, kind="text_block", owner_marker={"begin": begin, "end": end},
        preimage=None, postimage=owned_block,
    )

    uninstall.clean_policy(target, install)

    assert target.read_text(encoding="utf-8") == "User intro\n\nUser tail\n"
    manifest = read_install_manifest(install)
    entry = manifest["external_ownership"][0]
    assert entry["created_by_hub"] is True
    assert entry["preimage_digest"] is None
    assert entry["last_hub_written_digest"]
    assert "Hub policy v1" not in (install / uninstall.MANIFEST_NAME).read_text(encoding="utf-8")


def test_policy_cleanup_preserves_conflicted_owned_block(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    target = tmp_path / "AGENTS.md"
    begin, end = uninstall.POLICY_BEGIN, uninstall.POLICY_END
    owned_block = f"{begin}\nHub policy v1\n{end}"
    target.write_text(f"User intro\n{owned_block}\nUser tail\n", encoding="utf-8")
    write_install_manifest(install)
    record_external_block(
        install, target, kind="text_block", owner_marker={"begin": begin, "end": end},
        preimage=None, postimage=owned_block,
    )
    target.write_text(target.read_text(encoding="utf-8").replace("Hub policy v1", "Hub policy plus user edit"), encoding="utf-8")
    conflicted = target.read_text(encoding="utf-8")

    uninstall.clean_policy(target, install)

    assert target.read_text(encoding="utf-8") == conflicted


def test_reinstall_keeps_original_ownership_origin_for_policy_block(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    target = tmp_path / "AGENTS.md"
    begin, end = uninstall.POLICY_BEGIN, uninstall.POLICY_END
    old_block = f"{begin}\nHub policy v1\n{end}"
    new_block = f"{begin}\nHub policy v2\n{end}"
    target.write_text(old_block, encoding="utf-8")
    write_install_manifest(install)
    marker = {"begin": begin, "end": end}
    record_external_block(
        install, target, kind="text_block", owner_marker=marker, preimage=None, postimage=old_block,
    )
    record_external_block(
        install, target, kind="text_block", owner_marker=marker, preimage=old_block, postimage=new_block,
    )

    manifest = read_install_manifest(install)
    assert manifest["external_ownership"][0]["created_by_hub"] is True
    assert manifest["external_ownership"][0]["preimage_digest"] is None
    target.write_text(new_block, encoding="utf-8")
    uninstall.clean_policy(target, install)
    assert target.read_text(encoding="utf-8") == ""


def test_schema_one_marker_migrates_without_claiming_legacy_external_blocks(tmp_path: Path) -> None:
    install = tmp_path / "install"
    install.mkdir()
    manifest_path = install / uninstall.MANIFEST_NAME
    manifest_path.write_text(json.dumps({
        "schema_version": 1,
        "product": "local-ai-hub",
        "install_id": "legacy-install",
        "install_root": str(install),
        "managed_paths": [],
    }), encoding="utf-8")

    write_install_manifest(install)

    manifest = read_install_manifest(install)
    assert manifest["schema_version"] == 2
    assert manifest["install_id"] == "legacy-install"
    assert manifest["external_ownership"] == []
