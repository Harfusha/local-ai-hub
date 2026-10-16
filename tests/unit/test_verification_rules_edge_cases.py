from __future__ import annotations

from types import SimpleNamespace

import pytest

from local_ai_hub.verification_rules import (
    CompletionGateError,
    _canonical_project_root,
    project_command_environment_sha256,
)


@pytest.mark.parametrize("root", [None, "", "   "])
def test_canonical_project_root_does_not_resolve_empty_values_to_cwd(root: object) -> None:
    assert _canonical_project_root(root) == ""  # type: ignore[arg-type]


@pytest.mark.parametrize("criterion", ["", "   "])
def test_project_command_environment_rejects_empty_criterion(criterion: str) -> None:
    with pytest.raises(CompletionGateError, match="criterion must not be empty"):
        project_command_environment_sha256(SimpleNamespace(commands={}), criterion)


def test_project_command_environment_hashes_mapping_based_command_env() -> None:
    settings = SimpleNamespace(
        commands={
            "test": {"env": {"MODE": "test"}},
            "lint": {"env": {"MODE": "lint"}},
        },
        env={},
        env_references={},
    )

    test_digest = project_command_environment_sha256(settings, "test")
    lint_digest = project_command_environment_sha256(settings, "lint")
    assert len(test_digest) == len(lint_digest) == 64
    assert test_digest != lint_digest
