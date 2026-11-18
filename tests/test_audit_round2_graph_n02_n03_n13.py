from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_memory import MemoryStore


def test_n03_traverse_graph_bounds_computation_and_reports_truncated(tmp_path: Path):
    db_path = tmp_path / "graph_state.sqlite3"
    state_store = AgentStateStore(db_path=db_path)
    state_store._ensure_schema()
    mem_store = MemoryStore(state_store=state_store)

    # Star graph: Root -> Node_1 ... Node_20
    for i in range(1, 21):
        mem_store.record_relation("Root", "links", f"Node_{i}", weight=1.0, root=str(tmp_path))
        # Cycle back: Node_i -> Root
        mem_store.record_relation(f"Node_{i}", "links", "Root", weight=0.5, root=str(tmp_path))

    # Max nodes 5 out of 21 reachable nodes
    traversal = mem_store.traverse_graph("Root", max_depth=3, max_nodes=5, root=str(tmp_path))
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

    mem_store.record_relation("ServiceA", "calls", "ServiceB", weight=1.0, root=str(tmp_path))
    mem_store.record_relation("ServiceA", "calls", "ServiceC", weight=1.0, root=str(tmp_path))
    mem_store.record_relation("ServiceD", "calls", "ServiceB", weight=1.0, root=str(tmp_path))

    # Query with both source_entity and target_entity
    res = mem_store.find_relations(source_entity="ServiceA", target_entity="ServiceB", root=str(tmp_path))
    assert len(res) == 1
    assert res[0]["source_entity"] == "ServiceA"
    assert res[0]["target_entity"] == "ServiceB"


def test_n13_relations_and_graph_traversal_are_repository_scoped(tmp_path: Path):
    state_store = AgentStateStore(db_path=tmp_path / "relations_scope.sqlite3")
    state_store._ensure_schema()
    mem_store = MemoryStore(state_store=state_store)
    root_a = str(tmp_path / "repo-a")
    root_b = str(tmp_path / "repo-b")

    mem_store.record_relation("ServiceA", "calls", "ServiceB", root=root_a)
    mem_store.record_relation("ServiceB", "calls", "ServiceC", root=root_b)
    with closing(sqlite3.connect(state_store.db_path)) as con, con:
        con.execute(
            """INSERT INTO agent_entity_relations (
                relation_id, source_entity, relation, target_entity, weight,
                metadata, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("legacy", "ServiceA", "calls", "LegacySecret", 1.0, "{}", 0.0, 0.0),
        )

    found_a = mem_store.find_relations(
        source_entity="ServiceA", target_entity="ServiceB", root=root_a
    )
    found_b = mem_store.find_relations(
        source_entity="ServiceA", target_entity="ServiceB", root=root_b
    )
    graph_a = mem_store.traverse_graph("ServiceA", root=root_a)
    graph_b = mem_store.traverse_graph("ServiceB", root=root_b)

    assert len(found_a) == 1
    assert found_a[0]["metadata"]["root"] == root_a.replace("\\", "/").casefold()
    assert found_b == []
    assert graph_a["nodes"] == ["ServiceA", "ServiceB"]
    assert "LegacySecret" not in graph_a["nodes"]
    assert graph_b["nodes"] == ["ServiceB", "ServiceC"]
    with pytest.raises(ValueError, match="absolute path"):
        mem_store.find_relations(root="relative-root")
