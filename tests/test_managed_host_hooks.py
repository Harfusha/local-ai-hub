"""Real host schemas, private steering bounds and reversible owned registration."""
import io
import json
import sys
from pathlib import Path

import pytest

from local_ai_hub.repo_plan.host_adapters import SteeringManager, probe_host_capabilities


def installation(root, host="codex"):
    from local_ai_hub.repo_plan.host_hooks import ManagedHostInstallation
    return ManagedHostInstallation(root, host)


@pytest.mark.parametrize("host,relative,prompt_event", [
    ("codex", ".codex/hooks.json", "UserPromptSubmit"),
    ("gemini_cli", ".gemini/settings.json", "BeforeAgent"),
])
def test_registration_real_schema_preserves_custom_and_rollback(tmp_path, host, relative, prompt_event):
    path = tmp_path / relative
    path.parent.mkdir()
    custom = {"type": "command", "command": "custom-scanner", "timeout": 17}
    path.write_text(json.dumps({"other": {"secret": "preserved"}, "hooks": {
        "SessionStart": [{"hooks": [custom]}]}}))
    manager = installation(tmp_path, host)
    preview = manager.preview()
    assert preview["support_level"] == "advisory"
    assert not (tmp_path / ".local-ai-hub").exists()
    result = manager.apply(expected_revision=preview["revision"])
    assert result["success"]
    config = json.loads(path.read_text())
    assert config["other"] == {"secret": "preserved"}
    assert config["hooks"]["SessionStart"][0]["hooks"] == [custom]
    handler = config["hooks"][prompt_event][0]["hooks"][0]
    assert handler["type"] == "command"
    assert "host_hooks.py" in handler["command"]
    assert handler["timeout"] == (5 if host == "codex" else 5000)
    if host == "codex":
        assert set(config["hooks"]) == {
            "SessionStart", "UserPromptSubmit", "SubagentStart", "PreToolUse",
            "PermissionRequest", "PostToolUse", "Stop",
        }
        assert config["hooks"]["PermissionRequest"][0]["matcher"] == "Bash|apply_patch"
    assert manager.apply(expected_revision=manager.preview()["revision"])["changed"] is False
    # A later user's customization must survive owned rollback.
    config["later"] = 42
    path.write_text(json.dumps(config))
    assert manager.rollback()["success"]
    restored = json.loads(path.read_text())
    assert restored["later"] == 42
    assert restored["hooks"] == {"SessionStart": [{"hooks": [custom]}]}
    assert manager.rollback()["changed"] is False


def test_preview_stale_and_modified_owned_hook_refuse_mutation(tmp_path):
    manager = installation(tmp_path)
    preview = manager.preview()
    path = tmp_path / ".codex/hooks.json"
    path.parent.mkdir()
    path.write_text('{"custom": true}')
    with pytest.raises(ValueError, match="changed"):
        manager.apply(expected_revision=preview["revision"])
    manager.apply(expected_revision=manager.preview()["revision"])
    config = json.loads(path.read_text())
    config["hooks"]["SessionStart"][0]["hooks"][0]["command"] = "user-customized"
    path.write_text(json.dumps(config))
    before = path.read_bytes()
    with pytest.raises(ValueError, match="modified"):
        manager.rollback()
    assert path.read_bytes() == before


def test_existing_identical_unowned_configuration_is_never_adopted(tmp_path):
    manager = installation(tmp_path)
    preview = manager.preview()
    path = tmp_path / ".codex/hooks.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"hooks": preview["registrations"]}))
    with pytest.raises(ValueError, match="unowned"):
        manager.apply(expected_revision=manager.preview()["revision"])


def test_config_bounds_and_unsupported_host(tmp_path):
    with pytest.raises(ValueError, match="unsupported"):
        installation(tmp_path, "gemini_antigravity")
    manager = installation(tmp_path)
    path = tmp_path / ".codex/hooks.json"
    path.parent.mkdir()
    path.write_bytes(b" " * 131073)
    with pytest.raises(ValueError, match="large"):
        manager.preview()


def test_corrupt_ownership_manifest_cannot_remove_user_hook(tmp_path):
    manager = installation(tmp_path)
    preview = manager.preview()
    manager.apply(expected_revision=preview["revision"])
    config_path = tmp_path / ".codex/hooks.json"
    config = json.loads(config_path.read_text())
    custom = {"hooks": [{"type": "command", "command": "user-hook"}]}
    config["hooks"]["SessionStart"].append(custom)
    config_path.write_text(json.dumps(config))
    manifest_path = tmp_path / ".local-ai-hub/local/host-adapters/codex.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["groups"] = {"SessionStart": [custom]}
    manifest_path.write_text(json.dumps(manifest))
    before = config_path.read_bytes()
    with pytest.raises(ValueError, match="ownership"):
        manager.rollback()
    assert config_path.read_bytes() == before


