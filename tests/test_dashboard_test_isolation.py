from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_dashboard_modal_tests_do_not_patch_subprocess_run_on_import():
    root = Path(__file__).parents[1]
    script = (
        "import runpy, subprocess; "
        "original = subprocess.run; "
        "runpy.run_path('tests/test_dashboard_custom_modals.py'); "
        "raise SystemExit(0 if subprocess.run is original else 1)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
