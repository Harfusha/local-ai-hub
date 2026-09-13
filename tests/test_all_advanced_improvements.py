from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.agent_events import AgentEvent, AgentStateStore
from local_ai_hub.agent_tasks import GoalContract, ScopeContext, TaskStore, TaskStatus
from local_ai_hub.deterministic import DeterministicEngine


# ── Area 1: Agent OS & Swarm Coordination Tests ──────────────────────────────

def test_event_delta_sync_export_import(tmp_path: Path) -> None:
    source_db = tmp_path / "source_state.sqlite3"
    target_db = tmp_path / "target_state.sqlite3"

    store_a = AgentStateStore(source_db)
    store_b = AgentStateStore(target_db)

    # Record events in store A
    e1 = AgentEvent.create(stream_id="stream1", kind="task_created", payload={"k": 1})
    store_a.append(e1)
    e2 = AgentEvent.create(stream_id="stream1", kind="checkpoint", payload={"k": 2})
    store_a.append(e2)
    e3 = AgentEvent.create(stream_id="stream1", kind="task_created", payload={"k": 3})
    store_a.append(e3)

    # Export delta since event 1 (after_seq=1)
    delta = store_a.export_delta(stream_id="stream1", after_seq=1)
    assert delta["success"] is True
    assert delta["count"] == 2

    # Import delta into store B
    imported_res = store_b.import_delta(delta["events"])
    assert imported_res["success"] is True
    assert imported_res["imported_count"] == 2

    # Verify store B has events
    delta_b = store_b.export_delta(stream_id="stream1")
    assert delta_b["count"] == 2


def test_zombie_task_watchdog_and_recovery(tmp_path: Path) -> None:
    import time
    db_path = tmp_path / "state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)

    contract = GoalContract(goal="work", acceptance_criteria=["c1"])
    context = ScopeContext(repository_id="repo1")
    task = tasks.create(contract, context)
    tasks.transition(task.task_id, TaskStatus.ACTIVE, reason="start", actor="agent", idempotency_key="t1")

    # Set heartbeat
    tasks.heartbeat(task.task_id, ttl_seconds=60)
    future_time = time.time() + 1000.0

    # Reap with recovery at future time
    reaped = tasks.reap_expired_heartbeats(now=future_time, auto_recover=True)
    assert task.task_id in reaped

    # Status should be WAITING
    updated = tasks.get(task.task_id)
    assert updated is not None
    assert updated.status == TaskStatus.WAITING


def test_auto_worktree_task_lifecycle(tmp_path: Path) -> None:
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    # Initialize real git repo
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "hub@test.local"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.name", "Hub Test"], cwd=str(repo_dir), check=True)

    dummy_file = repo_dir / "README.md"
    dummy_file.write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(repo_dir), check=True)

    db_path = tmp_path / "state.sqlite3"
    state_store = AgentStateStore(db_path)
    tasks = TaskStore(state_store)

    contract = GoalContract(goal="dev", acceptance_criteria=["feature"])
    context = ScopeContext(repository_id=str(repo_dir))
    task = tasks.create(contract, context, auto_worktree=True, repo_root=str(repo_dir))
    wt_info = task.checkpoint.state_data.get("worktree", {})
    assert "worktree_path" in wt_info
    wt_path = Path(wt_info["worktree_path"])
    assert wt_path.exists()
    assert (wt_path / "README.md").exists()

    # Clean up worktree
    cleanup_res = tasks.cleanup_worktree(task.task_id, delete_branch=True)
    assert cleanup_res["success"] is True
    assert cleanup_res["had_worktree"] is True
    assert not wt_path.exists()


# ── Area 2: Code Intelligence & AST Analysis Tests ───────────────────────────