def test_steering_lock_serializes_capture_and_fails_closed(tmp_path):
    manager = SteeringManager(tmp_path)
    manager._ensure_dir()
    lock = manager.steering_dir / ".inbox.lock"
    lock.write_text("owned by active writer")
    with pytest.raises(ValueError, match="busy"):
        manager.capture_steering("session", "message", event_id="turn")
    assert manager.list_pending_steering() == []
    assert lock.exists()


def test_codex_user_prompt_hook_adds_guidance_without_persisting_or_echoing_prompt(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "session-1",
               "turn_id": "turn-1", "cwd": str(tmp_path), "prompt": "private-prompt-marker"}
    first = handle_host_event(tmp_path, "codex", payload)
    second = handle_host_event(tmp_path, "codex", payload)
    assert first == second
    output = first["hookSpecificOutput"]
    assert output["hookEventName"] == "UserPromptSubmit"
    assert "Laya output as advisory" in output["additionalContext"]
    assert "private-prompt-marker" not in json.dumps(first)
    assert probe_host_capabilities("codex", tmp_path).support_level != "enforced"
    assert not (tmp_path / ".local-ai-hub").exists()


def test_gemini_before_agent_adds_static_laya_guidance_without_prompt_access(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    result = handle_host_event(tmp_path, "gemini_cli", {
        "hook_event_name": "BeforeAgent",
        "session_id": "session-gemini",
        "cwd": str(tmp_path),
        "prompt": "private-prompt-marker",
    })

    output = result["hookSpecificOutput"]
    assert output["hookEventName"] == "BeforeAgent"
    assert "typed Laya advice" in output["additionalContext"]
    assert "private-prompt-marker" not in json.dumps(result)
    assert not (tmp_path / ".local-ai-hub").exists()


def test_codex_subagent_start_receives_laya_guidance_without_transcript_access(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    result = handle_host_event(tmp_path, "codex", {
        "hook_event_name": "SubagentStart",
        "session_id": "session-1",
        "cwd": str(tmp_path),
        "agent_type": "explorer",
        "agent_transcript_path": str(tmp_path / "private.jsonl"),
    })
    output = result["hookSpecificOutput"]
    assert output["hookEventName"] == "SubagentStart"
    assert "Laya output as advisory" in output["additionalContext"]
    assert "private.jsonl" not in json.dumps(result)
    assert not (tmp_path / ".local-ai-hub").exists()


def test_claude_subagent_start_receives_laya_guidance_without_transcript_access(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    result = handle_host_event(tmp_path, "claude", {
        "hook_event_name": "SubagentStart",
        "session_id": "session-claude",
        "cwd": str(tmp_path),
        "agent_id": "agent-1",
        "agent_type": "Explore",
        "transcript_path": str(tmp_path / "private.jsonl"),
    })
    output = result["hookSpecificOutput"]
    assert output["hookEventName"] == "SubagentStart"
    assert "typed Laya advice" in output["additionalContext"]
    assert "private.jsonl" not in json.dumps(result)


def test_claude_user_prompt_hook_adds_guidance_without_echoing_or_deciding(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    result = handle_host_event(tmp_path, "claude", {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "session-claude",
        "cwd": str(tmp_path),
        "prompt": "private-prompt-marker",
    })

    output = result["hookSpecificOutput"]
    assert output["hookEventName"] == "UserPromptSubmit"
    assert "typed Laya advice" in output["additionalContext"]
    assert "private-prompt-marker" not in json.dumps(result)
    assert "decision" not in result
    assert not (tmp_path / ".local-ai-hub").exists()


def test_claude_session_start_receives_static_laya_guidance_without_hub_call(tmp_path, monkeypatch):
    from local_ai_hub.repo_plan import host_hooks

    warmups = []
    monkeypatch.setattr(host_hooks, "_trigger_repo_warmup", lambda root: warmups.append(root))
    result = host_hooks.handle_host_event(tmp_path, "claude", {
        "hook_event_name": "SessionStart",
        "session_id": "session-claude",
        "cwd": str(tmp_path),
        "source": "compact",
        "transcript_path": str(tmp_path / "private.jsonl"),
    })

    assert warmups == [tmp_path]
    assert "additionalContext" in result["hookSpecificOutput"]
    assert "typed Laya advice" in result["hookSpecificOutput"]["additionalContext"]
    assert "private.jsonl" not in json.dumps(result)


def test_payloads_do_not_cross_root_or_accept_invalid_shapes(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": "s",
               "cwd": str(tmp_path.parent), "prompt": "x"}
    with pytest.raises(ValueError, match="root"):
        handle_host_event(tmp_path, "codex", payload)
    payload["cwd"] = str(tmp_path)
    payload["prompt"] = "x" * 17000
    assert handle_host_event(tmp_path, "codex", payload) == handle_host_event(tmp_path, "codex", payload)
    with pytest.raises(ValueError):
        handle_host_event(tmp_path, "codex", [])
    assert not (tmp_path / ".local-ai-hub").exists()


def test_tool_policy_denials_use_native_host_formats_without_allowing_safe_calls(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    command = "python -m pytest -q"
    codex = {"hook_event_name": "PreToolUse", "session_id": "s", "cwd": str(tmp_path),
             "tool_name": "Bash", "tool_input": {"command": command}}
    expected_reason = "Unconstrained bare pytest"
    result = handle_host_event(tmp_path, "codex", codex)
    assert result["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert expected_reason in result["hookSpecificOutput"]["permissionDecisionReason"]

    claude = {**codex, "tool_name": "Bash"}
    result = handle_host_event(tmp_path, "claude", claude)
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert expected_reason in result["hookSpecificOutput"]["permissionDecisionReason"]

    copilot = {"hook_event_name": "preToolUse", "session_id": "s", "cwd": str(tmp_path),
               "tool_name": "shell", "tool_input": {"command": command}}
    result = handle_host_event(tmp_path, "copilot", copilot)
    assert result["permissionDecision"] == "deny"
    assert expected_reason in result["permissionDecisionReason"]

    # Copilot/VS Code hooks send camelCase fields. Configured event identity comes
    # from the managed command because native payloads need not include event name.
    copilot_native = {
        "sessionId": "s",
        "cwd": str(tmp_path),
        "toolName": "shell",
        "toolArgs": {"command": command},
    }
    result = handle_host_event(tmp_path, "copilot", copilot_native)
    assert result["permissionDecision"] == "deny"
    assert expected_reason in result["permissionDecisionReason"]

    safe = {**copilot, "tool_input": {"command": "python -m pytest tests/test_one.py -q"}}
    assert handle_host_event(tmp_path, "copilot", safe) == {}


def test_codex_permission_request_hook_only_denies_policy_violations(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    blocked = handle_host_event(tmp_path, "codex", {
        "hook_event_name": "PermissionRequest",
        "session_id": "s",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "python -m pytest -q"},
    })
    specific = blocked["hookSpecificOutput"]
    assert specific["hookEventName"] == "PermissionRequest"
    assert specific["decision"]["behavior"] == "deny"
    assert "Unconstrained bare pytest" in specific["decision"]["message"]

    safe = handle_host_event(tmp_path, "codex", {
        "hook_event_name": "PermissionRequest",
        "session_id": "s",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "python -m pytest tests/test_one.py -q"},
    })
    assert safe == {}


def test_claude_permission_request_hook_only_denies_policy_violations(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    blocked = handle_host_event(tmp_path, "claude", {
        "hook_event_name": "PermissionRequest",
        "session_id": "s",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "python -m pytest -q"},
    })
    specific = blocked["hookSpecificOutput"]
    assert specific["hookEventName"] == "PermissionRequest"
    assert specific["decision"]["behavior"] == "deny"
    assert "Unconstrained bare pytest" in specific["decision"]["message"]

    safe = handle_host_event(tmp_path, "claude", {
        "hook_event_name": "PermissionRequest",
        "session_id": "s",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "python -m pytest tests/test_one.py -q"},
    })
    assert safe == {}


@pytest.mark.parametrize("tool_name", ["Edit", "Write"])
def test_claude_post_tool_use_checks_changed_file_with_native_tool_input(tmp_path, monkeypatch, tool_name):
    from local_ai_hub import shadow_compiler
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    target = tmp_path / "changed.py"
    checked = []
    monkeypatch.setattr(shadow_compiler, "shadow_check", lambda path, root=None: checked.append((path, root)) or {})
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "s",
        "cwd": str(tmp_path),
        "tool_name": tool_name,
        "tool_input": {"file_path": str(target)},
    }

    assert handle_host_event(tmp_path, "claude", payload) == {}
    assert checked == [(str(target), tmp_path)]


def test_claude_post_tool_use_returns_static_findings_as_non_permission_context(tmp_path, monkeypatch):
    from local_ai_hub import shadow_compiler
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    target = tmp_path / "changed.py"
    monkeypatch.setattr(shadow_compiler, "shadow_check", lambda *_args, **_kwargs: {
        "syntax_ok": False,
        "violations": [{"severity": "high", "message": "call is missing timeout"}],
    })
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "s",
        "cwd": str(tmp_path),
        "tool_name": "Edit",
        "tool_input": {"file_path": str(target)},
    }

    result = handle_host_event(tmp_path, "claude", payload)
    output = result["hookSpecificOutput"]
    assert output["hookEventName"] == "PostToolUse"
    assert "syntax error" in output["additionalContext"]
    assert "missing timeout" in output["additionalContext"]
    assert "permissionDecision" not in output


def test_opencode_post_tool_use_returns_static_findings_as_non_permission_context(tmp_path, monkeypatch):
    from local_ai_hub import shadow_compiler
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    target = tmp_path / "changed.py"
    checked = []
    monkeypatch.setattr(shadow_compiler, "shadow_check", lambda path, root=None: checked.append((path, root)) or {
        "syntax_ok": False,
        "violations": [{"severity": "high", "message": "call is missing timeout"}],
    })
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "s",
        "cwd": str(tmp_path),
        "tool_name": "edit",
        "tool_input": {"filePath": str(target), "newString": "must not be forwarded"},
    }

    result = handle_host_event(tmp_path, "opencode", payload)
    assert checked == [(str(target), tmp_path)]
    assert "syntax error" in result["additionalContext"]
    assert "missing timeout" in result["additionalContext"]
    assert set(result) == {"additionalContext"}


def test_opencode_post_tool_use_rejects_non_absolute_file_path(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    with pytest.raises(ValueError, match="edited file path"):
        handle_host_event(tmp_path, "opencode", {
            "hook_event_name": "PostToolUse", "session_id": "s", "cwd": str(tmp_path),
            "tool_name": "edit", "tool_input": {"file_path": "relative.py"},
        })


def test_opencode_post_tool_use_does_not_check_outside_workspace(tmp_path, monkeypatch):
    from local_ai_hub import shadow_compiler
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    outside = tmp_path.parent / "outside.py"
    monkeypatch.setattr(shadow_compiler, "shadow_check", lambda *_args, **_kwargs: pytest.fail("outside path checked"))
    result = handle_host_event(tmp_path, "opencode", {
        "hook_event_name": "PostToolUse", "session_id": "s", "cwd": str(tmp_path),
        "tool_name": "write", "tool_input": {"file_path": str(outside)},
    })
    assert result == {}


def test_opencode_permission_request_denies_only_bare_pytest(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    payload = {
        "hook_event_name": "PermissionRequest", "session_id": "s", "cwd": str(tmp_path),
        "tool_name": "Bash", "tool_input": {"command": "python -m pytest -q"},
    }
    denied = handle_host_event(tmp_path, "opencode", payload)
    assert denied["decision"] == "deny"
    assert "Unconstrained bare pytest" in denied["reason"]

    payload["tool_input"]["command"] = "python -m pytest tests/test_one.py -q"
    assert handle_host_event(tmp_path, "opencode", payload) == {}


def test_opencode_permission_request_rejects_unbounded_or_unrelated_events(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    base = {"hook_event_name": "PermissionRequest", "session_id": "s", "cwd": str(tmp_path)}
    with pytest.raises(ValueError, match="permission action"):
        handle_host_event(tmp_path, "opencode", {**base, "tool_name": "edit", "tool_input": {"command": "x"}})
    with pytest.raises(ValueError, match="permission command"):
        handle_host_event(tmp_path, "opencode", {**base, "tool_name": "Bash", "tool_input": {"command": "x" * 4100}})


def test_devin_post_tool_use_checks_edit_and_returns_context_without_permission(tmp_path, monkeypatch):
    from local_ai_hub import shadow_compiler
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    target = tmp_path / "changed.py"
    checked = []
    monkeypatch.setattr(shadow_compiler, "shadow_check", lambda path, root=None: checked.append((path, root)) or {
        "syntax_ok": False, "violations": [],
    })
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "s",
        "cwd": str(tmp_path),
        "tool_name": "edit",
        "tool_input": {"file_path": str(target)},
    }

    result = handle_host_event(tmp_path, "devin", payload)
    assert checked == [(str(target), tmp_path)]
    assert result["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "syntax error" in result["hookSpecificOutput"]["additionalContext"]
    assert "decision" not in result


def test_devin_post_tool_use_cli_accepts_configured_event_identity(tmp_path, monkeypatch, capsys):
    from local_ai_hub import shadow_compiler
    from local_ai_hub.repo_plan import host_hooks

    target = tmp_path / "changed.py"
    monkeypatch.setattr(shadow_compiler, "shadow_check", lambda *_args, **_kwargs: {"syntax_ok": True})
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "s", "cwd": str(tmp_path), "tool_name": "edit",
        "tool_input": {"file_path": str(target)},
    })))

    assert host_hooks.main(["--root", str(tmp_path), "--host", "devin", "--event", "PostToolUse"]) == 0
    assert json.loads(capsys.readouterr().out) == {}


