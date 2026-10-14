from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_memory import MemoryStore
import local_ai_hub.sqlite_support as ss_mod


def test_traverse_graph_executes_single_sql_query(tmp_path: Path) -> None:
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

    # Count SELECT queries executed during traverse_graph
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
    assert len(select_queries) == 1, f"Expected 1 SELECT query, got {len(select_queries)}: {select_queries}"


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
