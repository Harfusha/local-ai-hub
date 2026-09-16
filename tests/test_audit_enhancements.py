import time
from pathlib import Path
from local_ai_hub.swarm import SwarmCoordinator, SwarmState
from local_ai_hub.agent_memory import MemoryStore, MemoryRecord, AgentScope, MemoryKind
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.sqlite_support import clean_quarantined_files
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.leases import ScopeLeaseStore


def test_swarm_coordinator_list_and_cancel(tmp_path):
    leases_db = tmp_path / "leases.sqlite3"
    leases = ScopeLeaseStore(leases_db)
    db_path = tmp_path / "swarm.sqlite3"
    coord = SwarmCoordinator(db_path=db_path, leases=leases)

    disp = coord.dispatch(goal="Implement feature X", target_paths=["src/foo.py"], root=str(tmp_path))
    assert disp["success"] is True
    sid = disp["swarm_id"]

    lst = coord.list_swarms()
    assert lst["success"] is True
    assert lst["count"] == 1
    assert lst["swarms"][0]["swarm_id"] == sid
    assert lst["swarms"][0]["state"] == SwarmState.CODING.value

    # Check lease is held
    held = leases.list(root=str(tmp_path))
    assert len(held) == 1

    # 3. Cancel
    canc = coord.cancel(sid, reason="Cancelled by test")
    assert canc["success"] is True
    assert canc["state"] == SwarmState.FAILED.value

    # Verify status
    st = coord.get_status(sid)
    assert st["state"] == SwarmState.FAILED.value

    # Verify lease released
    held_after = leases.list(root=str(tmp_path))
    assert len(held_after) == 0


def test_agent_memory_auto_linking(tmp_path):
    state_db = tmp_path / "agent_state.sqlite3"
    state_store = AgentStateStore(state_db, enabled=True)
    mem_store = MemoryStore(state_store)

    rec = MemoryRecord.create(
        kind=MemoryKind.DECISION,
        scope=AgentScope.REPOSITORY,
        scope_id="repo_1",
        key="auth_strategy",
        value="Use JWT tokens in src/auth/service.py and refresh tokens in src/auth/refresh.py",
        confidence=0.9,
    )
    saved = mem_store.record(rec)
    assert saved.record_id == rec.record_id

    rels = mem_store.find_relations(source_entity=rec.record_id)
    assert len(rels) >= 2
    rel_types = {r["relation"] for r in rels}
    assert "defines" in rel_types
    assert "scoped_in" in rel_types

    target_rels = mem_store.find_relations(source_entity="auth_strategy")
    target_entities = {r["target_entity"] for r in target_rels}
    assert any("service.py" in t for t in target_entities)


def test_clean_quarantined_files(tmp_path):
    empty_corrupt = tmp_path / "cache.sqlite3.corrupt-12345"
    empty_corrupt.touch()

    fresh_corrupt = tmp_path / "index.sqlite3.corrupt-67890"
    fresh_corrupt.write_text("corrupted content", encoding="utf-8")

    res = clean_quarantined_files(tmp_path, max_age_seconds=3600, remove_empty=True)
    assert res["success"] is True
    assert res["pruned_count"] == 1
    assert empty_corrupt.name in res["files"]
    assert not empty_corrupt.exists()
    assert fresh_corrupt.exists()

    res2 = clean_quarantined_files(tmp_path, max_age_seconds=0, remove_empty=True)
    assert res2["pruned_count"] == 1
    assert fresh_corrupt.name in res2["files"]
    assert not fresh_corrupt.exists()


def test_repo_tools_hash_cache(tmp_path):
    test_file = tmp_path / "sample.py"
    test_file.write_text("print('hello world')", encoding="utf-8")

    cfg = {"server": {"state_dir": str(tmp_path)}}
    tools = RepositoryTools(cfg)

    h1 = tools._hash_file_only(test_file)
    assert len(h1) == 64

    initial_hits = tools.snapshot_hits
    h2 = tools._hash_file_only(test_file)
    assert h2 == h1
    assert tools.snapshot_hits == initial_hits + 1


def test_polyglot_brace_folding_and_skeletonize(tmp_path):
    go_code = """package main

type Config struct {
    Port int
    Host string
}

func (c *Config) Address() string {
    return fmt.Sprintf("%s:%d", c.Host, c.Port)
}

func main() {
    cfg := &Config{Port: 8080, Host: "localhost"}
    println(cfg.Address())
}
"""
    engine = DeterministicEngine({"server": {"state_dir": str(tmp_path)}})
    res = engine.skeletonize_code(go_code)
    assert res["success"] is True
    assert res.get("polyglot") is True
    assert res["savings_ratio"] > 0
    skel = res["skeleton_code"]
    assert "type Config struct {" in skel
    assert "Port int" in skel
    assert "/* ... */" in skel

    rust_code = """pub struct Greeter {
    name: String,
}

impl Greeter {
    pub fn greet(&self) -> String {
        format!("Hello, {}!", self.name)
    }
}
"""
    res_rs = engine.skeletonize_code(rust_code)
    assert res_rs["success"] is True
    assert res_rs.get("polyglot") is True
    assert "pub struct Greeter {" in res_rs["skeleton_code"]
    assert "/* ... */" in res_rs["skeleton_code"]


def test_code_index_find_dead_code(tmp_path):
    cfg = {"server": {"state_dir": str(tmp_path)}}
    tools = RepositoryTools(cfg)
    idx = CodeIndex(cfg, tools)

    root = str(tmp_path)
    con = idx._connect()
    with con:
        con.execute(
            "INSERT INTO symbols (root, path, name, kind, line, end_line, container, name_path, signature, access, docstring) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (root, "src/unused.py", "orphan_function", "function", 10, 20, "", "orphan_function", "()", "private", ""),
        )
        con.execute(
            "INSERT INTO symbols (root, path, name, kind, line, end_line, container, name_path, signature, access, docstring) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (root, "src/used.py", "used_function", "function", 1, 5, "", "used_function", "()", "public", ""),
        )
        con.execute(
            "INSERT INTO refs (root, path, name, line, kind) VALUES (?, ?, ?, ?, ?)",
            (root, "src/main.py", "used_function", 15, "call"),
        )
    con.close()

    res = idx.find_dead_code(root)
    assert res["success"] is True
    assert res["candidate_count"] == 1
    assert res["dead_code"][0]["name"] == "orphan_function"
