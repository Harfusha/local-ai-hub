from contextlib import closing
import sqlite3
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.sqlite_support import connect_sqlite


def test_scoped_delete_purges_fts_and_embedding_artifacts(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    store = MemoryStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    record = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            scope_id=str(root),
            key="delete-search-artifacts",
            value="sensitive searchable memory",
            source="user",
            provenance={"root": str(root), "tenant": "tenant-a", "repository_id": str(root)},
        ),
        actor="user",
        idempotency_key="delete-search-artifacts",
    )
    assert store.set_embedding(record.record_id, [0.25, 0.75])
    with closing(connect_sqlite(store.state_store.db_path)) as con:
        fts_exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_memory_fts'"
        ).fetchone() is not None
        assert con.execute(
            "SELECT COUNT(*) FROM agent_memory_embeddings WHERE record_id = ?",
            (record.record_id,),
        ).fetchone()[0] == 1
        if fts_exists:
            assert con.execute(
                "SELECT COUNT(*) FROM agent_memory_fts WHERE record_id = ?",
                (record.record_id,),
            ).fetchone()[0] == 1

    assert store.delete(
        record.record_id,
        scope=AgentScope.REPOSITORY,
        scope_id=str(root),
        root=str(root),
        repository_id=str(root),
    )
    reopened = MemoryStore(AgentStateStore(store.state_store.db_path))
    assert reopened.get(
        record.record_id,
        scope=AgentScope.REPOSITORY,
        scope_id=str(root),
        root=str(root),
        repository_id=str(root),

        include_expired=True,
    ) is None
    with closing(connect_sqlite(store.state_store.db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_memory_embeddings WHERE record_id = ?",
            (record.record_id,),
        ).fetchone()[0] == 0
        if fts_exists:
            assert con.execute(
                "SELECT COUNT(*) FROM agent_memory_fts WHERE record_id = ?",
                (record.record_id,),
            ).fetchone()[0] == 0


def test_replaying_record_after_delete_does_not_restore_memory_or_fts(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    store = MemoryStore(AgentStateStore(tmp_path / "agent_state.sqlite3"))
    record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        scope_id=str(root),
        key="delete-replay-does-not-resurrect",
        value="deleted searchable memory",
        source="user",
        provenance={"root": str(root), "tenant": "tenant-a", "repository_id": str(root)},
    )
    store.record(record, actor="user", idempotency_key="delete-replay-record")
    assert store.set_embedding(record.record_id, [0.25, 0.75])
    stream_id = "memory:" + "".join(
        f"{len(part)}:{part}"
        for part in (record.scope.value, record.scope_id or "", record.key or record.record_id)
    )

    assert store.delete(
        record.record_id,
        scope=AgentScope.REPOSITORY,
        scope_id=str(root),
        root=str(root),
        repository_id=str(root),
    )

    with pytest.raises(ValueError, match="memory record was deleted and cannot be replayed"):
        store.record(record, actor="user", idempotency_key="delete-replay-record")
    assert store.get(
        record.record_id,
        scope=AgentScope.REPOSITORY,
        root=str(root),
        repository_id=str(root),

        include_expired=True,
    ) is None
    events = store.state_store.events(stream_id)
    assert [event.kind for event in events] == ["memory.recorded", "memory.deleted"]
    assert events[-1].payload == {"record_id": record.record_id}
    with closing(connect_sqlite(store.state_store.db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_memory_embeddings WHERE record_id = ?",
            (record.record_id,),
        ).fetchone()[0] == 0
        fts_exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_memory_fts'"
        ).fetchone() is not None
        if fts_exists:
            assert con.execute(
                "SELECT COUNT(*) FROM agent_memory_fts WHERE record_id = ?",
                (record.record_id,),
            ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "fault_table",
    ["agent_entity_relations", "agent_memory_embeddings", "agent_memory_fts"],
)
def test_delete_cleanup_failure_rolls_back_memory_and_search_state(tmp_path, monkeypatch, fault_table):
    root = tmp_path / "repo"
    root.mkdir()
    db_path = tmp_path / "agent_state.sqlite3"
    store = MemoryStore(AgentStateStore(db_path))
    record = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            scope_id=str(root),
            key="rollback-delete-primary",
            value="retain after failed deletion",
            source="user",
            provenance={"root": str(root), "tenant": "tenant-a", "repository_id": str(root)},
        ),
        actor="user",
    )
    related = store.record(
        MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            scope_id=str(root),
            key="rollback-delete-related",
            value="retain relation",
            source="user",
            provenance={"root": str(root), "tenant": "tenant-a", "repository_id": str(root)},
        ),
        actor="user",
    )
    store.record_relation(record.record_id, "related_to", related.record_id)
    assert store.set_embedding(record.record_id, [0.5, 0.5])
    with closing(connect_sqlite(db_path)) as con:
        fts_exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_memory_fts'"
        ).fetchone() is not None
    if fault_table == "agent_memory_fts" and not fts_exists:
        pytest.skip("FTS5 unavailable")
    stream_id = "memory:" + "".join(
        f"{len(part)}:{part}" for part in (record.scope.value, record.scope_id or "", record.key or record.record_id)
    )
    seeded_event = AgentEvent.create(stream_id, "test.marker", {"safe": True}, "delete-fault-before")
    assert store.state_store.append(seeded_event).event == seeded_event.with_seq(2)
    events_before = store.state_store.events(stream_id)

    real_connect = sqlite3.connect

    class FailingDeleteConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            normalized_sql = " ".join(str(sql).split()).casefold()
            if normalized_sql.startswith(f"delete from {fault_table}"):
                raise sqlite3.OperationalError(f"injected {fault_table} delete failure")
            return super().execute(sql, parameters)

    def connect_with_delete_failure(database, *args, **kwargs):
        if Path(database).resolve(strict=False) == db_path.resolve():
            kwargs["factory"] = FailingDeleteConnection
        return real_connect(database, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", connect_with_delete_failure)
        with pytest.raises(sqlite3.OperationalError, match=f"injected {fault_table} delete failure"):
            store.delete(
                record.record_id,
                scope=AgentScope.REPOSITORY,
                scope_id=str(root),
                root=str(root),
                repository_id=str(root),
                tenant="tenant-a",
            )

    assert store.state_store.events(stream_id) == events_before
    assert store.get(
        record.record_id,
        scope=AgentScope.REPOSITORY,
        scope_id=str(root),
        root=str(root),
        repository_id=str(root),
    ) == record
    assert store.find_relations(source_entity=record.record_id)
    with closing(connect_sqlite(db_path)) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM agent_memory_embeddings WHERE record_id = ?",
            (record.record_id,),
        ).fetchone()[0] == 1
        if fts_exists:
            assert con.execute(
                "SELECT COUNT(*) FROM agent_memory_fts WHERE record_id = ?",
                (record.record_id,),
            ).fetchone()[0] == 1
