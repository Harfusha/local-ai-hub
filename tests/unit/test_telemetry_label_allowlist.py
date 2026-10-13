import pytest
from pathlib import Path
from local_ai_hub.telemetry import TelemetryStore, _SAFE_TOOL_ACTIONS

def test_clean_event_preserves_tool_action_labels():
    for action in ("local_ai_repo:context", "local_ai_command:test", "skeletonize", "verify_receipt"):
        event = TelemetryStore._clean_event({
            "event_type": "tool_call",
            "action": action,
        })
        assert event["action"] == action
        assert "<path>" not in event["action"]


def test_clean_event_preserves_root_basename():
    event = TelemetryStore._clean_event({
        "event_type": "tool_call",
        "action": "local_ai_repo:context",
        "root": "C:/Users/Adam/my-awesome-repo",
    })
    assert event.get("root") == "my-awesome-repo"
    assert "C:" not in event.get("root", "")


def test_clean_event_records_phase_durations(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True)
    try:
        ok = store.record(
            event_type="stage",
            action="local_ai_repo:context",
            db_wait_ms=14.5,
            exec_ms=52.0,
            serialization_ms=3.5,
        )
        assert ok is True
        assert store.flush(5)
        con = store._connect()
        try:
            row = con.execute("SELECT db_wait_ms, exec_ms, serialization_ms FROM events ORDER BY id DESC LIMIT 1").fetchone()
            assert row is not None
            assert row[0] == 14.5
            assert row[1] == 52.0
            assert row[2] == 3.5
        finally:
            con.close()
    finally:
        store.close()
