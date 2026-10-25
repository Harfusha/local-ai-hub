from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import (
    MemoryKind,
    MemoryRecord,
    MemoryStore,
)
from local_ai_hub.sqlite_support import connect_sqlite


class MockServices:
    def __init__(self, query_vec: list[float]):
        self.query_vec = query_vec

    def embed(self, texts: list[str], **kwargs: Any) -> dict[str, Any]:
        return {"embeddings": [self.query_vec]}


@pytest.fixture
def memory_store(tmp_path: Path) -> MemoryStore:
    db_path = tmp_path / "test_memory_scope_recall.sqlite3"
    state_store = AgentStateStore(db_path)
    store = MemoryStore(state_store)
    store._init_table()
    return store


def test_older_repository_record_not_starved_by_550_foreign_embeddings(memory_store: MemoryStore):
    repo_a = "C:/repos/primary_project"
    repo_b = "C:/repos/foreign_service"

    # 1. Create an older relevant record in repo_a with a specific embedding
    vec_relevant = [1.0] + [0.0] * 383
    rec_old = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        key="architecture.storage.backend",
        value="PostgreSQL with partitioned time-series engine",
        provenance={"root": repo_a, "repository_id": "repo-a"},
    )
    memory_store._save_record(rec_old)
    memory_store.set_embedding(rec_old.record_id, vec_relevant)

    # 2. Batch-create 550 newer foreign records in repo_b with orthogonal embeddings
    vec_foreign = [0.0, 1.0] + [0.0] * 382
    con = connect_sqlite(memory_store.state_store.db_path)
    try:
        records_data = []
        embeddings_data = []
        now = time.time() + 10.0
        for i in range(550):
            rec = MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope=AgentScope.REPOSITORY,
                key=f"foreign.metric.{i}",
                value=f"Foreign cluster metrics for node {i}",
                provenance={"root": repo_b, "repository_id": "repo-b"},
            )
            records_data.append((
                rec.record_id, rec.kind.value, rec.scope.value, rec.scope_id,
                rec.key, rec.value, rec.status.value, rec.confidence, rec.source,
                json.dumps(rec.evidence_ids), rec.sensitivity, rec.contradicts_record_id,
                rec.supersedes_record_id, rec.quarantine_reason, json.dumps(rec.provenance),
                rec.created_at, rec.updated_at, rec.expires_at,
            ))
            embeddings_data.append((rec.record_id, json.dumps(vec_foreign), now + i * 0.01))

        con.executemany(
            """
            INSERT INTO agent_memory_records (
                record_id, kind, scope, scope_id, key, value, status, confidence,
                source, evidence_ids, sensitivity, contradicts_record_id,
                supersedes_record_id, quarantine_reason, provenance, created_at,
                updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records_data,
        )
        con.executemany(
            """
            INSERT INTO agent_memory_embeddings (record_id, embedding, created_at)
            VALUES (?, ?, ?)
            """,
            embeddings_data,
        )
        con.commit()
    finally:
        con.close()

    # 3. Perform semantic query in repo_a targeting vec_relevant
    services = MockServices(query_vec=vec_relevant)
    results = memory_store.find(
        query="database storage architecture",
        scope=AgentScope.REPOSITORY,
        root=repo_a,
        repository_id="repo-a",
        semantic=True,
        services=services,
    )

    found_ids = [r.record_id for r in results]
    assert rec_old.record_id in found_ids, "Older relevant record was starved by foreign embeddings!"
    assert all(r.provenance.get("repository_id") == "repo-a" for r in results), "Foreign records leaked into results!"


def test_older_record_not_starved_by_150_foreign_fts_matches(memory_store: MemoryStore):
    repo_a = "C:/repos/primary_project"
    repo_b = "C:/repos/foreign_service"

    # 1. Target record in repo_a matching keyword 'partitioning'
    rec_target = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        key="postgres.partitioning.strategy",
        value="Range partitioning on timestamp column",
        provenance={"root": repo_a, "repository_id": "repo-a"},
    )
    memory_store._save_record(rec_target)

    # 2. Batch-create 150 foreign records in repo_b also containing 'partitioning'
    con = connect_sqlite(memory_store.state_store.db_path)
    try:
        records_data = []
        fts_data = []
        for i in range(150):
            rec = MemoryRecord.create(
                kind=MemoryKind.FACT,
                scope=AgentScope.REPOSITORY,
                key=f"foreign.partitioning.{i}",
                value=f"Kafka topic partitioning schema {i}",
                provenance={"root": repo_b, "repository_id": "repo-b"},
            )
            records_data.append((
                rec.record_id, rec.kind.value, rec.scope.value, rec.scope_id,
                rec.key, rec.value, rec.status.value, rec.confidence, rec.source,
                json.dumps(rec.evidence_ids), rec.sensitivity, rec.contradicts_record_id,
                rec.supersedes_record_id, rec.quarantine_reason, json.dumps(rec.provenance),
                rec.created_at, rec.updated_at, rec.expires_at,
            ))
            fts_data.append((rec.record_id, rec.key, rec.value))

        con.executemany(
            """
            INSERT INTO agent_memory_records (
                record_id, kind, scope, scope_id, key, value, status, confidence,
                source, evidence_ids, sensitivity, contradicts_record_id,
                supersedes_record_id, quarantine_reason, provenance, created_at,
                updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records_data,
        )
        con.executemany(
            "INSERT INTO agent_memory_fts (record_id, key, value) VALUES (?, ?, ?)",
            fts_data,
        )
        con.commit()
    finally:
        con.close()

    # 3. Query repo_a for 'partitioning' via semantic hybrid search
    results = memory_store.find(
        query="partitioning",
        scope=AgentScope.REPOSITORY,
        root=repo_a,
        repository_id="repo-a",
        semantic=True,
    )

    found_ids = [r.record_id for r in results]
    assert rec_target.record_id in found_ids, "Target record was starved by 150 foreign FTS matches!"
    assert all(r.provenance.get("repository_id") == "repo-a" for r in results), "Foreign FTS records leaked!"


def test_task_scope_isolation_prevents_foreign_task_starvation(memory_store: MemoryStore):
    repo_root = "C:/repos/work_project"

    # Task 1 record
    vec_task1 = [0.8, 0.6] + [0.0] * 382
    rec_task1 = MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.TASK,
        scope_id="task-001",
        key="task.discovery.phase",
        value="Identified critical concurrency bottleneck in queue admission",
        provenance={"root": repo_root, "repository_id": "repo-work", "task_id": "task-001"},
    )
    memory_store._save_record(rec_task1)
    memory_store.set_embedding(rec_task1.record_id, vec_task1)

    # 550 records for Task 2
    vec_task2 = [0.0, 1.0] + [0.0] * 382
    con = connect_sqlite(memory_store.state_store.db_path)
    try:
        records_data = []
        embeddings_data = []
        now = time.time() + 5.0
        for i in range(550):
            rec = MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope=AgentScope.TASK,
                scope_id="task-002",
                key=f"task.progress.{i}",
                value=f"Task 2 unrelated background item {i}",
                provenance={"root": repo_root, "repository_id": "repo-work", "task_id": "task-002"},
            )
            records_data.append((
                rec.record_id, rec.kind.value, rec.scope.value, rec.scope_id,
                rec.key, rec.value, rec.status.value, rec.confidence, rec.source,
                json.dumps(rec.evidence_ids), rec.sensitivity, rec.contradicts_record_id,
                rec.supersedes_record_id, rec.quarantine_reason, json.dumps(rec.provenance),
                rec.created_at, rec.updated_at, rec.expires_at,
            ))
            embeddings_data.append((rec.record_id, json.dumps(vec_task2), now + i * 0.01))

        con.executemany(
            """
            INSERT INTO agent_memory_records (
                record_id, kind, scope, scope_id, key, value, status, confidence,
                source, evidence_ids, sensitivity, contradicts_record_id,
                supersedes_record_id, quarantine_reason, provenance, created_at,
                updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records_data,
        )
        con.executemany(
            """
            INSERT INTO agent_memory_embeddings (record_id, embedding, created_at)
            VALUES (?, ?, ?)
            """,
            embeddings_data,
        )
        con.commit()
    finally:
        con.close()

    services = MockServices(query_vec=vec_task1)
    results = memory_store.find(
        query="concurrency bottleneck",
        scope=AgentScope.TASK,
        task_id="task-001",
        root=repo_root,
        semantic=True,
        services=services,
    )

    found_ids = [r.record_id for r in results]
    assert rec_task1.record_id in found_ids, "Task 1 record was starved by Task 2 embeddings!"
    assert all(r.scope_id == "task-001" for r in results), "Task 2 records leaked into Task 1 query!"


def test_numpy_cosine_similarity_numerical_parity(memory_store: MemoryStore):
    import numpy as np

    # Generate test vectors
    q_vec = [0.5] * 384
    q_norm = float(np.linalg.norm(q_vec))
    candidates = [
        [float((i + j) % 10) / 10.0 for j in range(384)]
        for i in range(25)
    ]

    # Calculate via reference Python _cosine_similarity
    ref_sims = [memory_store._cosine_similarity(q_vec, c) for c in candidates]

    # Calculate via batched NumPy
    mat = np.array(candidates, dtype=np.float32)
    q = np.array(q_vec, dtype=np.float32)
    dots = mat @ q
    norms = np.linalg.norm(mat, axis=1) * q_norm
    numpy_sims = dots / norms

    # Verify max difference < 1e-5
    for ref, npy in zip(ref_sims, numpy_sims):
        assert abs(ref - float(npy)) < 1e-5, f"NumPy parity error: ref={ref} vs numpy={npy}"
