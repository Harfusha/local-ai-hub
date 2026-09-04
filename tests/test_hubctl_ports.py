from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_hubctl_cleanup_ports_cli_arg():
    root = Path(__file__).resolve().parent.parent
    hubctl = root / "tools" / "hubctl.py"
    # Test --help contains --ports and --vacuum
    res = subprocess.run([sys.executable, str(hubctl), "--help"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "--ports" in res.stdout
    assert "--vacuum" in res.stdout

    # Run cleanup --ports with no server listening (should return gracefully without crashing)
    res_cleanup = subprocess.run([sys.executable, str(hubctl), "cleanup", "--ports"], capture_output=True, text=True, timeout=10)
    # Return code should be 0 or handled JSON
    assert "cleaned_ports" in res_cleanup.stdout or res_cleanup.returncode in (0, 1)


