from __future__ import annotations

import json

import pytest

from local_ai_hub.telemetry import TelemetryStore
from local_ai_hub.dashboard import DASHBOARD_HTML


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            json.JSONDecodeError(
                'PROMPT-PRIVATE token=TOKEN-PRIVATE at /private/project/config.json',
                '{"source":"/private/project/source.py","secret":"SOURCE-PRIVATE"}',
                0,
            ),
            "JSONDecodeError: invalid JSON",
        ),
        (
            FileNotFoundError("missing MODEL-OUTPUT-PRIVATE /private/project/model.bin token=TOKEN-PRIVATE"),
            "FileNotFoundError: file not found",
        ),
        (
            PermissionError("denied SOURCE-PRIVATE /private/project/cache.sqlite3 token=TOKEN-PRIVATE"),
            "PermissionError: permission denied",
        ),
        (ValueError('invalid PROMPT-PRIVATE source="SOURCE-PRIVATE"'), "ValueError: invalid value or argument"),
        (OSError('read /private/project/source.py token=SECRET-TOKEN'), "OSError: operating system failure"),
        (TimeoutError('MODEL-OUTPUT-PRIVATE timed out at /private/project/model.bin'), "TimeoutError: operation timed out"),
    ],
)
def test_error_diagnostics_are_actionable_bounded_and_private(tmp_path, error, expected):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        store.record_error("inference", "generate", error)
        assert store.flush(1)
        con = store._connect()
        try:
            rows = con.execute("SELECT error_type, safe_message FROM errors").fetchall()
        finally:
            con.close()
    finally:
        store.close()

    assert rows == [(type(error).__name__, expected)]
    persisted = repr(rows)
    for private in ("PROMPT-PRIVATE", "SOURCE-PRIVATE", "SECRET-TOKEN", "MODEL-OUTPUT-PRIVATE", "/private/project"):
        assert private not in persisted
    assert len(rows[0][1]) <= 96


def test_public_error_report_and_dashboard_expose_only_safe_diagnostic(tmp_path):
    error = ValueError('PROMPT-SECRET SOURCE-SECRET token=TOKEN-SECRET MODEL-OUTPUT-SECRET at /private/project/file.py')
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        store.record_error("inference", "generate", error)
        assert store.flush(1)
        report = store.report(days=30, recent_errors=10, _flush=False)
        con = store._connect()
        try:
            persisted = con.execute("SELECT safe_message FROM errors").fetchone()[0]
        finally:
            con.close()
    finally:
        store.close()

    expected = "ValueError: invalid value or argument"
    public_rows = report["error_fingerprints"]
    assert persisted == expected
    assert len(public_rows) == 1
    assert public_rows[0]["safe_message"] == expected
    serialized = repr((persisted, report))
    for private in ("PROMPT-SECRET", "SOURCE-SECRET", "TOKEN-SECRET", "MODEL-OUTPUT-SECRET", "/private/project"):
        assert private not in serialized

    modal_start = DASHBOARD_HTML.index("function renderErrorFingerprintModal(err)")
    modal_end = DASHBOARD_HTML.index("function openArchNodeModal", modal_start)
    modal_source = DASHBOARD_HTML[modal_start:modal_end]
    assert "Diagnostic" in modal_source
    assert "esc(String(err.safe_message||'Diagnostic unavailable').slice(0,96))" in modal_source
    assert '<th>Diagnostic</th>' in DASHBOARD_HTML
    assert "esc(String(x.safe_message||'Diagnostic unavailable').slice(0,96))" in DASHBOARD_HTML

