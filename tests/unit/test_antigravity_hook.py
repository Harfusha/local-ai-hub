import tempfile
from pathlib import Path
import pytest
import local_ai_hub.antigravity_hook as antigravity_hook

from local_ai_hub.antigravity_hook import (
    handle_pre_tool_use,
    handle_post_tool_use,
)


@pytest.fixture(autouse=True)
def hub_offline_by_default(monkeypatch):
    monkeypatch.setattr(antigravity_hook, "_is_hub_online", lambda: False)


def test_antigravity_hook_read_file_bounds():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        huge_file = tmp_path / "huge.py"
        huge_file.write_text("\n".join(f"x_{i} = {i}" for i in range(300)), encoding="utf-8")

        # Full read above the shared 80-line budget is automatically clamped to 1..80
        payload_full = {
            "toolCall": {
                "name": "read_file",
                "args": {"Path": str(huge_file)},
            }
        }
        res = handle_pre_tool_use(payload_full)
        assert res["decision"] == "allow"
        assert res.get("overwrite", {}).get("StartLine") == 1
        assert res.get("overwrite", {}).get("EndLine") == 80

        # A bounded 80-line slice is allowed; a wider requested slice is automatically clamped.
        payload_slice = {
            "toolCall": {
                "name": "read_file",
                "args": {
                    "Path": str(huge_file),
                    "StartLine": 1,
                    "EndLine": 80,
                },
            }
        }
        assert handle_pre_tool_use(payload_slice)["decision"] == "allow"
        payload_slice["toolCall"]["args"]["EndLine"] = 81
        res_wide = handle_pre_tool_use(payload_slice)
        assert res_wide["decision"] == "allow"
        assert res_wide.get("overwrite", {}).get("EndLine") == 80


def test_antigravity_hook_routes_source_reads_through_hub_when_online(tmp_path, monkeypatch):
    source_file = tmp_path / "module.py"
    source_file.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr(antigravity_hook, "_is_hub_online", lambda: True)

    result = handle_pre_tool_use({"toolCall": {
        "name": "read_file", "args": {"Path": str(source_file)},
    }})

    assert result["decision"] == "deny"
    assert "local ai hub" in result["reason"].casefold()
    assert "local_ai_artifact" in result["reason"]


def test_antigravity_hook_routes_native_search_through_hub_when_online(monkeypatch):
    monkeypatch.setattr(antigravity_hook, "_is_hub_online", lambda: True)

    result = handle_pre_tool_use({"toolCall": {
        "name": "run_command", "args": {"CommandLine": "rg -n -m 5 TODO src"},
    }})

    assert result["decision"] == "deny"
    assert "Local AI Hub" in result["reason"]
    assert "local_ai_repo" in result["reason"]


def test_antigravity_hook_keeps_native_source_read_fallback_when_hub_offline(tmp_path, monkeypatch):
    source_file = tmp_path / "module.py"
    source_file.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr(antigravity_hook, "_is_hub_online", lambda: False)

    result = handle_pre_tool_use({"toolCall": {
        "name": "read_file", "args": {"Path": str(source_file)},
    }})

    assert result["decision"] == "allow"


def test_antigravity_hook_run_command_guards():
    # Bare pytest across all tests denied
    payload_bare_pytest = {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "python -m pytest"},
        }
    }
    res_pytest = handle_pre_tool_use(payload_bare_pytest)
    assert res_pytest["decision"] == "deny"
    assert "Unconstrained bare pytest" in res_pytest["reason"]

    # Targeted pytest allowed
    payload_targeted = {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "python -m pytest tests/unit/test_foo.py"},
        }
    }
    assert handle_pre_tool_use(payload_targeted)["decision"] == "allow"

    # Broad recursive grep denied
    payload_grep = {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "grep -rn 'something' ."},
        }
    }
    assert handle_pre_tool_use(payload_grep)["decision"] == "deny"

    # Context-saving overwrite for git status
    payload_git = {
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "git status"},
        }
    }
    res_git = handle_pre_tool_use(payload_git)
    assert res_git["decision"] == "allow"
    assert res_git.get("overwrite", {}).get("CommandLine") == "git status -s"


def test_antigravity_hook_post_tool_shadow_compile():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Valid file
        good_file = tmp_path / "valid.py"
        good_file.write_text("def ok(): return 1\n", encoding="utf-8")
        payload_good = {
            "toolCall": {
                "name": "edit_file",
                "args": {"Path": str(good_file)},
            }
        }
        assert handle_post_tool_use(payload_good) == {}

        # Syntax error file
        bad_file = tmp_path / "invalid.py"
        bad_file.write_text("def broken(:\n", encoding="utf-8")
        payload_bad = {
            "toolCall": {
                "name": "edit_file",
                "args": {"Path": str(bad_file)},
            }
        }
        res_bad = handle_post_tool_use(payload_bad)
        assert res_bad == {}

        # Dangerous pattern file (bare except: pass)
        danger_file = tmp_path / "danger.py"
        danger_file.write_text("def silent():\n    try:\n        pass\n    except:\n        pass\n", encoding="utf-8")
        payload_danger = {
            "toolCall": {
                "name": "edit_file",
                "args": {"Path": str(danger_file)},
            }
        }
        res_danger = handle_post_tool_use(payload_danger)
        assert res_danger == {}