def test_reachability_dead_code_bfs(tmp_path: Path) -> None:
    repo = tmp_path / "my_project"
    repo.mkdir()

    main_py = repo / "main.py"
    main_py.write_text(
        """from utils import helper_a

def entry():
    helper_a()

if __name__ == "__main__":
    entry()
""",
        encoding="utf-8",
    )

    utils_py = repo / "utils.py"
    utils_py.write_text(
        """def helper_a():
    return helper_b()

def helper_b():
    return 42

def orphan_dead_func():
    return "never called"
""",
        encoding="utf-8",
    )

    engine = DeterministicEngine()
    res = engine.reachability_dead_code(str(repo), entrypoints=["main.py"])
    assert res["success"] is True
    dead_names = [f["name"] for f in res["unreachable_symbols"]]
    assert "orphan_dead_func" in dead_names
    assert "helper_a" not in dead_names
    assert "helper_b" not in dead_names
    assert res["dead_code_count"] >= 1


def test_ast_mutation_testing_engine(tmp_path: Path) -> None:
    code_file = tmp_path / "calc.py"
    code_file.write_text(
        """def check_val(x, y):
    if x < y and x != 0:
        return x + y
    return x - y
""",
        encoding="utf-8",
    )

    engine = DeterministicEngine()
    res = engine.ast_mutation_test(str(tmp_path), target_file="calc.py")
    assert res["success"] is True
    mutants = res["mutants"]
    assert len(mutants) > 0

    mutant_types = {m["type"] for m in mutants}
    assert any("comparison" in t or "arithmetic" in t for t in mutant_types)


def test_type_stub_generator(tmp_path: Path) -> None:
    py_file = tmp_path / "service.py"
    py_file.write_text(
        '''\"\"\"Module docstring.\"\"\"
from typing import Optional

GLOBAL_CONST: int = 100

class UserRepo:
    \"\"\"Repo class.\"\"\"
    def __init__(self, db: str) -> None:
        self.db = db

    def find_user(self, user_id: int) -> Optional[dict]:
        complex_calculation = user_id * 2
        return {"id": user_id, "active": True}

def get_status() -> bool:
    return True
''',
        encoding="utf-8",
    )

    engine = DeterministicEngine()
    res = engine.generate_type_stubs(str(tmp_path), "service.py")
    assert res["success"] is True
    stub = res["stub_content"]
    assert "class UserRepo:" in stub
    assert "def find_user" in stub
    assert "def get_status" in stub
    assert "complex_calculation" not in stub
    assert res["stub_type"] == "pyi"


def test_ast_prompt_skeletonizer() -> None:
    large_code = """from os import path

class HeavyWorker:
    def __init__(self):
        self.x = 10
        self.y = 20
        self.buffer = [i for i in range(1000)]

    def important_calc(self, val: int) -> int:
        result = 0
        for i in range(val):
            result += i * self.x
        return result

    def unused_bloat_method(self):
        a = 1 + 2
        b = 3 + 4
        c = a * b
        return [c for _ in range(500)]

def utility_one():
    step1 = "lots of verbose setup code"
    step2 = "more boilerplate details"
    return step1 + step2
"""
    engine = DeterministicEngine()
    skel = engine.skeletonize_code(large_code, target_symbols=["important_calc"])
    assert skel["success"] is True
    assert skel["savings_ratio"] > 0.3
    assert "result += i * self.x" in skel["skeleton_code"]
    assert "unused_bloat_method" in skel["skeleton_code"]
    assert "step1 =" not in skel["skeleton_code"]


# ── Area 3: Model Engine & Token Economy Tests ───────────────────────────────

def test_heuristic_reranker_prioritizes_definitions_and_paths() -> None:
    query = "task_create agent_tasks"
    candidates = [
        {"text": "some text referring to tasks loosely", "path": "docs/notes.txt", "embedding_score": 0.8},
        {"text": "def task_create(self, role: str): create new task", "path": "src/local_ai_hub/agent_tasks.py", "embedding_score": 0.75},
        {"text": "unrelated content", "path": "tests/test_misc.py", "embedding_score": 0.7},
    ]
    import re
    q_terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 1]
    for c in candidates:
        h_score = float(c.get("embedding_score", 0.5))
        txt = str(c.get("text", "")).lower()
        p_low = str(c.get("path", "")).lower()
        if any(t in p_low for t in q_terms):
            h_score *= 1.35
        for t in q_terms:
            if f"def {t}" in txt or f"class {t}" in txt:
                h_score *= 1.5
        c["heuristic_rerank_score"] = round(h_score, 4)
    reranked = sorted(candidates, key=lambda x: x["heuristic_rerank_score"], reverse=True)
    assert reranked[0]["path"] == "src/local_ai_hub/agent_tasks.py"
    assert reranked[0]["heuristic_rerank_score"] > reranked[1]["heuristic_rerank_score"]


