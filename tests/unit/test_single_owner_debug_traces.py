from __future__ import annotations

import inspect
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.debug_traces import DebugTraceStore, _normalize_trace_content


def test_trace_start_has_no_tenant_parameter_and_rejects_legacy_keyword() -> None:
    parameters = inspect.signature(DebugTraceStore.start).parameters
    assert "tenant" not in parameters
    assert parameters["kind"].kind is inspect.Parameter.KEYWORD_ONLY

    store = DebugTraceStore.__new__(DebugTraceStore)
    with pytest.raises(TypeError, match="tenant"):
        store.start(kind="model", tenant="")


def test_captured_trace_content_preserves_tenant_text_and_fields() -> None:
    payload = {"request": {"tenant": "another project label"}, "output": "tenant_id appears in raw model output"}

    assert _normalize_trace_content(payload) == payload


def test_old_trace_schema_is_rejected_read_only_and_preserved(tmp_path: Path) -> None:
    database = tmp_path / "debug_traces.sqlite3"
    with closing(sqlite3.connect(database)) as con, con:
        con.execute("CREATE TABLE traces (trace_id TEXT PRIMARY KEY, tenant TEXT NOT NULL)")
        con.execute("INSERT INTO traces VALUES ('trace-1', 'legacy-shape')")

    store = DebugTraceStore.__new__(DebugTraceStore)
    store.path = database
    before = database.read_bytes()

    with pytest.raises(RuntimeError, match="offline conversion required"):
        store._preflight_retired_schema()

    assert database.read_bytes() == before
    assert not Path(f"{database}-wal").exists()
