from __future__ import annotations

import errno

from local_ai_hub.telemetry import TelemetryStore


def test_errno_error_diagnostics_are_specific_and_private(tmp_path):
    missing = OSError("PROMPT-PRIVATE source=SOURCE-PRIVATE token=SECRET-TOKEN /private/project/missing.db")
    missing.errno = errno.ENOENT
    denied = OSError("PROMPT-PRIVATE source=SOURCE-PRIVATE token=SECRET-TOKEN /private/project/secret.db")
    denied.errno = errno.EACCES

    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        store.record_error("filesystem", "missing", missing)
        store.record_error("filesystem", "permission", denied)
        assert store.flush(10)
        connection = store._connect()
        try:
            rows = connection.execute(
                "SELECT error_type, safe_message FROM errors ORDER BY id"
            ).fetchall()
        finally:
            connection.close()
    finally:
        store.close()

    assert rows == [
        ("OSError", "OSError: file not found"),
        ("OSError", "OSError: permission denied"),
    ]
    serialized = repr(rows)
    for private in ("PROMPT-PRIVATE", "SOURCE-PRIVATE", "SECRET-TOKEN", "/private/project"):
        assert private not in serialized
    assert all(len(message) <= 96 for _, message in rows)
