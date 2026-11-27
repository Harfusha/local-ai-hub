from __future__ import annotations

import ctypes
import os
import sys

import pytest

from local_ai_hub.opencode_appcontainer import (
    build_environment_block,
    file_info_identity,
)


def test_explicit_environment_block_is_sorted_and_double_terminated():
    buffer, pointer = build_environment_block({"PATH": "C:\\Windows", "TEMP": "C:\\Temp"})
    assert "".join(buffer[:len(buffer)]) == "PATH=C:\\Windows\0TEMP=C:\\Temp\0\0"
    assert len(buffer) > 1


@pytest.mark.parametrize("environment", [
    {"PATH": "ok", "AWS_SECRET_ACCESS_KEY": "secret"},
    {"PATH": "bad\0value"},
    {"=C:": "drive-current-directory"},
])
def test_environment_block_rejects_secrets_and_malformed_entries(environment):
    with pytest.raises(ValueError):
        build_environment_block(environment)


def test_bridge_environment_is_separate_and_requires_session_secret():
    pipe_name = r"\\.\pipe\lah-opencode-0123456789abcdef0123456789abcdef"
    secret = "ab" * 32
    with pytest.raises(ValueError, match="not allowed"):
        build_environment_block({"LOCAL_AI_PIPE_SECRET": secret})
    with pytest.raises(ValueError, match="256-bit secret"):
        build_environment_block({"LOCAL_AI_PIPE_NAME": pipe_name}, bridge_client=True)
    buffer, _ = build_environment_block({
        "LOCAL_AI_PIPE_NAME": pipe_name,
        "LOCAL_AI_PIPE_SECRET": secret,
        "LOCAL_AI_PIPE_PORT_FILE": r"C:\Users\test\bridge.port",
    }, bridge_client=True)
    assert "".join(buffer[:len(buffer)]).count("LOCAL_AI_PIPE_SECRET=") == 1


def test_appcontainer_primitives_fail_closed_off_windows():
    if os.name == "nt" and sys.platform.startswith("win"):
        pytest.skip("Windows-native behavior covered by the Windows integration test")
    from local_ai_hub.opencode_appcontainer import AppContainerProfile

    with pytest.raises(OSError, match="Windows-only"):
        AppContainerProfile.create()


def test_file_info_identity_uses_volume_and_file_index_fields():
    first = [0, None, None, None, 11, 0, 8, 2, 3, 4]
    replacement = [0, None, None, None, 11, 0, 8, 2, 3, 5]

    assert file_info_identity(first) == (11, 3, 4)
    assert file_info_identity(replacement) == (11, 3, 5)
