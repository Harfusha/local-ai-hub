from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from service import (
    _read_owner,
    _role_stopped,
    is_valid_service_role,
    run,
)


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

