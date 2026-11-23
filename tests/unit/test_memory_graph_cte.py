from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
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
    store.record_relation("A", "connects", "B", weight=1.0, root=str(tmp_path), repository_id="repo-graph")
    store.record_relation("B", "connects", "C", weight=0.9, root=str(tmp_path), repository_id="repo-graph")
    store.record_relation("C", "connects", "D", weight=0.8, root=str(tmp_path), repository_id="repo-graph")
    store.record_relation("A", "connects", "E", weight=0.5, root=str(tmp_path), repository_id="repo-graph")

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
        res = store.traverse_graph("A", max_depth=2, max_nodes=10, root=str(tmp_path), repository_id="repo-graph")

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
    store.record_relation("X", "points_to", "Y", weight=1.0, root=str(tmp_path), repository_id="repo-graph")
    store.record_relation("Y", "points_to", "Z", weight=1.0, root=str(tmp_path), repository_id="repo-graph")
    store.record_relation("Z", "points_to", "X", weight=1.0, root=str(tmp_path), repository_id="repo-graph")

    res = store.traverse_graph("X", max_depth=3, max_nodes=50, root=str(tmp_path), repository_id="repo-graph")
    assert res["success"] is True
    assert set(res["nodes"]) == {"X", "Y", "Z"}
    assert len(res["edges"]) >= 3

    # Test max_nodes limit = 2
    res_bounded = store.traverse_graph("X", max_depth=3, max_nodes=2, root=str(tmp_path), repository_id="repo-graph")
    assert len(res_bounded["nodes"]) == 2


def test_traverse_graph_edges_stay_within_returned_node_limit(tmp_path: Path) -> None:
    state = AgentStateStore(tmp_path / "state.sqlite3")
    store = MemoryStore(state)
    store._init_table()

    store.record_relation("A", "connects", "B", weight=1.0, root=str(tmp_path), repository_id="repo-graph")
    store.record_relation("A", "connects", "C", weight=0.9, root=str(tmp_path), repository_id="repo-graph")
    store.record_relation("B", "connects", "D", weight=0.8, root=str(tmp_path), repository_id="repo-graph")

    result = store.traverse_graph("A", max_depth=2, max_nodes=2, root=str(tmp_path), repository_id="repo-graph")

    nodes = set(result["nodes"])
    assert result["truncated"] is True
    assert len(nodes) == 2
    assert len(result["edges"]) == 1
    assert all(edge["source_entity"] in nodes and edge["target_entity"] in nodes for edge in result["edges"])


def test_traverse_graph_stops_reading_neighbors_at_node_limit(tmp_path: Path, monkeypatch) -> None:
    from local_ai_hub import agent_memory as memory_module

    store = MemoryStore(AgentStateStore(tmp_path / "state.sqlite3"))
    root, repository_id = str(tmp_path), "repo-graph"
    for index in range(20):
        store.record_relation("center", "connects", f"node-{index}", root=root, repository_id=repository_id)

    rows_read = 0

    class GraphRows:
        def __init__(self, cursor: sqlite3.Cursor, neighbors: bool):
            self.cursor = cursor
            self.neighbors = neighbors

        def __iter__(self):
            nonlocal rows_read
            for row in self.cursor:
                if self.neighbors:
                    rows_read += 1
                yield row

        def fetchall(self):
            pytest.fail("graph queries must consume their cursors incrementally")

        def close(self):
            self.cursor.close()

    def connect(*args, **kwargs):
        con = ss_mod.connect_sqlite(*args, **kwargs)

        def execute(sql, params):
            cursor = con.execute(sql, params)
            return GraphRows(cursor, neighbors=sql.lstrip().startswith("SELECT CASE"))

        return SimpleNamespace(execute=execute, close=con.close)

    monkeypatch.setattr(memory_module, "connect_sqlite", connect)
    result = store.traverse_graph("center", root=root, repository_id=repository_id, max_nodes=3)

    assert result["truncated"] is True
    assert result["total_nodes"] == 3
    assert result["total_edges"] == 2
    assert rows_read == 3


@pytest.mark.parametrize("extra_edges", [0, 1])
def test_traverse_graph_caps_parallel_edges_and_keeps_highest_weights(tmp_path: Path, extra_edges: int) -> None:
    db_path = tmp_path / "state.sqlite3"
    store = MemoryStore(AgentStateStore(db_path))
    root, repository_id = str(tmp_path), "repo-graph"
    edge = store.record_relation("A", "connects", "B", weight=1000, root=root, repository_id=repository_id)
    with closing(sqlite3.connect(db_path)) as con, con:
        con.executemany(
            """INSERT INTO agent_entity_relations (
                   relation_id, repository_id, source_entity, relation, target_entity,
                   weight, metadata, created_at, updated_at
               ) SELECT ?, repository_id, source_entity, relation, target_entity,
                        ?, metadata, created_at, updated_at
                 FROM agent_entity_relations WHERE relation_id = ?""",
            [(f"parallel-{i}", i, edge["relation_id"]) for i in range(999 + extra_edges)],
        )

    graph = store.traverse_graph("A", root=root, repository_id=repository_id, max_nodes=2)

    assert graph["nodes"] == ["A", "B"]
    assert graph["truncated"] is bool(extra_edges)
    assert graph["total_edges"] == len(graph["edges"]) == 1000
    assert graph["edges"][0]["weight"] == 1000
    assert graph["edges"][-1]["weight"] == extra_edges
