from __future__ import annotations

from pathlib import Path
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_memory import MemoryStore


def test_n03_traverse_graph_bounds_computation_and_reports_truncated(tmp_path: Path):
    db_path = tmp_path / "graph_state.sqlite3"
    state_store = AgentStateStore(db_path=db_path)
    state_store._ensure_schema()
    mem_store = MemoryStore(state_store=state_store)

    # Star graph: Root -> Node_1 ... Node_20
    for i in range(1, 21):
        mem_store.record_relation("Root", "links", f"Node_{i}", weight=1.0)
        # Cycle back: Node_i -> Root
        mem_store.record_relation(f"Node_{i}", "links", "Root", weight=0.5)

    # Max nodes 5 out of 21 reachable nodes
    traversal = mem_store.traverse_graph("Root", max_depth=3, max_nodes=5)
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

    mem_store.record_relation("ServiceA", "calls", "ServiceB", weight=1.0)
    mem_store.record_relation("ServiceA", "calls", "ServiceC", weight=1.0)
    mem_store.record_relation("ServiceD", "calls", "ServiceB", weight=1.0)

    # Query with both source_entity and target_entity
    res = mem_store.find_relations(source_entity="ServiceA", target_entity="ServiceB")
    assert len(res) == 1
    assert res[0]["source_entity"] == "ServiceA"
    assert res[0]["target_entity"] == "ServiceB"
