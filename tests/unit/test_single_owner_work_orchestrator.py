"""Single-owner work-order persistence and API contracts."""

from __future__ import annotations

import inspect
import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.work_orchestrator import WorkOrchestrator


def test_work_order_public_methods_reject_retired_tenant_argument() -> None:
    for method_name in ("submit", "status", "get", "wait", "cancel", "continue_work"):
        signature = inspect.signature(getattr(WorkOrchestrator, method_name))
        assert "tenant" not in signature.parameters
        with pytest.raises(TypeError):
            signature.bind_partial(object(), tenant=None)


def test_submit_rejects_tenant_payload_even_when_empty() -> None:
    orchestrator = WorkOrchestrator.__new__(WorkOrchestrator)

    result = orchestrator.submit({"tenant": ""})

    assert result["success"] is False
    assert result["terminal"] is True


def test_legacy_database_schema_fails_before_mutating_it(tmp_path) -> None:
    database = tmp_path / "work_orders.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        connection.execute(
            "CREATE TABLE work_orders("
            "work_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, root TEXT NOT NULL, "
            "task TEXT NOT NULL, state TEXT NOT NULL, payload_json TEXT NOT NULL, "
            "result_json TEXT NOT NULL DEFAULT '{}', cancel_requested INTEGER NOT NULL DEFAULT 0, "
            "created_at REAL NOT NULL, updated_at REAL NOT NULL)"
        )
        connection.execute(
            "INSERT INTO work_orders(work_id,tenant,root,task,state,payload_json,created_at,updated_at) "
            "VALUES('work-1','legacy-owner','/repo','task','queued','{}',1,1)"
        )

    orchestrator = WorkOrchestrator.__new__(WorkOrchestrator)
    orchestrator.path = database
    with pytest.raises(RuntimeError, match="explicit offline conversion required"):
        orchestrator._init_db()

    with closing(sqlite3.connect(database)) as connection, connection:
        row = connection.execute("SELECT tenant FROM work_orders WHERE work_id='work-1'").fetchone()
    assert row == ("legacy-owner",)