def test_cursor_after_file_edit_uses_shared_post_tool_check(tmp_path, monkeypatch):
    from local_ai_hub import shadow_compiler
    from local_ai_hub.repo_plan import host_hooks

    target = tmp_path / "changed.py"
    checked = []
    monkeypatch.setattr(shadow_compiler, "shadow_check", lambda path, root=None: checked.append((path, root)) or {})
    normalized = host_hooks._normalize_cursor_event({"hook_event_name": "afterFileEdit", "file_path": str(target)})
    assert normalized["hook_event_name"] == "PostToolUse"
    assert normalized["tool_input"]["file_path"] == str(target)
    assert host_hooks.handle_host_event(tmp_path, "cursor", normalized) == {}
    assert checked == [(str(target), tmp_path)]
    checked.clear()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"file_path": str(target)})))

    assert host_hooks.main(["--root", str(tmp_path), "--host", "cursor", "--event", "afterFileEdit"]) == 0
    assert checked == [(str(target), tmp_path)]


def test_cursor_shell_hook_denies_policy_violations_and_keeps_user_approval(tmp_path, monkeypatch, capsys):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    safe = {
        "hook_event_name": "beforeShellExecution",
        "cwd": str(tmp_path),
        "command": "python -m pytest tests/test_one.py -q",
        "sandbox": True,
    }
    allowed_by_policy = handle_host_event(tmp_path, "cursor", safe)
    assert allowed_by_policy["permission"] == "ask"
    assert "host approval is still required" in allowed_by_policy["agent_message"]

    unsafe = {**safe, "command": "python -m pytest"}
    denied = handle_host_event(tmp_path, "cursor", unsafe)
    assert denied["permission"] == "deny"
    assert "Unconstrained bare pytest" in denied["user_message"]

    import io
    import local_ai_hub.repo_plan.host_hooks as host_hooks
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(safe)))
    assert host_hooks.main(["--host", "cursor", "--event", "beforeShellExecution"]) == 0
    assert json.loads(capsys.readouterr().out)["permission"] == "ask"

    oversized = {**safe, "command": "x" * 16001}
    with pytest.raises(ValueError, match="Cursor shell command"):
        handle_host_event(tmp_path, "cursor", oversized)


