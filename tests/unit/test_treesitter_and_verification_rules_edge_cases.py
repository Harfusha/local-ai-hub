from __future__ import annotations

import pytest

from local_ai_hub.agent_tasks import CompletionGateError
from local_ai_hub.treesitter_parser import (
    is_supported_language,
    is_treesitter_available,
    language_for_path,
    parse_treesitter,
    parse_treesitter_with_status,
    supported_extensions,
    supported_languages,
)
from local_ai_hub.verification_rules import (
    _canonical_project_root,
    is_valid_project_root,
    is_valid_task_id,
    project_command_environment_sha256,
)


def test_treesitter_language_availability_and_discovery() -> None:
    # Non-string or null-byte lang inputs must not raise AttributeError
    assert is_treesitter_available(None) is False  # type: ignore[arg-type]
    assert is_treesitter_available(12345) is False  # type: ignore[arg-type]
    assert is_treesitter_available("") is False
    assert is_treesitter_available("   ") is False

    # Supported language and extensions discovery
    langs = supported_languages()
    assert isinstance(langs, list)
    assert "python" in langs
    assert "typescript" in langs
    assert "csharp" in langs

    assert is_supported_language("py") is True
    assert is_supported_language("python") is True
    assert is_supported_language("rust") is True
    assert is_supported_language("unknown_lang_xyz") is False
    assert is_supported_language(None) is False  # type: ignore[arg-type]
    assert is_supported_language(123) is False  # type: ignore[arg-type]

    exts = supported_extensions()
    assert isinstance(exts, list)
    assert ".py" in exts
    assert ".ts" in exts
    assert ".cs" in exts


def test_treesitter_language_for_path_edge_cases() -> None:
    # Invalid path types or null bytes must fall back safely
    assert language_for_path(None, "fallback") == "fallback"  # type: ignore[arg-type]
    assert language_for_path("", "fallback") == "fallback"
    assert language_for_path("code\x00.py", "fallback") in ("fallback", "python")
    assert language_for_path("src/app.py", "fallback") == "fallback"  # no settings overrides -> fallback


def test_treesitter_parse_invalid_inputs() -> None:
    # None or non-string text
    res = parse_treesitter_with_status(None, "python")  # type: ignore[arg-type]
    assert res["status"] == "empty"
    assert res["result"] == ([], [], [])

    # None or invalid language
    res2 = parse_treesitter_with_status("def foo(): pass", None)  # type: ignore[arg-type]
    assert res2["status"] == "unavailable"
    assert res2["fallback_reason"] == "invalid_language"

    res3 = parse_treesitter_with_status("def foo(): pass", "\x00   ")
    assert res3["status"] == "unavailable"

    # Tuple API wrapper
    assert parse_treesitter(None, "python") == ([], [], [])  # type: ignore[arg-type]
    assert parse_treesitter("def foo(): pass", None) is None  # type: ignore[arg-type]


def test_verification_rules_canonical_project_root() -> None:
    # None or invalid types
    assert _canonical_project_root(None) == ""  # type: ignore[arg-type]
    assert _canonical_project_root(123) == ""  # type: ignore[arg-type]
    assert _canonical_project_root("") == ""

    # Null bytes must not raise ValueError
    res = _canonical_project_root("C:\\test\x00\\repo")
    assert "\x00" not in res


def test_verification_rules_project_command_env_sha256_edge_cases() -> None:
    # None settings or invalid criterion
    with pytest.raises(CompletionGateError):
        project_command_environment_sha256(None, "test")

    with pytest.raises(CompletionGateError):
        project_command_environment_sha256(object(), None)  # type: ignore[arg-type]

    with pytest.raises(CompletionGateError):
        project_command_environment_sha256(object(), "test\x00")

    with pytest.raises(CompletionGateError):
        project_command_environment_sha256(object(), "")


def test_verification_rules_validation_helpers() -> None:
    assert is_valid_project_root("C:\\valid\\path") is True
    assert is_valid_project_root("") is False
    assert is_valid_project_root(None) is False
    assert is_valid_project_root("C:\\bad\x00\\path") is False

    assert is_valid_task_id("task-123_abc") is True
    assert is_valid_task_id("") is False
    assert is_valid_task_id("   ") is False
    assert is_valid_task_id(None) is False
    assert is_valid_task_id(12345) is False
    assert is_valid_task_id("task\x00bad") is False
