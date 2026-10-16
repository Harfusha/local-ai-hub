from __future__ import annotations

import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from setup import (
    expand,
    is_valid_persistent_mode,
)
from sync_prompt_policies import check_prompt_policies


def test_setup_expand_null_bytes() -> None:
    # Null bytes or invalid values in expand
    res = expand("~/.local\x00ai")
    assert res == ROOT

    res_none = expand(None)  # type: ignore[arg-type]
    assert res_none == ROOT


def test_setup_persistent_modes() -> None:
    assert is_valid_persistent_mode("windows-logon-task") is True
    assert is_valid_persistent_mode("windows-user-startup") is True
    assert is_valid_persistent_mode("launchd") is True
    assert is_valid_persistent_mode("systemd-user") is True
    assert is_valid_persistent_mode("existing-service") is True
    assert is_valid_persistent_mode("random-mode") is False
    assert is_valid_persistent_mode(None) is False
    assert is_valid_persistent_mode(123) is False


def test_check_prompt_policies_helper(tmp_path: Path) -> None:
    # Empty paths returns True
    ok, stale = check_prompt_policies(())
    assert ok is True
    assert stale == []

    # File without expected policy blocks is flagged as stale
    dummy_file = tmp_path / "dummy.md"
    dummy_file.write_text("No policy here\n", encoding="utf-8")
    ok, stale = check_prompt_policies((dummy_file,))
    assert ok is False
    assert dummy_file in stale