def test_codex_read_hook_enforces_shared_80_line_limit(tmp_path, monkeypatch):
    from local_ai_hub.repo_plan import host_hooks
    handle_host_event = host_hooks.handle_host_event
    monkeypatch.setattr(host_hooks, "_is_hub_online", lambda: False, raising=False)

    source = tmp_path / "long.py"
    source.write_text("\n".join(f"line_{i}" for i in range(81)), encoding="utf-8")
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "s",
        "cwd": str(tmp_path),
        "tool_name": "Read",
        "tool_input": {"file_path": str(source)},
    }
    result = handle_host_event(tmp_path, "codex", payload)
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "> 80 lines" in result["hookSpecificOutput"]["permissionDecisionReason"]


def test_gemini_before_tool_routes_source_reads_and_bounded_search_through_hub(tmp_path, monkeypatch):
    from local_ai_hub.repo_plan import host_hooks
    monkeypatch.setattr(host_hooks, "_is_hub_online", lambda: True, raising=False)
    source = tmp_path / "small.py"
    source.write_text("value = 1\n", encoding="utf-8")
    base = {
        "hook_event_name": "BeforeTool",
        "session_id": "session-1",
        "cwd": str(tmp_path),
    }

    read = host_hooks.handle_host_event(tmp_path, "gemini_cli", {
        **base, "tool_name": "read_file", "tool_input": {"file_path": str(source)},
    })
    search = host_hooks.handle_host_event(tmp_path, "gemini_cli", {
        **base, "tool_name": "run_shell_command", "tool_input": {"command": "rg -m 5 needle src"},
    })

    assert read["decision"] == "deny"
    assert "local_ai_repo" in read["reason"]
    assert search["decision"] == "deny"
    assert "local_ai_repo" in search["reason"]

    powershell_read = host_hooks.handle_host_event(tmp_path, "gemini_cli", {
        **base,
        "tool_name": "run_shell_command",
        "tool_input": {"command": "Get-Content .\\small.py"},
    })
    recursive_list = host_hooks.handle_host_event(tmp_path, "gemini_cli", {
        **base,
        "tool_name": "run_shell_command",
        "tool_input": {"command": "Get-ChildItem -Recurse src"},
    })
    assert powershell_read["decision"] == "deny"
    assert "local_ai_artifact" in powershell_read["reason"]
    assert recursive_list["decision"] == "deny"
    assert "local_ai_repo" in recursive_list["reason"]