def test_antigravity_post_tool_use_stdout_matches_empty_object_contract(monkeypatch, capsys):
    import io
    import json

    payload = {"toolCall": {"name": "edit_file", "args": {}}}
    monkeypatch.setattr(antigravity_hook.sys, "stdin", io.StringIO(json.dumps(payload)))

    assert antigravity_hook.main(["PostToolUse"]) == 0
    assert json.loads(capsys.readouterr().out) == {}


@pytest.mark.parametrize(
    ("tool_name", "target_arg"),
    [
        ("write_to_file", "TargetFile"),
        ("replace_file_content", "TargetFile"),
        ("multi_replace_file_content", "TargetFile"),
    ],
)
def test_post_tool_use_resolves_antigravity_native_file_tool_paths(
    tmp_path, monkeypatch, tool_name, target_arg,
):
    from local_ai_hub import shadow_compiler

    target = tmp_path / "edited.json"
    target.write_text("{}", encoding="utf-8")
    checked = []

    def shadow_check(path):
        checked.append(path)
        return {"syntax_ok": True, "violations": []}

    monkeypatch.setattr(shadow_compiler, "shadow_check", shadow_check)
    result = handle_post_tool_use({
        "toolCall": {"name": tool_name, "args": {target_arg: str(target)}}
    })

    assert result == {}
    assert checked == [target]


def test_antigravity_hook_session_start_dynamic_task_context(monkeypatch):
    monkeypatch.setattr(antigravity_hook, "_is_hub_online", lambda: True)
    monkeypatch.setattr(
        antigravity_hook,
        "_fetch_active_task_context",
        lambda root: "Active Local AI Hub task: task_test (active). Next action: Verify tests.",
    )
    warmup_calls = []
    monkeypatch.setattr(antigravity_hook, "_trigger_repo_warmup", lambda root: warmup_calls.append(root))

    res = antigravity_hook.handle_session_start({"workspacePaths": ["C:\\test_repo"]})
    assert len(res["injectSteps"]) == 1
    sys_msg = res["injectSteps"][0]["systemMessage"]["systemMessage"]
    assert "Active Local AI Hub task: task_test (active)" in sys_msg
    assert "local-ai-orchestrator" in sys_msg
    assert warmup_calls == ["C:\\test_repo"]


