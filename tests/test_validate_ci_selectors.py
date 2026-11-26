"""Tests for tools/validate_ci_selectors.py — LAH-002 regression guard.

Verifies that the validator correctly detects missing vs. present test paths
in a synthetic CI YAML, and that the real ci.yml passes the check.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools" / "validate_ci_selectors.py"


def _run(yaml_text: str, tmp_path: Path, *extra_args: str) -> tuple[int, str]:
    ci_dir = tmp_path / ".github" / "workflows"
    ci_dir.mkdir(parents=True, exist_ok=True)
    (ci_dir / "ci.yml").write_text(yaml_text, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--root", str(tmp_path), "--no-collect", *extra_args],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    return result.returncode, result.stderr


def test_validator_passes_when_all_paths_exist(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "test_example.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("# stub", encoding="utf-8")
    yaml = textwrap.dedent("""\
        jobs:
          fast:
            steps:
              - run: python -m pytest tests/test_example.py
    """)
    code, stderr = _run(yaml, tmp_path)
    assert code == 0, f"Expected pass but got exit {code}: {stderr}"


def test_validator_fails_when_path_is_missing(tmp_path: Path) -> None:
    yaml = textwrap.dedent("""\
        jobs:
          fast:
            steps:
              - run: python -m pytest tests/test_ghost.py
    """)
    code, stderr = _run(yaml, tmp_path)
    assert code != 0, "Expected failure for missing test path"
    assert "test_ghost.py" in stderr


def test_validator_passes_on_real_ci_yml() -> None:
    """The real ci.yml must not reference any missing test files (LAH-002)."""
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, (
        f"Real ci.yml has missing test paths:\n{result.stderr}"
    )
