from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_memory import MemoryStore
import local_ai_hub.sqlite_support as ss_mod


def test_traverse_graph_bounds_selects_by_node_limit(tmp_path: Path) -> None:
    state = AgentStateStore(tmp_path / "state.sqlite3")
    store = MemoryStore(state)
    store._init_table()

    # Create a small graph:
    # A -> B -> C -> D
    # A -> E
    store.record_relation("A", "connects", "B", weight=1.0)
    store.record_relation("B", "connects", "C", weight=0.9)
    store.record_relation("C", "connects", "D", weight=0.8)
    store.record_relation("A", "connects", "E", weight=0.5)

    # Count SELECT queries executed during traverse_graph; every expanded node
    # must be covered by the explicit max_nodes bound.
    statements: list[str] = []
    orig_connect = ss_mod.connect_sqlite

    def traced_connect(*args, **kwargs):
        con = orig_connect(*args, **kwargs)
        con.set_trace_callback(lambda stmt: statements.append(stmt) if "SELECT" in stmt.upper() else None)
        return con

    import local_ai_hub.agent_memory as am_mod
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(am_mod, "connect_sqlite", traced_connect)
        res = store.traverse_graph("A", max_depth=2, max_nodes=10)

    assert res["success"] is True
    assert "A" in res["nodes"]
    assert "B" in res["nodes"]
    assert "E" in res["nodes"]
    assert "C" in res["nodes"]

    select_queries = [s for s in statements if "SELECT" in s.upper()]
    assert len(select_queries) <= 11, f"SELECT count exceeded max_nodes + 1: {len(select_queries)}"


def test_traverse_graph_bounded_limits_and_cycles(tmp_path: Path) -> None:
    state = AgentStateStore(tmp_path / "state.sqlite3")
    store = MemoryStore(state)
    store._init_table()

    # Create cycle: X -> Y -> Z -> X
    store.record_relation("X", "points_to", "Y", weight=1.0)
    store.record_relation("Y", "points_to", "Z", weight=1.0)
    store.record_relation("Z", "points_to", "X", weight=1.0)

    res = store.traverse_graph("X", max_depth=3, max_nodes=50)
    assert res["success"] is True
    assert set(res["nodes"]) == {"X", "Y", "Z"}
    assert len(res["edges"]) >= 3

    # Test max_nodes limit = 2
    res_bounded = store.traverse_graph("X", max_depth=3, max_nodes=2)
    assert len(res_bounded["nodes"]) == 2


def test_traverse_graph_edges_stay_within_returned_node_limit(tmp_path: Path) -> None:
    state = AgentStateStore(tmp_path / "state.sqlite3")
    store = MemoryStore(state)
    store._init_table()

    store.record_relation("A", "connects", "B", weight=1.0)
    store.record_relation("A", "connects", "C", weight=0.9)
    store.record_relation("B", "connects", "D", weight=0.8)

    result = store.traverse_graph("A", max_depth=2, max_nodes=2)

    nodes = set(result["nodes"])
    assert result["truncated"] is True
    assert len(nodes) == 2
    assert len(result["edges"]) == 1
    assert all(edge["source_entity"] in nodes and edge["target_entity"] in nodes for edge in result["edges"])
