import sqlite3
import threading
from contextlib import closing

from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.learning import UsageLearner
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices
from tools.benchmark_preprocess_demand import run


def test_file_cards_prioritize_learned_queries_but_keep_regular_work(tmp_path):
    root = str(tmp_path / "repo")
    db = tmp_path / "pre.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, size INTEGER, card_key TEXT, last_accessed_at REAL)")
        con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED, path UNINDEXED, content)")
        for name in ["a.py", "b.py", "c.py", "z_hot.py"]:
            con.execute("INSERT INTO file_refs VALUES(?,?,10,NULL,0)", (root, name))
            con.execute("INSERT INTO source_fts VALUES(?,?,?)", (root, name, "rare_demand" if name == "z_hot.py" else "other"))
        con.commit()

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    class Learner:
        enabled = True
        def hot_queries(self, root, limit):
            return ["rare_demand"]

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._connect = connect
    pre._db_lock = threading.RLock()
    pre.learner = Learner()
    pre.repo_tools = RepositoryTools({})
    pre.cfg = {}

    paths = [row["path"] for row in pre._find_next_files(root, 2)]

    assert paths == ["z_hot.py", "a.py"]
    other = str(tmp_path / "other")
    with closing(connect()) as con:
        con.execute("INSERT INTO file_refs VALUES(?,?,10,NULL,0)", (other, "a.py"))
        con.execute("INSERT INTO file_refs VALUES(?,?,10,NULL,0)", (other, "z_hot.py"))
        con.execute("INSERT INTO source_fts VALUES(?,?,?)", (other, "z_hot.py", "unrelated"))
        con.commit()
    assert [row["path"] for row in pre._find_next_files(other, 2)] == ["a.py", "z_hot.py"]
    pre.learner.enabled = False
    assert [row["path"] for row in pre._find_next_files(root, 2)] == ["a.py", "b.py"]


def test_rag_batches_reserve_regular_work_when_demand_is_hot(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    db = tmp_path / "pre.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, size INTEGER, content_hash TEXT, needs_hash INTEGER, rag_hash TEXT, last_accessed_at REAL)")
        con.execute("CREATE TABLE source_index(root TEXT, path TEXT, content_hash TEXT, text TEXT)")
        con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED, path UNINDEXED, content)")
        for name in ["a.py", "b.py", "z_hot.py"]:
            (root / name).write_text("body", encoding="utf-8")
            con.execute("INSERT INTO file_refs VALUES(?,?,10,'hash',0,NULL,0)", (str(root), name))
            con.execute("INSERT INTO source_fts VALUES(?,?,?)", (str(root), name, "rare_demand" if name == "z_hot.py" else "other"))
        con.commit()

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    class Learner:
        enabled = True
        def hot_queries(self, root, limit):
            return ["rare_demand"]

    class Rag:
        def index_paths_step(self, root, *, workspace, paths, should_yield, content_overrides):
            self.paths = paths
            return {"preempted": True}

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._connect, pre._db_lock = connect, threading.RLock()
    pre._stats_lock, pre._stats = threading.RLock(), {"rag_steps": 0}
    pre._yield = lambda: False
    pre.learner, pre.repo_tools, pre.cfg = Learner(), RepositoryTools({}), {"rag_files_per_step": 2}
    pre.deterministic, pre.rag = None, Rag()

    assert pre._step_rag({"root": str(root), "workspace": "fixture"}) is False
    assert pre.rag.paths == ["z_hot.py", "a.py"]


def test_demand_benchmark_reports_actual_batch_selection():
    result = run(files=32, batch_size=4)
    assert result["baseline"]["batches_to_hot"] == 8
    assert result["demand"]["batches_to_hot"] == 1
    assert result["demand"]["regular_files_in_first_batch"] >= 1
    assert result["baseline"]["batches_to_complete"] == 8
    assert result["demand"]["batches_to_complete"] == 8
    assert result["baseline"]["completed_files"] == 32
    assert result["demand"]["completed_files"] == 32
    assert result["baseline"]["unprocessed_files"] == 0
    assert result["demand"]["unprocessed_files"] == 0


