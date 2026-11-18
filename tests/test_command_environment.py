from types import SimpleNamespace

import pytest

from local_ai_hub.command_environment import (
    resolve_project_environment,
    is_unsafe_project_command_env_key,
    is_valid_project_command_env_key,
)


@pytest.mark.parametrize(
    "key",
    [
        "PATH",
        "path",
        "GIT_CONFIG_COUNT",
        "git_config_global",
        "LD_PRELOAD",
        "DYLD_INSERT_LIBRARIES",
        "COMSPEC",
    ],
)
def test_project_command_environment_classifier_rejects_unsafe_keys(key: str) -> None:
    assert is_unsafe_project_command_env_key(key) is True


@pytest.mark.parametrize("key", ["APP_MODE", "CI", "MY_GIT_CONFIG_HINT"])
def test_project_command_environment_classifier_allows_other_keys(key: str) -> None:
    assert is_unsafe_project_command_env_key(key) is False


@pytest.mark.parametrize(
    ("key", "valid"),
    [
        ("APP_MODE", True),
        ("_CACHE2", True),
        ("PATH", False),
        ("GIT_CONFIG_COUNT", False),
        ("HAS-DASH", False),
        ("", False),
        (None, False),
    ],
)
def test_project_command_environment_key_validation(key: object, valid: bool) -> None:
    assert is_valid_project_command_env_key(key) is valid


def test_project_environment_resolves_valid_host_references(tmp_path):
    context = SimpleNamespace(
        config_digest="config-sha",
        root=str(tmp_path), settings=SimpleNamespace(env_references={"APP_MODE": "HOST_MODE"}),
    )

    result = resolve_project_environment(
        context,
        str(tmp_path),
        host_environment={"HOST_MODE": "test"},
        max_entries=8,
        max_bytes=128,
    )

    assert result == ("config-sha", {"APP_MODE": "test"}, None)


def test_project_environment_rejects_unsafe_target_key(tmp_path):
    context = SimpleNamespace(
        config_digest="config-sha",
        root=str(tmp_path), settings=SimpleNamespace(env_references={"GIT_CONFIG_COUNT": "HOST_VALUE"}),
    )

    result = resolve_project_environment(
        context,
        str(tmp_path),
        host_environment={"HOST_VALUE": "1"},
        max_entries=8,
        max_bytes=128,
    )

    assert result == ("", {}, "project environment configuration is invalid")
