"""Memory preload matching follows actual root, task, and session scope."""

from types import SimpleNamespace

import pytest

from local_ai_hub.agent_context import ContextCompiler, ContextRequest, _memory_record_matches_context
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope, ScopeContext


def _record(*, scope=AgentScope.REPOSITORY, scope_id="", provenance=None):
    return SimpleNamespace(scope=scope, scope_id=scope_id, provenance=provenance or {})


def test_memory_context_uses_repository_coordination_and_exact_root(tmp_path):
    request = ContextRequest(task_id="task-a", root=str(tmp_path), coordination_id="repo-id")
    assert _memory_record_matches_context(
        _record(provenance={"repository_id": "repo-id"}), request
    )
    assert not _memory_record_matches_context(
        _record(provenance={"repository_id": "other-repo"}), request
    )
    assert not _memory_record_matches_context(
        _record(provenance={"repository_id": "repo-id", "tenant": None}), request
    )


def test_memory_context_keeps_global_scope_and_real_session_distinct(tmp_path):
    request = ContextRequest(root=str(tmp_path), task_id="task-1", session_id="session-1")
    assert _memory_record_matches_context(_record(scope=AgentScope.GLOBAL), request)
    assert _memory_record_matches_context(
        _record(scope=AgentScope.SESSION, scope_id="session-1", provenance={"root": str(tmp_path)}), request
    )
    assert not _memory_record_matches_context(
        _record(scope=AgentScope.SESSION, scope_id="other-session", provenance={"root": str(tmp_path)}), request
    )


def test_scope_context_has_only_actual_scope_fields_and_rejects_retired_keys():
    value = ScopeContext.from_dict({"repository_id": "repo", "session_id": "chat"})
    assert value.repository_id == "repo"
    assert value.session_id == "chat"
    for retired in ("tenant", "tenant_key", "schema_version"):
        with pytest.raises((TypeError, ValueError)):
            ScopeContext.from_dict({"repository_id": "repo", retired: None})


def test_context_preload_does_not_require_or_substitute_session_owner(tmp_path):
    global_record = SimpleNamespace(
        record_id="global-fact", kind=SimpleNamespace(value="fact"), key="shared",
        value="owner-global fact", evidence_ids=(), confidence=1.0, updated_at=1.0,
        scope=AgentScope.GLOBAL, scope_id="", provenance={},
    )

    class MemoryStore:
        def find_for_context(self, **kwargs):
            assert kwargs["root"] == str(tmp_path)
            assert kwargs["session_id"] == "chat-1"
            assert "tenant" not in kwargs
            return [global_record]

    compiler = ContextCompiler(
        AgentStateStore(tmp_path / "state.sqlite3"),
        memory_store=MemoryStore(),
        config={"context": {"preloads": {"memory_kinds": ["fact"], "max_memory": 2}}},
    )
    elements = compiler._load_preloads(
        ContextRequest(root=str(tmp_path), task_id="task-1", session_id="chat-1"), [],
    )
    assert any(element.source_kind == "preload_memory" for _, element in elements)
