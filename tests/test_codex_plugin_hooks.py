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


def test_codex_hook_blocks_verbose_git_commands(tmp_path, monkeypatch):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()

    # PreToolUse event denials for unconstrained git commands
    for cmd, expected_hint in [
        ("git status", "git status -s"),
        ("git log", "git log --oneline -n 10"),
        ("git log -p", "git log --oneline -n 10"),
        ("git diff", "git diff --stat"),
        ("git branch", "git branch -v"),
        ("git branch -a", "git branch -a --column"),
        ("git show", "git show --stat -n 1"),
        ("python -m compileall src", "-q"),
    ]:
        payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "sess_1",
            "cwd": str(root),
            "tool_name": "Bash",
            "tool_input": {"command": cmd},
        }
        res = handle_host_event(root, "codex", payload)
        hso = res.get("hookSpecificOutput", {})
        assert hso.get("permissionDecision") == "deny"
        assert expected_hint in hso.get("permissionDecisionReason", "")

    # PermissionRequest event denials
    perm_payload = {
        "hook_event_name": "PermissionRequest",
        "session_id": "sess_1",
        "cwd": str(root),
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
    }
    perm_res = handle_host_event(root, "codex", perm_payload)
    hso_perm = perm_res.get("hookSpecificOutput", {})
    assert hso_perm.get("decision", {}).get("behavior") == "deny"
    assert "git status -s" in hso_perm.get("decision", {}).get("message", "")

    # Concise commands are allowed (no denial output)
    for cmd in ["git status -s", "git log --oneline -n 10", "git diff --stat", "git branch -v"]:
        ok_payload = {
            "hook_event_name": "PreToolUse",
            "session_id": "sess_1",
            "cwd": str(root),
            "tool_name": "Bash",
            "tool_input": {"command": cmd},
        }
        assert handle_host_event(root, "codex", ok_payload) == {}

