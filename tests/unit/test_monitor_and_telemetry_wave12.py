from __future__ import annotations

import math
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from monitor import (
    _format_time,
    format_event_line,
    format_monitor_header,
)
from telemetry_report import (
    _default_output_path,
    _safe_tuning,
)


def test_monitor_format_time() -> None:
    # Valid timestamp
    t = _format_time(1700000000.0)
    assert len(t.split(":")) == 3

    # Fallbacks
    assert _format_time(None) == "00:00:00"
    assert _format_time(-100) == "00:00:00"
    assert _format_time(float("nan")) == "00:00:00"
    assert _format_time(float("inf")) == "00:00:00"
    assert _format_time("bad") == "00:00:00"


def test_monitor_format_helpers() -> None:
    # format_monitor_header
    header = format_monitor_header({"hub_online": True, "ollama_online": False})
    assert "Hub: UP" in header
    assert "Ollama: DOWN" in header

    header_empty = format_monitor_header(None)  # type: ignore[arg-type]
    assert "Hub: DOWN" in header_empty

    # format_event_line
    event = {
        "created_at": 1700000000.0,
        "agent": "codex",
        "stage": "solve",
        "model": "qwen2.5-coder:7b",
        "action": "edit",
        "cache_hit": True,
    }
    line = format_event_line(event)
    assert "codex" in line
    assert "CACHE" in line

    # Invalid event
    assert format_event_line(None) == ""  # type: ignore[arg-type]


def test_telemetry_report_default_output_and_safe_tuning(tmp_path: Path) -> None:
    # Valid state dir
    out = _default_output_path(tmp_path)
    assert out.parent == (tmp_path / "diagnostics").resolve()

    # Null bytes in state dir
    fallback_out = _default_output_path("invalid\x00dir")
    assert "diagnostics" in str(fallback_out)
    assert "\x00" not in str(fallback_out)

    # _safe_tuning
    valid_cfg = {
        "routing": {"mode": "auto"},
        "secret_token": "hidden",
        "unknown_section": {"a": 1},
    }
    tuned = _safe_tuning(valid_cfg)
    assert "routing" in tuned
    assert "secret_token" not in tuned
    assert "unknown_section" not in tuned

    assert _safe_tuning(None) == {}  # type: ignore[arg-type]
