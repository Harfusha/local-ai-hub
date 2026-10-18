from __future__ import annotations

from local_ai_hub.telemetry import TelemetryStore


def test_error_telemetry_persists_classification_without_exception_text(tmp_path):
    prompt = "PROMPT-PRIVATE-SENTINEL"
    source = "SOURCE-PRIVATE-SENTINEL"
    secret_value = "API-" + "SECRET-" + "SENTINEL"
    path = r"C:\private\project\source.py"
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        store.record_error(
            "provider",
            "generate",
            RuntimeError(
                f'prompt="{prompt}" source_text="{source}" api_' + f'key="{secret_value}" file={path}'
            ),
            retryable=True,
            recovered=True,
        )
        assert store.flush(10)
        con = store._connect()
        try:
            row = con.execute(
                "SELECT component, operation, error_type, safe_message, retryable, recovered FROM errors"
            ).fetchone()
        finally:
            con.close()
    finally:
        store.close()

    assert row == (
        "provider",
        "generate",
        "RuntimeError",
        "RuntimeError: operation failed",
        1,
        1,
    )
    persisted = repr(row)
    assert prompt not in persisted
    assert source not in persisted
    assert secret_value not in persisted
    assert path not in persisted