def test_gemini_before_tool_keeps_native_small_reads_when_hub_is_offline(tmp_path, monkeypatch):
    from local_ai_hub.repo_plan import host_hooks

    monkeypatch.setattr(host_hooks, "_is_hub_online", lambda: False, raising=False)
    source = tmp_path / "small.py"
    source.write_text("value = 1\n", encoding="utf-8")
    result = host_hooks.handle_host_event(tmp_path, "gemini_cli", {
        "hook_event_name": "BeforeTool",
        "session_id": "session-offline",
        "cwd": str(tmp_path),
        "tool_name": "read_file",
        "tool_input": {"file_path": str(source)},
    })
    assert result == {}


def test_gemini_session_start_injects_static_laya_context_without_prompt(tmp_path, monkeypatch):
    from local_ai_hub.repo_plan import host_hooks

    monkeypatch.setattr(host_hooks, "_trigger_repo_warmup", lambda root: None)
    result = host_hooks.handle_host_event(tmp_path, "gemini_cli", {
        "hook_event_name": "SessionStart",
        "session_id": "session-1",
        "cwd": str(tmp_path),
        "prompt": "private-prompt-marker",
        "transcript_path": "private-transcript-marker",
    })

    context = result["hookSpecificOutput"]["additionalContext"]
    assert "Local AI Hub MCP" in context
    assert "Laya" in context
    assert "host permissions" in context
    assert "private-prompt-marker" not in json.dumps(result)
    assert "private-transcript-marker" not in json.dumps(result)


