from __future__ import annotations

import importlib.util
from pathlib import Path


PLUGIN_HOOK = Path(__file__).resolve().parents[1] / "plugins" / "codex" / "local-ai-hub" / "hooks" / "codex_hook.py"
SPEC = importlib.util.spec_from_file_location("codex_plugin_hook", PLUGIN_HOOK)
assert SPEC is not None and SPEC.loader is not None
codex_hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(codex_hook)


def _make_install(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.toml").write_text("", encoding="utf-8")
    (root / "src" / "local_ai_hub" / "repo_plan").mkdir(parents=True)
    (root / "src" / "local_ai_hub" / "repo_plan" / "host_hooks.py").write_text("", encoding="utf-8")
    python = root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"isolated-test-fixture")
    return python


def test_codex_hook_uses_explicit_custom_hub_install(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    custom = tmp_path / "custom hub"
    python = _make_install(custom)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("LOCAL_AI_HUB_DIR", str(custom))

    command = codex_hook._configured_hub_command()

    assert command is not None
    argv, cwd, env = command
    assert argv[0] == str(python)
    assert cwd == custom
    assert env["LOCAL_AI_AGENT"] == "codex"
    assert env["LOCAL_AI_CONFIG"] == str(custom / "config.toml")


def test_codex_hook_fails_closed_for_invalid_explicit_install(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    fallback = tmp_path / ".local-ai-hub"
    _make_install(fallback)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("LOCAL_AI_HUB_DIR", str(tmp_path / "missing hub"))
    monkeypatch.setattr(codex_hook.Path, "home", lambda: tmp_path)

    assert codex_hook._configured_hub_command() is None
