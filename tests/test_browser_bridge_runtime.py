from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_actual_current_tab_fixture_preserves_login_and_never_falls_back() -> None:
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [
            "node",
            str(root / "tests/fixtures/browser_bridge/current_tab_harness.js"),
            str(root / "browser_bridge/capture.js"),
            str(root / "browser_bridge/background.js"),
            str(root / "tests/fixtures/browser_bridge/login-preserving.html"),
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    evidence = json.loads(result.stdout)
    assert evidence["success"] is True
    assert evidence["cases"] == ["success", "timeout", "tab-switch", "same-tab-navigation", "password", "timestamp", "origin"]