def test_steering_bounds_and_reconciliation_path(tmp_path):
    manager = SteeringManager(tmp_path)
    with pytest.raises(ValueError, match="steering_id"):
        manager.mark_reconciled("../../outside")
    with pytest.raises(ValueError, match="message"):
        manager.capture_steering("s", "x" * 17000)
    for index in range(257):
        path = manager.steering_dir / f"steer_{index:024x}.json"
        path.write_text('{}')
    with pytest.raises(ValueError, match="capacity"):
        manager.capture_steering("s", "bounded")


def test_hook_cli_limits_input_and_emits_only_json(tmp_path, monkeypatch, capsys):
    from local_ai_hub.repo_plan import host_hooks
    monkeypatch.setattr(sys, "stdin", io.StringIO("x" * 65537))
    assert host_hooks.main(["--root", str(tmp_path), "--host", "codex"]) == 0
    assert json.loads(capsys.readouterr().out) == {}


def test_copilot_cli_hook_reads_native_camel_case_payload(tmp_path, monkeypatch, capsys):
    from local_ai_hub.repo_plan import host_hooks
    payload = {
        "sessionId": "s",
        "cwd": str(tmp_path),
        "toolName": "bash",
        "toolArgs": {"command": "python -m pytest"},
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert host_hooks.main(["--host", "copilot", "--event", "preToolUse"]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["permissionDecision"] == "deny"
    assert "Unconstrained bare pytest" in decision["permissionDecisionReason"]


def test_copilot_post_tool_use_checks_native_edit_payload_and_returns_context(tmp_path, monkeypatch):
    from local_ai_hub import shadow_compiler
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    target = tmp_path / "changed.py"
    checked = []
    monkeypatch.setattr(shadow_compiler, "shadow_check", lambda path, root=None: checked.append((path, root)) or {
        "syntax_ok": False,
    })
    event = {
        "hook_event_name": "postToolUse", "sessionId": "s", "cwd": str(tmp_path),
        "toolName": "edit", "toolArgs": {"filePath": str(target)},
    }
    result = handle_host_event(tmp_path, "copilot", event)
    assert checked == [(str(target), tmp_path)]
    assert "syntax error" in result["additionalContext"]
    assert "permissionDecision" not in result


def test_copilot_post_tool_use_cli_accepts_configured_event_identity(tmp_path, monkeypatch, capsys):
    from local_ai_hub.repo_plan import host_hooks

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "sessionId": "s", "cwd": str(tmp_path), "toolName": "read", "toolArgs": {},
    })))
    assert host_hooks.main(["--root", str(tmp_path), "--host", "copilot", "--event", "postToolUse"]) == 0
    assert json.loads(capsys.readouterr().out) == {}


def test_devin_native_pre_tool_hook_blocks_without_approving_clean_calls(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import handle_host_event

    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "exec",
        "tool_input": {"command": "python -m pytest"},
        "session_id": "devin-session",
        "cwd": str(tmp_path),
    }
    blocked = handle_host_event(tmp_path, "devin", event)
    assert blocked["decision"] == "block"
    assert "Unconstrained bare pytest" in blocked["reason"]

    event["tool_input"]["command"] = "python -m pytest tests/test_one.py -q"
    assert handle_host_event(tmp_path, "devin", event) == {}


