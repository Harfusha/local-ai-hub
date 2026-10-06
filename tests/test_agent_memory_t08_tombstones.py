from __future__ import annotations

import json
from contextlib import closing
from dataclasses import replace

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStatus, MemoryStore
from local_ai_hub.sqlite_support import connect_sqlite


def test_deleted_memory_record_replay_is_tombstoned_after_reopen(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    db_path = tmp_path / "agent_state.sqlite3"
    original = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        scope_id=str(root),
        key="deleted memory replay fact",
        value="private deleted value",
        status=MemoryStatus.CONFIRMED,
        source="user",
        provenance={"root": str(root), "tenant": "tenant-a"},
    )
    idempotency_key = "deleted-memory-replay-once"
    store = MemoryStore(AgentStateStore(db_path))
    saved = store.record(original, actor="user", idempotency_key=idempotency_key)

    assert store.delete(
        saved.record_id,
        scope=AgentScope.REPOSITORY,
        scope_id=str(root),
        root=str(root),
        tenant="tenant-a",
    )
    with closing(connect_sqlite(db_path)) as con:
        payloads = [
            str(row[0])
            for row in con.execute(
                "SELECT payload FROM agent_events WHERE kind = 'memory.deleted'"
            ).fetchall()
        ]
    assert any(
        json.loads(payload).get("record_id") == saved.record_id
        and "private deleted value" not in payload
        for payload in payloads
    )

    reopened = MemoryStore(AgentStateStore(db_path))
    with pytest.raises(ValueError, match="deleted"):
        reopened.record(original, actor="user", idempotency_key=idempotency_key)

    other_root = tmp_path / "other-repo"
    other_root.mkdir()
    relocated = replace(
        original,
        scope_id=str(other_root),
        provenance={"root": str(other_root), "tenant": "tenant-a"},
    )
    with pytest.raises(ValueError, match="deleted"):
        reopened.record(
            relocated,
            actor="user",
            idempotency_key="deleted-memory-replay-in-other-scope",
        )

    assert reopened.get(
        saved.record_id,
        scope=AgentScope.REPOSITORY,
        root=str(root),
        tenant="tenant-a",
    ) is None
    assert reopened.find(
        scope=AgentScope.REPOSITORY,
        root=str(root),
        tenant="tenant-a",
        semantic=False,
    ) == []
