from __future__ import annotations

from contextlib import closing
from pathlib import Path

from local_ai_hub.agent_memory import AgentScope, AgentStateStore, MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.context_delivery import prepare_context_delivery
from local_ai_hub.context_ledger import ContextLedger
from local_ai_hub.sqlite_support import connect_sqlite


class _TrackingArtifactStore:
    def __init__(self) -> None:
        self.put_calls = 0
        self.items: dict[str, str] = {}
        self.ttl_seconds = 3600

    def put(self, content: str, *, kind: str = "") -> str:
        self.put_calls += 1
        art_id = f"art-{self.put_calls}"
        self.items[art_id] = content
        return art_id

    def get(self, artifact_id: str, **kwargs):
        if artifact_id in self.items:
            return {"success": True, "text": self.items[artifact_id]}
        return {"success": False, "error": "not found"}


def test_n16_context_ledger_avoids_redundant_artifact_writes():
    store = _TrackingArtifactStore()
    ledger = ContextLedger()

    # Compile first time
    ledger.compile(
        task_id="task-1",
        revision="rev1",
        evidence_ids=["ev1"],
        context="Hello world context content",
        root="/test/root",
        session_id="session-1",
        phase="phase1",
        artifact_store=store,
    )
    assert store.put_calls == 1

    # Compile second time with identical context and parameters
    res2 = ledger.compile(
        task_id="task-1",
        revision="rev1",
        evidence_ids=["ev1"],
        context="Hello world context content",
        root="/test/root",
        session_id="session-1",
        phase="phase1",
        artifact_store=store,
    )
    # N16 requirement: ArtifactStore.put() must NOT be called again for unchanged context
    assert store.put_calls == 1, f"Expected 1 put call, got {store.put_calls}"
    assert res2.get("status") == "unchanged"


def test_n17_dynamic_text_budget_allocation():
    # Budget of 3000 tokens.
    # Text of 800 tokens (~3200 characters).
    # With old budget // 6: limit was 500 tokens -> text was truncated!
    # With dynamic allocation: metadata is ~50 tokens -> text gets ~2800 tokens -> NOT truncated.
    text_content = "important text sentence. " * 150
    input_val = {
        "task_context": {
            "success": True,
            "complete": True,
            "partial": False,
            "text": text_content,
        },
        "task_context_artifact_id": "art-1",
    }
    result = prepare_context_delivery(input_val, budget=3000)
    ctx = result["task_context"]
    assert ctx["success"] is True
    assert ctx.get("truncated") is not True, "Dynamic text budget should not truncate text when ample budget remains"
    assert result.get("context_truncated") is not True


def test_n10_historical_memory_recall_over_500(tmp_path: Path):
    db_path = tmp_path / "memory_state.sqlite3"
    state_store = AgentStateStore(db_path=db_path)
    state_store._ensure_schema()
    memory = MemoryStore(state_store=state_store)

    # Insert record 1: key architectural fact with oldest timestamp
    key_rec = MemoryRecord.create(
        scope=AgentScope.GLOBAL,
        key="arch_secret_decision",
        value="database engine is selected as PostgreSQL exclusively",
        kind=MemoryKind.FACT,
    )
    memory.record(key_rec)

    # Ingest 550 dummy records in a transaction to exceed old LIMIT 500
    with closing(connect_sqlite(db_path)) as con:
        con.execute("UPDATE agent_memory_records SET created_at = 1.0, updated_at = 1.0 WHERE record_id = ?", (key_rec.record_id,))
        for i in range(550):
            ts = 100.0 + i
            dummy = MemoryRecord.create(
                scope=AgentScope.GLOBAL,
                key=f"noise_{i}",
                value=f"routine unimportant log entry number {i}",
                kind=MemoryKind.FACT,
            )
            con.execute(
                "INSERT INTO agent_memory_records ("
                "record_id, kind, scope, scope_id, key, value, status, confidence, source, "
                "evidence_ids, sensitivity, contradicts_record_id, supersedes_record_id, "
                "quarantine_reason, provenance, created_at, updated_at, expires_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    dummy.record_id, dummy.kind.value, dummy.scope.value, dummy.scope_id,
                    dummy.key, dummy.value, dummy.status.value, dummy.confidence, dummy.source,
                    "[]", "normal", None, None, None, "{}", ts, ts, None,
                ),
            )
            con.execute(
                "INSERT INTO agent_memory_embeddings (record_id, embedding, embedding_space_id, dimension, created_at) VALUES (?, ?, ?, ?, ?)",
                (dummy.record_id, "[0.1, 0.1, 0.1, 0.1]", "test-space", 4, ts),
            )
        con.commit()

    # Fake embedding service returning identical embeddings for query and key record
    class FakeEmbedServices:
        def embed(self, texts):
            return {
                "embeddings": [[0.5, 0.5, 0.5, 0.5] for _ in texts],
                "embedding_space_id": "test-space",
            }

    # Record embedding for key record in agent_memory_embeddings (with older created_at)
    with closing(connect_sqlite(db_path)) as con:
        con.execute(
            "INSERT OR REPLACE INTO agent_memory_embeddings (record_id, embedding, embedding_space_id, dimension, created_at) VALUES (?, ?, ?, ?, ?)",
            (key_rec.record_id, "[0.5, 0.5, 0.5, 0.5]", "test-space", 4, 1.0),
        )
        con.commit()

    # Query with semantic retrieval where query does not share lexical words with value
    matches = memory.find(
        scope=AgentScope.GLOBAL,
        query="relational storage technology selection",
        semantic=True,
        services=FakeEmbedServices(),
        limit=10,
    )
    found_keys = [m.key for m in matches]
    assert "arch_secret_decision" in found_keys, f"Oldest record was starved out by LIMIT 500: found {found_keys}"
