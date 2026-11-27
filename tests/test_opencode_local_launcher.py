from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_opencode_diagnostics_are_read_only_and_do_not_claim_runtime_acceptance(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "opencode_local.py"), "--diagnostics"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["generated_manifest"] == {
        "path": "generated/opencode-mcp.json",
        "status": "not_present",
    }
    for key in ("configured", "installed", "trusted", "connected", "user_visible_tools"):
        assert report[key] == "NOT_VERIFIED"
    assert report["launcher"]["status"] == "disabled"
    assert "sandbox" in report["launcher"]["reason"].lower()
    assert list(tmp_path.iterdir()) == []


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
