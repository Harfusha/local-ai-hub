from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import setup
import uninstall


def test_uninstall_removes_only_owned_instruction_blocks(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    install = tmp_path / "install"
    home.mkdir()
    install.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(setup, "get_user_homes", lambda: [home])
    codex_home = home / ".codex"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    codex_home.mkdir()
    codex_rules = codex_home / "AGENTS.md"
    codex_rules.write_text("User Codex rules\n", encoding="utf-8")
    gemini = home / ".gemini"
    gemini.mkdir()
    gemini_rules = gemini / "GEMINI.md"
    gemini_rules.write_text("User Gemini rules\n", encoding="utf-8")
    cfg = {
        "setup": {"backup_existing_configs": False, "install_antigravity_style_policy": False},
        "tool_policy": {"install_global_instructions": True},
        "agents": {"codex": True, "gemini": True, "claude": False, "cursor": False, "windsurf": False, "copilot": False},
    }
    components = {
        f"agent_{agent}_{component}": component == "instructions"
        for agent in ("codex", "gemini", "claude", "cursor", "windsurf", "copilot")
        for component in ("mcp", "skills", "instructions")
    }

    setup.configure_agents(install, Path(sys.executable), None, cfg, include_companion=False, agent_components=components)
    assert not (gemini / "AGENTS.md").exists()
    assert setup.GLOBAL_POLICY_BEGIN in codex_rules.read_text(encoding="utf-8")
    assert setup.TOKEN_ECONOMY_POLICY_BEGIN in gemini_rules.read_text(encoding="utf-8")

    codex_rules.write_text(codex_rules.read_text(encoding="utf-8") + "User added after install\n", encoding="utf-8")
    gemini_rules.write_text(gemini_rules.read_text(encoding="utf-8") + "Another user note\n", encoding="utf-8")
    monkeypatch.setattr(uninstall, "configured_install_dir", lambda: install)
    monkeypatch.setattr(uninstall, "stop_hub", lambda _install: uninstall.StopResult("already_stopped"))
    monkeypatch.setattr(sys, "argv", ["uninstall.py"])

    assert uninstall.main() == 0

    codex_after = codex_rules.read_text(encoding="utf-8")
    gemini_after = gemini_rules.read_text(encoding="utf-8")
    assert "User Codex rules" in codex_after and "User added after install" in codex_after
    assert "User Gemini rules" in gemini_after and "Another user note" in gemini_after
    assert setup.GLOBAL_POLICY_BEGIN not in codex_after
    assert setup.TOKEN_ECONOMY_POLICY_BEGIN not in gemini_after
