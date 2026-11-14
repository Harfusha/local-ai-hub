import pytest

from local_ai_hub.command_policy import (
    classify_command_sequence,
    classify_dangerous_or_whitelisted_tool,
    classify_pipeline_filter,
    classify_user_whitelisted_tool,
    command_executable_identity,
    is_interactive_command_prompt,
    is_interactive_output_prompt,
)
from local_ai_hub.command_validation import classify_php_validation_script


def test_interactive_output_prompt_keeps_tail_limited_patterns():
    assert is_interactive_output_prompt("Do you want to continue [y/N]? ")
    assert is_interactive_output_prompt("Enter password for root: ")
    assert is_interactive_output_prompt("x" * 400 + "Press any key")
    assert not is_interactive_output_prompt("[y/N]" + "x" * 400)
    assert not is_interactive_output_prompt("")


def test_interactive_command_prompt_keeps_full_text_patterns():
    assert is_interactive_command_prompt("Enter passphrase to continue")
    assert is_interactive_command_prompt("Are you sure? " + "x" * 400)
    assert not is_interactive_command_prompt("Running test suite 100% complete")
    assert not is_interactive_command_prompt("")


def test_user_whitelisted_tool_is_validation_but_not_replay_safe():
    assert classify_user_whitelisted_tool("custom-tool", {"custom-tool"}) == {
        "class": "validation",
        "cacheable": True,
        "allowed": True,
        "replay_safe": False,
        "reason": "user-whitelisted tool: custom-tool",
    }


def test_user_whitelist_does_not_allow_shell_interpreters():
    for executable in ("sh", "bash", "cmd", "powershell", "pwsh"):
        assert classify_user_whitelisted_tool(executable, {executable}) is None


def test_non_whitelisted_tool_keeps_normal_classification():
    assert classify_user_whitelisted_tool("unknown-tool", {"custom-tool"}) is None


def test_dangerous_executable_stays_blocked_when_user_whitelisted():
    assert classify_dangerous_or_whitelisted_tool("rm", {"rm"}) == {
        "class": "dangerous",
        "cacheable": False,
        "allowed": False,
        "reason": "dangerous executable",
    }


def test_safe_user_whitelisted_tool_keeps_non_replay_safe_policy():
    assert classify_dangerous_or_whitelisted_tool("custom-tool", {"custom-tool"}) == {
        "class": "validation",
        "cacheable": True,
        "allowed": True,
        "replay_safe": False,
        "reason": "user-whitelisted tool: custom-tool",
    }


def test_pipeline_filter_allows_read_filter_and_read_only_tools():
    assert classify_pipeline_filter(["rg", "-n"], {"rg"}, set()) is None
    assert classify_pipeline_filter(["cat"], set(), {"cat"}) is None


def test_pipeline_filter_rejects_unclassified_tool_with_normalized_identity():
    assert classify_pipeline_filter(
        [r"C:\\Tools\\custom.EXE"], {"rg"}, {"cat"}
    ) == {
        "class": "unknown",
        "cacheable": False,
        "allowed": False,
        "reason": "pipeline filter custom not allowed",
    }


def test_pipeline_filter_skips_empty_tokens():
    assert classify_pipeline_filter([], {"rg"}, {"cat"}) is None


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        ([r'"C:\Program Files\Python\PYTHON3.11.EXE"', "-M", "PYTEST"], ("python3.11", ["-m", "pytest"])),
        (["/usr/bin/GIT.EXE", "STATUS"], ("git", ["status"])),
        ([r"C:\Tools\CUSTOM.PS1", "--Version"], ("custom", ["--version"])),
    ],
)
def test_command_executable_identity_normalizes_path_suffix_and_arguments(tokens, expected):
    assert command_executable_identity(tokens) == expected


@pytest.mark.parametrize(
    ("script_path", "config", "allowed"),
    [
        ("vendor/bin/phpunit", {}, True),
        (r"vendor\\bin\\phpstan-1.12.3", {"allow_validation": False}, False),
    ],
)
def test_php_validation_script_uses_basename_and_validation_policy(script_path, config, allowed):
    assert classify_php_validation_script(script_path, config) == {
        "class": "validation",
        "cacheable": True,
        "allowed": allowed,
        "replay_safe": True,
        "reason": "PHP validation tool",
    }


def test_php_non_validator_script_is_unclassified():
    assert classify_php_validation_script("scripts/check.php", {}) is None


def test_compound_command_prioritizes_dangerous_before_blocked():
    blocked = {"class": "read", "allowed": False, "reason": "blocked read"}
    dangerous = {"class": "dangerous", "allowed": False, "reason": "dangerous command"}

    assert classify_command_sequence([blocked, dangerous], {}) is dangerous


def test_compound_command_returns_first_blocked_result():
    first = {"class": "build", "allowed": False, "reason": "first blocked"}
    second = {"class": "validation", "allowed": False, "reason": "second blocked"}

    assert classify_command_sequence([first, second], {}) is first


def test_compound_command_uses_class_priority_and_configured_permission():
    result = classify_command_sequence(
        [
            {"class": "read", "allowed": True},
            {"class": "validation", "allowed": True, "replay_safe": True},
            {"class": "build", "allowed": True},
        ],
        {"allow_build": False},
    )

    assert result == {
        "class": "build",
        "cacheable": False,
        "allowed": False,
        "replay_safe": False,
        "reason": "compound sequence (build)",
    }


def test_compound_validation_replay_safety_and_empty_fallback():
    result = classify_command_sequence(
        [
            {"class": "read", "allowed": True},
            {"class": "validation", "allowed": True, "replay_safe": True},
        ],
        {},
    )
    assert result["class"] == "validation"
    assert result["replay_safe"] is True

    assert classify_command_sequence([], {}) == {
        "class": "read",
        "cacheable": False,
        "allowed": True,
        "reason": "compound sequence",
    }