def test_devin_hook_cli_blocks_unreadable_events(monkeypatch, capsys, tmp_path):
    from local_ai_hub.repo_plan import host_hooks

    monkeypatch.setattr(sys, "stdin", io.StringIO("{"))
    assert host_hooks.main(["--root", str(tmp_path), "--host", "devin", "--event", "PreToolUse"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["decision"] == "block"
    assert "could not evaluate" in result["reason"]


def test_windsurf_hook_blocks_bare_pytest_but_keeps_clean_host_flow(monkeypatch, capsys):
    import local_ai_hub.windsurf_hook as windsurf_hook

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "agent_action_name": "pre_run_command",
        "tool_info": {"command_line": "python -m pytest", "cwd": "."},
    })))
    assert windsurf_hook.main() == 2
    assert "Unconstrained bare pytest" in capsys.readouterr().err

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "agent_action_name": "pre_run_command",
        "tool_info": {"command_line": "python -m pytest tests/test_one.py -q", "cwd": "."},
    })))
    assert windsurf_hook.main() == 0
    assert capsys.readouterr().err == ""


def test_windsurf_pre_mcp_hook_validates_only_local_ai_hub_calls(monkeypatch, capsys):
    import local_ai_hub.windsurf_hook as windsurf_hook

    invalid_hub_call = {
        "agent_action_name": "pre_mcp_tool_use",
        "tool_info": {
            "mcp_server_name": "local-ai",
            "mcp_tool_name": "local_ai_coord",
            "mcp_tool_arguments": {"action": "gpu_reservation_release"},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(invalid_hub_call)))
    assert windsurf_hook.main() == 2
    assert "Invalid Local AI Hub MCP request" in capsys.readouterr().err

    valid_hub_call = {
        "agent_action_name": "pre_mcp_tool_use",
        "tool_info": {
            "mcp_server_name": "local-ai",
            "mcp_tool_name": "local_ai_coord",
            "mcp_tool_arguments": {"action": "leases"},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(valid_hub_call)))
    assert windsurf_hook.main() == 0
    assert capsys.readouterr().err == ""

    external_call = {
        "agent_action_name": "pre_mcp_tool_use",
        "tool_info": {
            "mcp_server_name": "browser-mcp",
            "mcp_tool_name": "navigate",
            "mcp_tool_arguments": {"url": "https://example.test"},
        },
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(external_call)))
    assert windsurf_hook.main() == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("payload_kind", ["malformed", "oversized"])
def test_windsurf_hook_fails_closed_when_payload_cannot_be_evaluated(payload_kind, monkeypatch, capsys):
    import local_ai_hub.windsurf_hook as windsurf_hook

    raw = "{" if payload_kind == "malformed" else " " * (windsurf_hook.MAX_INPUT_BYTES + 1)
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    assert windsurf_hook.main() == 2
    error = capsys.readouterr().err
    assert "could not evaluate" in error or "exceeds its limit" in error


def test_windsurf_post_write_hook_reports_static_check_warning_without_blocking(monkeypatch, capsys, tmp_path):
    import local_ai_hub.windsurf_hook as windsurf_hook

    target = tmp_path / "changed.py"
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "agent_action_name": "post_write_code",
        "tool_info": {"file_path": str(target)},
    })))

    def fake_shadow_check(path):
        assert path == str(target)
        return {"syntax_ok": False, "error": "invalid syntax"}

    monkeypatch.setattr(windsurf_hook, "_shadow_check", fake_shadow_check)
    assert windsurf_hook.main() == 0
    assert "SYNTAX ERROR in changed.py" in capsys.readouterr().err


def test_windsurf_post_write_hook_ignores_unsupported_file_types(monkeypatch, capsys, tmp_path):
    import local_ai_hub.windsurf_hook as windsurf_hook

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "agent_action_name": "post_write_code",
        "tool_info": {"file_path": str(tmp_path / "notes.md")},
    })))
    monkeypatch.setattr(windsurf_hook, "_shadow_check", lambda _path: pytest.fail("unexpected check"))
    assert windsurf_hook.main() == 0
    assert capsys.readouterr().err == ""


def test_no_symlink_config_or_steering_escape(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    try:
        (root / ".codex").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="link"):
        installation(root).preview()
    assert list(outside.iterdir()) == []


