from __future__ import annotations

import sys
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import setup
import setup_wizard
from install_ownership import read_install_manifest, write_install_manifest


def test_antigravity_style_policy_defaults_to_opt_out() -> None:
    assert setup_wizard.defaults_from_config({})["antigravity_style_policy"] is False


def test_antigravity_style_policy_choice_is_saved_to_setup_config() -> None:
    config: dict = {}
    args = SimpleNamespace(
        profile=None,
        skip_model_pull=None,
        skip_tools=None,
        skip_token_economy=None,
        skip_agent_config=None,
        skip_service=None,
        skip_companion_skills=None,
        skip_laya_runtime=None,
        skip_ast_index=None,
        skip_performance=None,
        skip_profiling=None,
    )
    setup_wizard.apply_choices(args, config, {"antigravity_style_policy": True})
    assert config["setup"]["install_antigravity_style_policy"] is True


def test_global_policy_records_owned_block_and_refuses_unowned_collision(tmp_path: Path, monkeypatch) -> None:
    install = tmp_path / "install"
    install.mkdir()
    write_install_manifest(install)
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", install)
    target = tmp_path / "AGENTS.md"
    target.write_text("User text\n", encoding="utf-8")

    setup.merge_global_policy(target, backup_enabled=False, cfg={})

    manifest = read_install_manifest(install)
    assert len(manifest["external_ownership"]) == 1
    entry = manifest["external_ownership"][0]
    assert entry["path"] == str(target)
    assert entry["owner_marker"]["begin"] == setup.GLOBAL_POLICY_BEGIN
    assert entry["created_by_hub"] is True
    assert "User text" in target.read_text(encoding="utf-8")

    collision = tmp_path / "Other.md"
    collision.write_text(
        f"{setup.GLOBAL_POLICY_BEGIN}\nUser-authored block\n{setup.GLOBAL_POLICY_END}\n",
        encoding="utf-8",
    )
    original = collision.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="no ownership record"):
        setup.merge_global_policy(collision, backup_enabled=False, cfg={})
    assert collision.read_text(encoding="utf-8") == original


def test_json_mcp_merge_does_not_overwrite_unowned_same_name_entry(tmp_path: Path, monkeypatch) -> None:
    install = tmp_path / "install"
    install.mkdir()
    write_install_manifest(install)
    monkeypatch.setattr(setup, "_ACTIVE_INSTALL_ROOT", install)
    target = tmp_path / "mcp.json"
    original = {"command": "user-command", "args": ["keep"]}
    target.write_text(json.dumps({"mcpServers": {"local-ai": original}}), encoding="utf-8")

    setup.json_server_merge(target, {"local-ai": {"command": "hub-command", "args": []}}, False)

    assert json.loads(target.read_text(encoding="utf-8"))["mcpServers"]["local-ai"] == original
    assert read_install_manifest(install)["external_ownership"] == []


def test_companion_skills_do_not_install_style_policy_by_default(tmp_path: Path, monkeypatch) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(setup, "merge_global_policy", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "merge_token_economy_policy", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "merge_antigravity_skill_policy", lambda path, *_args: calls.append(path))

    setup.configure_gemini_instance(
        tmp_path / ".gemini",
        tmp_path / "install",
        tmp_path / "python.exe",
        None,
        {"tool_policy": {"install_global_instructions": True}},
        False,
        True,
        project_root=tmp_path / "project",
        agent_components={"agent_gemini_skills": False, "agent_gemini_mcp": False},
    )

    assert calls == []


def test_style_policy_installs_only_when_explicitly_selected(tmp_path: Path, monkeypatch) -> None:
    calls: list[Path] = []
    monkeypatch.setattr(setup, "merge_global_policy", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "merge_token_economy_policy", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup, "merge_antigravity_skill_policy", lambda path, *_args: calls.append(path))

    setup.configure_gemini_instance(
        tmp_path / ".gemini",
        tmp_path / "install",
        tmp_path / "python.exe",
        None,
        {"setup": {"install_antigravity_style_policy": True}, "tool_policy": {"install_global_instructions": True}},
        False,
        True,
        project_root=tmp_path / "project",
        agent_components={"agent_gemini_skills": False, "agent_gemini_mcp": False},
    )

    assert calls == [tmp_path / ".gemini" / "AGENTS.md", tmp_path / "project" / "AGENTS.md"]
