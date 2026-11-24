import tempfile
from pathlib import Path
import pytest

from local_ai_hub.antigravity_hook import (
    handle_pre_tool_use,
    handle_post_tool_use,
)


def test_antigravity_hook_read_file_bounds():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        huge_file = tmp_path / "huge.py"
        huge_file.write_text("\n".join(f"x_{i} = {i}" for i in range(300)), encoding="utf-8")

        # Full read above the shared 80-line budget is denied before execution.
        payload_full = {
            "toolCall": {
                "name": "read_file",
                "args": {"Path": str(huge_file)},
            }
        }
        res = handle_pre_tool_use(payload_full)
        assert res["decision"] == "deny"
        assert "lines > 80" in res["reason"]

        # A bounded 80-line slice is allowed; a wider requested slice is denied.
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
        assert handle_pre_tool_use(payload_slice)["decision"] == "deny"


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
        assert handle_post_tool_use(payload_good)["decision"] == "allow"

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
        assert res_bad["decision"] == "warn"
        assert "SYNTAX ERROR" in res_bad["warning"]

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
        assert res_danger["decision"] == "warn"
        assert "INVARIANT GATE" in res_danger["warning"]
