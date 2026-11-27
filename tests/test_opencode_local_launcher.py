from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_managed_opencode_launcher_fails_closed_with_sandbox_reason():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "opencode_local.py"), "--model", "gemma4:12b-128k"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 2
    assert "sandbox" in result.stderr.lower()
    assert "disabled" in result.stderr.lower()


def test_managed_opencode_launcher_help_remains_available():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "opencode_local.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0
    assert "--model" in result.stdout
