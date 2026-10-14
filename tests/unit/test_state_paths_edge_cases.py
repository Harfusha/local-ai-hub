from __future__ import annotations

import os
from pathlib import Path

import pytest

from local_ai_hub.state_paths import (
    cleanup_fallback_state_dir,
    clear_all_fallback_state_dirs,
    configured_cache_dir,
    configured_state_dir,
    get_fallback_state_dir,
)


def test_configured_state_dir_defensive_config() -> None:
    # None or non-dict inputs must not raise AttributeError
    p1 = configured_state_dir(None)
    assert p1.is_dir()

    p2 = configured_state_dir("not-a-dict")  # type: ignore[arg-type]
    assert p2 == p1

    p3 = configured_state_dir({"server": "not-a-dict"})
    assert p3 == p1

    p4 = configured_state_dir({"server": {"state_dir": 12345}})
    # Non-string or numeric path should be stringified or fallback safely
    assert p4.is_dir()


def test_configured_state_dir_null_byte_prevention() -> None:
    # Null byte in path must not crash with ValueError, should fallback
    fallback_pid = configured_state_dir({"server": {"state_dir": "state\x00poison"}})
    assert fallback_pid.is_dir()
    assert "\x00" not in str(fallback_pid)


def test_configured_cache_dir(tmp_path: Path) -> None:
    custom_cache = tmp_path / "my_cache"
    cfg = {"server": {"cache_dir": str(custom_cache)}}
    cdir = configured_cache_dir(cfg)
    assert cdir == custom_cache
    assert cdir.is_dir()

    # Fallback to state_dir / cache
    custom_state = tmp_path / "my_state"
    cfg2 = {"server": {"state_dir": str(custom_state)}}
    cdir2 = configured_cache_dir(cfg2)
    assert cdir2 == custom_state / "cache"
    assert cdir2.is_dir()

    # Null byte or malformed config
    bad_cfg = {"server": {"cache_dir": "cache\x00poison"}}
    cdir_fallback = configured_cache_dir(bad_cfg)
    assert cdir_fallback.is_dir()
    assert "\x00" not in str(cdir_fallback)


def test_fallback_state_dir_cleanup_and_inspection() -> None:
    # Ensure current pid has a fallback state dir
    sdir = configured_state_dir(None)
    assert sdir.is_dir()

    pid = os.getpid()
    cached = get_fallback_state_dir(pid)
    assert cached == sdir

    # Cleanup specific pid
    assert cleanup_fallback_state_dir(pid) is True
    assert not sdir.exists()
    assert get_fallback_state_dir(pid) is None
    assert cleanup_fallback_state_dir(pid) is False

    # Clear all
    _ = configured_state_dir(None)
    count = clear_all_fallback_state_dirs()
    assert count >= 1
    assert get_fallback_state_dir(pid) is None