def test_superpowers_pinned_manifest_and_install_contract(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import inspect_superpowers
    missing = inspect_superpowers("gemini_cli", tmp_path)
    assert missing["status"] == "missing"
    assert missing["install_argv"][-2:] == ["--ref", "v7.0.1"]
    (tmp_path / "gemini-extension.json").write_text('{"name":"superpowers","version":"7.0.1"}')
    assert inspect_superpowers("gemini_cli", tmp_path)["status"] == "incomplete"
    skill = tmp_path / "skills/using-superpowers/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: using-superpowers\n---\nbootstrap")
    (tmp_path / "GEMINI.md").write_text("Superpowers bootstrap")
    assert inspect_superpowers("gemini_cli", tmp_path)["status"] == "compatible_on_disk"
    (tmp_path / "gemini-extension.json").write_text('{"name":"superpowers","version":"7.0.0"}')
    assert inspect_superpowers("gemini_cli", tmp_path)["status"] == "incompatible"


def test_setup_entrypoint_isolated_preview_apply_rollback(tmp_path):
    from local_ai_hub.process_utils import run_hidden
    setup = Path(__file__).resolve().parents[1] / "tools/setup.py"
    arguments = [sys.executable, str(setup), "--host-project-root", str(tmp_path), "--host-adapter", "codex"]
    preview = run_hidden(arguments, capture_output=True, text=True, timeout=20, max_output_bytes=32768)
    assert preview.returncode == 0, preview.stderr
    data = json.loads(preview.stdout)
    assert data["superpowers"]["status"] == "not_checked"
    assert not (tmp_path / ".local-ai-hub").exists()
    applied = run_hidden(arguments + ["--host-action", "apply", "--host-preview-revision", data["revision"]],
                         capture_output=True, text=True, timeout=20, max_output_bytes=32768)
    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["changed"]
    rollback = run_hidden(arguments + ["--host-action", "rollback"], capture_output=True, text=True,
                          timeout=20, max_output_bytes=32768)
    assert rollback.returncode == 0, rollback.stderr
    assert json.loads(rollback.stdout)["changed"]
    assert not (tmp_path / ".codex/hooks.json").exists()


def test_confirm_reconciliation_requires_scoped_actual_revisions(tmp_path):
    manager = SteeringManager(tmp_path)
    steering = manager.capture_steering("session-a", "Revise acceptance", task_id="task-a")["steering_id"]
    arguments = {"task_id": "task-a", "session_id": "session-a", "contract_revision": 2,
                 "plan_revision": "actual-plan-3", "spec_revision": "actual-spec-sha"}
    with pytest.raises(ValueError, match="scope"):
        manager.confirm_reconciled(steering, **{**arguments, "task_id": "task-b"})
    with pytest.raises(ValueError, match="contract_revision"):
        manager.confirm_reconciled(steering, **{**arguments, "contract_revision": ""})
    assert manager.confirm_reconciled(steering, **arguments)
    assert manager.list_pending_steering() == []


def test_dependency_install_explicit_and_bounded(tmp_path, monkeypatch):
    from local_ai_hub.repo_plan import host_hooks
    from local_ai_hub import process_utils
    package = tmp_path / "installed"
    calls = []

    def fake_run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        package.mkdir()
        (package / "gemini-extension.json").write_text('{"name":"superpowers","version":"7.0.1"}')
        skill = package / "skills/using-superpowers/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("bootstrap")
        (package / "GEMINI.md").write_text("bootstrap")
        import subprocess
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(process_utils, "run_hidden", fake_run)
    arguments = dict(repo_root=tmp_path, package_root=package, executable=str(Path(sys.executable).resolve()))
    with pytest.raises(ValueError, match="authorization"):
        host_hooks.install_superpowers("gemini_cli", **arguments)
    waiting = host_hooks.install_superpowers("gemini_cli", **arguments, operator_authorized=True)
    assert waiting["requires_consent"] and not calls
    result = host_hooks.install_superpowers("gemini_cli", **arguments, operator_authorized=True, consent=True)
    assert result["success"] and result["dependency"]["compatible"]
    assert calls[0][0][-3:] == ["--ref", "v7.0.1", "--consent"]
    assert calls[0][1]["timeout"] == 60
    assert calls[0][1]["max_output_bytes"] == 65536
    assert calls[0][1]["shell"] is False
    assert host_hooks.install_superpowers("gemini_cli", **arguments, operator_authorized=True, consent=True)["changed"] is False
    assert len(calls) == 1
    with pytest.raises(ValueError, match="Codex"):
        host_hooks.install_superpowers("codex", **arguments, operator_authorized=True, consent=True)


def test_dependency_install_refuses_incompatible_customization(tmp_path):
    from local_ai_hub.repo_plan.host_hooks import install_superpowers
    (tmp_path / "gemini-extension.json").write_text('{"name":"superpowers","version":"custom"}')
    with pytest.raises(ValueError, match="existing"):
        install_superpowers("gemini_cli", repo_root=tmp_path, package_root=tmp_path,
                            executable=sys.executable, operator_authorized=True, consent=True)
