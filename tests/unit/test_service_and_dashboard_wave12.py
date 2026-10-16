from __future__ import annotations

import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from service import (
    _read_owner,
    _role_stopped,
    is_valid_service_role,
    run,
)
from check_dashboard import validate_dashboard_html


def test_service_null_bytes_and_path_traversal() -> None:
    # Null bytes and path traversals in _read_owner and _role_stopped
    assert _read_owner("bad\x00role") is None
    assert _read_owner("../escape") is None
    assert _read_owner(None) is None  # type: ignore[arg-type]

    assert _role_stopped("bad\x00role") is False
    assert _role_stopped("../escape") is False
    assert _role_stopped(None) is False  # type: ignore[arg-type]

    # is_valid_service_role
    assert is_valid_service_role("supervisor") is True
    assert is_valid_service_role("hub") is True
    assert is_valid_service_role("ollama") is True
    assert is_valid_service_role("SUPERVISOR") is True
    assert is_valid_service_role("other") is False
    assert is_valid_service_role(None) is False

    # run helper handles null bytes without raising unhandled ValueError
    cp = run(["echo\x00bad"])
    assert cp.returncode == 127


def test_validate_dashboard_html() -> None:
    valid_html = """
    <html>
      <body>
        <div id="status-card">Status</div>
        <div id="chart-panel">Chart</div>
        <script>console.log("ok");</script>
      </body>
    </html>
    """
    valid, errors = validate_dashboard_html(valid_html)
    assert valid is True
    assert errors == []

    # Duplicate IDs
    dup_html = """
    <html>
      <body>
        <div id="status-card">Status 1</div>
        <div id="status-card">Status 2</div>
        <script>console.log("ok");</script>
      </body>
    </html>
    """
    valid, errors = validate_dashboard_html(dup_html)
    assert valid is False
    assert any("duplicate" in err.lower() for err in errors)

    # Missing script block
    no_script = """
    <html><body><div id="one"></div></body></html>
    """
    valid, errors = validate_dashboard_html(no_script)
    assert valid is False
    assert any("script" in err.lower() for err in errors)

    # Empty / non-str
    assert validate_dashboard_html("")[0] is False
    assert validate_dashboard_html(None)[0] is False  # type: ignore[arg-type]
