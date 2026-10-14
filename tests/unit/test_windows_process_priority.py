from __future__ import annotations

import os
import subprocess
import pytest

from local_ai_hub.process_utils import (
    get_process_priority,
    hidden_run_kwargs,
    set_process_priority,
    windows_creationflags,
)


def test_windows_creationflags_priority() -> None:
    if os.name != "nt":
        pytest.skip("Windows-specific test")

    flags_normal = windows_creationflags()
    assert flags_normal & 0x08000000  # CREATE_NO_WINDOW
    assert not (flags_normal & 0x00004000)

    flags_below_normal = windows_creationflags(priority="below_normal")
    assert flags_below_normal & 0x08000000
    assert flags_below_normal & 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS

    flags_idle = windows_creationflags(priority="idle")
    assert flags_idle & 0x08000000
    assert flags_idle & 0x00000040  # IDLE_PRIORITY_CLASS


def test_hidden_run_kwargs_passes_priority() -> None:
    if os.name != "nt":
        pytest.skip("Windows-specific test")

    kwargs = hidden_run_kwargs(priority="below_normal")
    assert "creationflags" in kwargs
    assert kwargs["creationflags"] & 0x00004000


def test_get_and_set_process_priority() -> None:
    if os.name != "nt":
        pytest.skip("Windows-specific test")

    proc = subprocess.Popen(
        ["cmd.exe", "/c", "timeout 5 >nul"],
        **hidden_run_kwargs(priority="normal"),
    )
    try:
        initial = get_process_priority(proc.pid)
        assert initial in {"normal", "below_normal"}

        # Dynamic change to below_normal
        changed = set_process_priority(proc.pid, "below_normal")
        assert changed is True
        assert get_process_priority(proc.pid) == "below_normal"

        # Dynamic change to idle
        changed_idle = set_process_priority(proc.pid, "idle")
        assert changed_idle is True
        assert get_process_priority(proc.pid) == "idle"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_spawn_directly_in_below_normal_priority() -> None:
    if os.name != "nt":
        pytest.skip("Windows-specific test")

    proc = subprocess.Popen(
        ["cmd.exe", "/c", "timeout 5 >nul"],
        **hidden_run_kwargs(priority="below_normal"),
    )
    try:
        priority = get_process_priority(proc.pid)
        assert priority == "below_normal"
    finally:
        proc.terminate()
        proc.wait(timeout=5)
