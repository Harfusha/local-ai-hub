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
    # None or empty dict inputs return fallback dir
    p1 = configured_state_dir(None)
    assert p1.is_dir()

    # Non-mapping config or server must raise TypeError
    with pytest.raises(TypeError, match="config must be a mapping or None"):
        configured_state_dir("not-a-dict")  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="config.server must be a mapping or None"):
        configured_state_dir({"server": "not-a-dict"})

    # Non-pathlike state_dir must raise TypeError
    with pytest.raises(TypeError, match="server.state_dir must be a path string or path-like value"):
        configured_state_dir({"server": {"state_dir": 12345}})


def test_configured_state_dir_null_byte_prevention() -> None:
    # Null byte in state_dir path must raise ValueError
    with pytest.raises(ValueError, match="server.state_dir cannot contain a NUL character"):
        configured_state_dir({"server": {"state_dir": "state\x00poison"}})


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

    # Null byte in cache_dir must raise ValueError
    bad_cfg = {"server": {"cache_dir": "cache\x00poison"}}
    with pytest.raises(ValueError, match="configured directory cannot contain a NUL character"):
        configured_cache_dir(bad_cfg)


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