def test_real_search_recording_drives_preprocessing_priority(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    for name, body in [("a.py", "ordinary\n"), ("b.py", "ordinary\n"), ("z_hot.py", "rare_demand\n")]:
        (root / name).write_text(body, encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")},
              "preprocessing": {"enabled": False}, "rag": {"extensions": [".py"]}}
    learner = UsageLearner(config)
    tools = RepositoryTools(config)
    pre = ProjectPreprocessor(config, None, None, None, None, tools, learner=learner)
    try:
        with closing(pre._connect()) as con:
            for name in ["a.py", "b.py", "z_hot.py"]:
                con.execute("INSERT INTO file_refs(root,path,content_hash,size,generation,updated_at) VALUES(?,?,?,?,?,?)",
                            (str(root), name, "hash", 10, 1, 0))
                con.execute("INSERT INTO source_fts(root,path,content) VALUES(?,?,?)",
                            (str(root), name, "rare_demand" if name == "z_hot.py" else "ordinary"))
            con.commit()
        service = LocalAIServices.__new__(LocalAIServices)
        service.config, service.repo_tools, service.learner = config, tools, learner
        service.deterministic = service.code_index = service.preprocessor = service.evidence_store = None
        service._repo_cache_state = lambda _root: {}
        service._repo_cached = lambda _name, _root, _params, compute, **_kwargs: compute()

        result = service.repo_search(str(root), "rare_demand", limit=5)

        assert result["success"] is True
        assert [item["path"] for item in pre._find_next_files(str(root), 2)] == ["z_hot.py", "a.py"]
    finally:
        pre.close()


def test_repository_benchmark_measures_real_hot_files_against_cold_queue(tmp_path):
    root = tmp_path / "representative-repo"
    root.mkdir()
    (root / "a_cold.py").write_text("ordinary code path", encoding="utf-8")
    (root / "b_cold.py").write_text("another ordinary code path", encoding="utf-8")
    (root / "z_hot.py").write_text("rare_demand occurs in this real source file", encoding="utf-8")

    result = run(files=3, batch_size=2, root=str(root), query="rare_demand")

    assert result["scope"] == "repository text file-card queue selection, no model inference"
    assert result["query_match_count"] == 1
    assert result["baseline"]["batches_to_first_query_match"] == 2
    assert result["demand"]["batches_to_first_query_match"] == 1
    assert result["demand"]["query_matches_selected_first_batch"] == 1
    assert result["demand"]["completed_files"] == 3
    assert result["demand"]["unprocessed_files"] == 0
    assert result["demand"]["selection_p95_ms"] >= 0
    assert result["useful_context_verified"] is False


def test_learned_priority_cache_invalidates_on_query_or_index_change(tmp_path, monkeypatch):
    from local_ai_hub import preprocess as preprocess_module

    root = str(tmp_path / "repo")
    db = tmp_path / "pre.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED, path UNINDEXED, content)")
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, size INTEGER, generation INTEGER, updated_at REAL)")
        con.execute("INSERT INTO source_fts VALUES(?,?,?)", (root, "old.py", "old_demand"))
        con.execute("INSERT INTO file_refs VALUES(?,?,?,?,?,?)", (root, "old.py", "old", 10, 1, 1.0))
        con.commit()

    def connect():
        return sqlite3.connect(db)

    class Learner:
        enabled = True
        query = "old_demand"

        def hot_queries(self, _root, _limit):
            return [self.query]

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._connect, pre._db_lock = connect, threading.RLock()
    pre._demand_priority_cache, pre._demand_priority_lock = {}, threading.Lock()
    pre.repo_tools, pre.learner = RepositoryTools({}), Learner()
    now = [100.0]
    monkeypatch.setattr(preprocess_module.time, "monotonic", lambda: now[0])

    assert pre._learned_priority_paths(root) == ("old.py",)
    pre.learner.query = "new_demand"
    with closing(connect()) as con:
        con.execute("DELETE FROM source_fts WHERE root=?", (root,))
        con.execute("INSERT INTO source_fts VALUES(?,?,?)", (root, "new.py", "new_demand"))
        con.execute("DELETE FROM file_refs WHERE root=?", (root,))
        con.execute("INSERT INTO file_refs VALUES(?,?,?,?,?,?)", (root, "new.py", "new", 10, 2, 2.0))
        con.commit()
    now[0] = 114.999
    assert pre._learned_priority_paths(root) == ("new.py",)

    with closing(connect()) as con:
        con.execute("DELETE FROM source_fts WHERE root=?", (root,))
        con.execute("INSERT INTO source_fts VALUES(?,?,?)", (root, "newer.py", "new_demand"))
        con.execute("DELETE FROM file_refs WHERE root=?", (root,))
        con.execute("INSERT INTO file_refs VALUES(?,?,?,?,?,?)", (root, "newer.py", "newer", 12, 3, 3.0))
        con.commit()
    assert pre._learned_priority_paths(root) == ("newer.py",)

    now[0] = 115.0
    assert pre._learned_priority_paths(root) == ("newer.py",)


def test_sustained_hot_queries_do_not_starve_regular_file_cards(tmp_path):
    root = str(tmp_path / "repo")
    db = tmp_path / "pre.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, size INTEGER, card_key TEXT, last_accessed_at REAL)")
        con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED, path UNINDEXED, content)")
        for i in range(8):
            name = f"hot_{i:02}.py"
            con.execute("INSERT INTO file_refs VALUES(?,?,10,NULL,0)", (root, name))
            con.execute("INSERT INTO source_fts VALUES(?,?,?)", (root, name, "rare_demand"))
        for i in range(12):
            name = f"cold_{i:02}.py"
            con.execute("INSERT INTO file_refs VALUES(?,?,10,NULL,0)", (root, name))
            con.execute("INSERT INTO source_fts VALUES(?,?,?)", (root, name, "ordinary"))
        con.commit()

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    class Learner:
        enabled = True

        def hot_queries(self, _root, _limit):
            return ["rare_demand"]

    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._connect, pre._db_lock = connect, threading.RLock()
    pre._demand_priority_cache, pre._demand_priority_lock = {}, threading.Lock()
    pre.repo_tools, pre.learner, pre.cfg = RepositoryTools({}), Learner(), {}
    cold_progress = []
    hot_progress = []

    for _ in range(4):
        batch = pre._find_next_files(root, 4)
        names = [str(row["path"]) for row in batch]
        hot = [name for name in names if name.startswith("hot_")]
        cold = [name for name in names if name.startswith("cold_")]
        assert len(batch) == 4
        assert len(hot) == 1
        assert len(cold) == 3
        hot_progress.extend(hot)
        cold_progress.extend(cold)
        with closing(connect()) as con:
            con.executemany("UPDATE file_refs SET card_key='done' WHERE root=? AND path=?", [(root, name) for name in names])
            con.commit()

    assert len(set(hot_progress)) == 4
    assert len(set(cold_progress)) == 12
