"""Tests for dependency graph centrality and architectural hub detection."""

from src.local_ai_hub.preprocess_graph import (
    analyze_repo_graph,
    compute_pagerank,
)


def test_compute_pagerank_simple_graph():
    # A points to B and C; B points to C; C points to A
    edges = {
        "A": ["B", "C"],
        "B": ["C"],
        "C": ["A"],
    }
    nodes = ["A", "B", "C"]
    ranks = compute_pagerank(edges, nodes)
    assert len(ranks) == 3
    # Sum of PageRanks should equal approximately 1.0
    assert abs(sum(ranks.values()) - 1.0) < 1e-4
    # C has incoming edges from both A and B, so C should have high rank
    assert ranks["C"] > ranks["B"]


def test_analyze_repo_graph_hub_detection():
    # Backbone module "core.py" is imported by many worker modules
    nodes = ["core.py", "w1.py", "w2.py", "w3.py", "w4.py", "leaf.py"]
    edges = {
        "w1.py": ["core.py"],
        "w2.py": ["core.py"],
        "w3.py": ["core.py"],
        "w4.py": ["core.py"],
        "leaf.py": ["w1.py"],
    }
    result = analyze_repo_graph(edges, nodes, hub_top_percent=0.25, min_in_degree_for_hub=2)
    assert result.is_hub("core.py") is True
    assert result.is_hub("leaf.py") is False
    assert result.get_score("core.py") > result.get_score("leaf.py")
    assert "core.py" in result.top_backbones
