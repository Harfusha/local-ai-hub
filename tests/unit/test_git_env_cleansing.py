from __future__ import annotations

import os
import pytest

from local_ai_hub.process_utils import clean_git_env


def test_clean_git_env_strips_git_vars() -> None:
    fake_env = {
        "PATH": "C:\\bin;/usr/bin",
        "GIT_DIR": ".git",
        "GIT_WORK_TREE": "C:\\repo",
        "GIT_INDEX_FILE": ".git/index",
        "git_prefix": "sub/",
        "USER": "developer",
    }

    cleaned = clean_git_env(base_env=fake_env)

    assert "PATH" in cleaned
    assert "USER" in cleaned
    assert "GIT_DIR" not in cleaned
    assert "GIT_WORK_TREE" not in cleaned
    assert "GIT_INDEX_FILE" not in cleaned
    assert "git_prefix" not in cleaned


def test_clean_git_env_extra_env_and_preserve() -> None:
    fake_env = {
        "PATH": "/bin",
        "GIT_DIR": ".git",
        "GIT_AUTHOR_NAME": "Lead Integrator",
        "GIT_AUTHOR_EMAIL": "lead@example.invalid",
    }

    cleaned = clean_git_env(
        base_env=fake_env,
        extra_env={"CUSTOM_SETTING": "enabled", "GIT_TRACE": "0"},
        preserve=["GIT_AUTHOR_NAME"],
    )

    assert cleaned["PATH"] == "/bin"
    assert "GIT_DIR" not in cleaned
    assert cleaned["GIT_AUTHOR_NAME"] == "Lead Integrator"
    assert "GIT_AUTHOR_EMAIL" not in cleaned
    assert cleaned["CUSTOM_SETTING"] == "enabled"
    assert cleaned["GIT_TRACE"] == "0"


def test_clean_git_env_defaults_to_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_TEST_CONTAMINATION", "active")
    monkeypatch.setenv("HUB_TEST_VAR", "preserved")

    cleaned = clean_git_env()

    assert "GIT_TEST_CONTAMINATION" not in cleaned
    assert cleaned.get("HUB_TEST_VAR") == "preserved"
    assert "PATH" in cleaned or "Path" in cleaned


def test_clean_git_env_does_not_mutate_input() -> None:
    orig = {"GIT_DIR": "/tmp/git", "KEEP": "1"}
    cleaned = clean_git_env(base_env=orig)

    assert "GIT_DIR" in orig  # Original dictionary unharmed
    assert "GIT_DIR" not in cleaned
