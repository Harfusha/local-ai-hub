from __future__ import annotations

from local_ai_hub.json_utils import dumps as json_dumps
from local_ai_hub.telemetry import (
    _MAX_TELEMETRY_REPORT_BYTES,
    _bound_telemetry_report,
    TelemetryStore,
)

def test_telemetry_report_error_rows_are_paginated(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        for index in range(5):
            store.record_error("inference", f"generate-{index}", ValueError("invalid argument"))
        assert store.flush(1)

        first = store.report(recent_errors=2, error_offset=0, _flush=False)
        second = store.report(recent_errors=2, error_offset=2, _flush=False)
        last = store.report(recent_errors=2, error_offset=4, _flush=False)
    finally:
        store.close()

    assert [len(page["error_fingerprints"]) for page in (first, second, last)] == [2, 2, 1]
    assert first["error_fingerprints_page"] == {"offset": 0, "limit": 2, "total": 5, "next_offset": 2}
    assert second["error_fingerprints_page"]["next_offset"] == 4
    assert last["error_fingerprints_page"]["next_offset"] is None



def test_telemetry_report_response_stays_within_byte_budget():
    report = _bound_telemetry_report({
        "generated_at": "now",
        "window_days": 30,
        "scope": "window",
        "by_agent": [{"agent": f"agent-{index}", "label": "x" * 500} for index in range(1000)],
    })

    assert len(json_dumps(report).encode("utf-8")) <= _MAX_TELEMETRY_REPORT_BYTES
    assert report["response_truncated"] is True
    assert "by_agent" in report["response_truncated_fields"]
    assert report["by_agent"]


def test_telemetry_error_cursor_survives_rank_changes_between_pages(monkeypatch, tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        for index in range(5):
            for _ in range(index + 1):
                store.record_error("component", f"operation-{index}", ValueError("same safe class"))
        assert store.flush(1)

        first = store.report(recent_errors=2, error_cursor="", _flush=False)
        first_keys = {(row["fingerprint"], row["error_type"], row["component"], row["operation"])
                      for row in first["error_fingerprints"]}
        assert first["error_fingerprints_page"]["next_cursor"]
        for row in first["error_fingerprints"]:
            for _ in range(8):
                store.record_error(row["component"], row["operation"], ValueError("new ranking"))
        store.record_error("component", "new-operation", RuntimeError("new group"))
        assert store.flush(1)
        snapshot_cutoff = first["error_fingerprints_page"]["snapshot_cutoff"]
        monkeypatch.setattr(store, "_scope_cutoff", lambda _days, scope: (snapshot_cutoff + 100_000, scope))

        second = store.report(
            recent_errors=2, error_cursor=first["error_fingerprints_page"]["next_cursor"], _flush=False
        )
        third = store.report(
            recent_errors=2, error_cursor=second["error_fingerprints_page"]["next_cursor"], _flush=False
        )
        all_rows = first["error_fingerprints"] + second["error_fingerprints"] + third["error_fingerprints"]
        all_keys = [(row["fingerprint"], row["error_type"], row["component"], row["operation"]) for row in all_rows]
    finally:
        store.close()

    assert len(all_keys) == 5
    assert len(set(all_keys)) == 5
    assert first_keys.isdisjoint(set(all_keys[2:]))
    assert all(row["operation"] != "new-operation" for row in all_rows)
