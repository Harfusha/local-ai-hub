from __future__ import annotations

import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from clean import (
    clean,
    is_safe_clean_target,
    SAFE_DIR_NAMES_TO_REMOVE,
)
from hubctl import (
    _activity_mode_transition_failures,
    _config_arg,
    is_valid_activity_mode,
)


def test_clean_root_validation_and_safe_target(tmp_path: Path) -> None:
    # Null bytes in clean root should raise ValueError
    with pytest.raises(ValueError, match="invalid"):
        clean("invalid\x00path")  # type: ignore[arg-type]

    # Non-existent dir returns (0, 0)
    assert clean(tmp_path / "non_existent") == (0, 0)

    # Cache directory targets include .mypy_cache and .ruff_cache
    assert ".mypy_cache" in SAFE_DIR_NAMES_TO_REMOVE
    assert ".ruff_cache" in SAFE_DIR_NAMES_TO_REMOVE

    # is_safe_clean_target helper
    assert is_safe_clean_target(tmp_path / "build", tmp_path) is True
    assert is_safe_clean_target(tmp_path / ".git", tmp_path) is False
    assert is_safe_clean_target(tmp_path / "nested" / ".git" / "file", tmp_path) is False
    assert is_safe_clean_target(tmp_path / ".." / "escaped", tmp_path) is False
    assert is_safe_clean_target("invalid\x00path", tmp_path) is False
    assert is_safe_clean_target(None, tmp_path) is False  # type: ignore[arg-type]


def test_hubctl_config_arg_null_bytes() -> None:
    # Null bytes in explicit config arg
    assert _config_arg(Path("config\x00.toml")) is None


def test_hubctl_activity_mode_helpers() -> None:
    # is_valid_activity_mode
    assert is_valid_activity_mode("active") is True
    assert is_valid_activity_mode("gaming") is True
    assert is_valid_activity_mode("maintenance") is True
    assert is_valid_activity_mode("ACTIVE") is True
    assert is_valid_activity_mode("invalid") is False
    assert is_valid_activity_mode("") is False
    assert is_valid_activity_mode(None) is False
    assert is_valid_activity_mode(123) is False

    # _activity_mode_transition_failures handles non-dict input
    assert _activity_mode_transition_failures(None, "gaming") == ["invalid result"]  # type: ignore[arg-type]
    assert _activity_mode_transition_failures("bad", "active") == ["invalid result"]  # type: ignore[arg-type]
