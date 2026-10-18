from pathlib import Path

import pytest

from local_ai_hub import telemetry
from local_ai_hub.telemetry import TelemetryStore, _SAFE_TOOL_ACTIONS
from local_ai_hub.operation_contracts import operation_actions

def test_clean_event_preserves_tool_action_labels():
    labels = {"skeletonize", "verify_receipt"}
    labels.update(
        f"{tool}:{action}"
        for tool in _SAFE_TOOL_ACTIONS
        if tool.startswith("local_ai_")
        for action in operation_actions(tool)
    )
    assert "local_ai_repo:dead_code" in labels
    for action in labels:
        event = TelemetryStore._clean_event({
            "event_type": "tool_call",
            "action": action,
        })
        assert event["action"] == action
        assert "<path>" not in event["action"]


def test_clean_event_redacts_unregistered_compound_action_labels():
    source_root = Path(__file__).resolve().parents[2] / "src"
    assert Path(telemetry.__file__).resolve().is_relative_to(source_root.resolve())
    for action in (
        "local_ai_repo:private_operation",
        "unregistered_tool:context",
        "local_ai_repo:status",
    ):
        event = TelemetryStore._clean_event({
            "event_type": "tool_call",
            "action": action,
        })
        assert event["action"] == "<path>"


def test_clean_event_preserves_root_basename():
    event = TelemetryStore._clean_event({
        "event_type": "tool_call",
        "action": "local_ai_repo:context",
        "root": "C:/Users/developer/my-awesome-repo",
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


def test_phase_measurement_availability_distinguishes_unknown_from_measured_zero(tmp_path):
    source_root = Path(__file__).resolve().parents[2] / "src"
    assert Path(telemetry.__file__).resolve().is_relative_to(source_root.resolve())
    cleaned = TelemetryStore._clean_event({
        "event_type": "http", "db_wait_ms": None, "exec_ms": 0.0,
        "serialization_ms": float("nan"), "db_wait_measured": 1,
    })
    assert (cleaned["db_wait_ms"], cleaned["db_wait_measured"]) == (0.0, 0)
    assert (cleaned["exec_ms"], cleaned["exec_measured"]) == (0.0, 1)
    assert (cleaned["serialization_ms"], cleaned["serialization_measured"]) == (0.0, 0)
    assert TelemetryStore._clean_event(cleaned)["exec_measured"] == 1

    store = TelemetryStore(tmp_path / "telemetry-availability", enabled=True)
    try:
        assert store.record(
            event_type="http", action="local_ai_repo:context",
            db_wait_ms=None, exec_ms=0.0, serialization_ms=float("nan"),
        )
        assert store.flush(5)
        con = store._connect()
        try:
            row = con.execute(
                "SELECT db_wait_ms, db_wait_measured, exec_ms, exec_measured, "
                "serialization_ms, serialization_measured FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            con.close()
        assert tuple(row) == (0.0, 0, 0.0, 1, 0.0, 0)
        live_event = store.live()["events"][-1]
        assert live_event["exec_ms"] == 0.0
        assert live_event["exec_measured"] == 1
        assert live_event["db_wait_measured"] == 0
    finally:
        store.close()


def test_legacy_schema_requires_explicit_offline_conversion_and_preserves_durations(tmp_path):
    state_dir = tmp_path / "legacy-telemetry"
    store = TelemetryStore(state_dir, enabled=True)
    try:
        assert store.record(
            event_type="http", action="local_ai_repo:context",
            db_wait_ms=7.0, exec_ms=8.0, serialization_ms=9.0,
        )
        assert store.flush(5)
    finally:
        store.close()

    con = store._connect()
    try:
        for column in ("db_wait_measured", "exec_measured", "serialization_measured"):
            con.execute(f'ALTER TABLE events DROP COLUMN "{column}"')
    finally:
        con.close()

    database = store.path
    legacy_bytes = database.read_bytes()
    with pytest.raises(RuntimeError, match="explicit offline conversion required"):
        TelemetryStore(state_dir, enabled=True)
    assert database.read_bytes() == legacy_bytes
