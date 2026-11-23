"""Unit tests for Hierarchical GraphRAG Community Detection."""

from local_ai_hub.graphrag_communities import HierarchicalGraphRAG


def test_graphrag_community_clustering() -> None:
    graph = HierarchicalGraphRAG(resolution=1.0)

    # Cluster 1: Preprocessing cluster
    graph.add_edge("preprocess/cards.py", "preprocess/ast.py", weight=2.0)
    graph.add_edge("preprocess/ast.py", "preprocess/graph.py", weight=3.0)
    graph.add_edge("preprocess/graph.py", "preprocess/watchdog.py", weight=2.0)
    graph.add_edge("preprocess/cards.py", "preprocess/watchdog.py", weight=1.5)

    # Cluster 2: Storage cluster
    graph.add_edge("storage/db.py", "storage/mmap.py", weight=3.0)
    graph.add_edge("storage/mmap.py", "storage/wal.py", weight=3.0)
    graph.add_edge("storage/db.py", "storage/wal.py", weight=2.0)

    # Weak bridge between clusters
    graph.add_edge("preprocess/cards.py", "storage/db.py", weight=0.2)

    hierarchy = graph.detect_communities(max_levels=2)
    assert 1 in hierarchy
    l1_comms = hierarchy[1]
    assert len(l1_comms) >= 2

    # Check members grouped into domain subsystems
    preprocess_members = set()
    storage_members = set()
    for c in l1_comms:
        if "preprocess" in c.name.lower():
            preprocess_members.update(c.members)
        if "storage" in c.name.lower():
            storage_members.update(c.members)

    assert "preprocess/cards.py" in preprocess_members
    assert "preprocess/ast.py" in preprocess_members
    assert "preprocess/graph.py" in preprocess_members
    assert "preprocess/watchdog.py" in preprocess_members

    assert "storage/db.py" in storage_members
    assert "storage/mmap.py" in storage_members
    assert "storage/wal.py" in storage_members


def test_graphrag_empty_and_single_edge() -> None:
    graph = HierarchicalGraphRAG()
    empty_res = graph.detect_communities()
    assert empty_res == {0: []}

    graph.add_edge("a.py", "b.py", weight=1.0)
    res = graph.detect_communities()
    assert 1 in res
    assert len(res[1]) == 1
    assert "a.py" in res[1][0].members
    assert "b.py" in res[1][0].members
