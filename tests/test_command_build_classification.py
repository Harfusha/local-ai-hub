from __future__ import annotations

import pytest

from local_ai_hub.command_policy import (
    contains_user_whitelisted_tool,
    normalize_user_whitelisted_tools,
)
from local_ai_hub.command_build import (
    _build_classification,
    _mutating_classification,
    _unknown_classification,
)
from local_ai_hub.command_validation import is_validation_executable
from local_ai_hub.command_broker import CommandBroker


def _broker(tmp_path) -> CommandBroker:
    return CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {"enabled": True, "allow_mutating": True},
        },
        artifacts=None,
        repo_state=None,
    )


@pytest.mark.parametrize(
    ("command", "expected_class", "replay_safe"),
    [
        ("dotnet --info", "read", None),
        ("dotnet test", "validation", True),
        ("dotnet format --verify-no-changes", "validation", True),
        ("dotnet format", "mutating", None),
        ("dotnet build", "build", None),
        ("npm run lint", "validation", True),
        ("npm install", "mutating", None),
        ("composer validate", "validation", True),
        ("composer install", "mutating", None),
        ("make test", "validation", True),
        ("make build", "build", None),
        ("make deploy", "mutating", None),
        ("cargo fmt --check", "validation", True),
        ("cargo fmt", "mutating", None),
        ("cargo build", "build", None),
        ("go test ./...", "validation", True),
        ("mvn package", "build", None),
        ("gradle build", "build", None),
        ("cmake -S . -B build", "build", None),
        ("ctest --test-dir build", "validation", True),
    ],
)
def test_package_and_build_tool_classification_contract(
    tmp_path, command: str, expected_class: str, replay_safe: bool | None
) -> None:
    result = _broker(tmp_path)._classify_single(command)

    assert result["class"] == expected_class
    if replay_safe is None:
        assert "replay_safe" not in result
    else:
        assert result["replay_safe"] is replay_safe


@pytest.mark.parametrize("command", ["my-pytest-wrapper --run", "wrapper-phpunit --test"])
def test_validator_name_lookalikes_are_not_allowed_as_validation_tools(tmp_path, command: str) -> None:
    result = _broker(tmp_path)._classify_single(command)

    assert result["class"] == "unknown"
    assert result["allowed"] is False


def test_versioned_validator_executable_remains_supported(tmp_path) -> None:
    result = _broker(tmp_path)._classify_single("pytest-8.4 --version")

    assert result["class"] == "validation"
    assert result["allowed"] is True


@pytest.mark.parametrize(
    ("executable", "expected"),
    [
        ("pytest", True),
        ("pytest-8.4", True),
        ("phpunit-10.2.1", True),
        ("my-pytest-wrapper", False),
        ("wrapper-phpunit", False),
        ("pytest-nightly", False),
        ("pytest-8.4-rc1", False),
    ],
)
def test_validator_executable_match_is_exact_or_numeric_versioned(
    executable: str, expected: bool
) -> None:
    assert is_validation_executable(executable, {"pytest", "phpunit"}) is expected


@pytest.mark.parametrize(
    ("text", "extra_allowed", "expected"),
    [
        ("eslint .", {"eslint"}, True),
        ("ESLINT .", {"eslint"}, True),
        ("eslinting .", {"eslint"}, False),
        ("myeslint .", {"eslint"}, False),
        ("eslint .", set(), False),
    ],
)
def test_user_whitelisted_tool_match_preserves_word_boundaries(
    text: str, extra_allowed: set[str], expected: bool
) -> None:
    assert contains_user_whitelisted_tool(text, extra_allowed) is expected


def test_normalize_user_whitelisted_tools_trims_deduplicates_and_drops_empty() -> None:
    assert normalize_user_whitelisted_tools([" ESLint ", "", "eslint", " PYTEST "]) == {
        "eslint",
        "pytest",
    }


def test_user_whitelisted_tool_occurrence_disables_replay_and_cache(tmp_path) -> None:
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {
                "enabled": True,
                "allow_mutating": True,
                "extra_allowed_tools": ["eslint"],
            },
        },
        artifacts=None,
        repo_state=None,
    )

    result = broker.classify("pytest -k eslint")

    assert result["class"] == "validation"
    assert result["cacheable"] is False
    assert result["replay_safe"] is False


def test_powershell_whitelist_match_requires_word_boundary(tmp_path) -> None:
    broker = CommandBroker(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "commands": {
                "enabled": True,
                "allow_mutating": True,
                "extra_allowed_tools": ["eslint"],
            },
        },
        artifacts=None,
        repo_state=None,
    )

    result = broker.classify("Write-Output eslinting")

    assert result["class"] == "unknown"
    assert result["allowed"] is False


@pytest.mark.parametrize(
    ("command", "expected_class"),
    [
        ("php vendor/bin/phpunit --version", "validation"),
        ("php.exe vendor/bin/phpunit --version", "validation"),
        ("php vendor/bin/my-phpunit-wrapper --version", "unknown"),
        ("php vendor/bin/phpstan-2.1 --version", "validation"),
    ],
)
def test_php_validator_target_requires_exact_or_numeric_versioned_name(
    tmp_path, command: str, expected_class: str
) -> None:
    result = _broker(tmp_path)._classify_single(command)

    assert result["class"] == expected_class


@pytest.mark.parametrize(
    ("command", "expected_class", "replay_safe"),
    [
        ("black --check .", "validation", True),
        ("isort --diff .", "validation", True),
        ("black .", "mutating", None),
        ("isort .", "mutating", None),
    ],
)
def test_formatter_classification_preserves_check_and_mutation_modes(
    tmp_path, command: str, expected_class: str, replay_safe: bool | None
) -> None:
    result = _broker(tmp_path)._classify_single(command)

    assert result["class"] == expected_class
    if replay_safe is None:
        assert "replay_safe" not in result
    else:
        assert result["replay_safe"] is replay_safe


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        ("pytest --version", "pytest validation tool"),
        ("php vendor/bin/phpunit --version", "PHP validation tool"),
    ],
)
def test_validator_classification_result_shape(tmp_path, command: str, reason: str) -> None:
    result = _broker(tmp_path)._classify_single(command)

    assert result == {
        "class": "validation",
        "cacheable": True,
        "allowed": True,
        "replay_safe": True,
        "reason": reason,
    }


def test_extracted_build_classification_respects_build_gate() -> None:
    assert _build_classification({}, "cargo build") == {
        "class": "build",
        "cacheable": True,
        "allowed": True,
        "reason": "cargo build",
    }
    assert _build_classification({"allow_build": False}, "dotnet build")["allowed"] is False


def test_extracted_mutating_classification_respects_mutation_gate() -> None:
    assert _mutating_classification({}, "composer install") == {
        "class": "mutating",
        "cacheable": False,
        "allowed": False,
        "reason": "composer install",
    }
    assert _mutating_classification(
        {"allow_mutating": True}, "cargo fmt changes source"
    )["allowed"] is True


def test_extracted_unknown_classification_respects_unknown_gate() -> None:
    assert _unknown_classification({}, "composer custom") == {
        "class": "unknown",
        "cacheable": False,
        "allowed": False,
        "reason": "composer custom",
    }
    assert _unknown_classification(
        {"allow_unknown": True}, "custom build command"
    )["allowed"] is True