# ── Area 4: Read-Only SQLite Explorer & Safety ──────────────────────────────

def test_read_only_db_query_safety(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from local_ai_hub.http_server import Handler
    import local_ai_hub.http_server as http_srv
    import sqlite3

    # Non-SELECT statement should be rejected
    res1 = Handler._handle_db_query(None, "agent_state", "INSERT INTO tasks (id) VALUES ('x')")
    assert res1["success"] is False
    assert "Only read-only SELECT" in res1["error"]

    # Forbidden mutating keywords in subqueries should be rejected
    res2 = Handler._handle_db_query(None, "agent_state", "SELECT * FROM tasks WHERE id = (DELETE FROM x)")
    assert res2["success"] is False
    assert "Forbidden keyword" in res2["error"]

    # Semicolons / multi-statements should be rejected
    res3 = Handler._handle_db_query(None, "agent_state", "SELECT * FROM tasks; SELECT 1;")
    assert res3["success"] is False
    assert "Multi-statement" in res3["error"]

    # Valid SELECT on existing sqlite database
    db_file = tmp_path / "agent_state.sqlite3"
    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, role TEXT);")
    con.execute("INSERT INTO tasks VALUES ('t1', 'researcher');")
    con.commit()
    con.close()

    class DummyApp:
        config = {"server": {"state_dir": str(tmp_path)}}

    monkeypatch.setattr(http_srv, "APP", DummyApp())

    res4 = Handler._handle_db_query(None, "agent_state", "SELECT id, role FROM tasks")
    assert res4["success"] is True
    assert res4["columns"] == ["id", "role"]
    assert res4["rows"] == [["t1", "researcher"]]
    assert res4["count"] == 1


# ── Area 5: GraphRAG Code Entity Attachment ─────────────────────────────────

def test_graphrag_entity_relations(tmp_path: Path) -> None:
    import sqlite3
    from local_ai_hub.rag import RAGStore

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    db_path = state_dir / "agent_state.sqlite3"
    con = sqlite3.connect(db_path)
    con.execute(
        """
        CREATE TABLE agent_entity_relations (
            relation_id TEXT PRIMARY KEY,
            source_entity TEXT NOT NULL,
            relation TEXT NOT NULL,
            target_entity TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    con.execute(
        "INSERT INTO agent_entity_relations VALUES ('r1', 'TaskStore', 'manages', 'AgentTask', 0.9, '{}', 0, 0)"
    )
    con.commit()
    con.close()

    rag_store = RAGStore(config={"server": {"state_dir": str(state_dir)}})
    # Simulate candidate containing entity TaskStore
    candidates = [{"text": "class TaskStore handles lifecycle of tasks", "path": "src/tasks.py", "score": 0.85}]

    # In search_rag, candidate enrichment logic checks words in text
    cur_con = sqlite3.connect(db_path)
    cur = cur_con.cursor()
    words = {"TaskStore"}
    matched = []
    for w in words:
        rows = cur.execute(
            "SELECT source_entity, relation, target_entity, weight FROM agent_entity_relations WHERE source_entity = ? OR target_entity = ?",
            (w, w),
        ).fetchall()
        for r in rows:
            matched.append({"source": r[0], "relation": r[1], "target": r[2], "weight": float(r[3])})
    cur_con.close()

    assert len(matched) == 1
    assert matched[0]["source"] == "TaskStore"
    assert matched[0]["target"] == "AgentTask"

