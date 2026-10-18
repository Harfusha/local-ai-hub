from __future__ import annotations

import inspect
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.telemetry import TelemetryStore, _retired_tenant_field


@pytest.mark.parametrize("value", [None, False, ""])
def test_record_rejects_retired_tenant_field_by_presence(value: object, tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path, enabled=False)

    with pytest.raises(ValueError, match="Retired telemetry field"):
        store.record(tenant=value)


@pytest.mark.parametrize("method", ["record", "record_stage", "record_live"])
def test_event_writers_reject_nested_retired_tenant_fields(method: str, tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path, enabled=False)

    with pytest.raises(ValueError, match="tenant_id"):
        getattr(store, method)(metadata={"tenant_id": None})


def test_retired_field_scan_ignores_semantic_text_and_handles_cycles() -> None:
    event: dict[str, object] = {"message": "tenant_id is ordinary text"}
    event["scope"] = [event, {"tenant_scope": False}]

    assert _retired_tenant_field(event) == ""
    assert "tenant_scope" in _retired_tenant_field({"scope": {"tenant_scope": False}})
    assert _retired_tenant_field({"metadata": [{"tenant_id": None}]}) == ""
    assert _retired_tenant_field({"message": "tenant fields are discussed here"}) == ""


def test_record_error_has_no_tenant_parameter() -> None:
    assert "tenant" not in inspect.signature(TelemetryStore.record_error).parameters


@pytest.mark.parametrize("value", [None, False, ""])
def test_record_error_rejects_legacy_tenant_keyword(value: object, tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path, enabled=False)

    with pytest.raises(TypeError, match="tenant"):
        store.record_error("component", "operation", RuntimeError(), tenant=value)


def test_snapshot_rejects_nested_retired_field_before_filtering(tmp_path: Path) -> None:
    store = TelemetryStore(tmp_path, enabled=False)

    with pytest.raises(ValueError, match="tenant"):
        store.record_snapshot("status", {"scope": {"tenant": ""}})


def test_event_schema_has_no_tenant_partition() -> None:
    assert "tenant" not in TelemetryStore._EVENT_COLUMNS


def test_existing_tenant_schema_fails_before_writes_and_preserves_database(tmp_path: Path) -> None:
    database = tmp_path / "telemetry.sqlite3"
    with closing(sqlite3.connect(database)) as con, con:
        con.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, tenant TEXT)")
        con.execute("INSERT INTO events (tenant) VALUES ('old-shape')")

    store = TelemetryStore.__new__(TelemetryStore)
    store.path = database
    before = database.read_bytes()

    with pytest.raises(RuntimeError, match="offline conversion required"):
        store._reject_retired_schema()

    assert database.read_bytes() == before
    assert not Path(f"{database}-wal").exists()
