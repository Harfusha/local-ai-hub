"""Declared memory namespaces without tenant filtering or global rewrites."""

from contextlib import closing
import json
import sqlite3
from types import SimpleNamespace

import pytest

from local_ai_hub.agent_context import ContextRequest, _memory_record_matches_context
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import (
    MemoryKind, MemoryRecord, MemoryStore, _context_scope_sql, _normalise_scope_root,
)


def test_context_sql_preserves_all_declared_namespaces(tmp_path):
    root_a = str(tmp_path / "repo-a")
    root_b = str(tmp_path / "repo-b")
    rows = [
        ("global", "global", "", {}),
        ("repository-a", "repository", "repository-one", {"repository_id": "repository-one", "root": root_a}),
        ("shared-clone", "repository", "repository-one", {"repository_id": "repository-one", "root": root_b}),
        ("other-repository", "repository", "repository-two", {"repository_id": "repository-two", "root": root_a}),
    ]
    identities = {"task": "task-one", "session": "chat-one", "clone": "clone-one", "worktree": "worktree-one", "branch": "main"}
    for scope, identity in identities.items():
        rows.extend([
            (f"{scope}-a", scope, identity, {"root": root_a}),
            (f"{scope}-b", scope, identity, {"root": root_b}),
            (f"{scope}-other", scope, "other", {"root": root_a}),
        ])
    sql, params = _context_scope_sql(
        root=root_a, coordination_id="repository-one", task_id="task-one", session_id="chat-one",
        clone_id="clone-one", worktree_id="worktree-one", branch="main",
    )
    assert "tenant" not in sql
    with closing(sqlite3.connect(":memory:")) as con:
        con.create_function("canonical_scope_root", 1, lambda value: _normalise_scope_root(value) if value else "")
        con.execute("CREATE TABLE memories (name TEXT, scope TEXT, scope_id TEXT, provenance TEXT)")
        con.executemany("INSERT INTO memories VALUES (?, ?, ?, ?)", [
            (name, scope, identity, json.dumps(provenance)) for name, scope, identity, provenance in rows
        ])
        found = {row[0] for row in con.execute(f"SELECT name FROM memories WHERE {sql}", params)}
    assert found == {"global", "repository-a", "shared-clone", *[f"{scope}-a" for scope in identities]}


def test_repository_context_has_no_physical_root_identity_fallback(tmp_path):
    request = ContextRequest(task_id="task-one", root=str(tmp_path), coordination_id="repository-one")
    correct = SimpleNamespace(scope=AgentScope.REPOSITORY, provenance={"repository_id": "repository-one"})
    wrong = SimpleNamespace(scope=AgentScope.REPOSITORY, provenance={"repository_id": "other", "root": str(tmp_path)})
    missing = SimpleNamespace(scope=AgentScope.REPOSITORY, provenance={"root": str(tmp_path)})
    assert _memory_record_matches_context(correct, request)
    assert not _memory_record_matches_context(wrong, request)
    assert not _memory_record_matches_context(missing, request)


@pytest.mark.parametrize("value", [None, "", False, "former-owner"])
def test_memory_record_rejects_retired_provenance_by_presence(value):
    with pytest.raises(ValueError, match="retired memory provenance"):
        MemoryRecord.create(MemoryKind.FACT, AgentScope.GLOBAL, "example", provenance={"tenant": value})


def test_context_request_no_longer_accepts_tenant():
    with pytest.raises(TypeError, match="tenant"):
        ContextRequest(task_id="task-one", tenant=None)


def test_existing_tenant_data_blocks_runtime_without_changing_record(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    store = MemoryStore(AgentStateStore(db_path))
    record = store.record(MemoryRecord.create(
        MemoryKind.FACT, AgentScope.GLOBAL, "preserve-this", "durable-value", source="user",
    ), actor="user")
    provenance = '{"tenant":null,"evidence":"preserve-exactly"}'
    with closing(sqlite3.connect(db_path)) as con:
        con.execute("UPDATE agent_memory_records SET provenance = ? WHERE record_id = ?", (provenance, record.record_id))
        con.commit()
        before = con.execute("SELECT * FROM agent_memory_records WHERE record_id = ?", (record.record_id,)).fetchone()
    with pytest.raises(RuntimeError, match="explicit offline data conversion"):
        MemoryStore(AgentStateStore(db_path))
    with closing(sqlite3.connect(db_path)) as con:
        after = con.execute("SELECT * FROM agent_memory_records WHERE record_id = ?", (record.record_id,)).fetchone()
    assert after == before
