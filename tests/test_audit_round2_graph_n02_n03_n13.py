from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.state_lifecycle import write_state_version
from tools.state_migrations import run_state_migrations


def test_n13_old_relation_projection_is_migrated_before_runtime_open(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    db_path = state_dir / "agent_state.sqlite"
    root = str(tmp_path / "GraphRepo")
    state_store = AgentStateStore(db_path=db_path)
    MemoryStore(state_store)
    write_state_version(state_dir, version=6)
    with closing(sqlite3.connect(db_path)) as con, con:
        con.execute("DROP TABLE agent_entity_relations")
        con.execute(
            """CREATE TABLE agent_entity_relations (
                relation_id TEXT PRIMARY KEY,
                source_entity TEXT NOT NULL,
                relation TEXT NOT NULL,
                target_entity TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        con.execute(
            """INSERT INTO agent_entity_relations (
                relation_id, source_entity, relation, target_entity, weight,
                metadata, created_at, updated_at
            ) VALUES ('legacy', 'source', 'links', 'target', 1.0, ?, 0.0, 0.0)""",
            (json.dumps({"root": Path(os.path.normcase(root)).as_posix(), "provenance": {"repository_id": "repo-a"}}),),
        )

    migration = run_state_migrations(state_dir)
    assert migration["status"] == "migrated"

    store = MemoryStore(AgentStateStore(db_path))
    assert store.find_relations(source_entity="source", root=root, repository_id="repo-a") == []
    with closing(sqlite3.connect(db_path)) as con:
        assert con.execute(
            "SELECT repository_id FROM agent_entity_relations WHERE relation_id = 'legacy'"
        ).fetchone() == ("",)


def test_n13_memory_delete_preserves_relations_in_another_root_of_the_same_repository(tmp_path: Path):
    store = MemoryStore(AgentStateStore(db_path=tmp_path / "memory.sqlite3"))
    own_root = str(tmp_path / "primary")
    other_root = str(tmp_path / "linked")
    repository_id = "repo-shared"
    record = store.record(MemoryRecord.create(
        kind=MemoryKind.FINDING,
        scope=AgentScope.REPOSITORY,
        key="storage.backend",
        value="fixture backend",
        provenance={"root": own_root, "repository_id": repository_id},
    ))
    store.record_relation("primary-context", "mentions", record.record_id, root=own_root, repository_id=repository_id)
    other = store.record_relation(
        "linked-context", "mentions", record.record_id, root=other_root, repository_id=repository_id,
    )
    assert store.find_relations(record.record_id, root=own_root, repository_id=repository_id)

    assert store.delete(record.record_id, scope=AgentScope.REPOSITORY, root=own_root, repository_id=repository_id)
    assert store.find_relations(record.record_id, root=own_root, repository_id=repository_id) == []
    remaining = store.find_relations(record.record_id, root=other_root, repository_id=repository_id)
    assert [row["relation_id"] for row in remaining] == [other["relation_id"]]


def test_n03_traverse_graph_bounds_computation_and_reports_truncated(tmp_path: Path):
    db_path = tmp_path / "graph_state.sqlite3"
    state_store = AgentStateStore(db_path=db_path)
    state_store._ensure_schema()
    mem_store = MemoryStore(state_store=state_store)

    # Star graph: Root -> Node_1 ... Node_20
    for i in range(1, 21):
        mem_store.record_relation("Root", "links", f"Node_{i}", weight=1.0, root=str(tmp_path), repository_id="repo-test")
        # Cycle back: Node_i -> Root
        mem_store.record_relation(f"Node_{i}", "links", "Root", weight=0.5, root=str(tmp_path), repository_id="repo-test")

    # Max nodes 5 out of 21 reachable nodes
    traversal = mem_store.traverse_graph("Root", max_depth=3, max_nodes=5, root=str(tmp_path), repository_id="repo-test")
    assert traversal["success"] is True
    assert len(traversal["nodes"]) <= 5
    assert traversal["truncated"] is True
    # Edges must only connect the returned nodes
    node_set = set(traversal["nodes"])
    for edge in traversal["edges"]:
        assert edge["source_entity"] in node_set
        assert edge["target_entity"] in node_set


def test_n13_find_relations_supports_simultaneous_source_and_target(tmp_path: Path):
    db_path = tmp_path / "relations_state.sqlite3"
    state_store = AgentStateStore(db_path=db_path)
    state_store._ensure_schema()
    mem_store = MemoryStore(state_store=state_store)

    mem_store.record_relation("ServiceA", "calls", "ServiceB", weight=1.0, root=str(tmp_path), repository_id="repo-test")
    mem_store.record_relation("ServiceA", "calls", "ServiceC", weight=1.0, root=str(tmp_path), repository_id="repo-test")
    mem_store.record_relation("ServiceD", "calls", "ServiceB", weight=1.0, root=str(tmp_path), repository_id="repo-test")

    # Query with both source_entity and target_entity
    res = mem_store.find_relations(source_entity="ServiceA", target_entity="ServiceB", root=str(tmp_path), repository_id="repo-test")
    assert len(res) == 1
    assert res[0]["source_entity"] == "ServiceA"
    assert res[0]["target_entity"] == "ServiceB"


def test_n13_relations_and_graph_traversal_are_repository_scoped(tmp_path: Path):
    state_store = AgentStateStore(db_path=tmp_path / "relations_scope.sqlite3")
    state_store._ensure_schema()
    mem_store = MemoryStore(state_store=state_store)
    root_a = str(tmp_path / "repo")
    root_b = root_a

    with pytest.raises(TypeError, match="repository_id"):
        mem_store.record_relation(
            "ServiceA", "calls", "Unscoped", root=root_a, metadata={"provenance": {"repository_id": "repo-a"}},
        )
    with pytest.raises(ValueError, match="repository_id"):
        mem_store.record_relation("ServiceA", "calls", "Unscoped", root=root_a, repository_id="")

    mem_store.record_relation("ServiceA", "calls", "ServiceB", root=root_a, repository_id="repo-a")
    mem_store.record_relation("ServiceB", "calls", "ServiceC", root=root_b, repository_id="repo-b")
    with closing(sqlite3.connect(state_store.db_path)) as con, con:
        con.execute(
            """INSERT INTO agent_entity_relations (
                relation_id, source_entity, relation, target_entity, weight,
                metadata, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("legacy", "ServiceA", "calls", "LegacySecret", 1.0, "{}", 0.0, 0.0),
        )

    found_a = mem_store.find_relations(
        source_entity="ServiceA", target_entity="ServiceB", root=root_a, repository_id="repo-a"
    )
    found_b = mem_store.find_relations(
        source_entity="ServiceA", target_entity="ServiceB", root=root_b, repository_id="repo-b"
    )
    graph_a = mem_store.traverse_graph("ServiceA", root=root_a, repository_id="repo-a")
    graph_b = mem_store.traverse_graph("ServiceB", root=root_b, repository_id="repo-b")

    assert len(found_a) == 1
    assert found_a[0]["metadata"]["root"] == Path(os.path.normcase(root_a)).as_posix()
    assert found_b == []
    assert graph_a["nodes"] == ["ServiceA", "ServiceB"]
    assert "LegacySecret" not in graph_a["nodes"]
    assert graph_b["nodes"] == ["ServiceB", "ServiceC"]
    with pytest.raises(ValueError, match="absolute path"):
        mem_store.find_relations(root="relative-root", repository_id="repo-a")
