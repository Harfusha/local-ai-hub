"""Unit tests for Universal Memory Knowledge Graph."""

import json
from local_ai_hub.memory_graph import (
    MemoryEdge,
    MemoryNode,
    UniversalMemoryGraph,
)


def test_memory_graph_traversal() -> None:
    graph = UniversalMemoryGraph()

    n1 = MemoryNode(id="n1", node_type="architecture", content="Core Hub", scope="hub")
    n2 = MemoryNode(id="n2", node_type="invariant", content="Keep tests fast", scope="hub/tests")
    n3 = MemoryNode(id="n3", node_type="incident", content="OOM on 3B training", scope="hub/models")

    graph.add_node(n1)
    graph.add_node(n2)
    graph.add_node(n3)

    graph.add_edge(MemoryEdge(source="n1", target="n2", relation="depends_on"))
    graph.add_edge(MemoryEdge(source="n2", target="n3", relation="applies_to"))

    traversed = graph.traverse(start_id="n1", max_depth=2)
    traversed_ids = [n.id for n in traversed]
    assert "n2" in traversed_ids
    assert "n3" in traversed_ids


def test_subsystem_card_generation() -> None:
    graph = UniversalMemoryGraph()

    graph.add_node(MemoryNode(id="inv1", node_type="invariant", content="[INVARIANT] Never unconstrain pytest", scope="tests"))
    graph.add_node(MemoryNode(id="fact1", node_type="fact", content="Preprocessing uses 3B Qwen coder", scope="preprocessing"))
    graph.add_node(MemoryNode(id="inc1", node_type="incident", content="[INCIDENT] OOM on long sequence in training", scope="preprocessing/training"))

    card = graph.generate_subsystem_card("preprocessing")
    assert card["subsystem"] == "preprocessing"
    assert card["total_nodes"] == 2
    assert len(card["facts"]) == 1
    assert len(card["incidents"]) == 1


def test_conflict_detection() -> None:
    graph = UniversalMemoryGraph()

    inv = MemoryNode(id="inv_wal", node_type="invariant", content="SQLite must always use WAL mode", scope="db")
    inc = MemoryNode(id="inc_lock", node_type="incident", content="DB lock failure when WAL disabled", scope="db")

    graph.add_node(inv)
    graph.add_node(inc)
    graph.add_edge(MemoryEdge(source="inc_lock", target="inv_wal", relation="violates"))

    conflicts = graph.detect_conflicts()
    assert len(conflicts) == 1
    assert conflicts[0]["type"] == "explicit_violation"
    assert conflicts[0]["source_type"] == "incident"
    assert conflicts[0]["target_type"] == "invariant"


def test_serialization_roundtrip() -> None:
    graph = UniversalMemoryGraph()
    n1 = MemoryNode(id="node_a", node_type="fact", content="Test fact A", scope="core", tags=("tag1", "tag2"))
    n2 = MemoryNode(id="node_b", node_type="rule", content="Test rule B", scope="core")
    graph.add_node(n1)
    graph.add_node(n2)
    graph.add_edge(MemoryEdge(source="node_a", target="node_b", relation="depends_on"))

    data = graph.to_dict()
    reconstructed = UniversalMemoryGraph.from_dict(data)

    assert reconstructed.get_node("node_a") is not None
    assert reconstructed.get_node("node_b") is not None
    neighbors = reconstructed.neighbors("node_a", direction="out")
    assert len(neighbors) == 1
    assert neighbors[0][0].id == "node_b"