def test_antigravity_hook_pre_invocation_review_notice(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_AI_STATE_DIR", str(tmp_path))
    conv_id = "conv_test_123"

    # Initially no pending edits
    assert antigravity_hook.handle_pre_invocation({"conversationId": conv_id}) == {}

    # Record a file edit via handle_post_tool_use
    target_file = tmp_path / "code.py"
    target_file.write_text("x = 1\n", encoding="utf-8")
    antigravity_hook.handle_post_tool_use({
        "conversationId": conv_id,
        "toolCall": {"name": "edit_file", "args": {"Path": str(target_file)}},
    })

    # PreInvocation should now inject the review notice
    res_inv = antigravity_hook.handle_pre_invocation({"conversationId": conv_id})
    assert len(res_inv["injectSteps"]) == 1
    assert "Code modifications detected in this session" in res_inv["injectSteps"][0]["systemMessage"]["systemMessage"]

    # Calling PreInvocation again in the same state should not re-spam (review_notified is True)
    assert antigravity_hook.handle_pre_invocation({"conversationId": conv_id}) == {}

    # Guard on git commit when unreviewed edits are pending
    res_commit = antigravity_hook.handle_pre_tool_use({
        "conversationId": conv_id,
        "toolCall": {"name": "run_command", "args": {"CommandLine": "git commit -m 'test'"}},
    })
    assert res_commit["decision"] == "deny"
    assert "Unreviewed code modifications" in res_commit["reason"]

    # When the agent calls local_ai_task:review, the pending review flag is cleared
    antigravity_hook.handle_pre_tool_use({
        "conversationId": conv_id,
        "toolCall": {
            "name": "call_mcp_tool",
            "args": {
                "ServerName": "local-ai-hub_local-ai",
                "ToolName": "local_ai_task",
                "Arguments": {"action": "review", "code": "diff"},
            },
        },
    })

    # Now git commit is allowed
    res_commit_after = antigravity_hook.handle_pre_tool_use({
        "conversationId": conv_id,
        "toolCall": {"name": "run_command", "args": {"CommandLine": "git commit -m 'test'"}},
    })
    assert res_commit_after["decision"] == "allow"


def test_antigravity_hook_invoke_subagent_prompt_steering():
    # Prompt without Hub policy is enriched with subagent routing contract
    payload = {
        "toolCall": {
            "name": "invoke_subagent",
            "args": {
                "Role": "Research Assistant",
                "Prompt": "Investigate authentication flow in repo.",
            },
        }
    }
    res = antigravity_hook.handle_pre_tool_use(payload)
    assert res["decision"] == "allow"
    assert "overwrite" in res
    modified_prompt = res["overwrite"]["Prompt"]
    assert "Investigate authentication flow in repo." in modified_prompt
    assert "Local AI Hub Subagent Policy" in modified_prompt
    assert "local_ai_repo" in modified_prompt
    assert "local_ai_artifact" in modified_prompt

    # Prompt that already references Local AI Hub is left unchanged
    payload_existing = {
        "toolCall": {
            "name": "invoke_subagent",
            "args": {
                "Role": "Researcher",
                "Prompt": "Use Local AI Hub tools for research.",
            },
        }
    }
    res_existing = antigravity_hook.handle_pre_tool_use(payload_existing)
    assert res_existing["decision"] == "allow"
    assert "overwrite" not in res_existing


def test_antigravity_hook_post_invocation_and_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_AI_STATE_DIR", str(tmp_path))
    conv_id = "conv_post_inv"

    # PostInvocation with no edits returns empty
    assert antigravity_hook.handle_post_invocation({"conversationId": conv_id}) == {}

    # Record edit
    target_file = tmp_path / "foo.py"
    target_file.write_text("a = 1", encoding="utf-8")
    antigravity_hook.handle_post_tool_use({
        "conversationId": conv_id,
        "toolCall": {"name": "write_file", "args": {"Path": str(target_file)}},
    })

    # PostInvocation now advises verification
    res_post = antigravity_hook.handle_post_invocation({"conversationId": conv_id})
    assert len(res_post["injectSteps"]) == 1
    assert "require verification" in res_post["injectSteps"][0]["systemMessage"]["systemMessage"]

    # Second call does not duplicate
    assert antigravity_hook.handle_post_invocation({"conversationId": conv_id}) == {}

    # Stop hook returns empty dict
    assert antigravity_hook.handle_stop({"conversationId": conv_id}) == {}


def test_antigravity_hook_powershell_unconstrained_searches():
    # Get-ChildItem -Recurse denied
    res_gci = antigravity_hook.handle_pre_tool_use({
        "toolCall": {"name": "run_command", "args": {"CommandLine": "Get-ChildItem -Recurse"}}
    })
    assert res_gci["decision"] == "deny"
    assert "Unconstrained repository search" in res_gci["reason"]

    # Select-String -Pattern denied
    res_sls = antigravity_hook.handle_pre_tool_use({
        "toolCall": {"name": "run_command", "args": {"CommandLine": "Select-String -Pattern 'TODO' -Path src/*"}}
    })
    assert res_sls["decision"] == "deny"

    # fd unconstrained denied
    res_fd = antigravity_hook.handle_pre_tool_use({
        "toolCall": {"name": "run_command", "args": {"CommandLine": "fd 'needle'"}}
    })
    assert res_fd["decision"] == "deny"


def test_antigravity_hook_test_verification_clears_commit_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_AI_STATE_DIR", str(tmp_path))
    conv_id = "conv_test_clears"

    # Record edit
    target_file = tmp_path / "mod.py"
    target_file.write_text("b = 2", encoding="utf-8")
    antigravity_hook.handle_post_tool_use({
        "conversationId": conv_id,
        "toolCall": {"name": "write_file", "args": {"Path": str(target_file)}},
    })

    # git commit is initially blocked by pending edit
    res_commit = antigravity_hook.handle_pre_tool_use({
        "conversationId": conv_id,
        "toolCall": {"name": "run_command", "args": {"CommandLine": "git commit -m 'feat'"}},
    })
    assert res_commit["decision"] == "deny"

    # Passing test command clears the commit guard
    antigravity_hook.handle_post_tool_use({
        "conversationId": conv_id,
        "toolCall": {
            "name": "run_command",
            "args": {"CommandLine": "python -m pytest tests/unit/test_foo.py"},
        },
        "output": "1 passed in 0.05s",
    })

    # Now git commit is allowed
    res_commit_after = antigravity_hook.handle_pre_tool_use({
        "conversationId": conv_id,
        "toolCall": {"name": "run_command", "args": {"CommandLine": "git commit -m 'feat'"}},
    })
    assert res_commit_after["decision"] == "allow"
