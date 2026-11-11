from __future__ import annotations

import pytest

from local_ai_hub.commands import CommandBroker


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
