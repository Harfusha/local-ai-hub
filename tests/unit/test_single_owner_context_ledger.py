from __future__ import annotations

import inspect

import pytest

from local_ai_hub.context_ledger import ContextLedger


class _Artifacts:
    ttl_seconds = 600

    def __init__(self) -> None:
        self.value = ""

    def put(self, content: str, *, kind: str) -> str:
        assert kind == "agent-context"
        self.value = content
        return "artifact-id"

    def get(self, artifact_id: str, *, offset: int, max_chars: int) -> dict[str, object]:
        assert artifact_id == "artifact-id"
        return {"success": True, "text": self.value[offset:offset + max_chars]}


def test_record_retains_actual_session_identity() -> None:
    ledger = ContextLedger()
    ledger.record(tool="local_ai_repo", operation="context", session_id="session-7")

    assert ledger.snapshot()["last"]["session_id"] == "session-7"


def test_compiled_pointer_identity_includes_actual_session() -> None:
    ledger = ContextLedger()
    common = {"task_id": "task-1", "revision": "rev-2", "evidence_ids": [], "context": "context",
              "root": "C:/repo"}

    first = ledger.compile(**common, session_id="session-a")
    second = ledger.compile(**common, session_id="session-b")

    assert first["reuse_key"] != second["reuse_key"]


def test_materialize_checks_the_compiled_session_identity() -> None:
    ledger = ContextLedger()
    artifacts = _Artifacts()
    compiled = ledger.compile(
        "task-1", "rev-2", [], "context", root="C:/repo",
        session_id="session-a", artifact_store=artifacts,
    )

    rejected = ledger.materialize(
        compiled["reuse_key"], artifacts, root="C:/repo",
        task_id="task-1", session_id="session-b",
    )
    accepted = ledger.materialize(
        compiled["reuse_key"], artifacts, root="C:/repo",
        task_id="task-1", session_id="session-a",
    )

    assert rejected["status"] == "unavailable"
    assert accepted["status"] == "materialized"


def test_context_ledger_has_no_tenant_parameter_or_keyword_alias() -> None:
    assert "tenant" not in inspect.signature(ContextLedger.compile).parameters
    assert "tenant" not in inspect.signature(ContextLedger.materialize).parameters
    ledger = ContextLedger()
    with pytest.raises(TypeError, match="tenant"):
        ledger.compile("task", "rev", [], "text", tenant=None)


def test_materialize_rejects_old_positional_tenant_argument() -> None:
    ledger = ContextLedger()
    with pytest.raises(TypeError):
        ledger.materialize("key", None, "old-tenant", root="", task_id="task")
