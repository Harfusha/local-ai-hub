from __future__ import annotations

from contextlib import closing

from local_ai_hub.json_utils import dumps as json_dumps
from local_ai_hub.telemetry import TelemetryStore


def test_custom_exception_keeps_safe_type_and_category_without_raw_details(tmp_path):
    class ProviderResponseError(RuntimeError):
        pass

    private_values = (
        "PROMPT-PRIVATE-CLASSIFY",
        "SOURCE-PRIVATE-CLASSIFY",
        "APIKEY-PRIVATE-CLASSIFY",
        "C:\\Users\\alice\\private\\source.py",
        "/home/alice/private/source.py",
    )
    error = ProviderResponseError(
        "PROMPT-PRIVATE-CLASSIFY SOURCE-PRIVATE-CLASSIFY "
        "api_key=APIKEY-PRIVATE-CLASSIFY "
        "C:\\Users\\alice\\private\\source.py /home/alice/private/source.py"
    )
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        store.record_error("inference", "generate", error)
        assert store.flush(1)
        with closing(store._connect()) as con:
            persisted_error = con.execute(
                "SELECT error_type, safe_message FROM errors"
            ).fetchone()
            persisted_event = con.execute(
                "SELECT error_type, action FROM events WHERE event_type='error'"
            ).fetchone()
        report = store.report(days=30, recent_errors=10, _flush=False)
    finally:
        store.close()

    expected = ("ProviderResponseError", "ProviderResponseError: operation failed")
    assert tuple(persisted_error) == expected
    assert tuple(persisted_event) == ("ProviderResponseError", "inference:generate")
    assert report["error_fingerprints"][0]["safe_message"] == expected[1]
    serialized = json_dumps((persisted_error, persisted_event, report))
    assert all(value not in serialized for value in private_values)
