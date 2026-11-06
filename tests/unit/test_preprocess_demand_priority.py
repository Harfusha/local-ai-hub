import hashlib
import sqlite3
import threading
from contextlib import closing

from local_ai_hub.preprocess import ProjectPreprocessor, _ensure_file_refs_revision_tracking
from local_ai_hub.learning import UsageLearner
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices
from tools.benchmark_preprocess_demand import _read_learned_query, run


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
    runtime = root / ".local-ai-hub" / "local" / "intents"
    runtime.mkdir(parents=True)
    (runtime / "intent.json").write_text("rare_demand runtime state", encoding="utf-8")
    skills = root / ".local-ai-hub-superpowers" / "skills"
    skills.mkdir(parents=True)
    (skills / "installed.md").write_text("rare_demand installed tool payload", encoding="utf-8")
    merge_artifacts = root / ".merge-checks" / "pytest" / "fixture"
    merge_artifacts.mkdir(parents=True)
    (merge_artifacts / "artifact.txt").write_text("rare_demand generated test state", encoding="utf-8")
    workflows = root / ".superpowers" / "coordination"
    workflows.mkdir(parents=True)
    (workflows / "plan.py").write_text("rare_demand workflow script", encoding="utf-8")
    t03_artifacts = root / ".t03-sync-checks" / "pytest-temp"
    t03_artifacts.mkdir(parents=True)
    (t03_artifacts / "output.txt").write_text("rare_demand validation output", encoding="utf-8")

    result = run(files=4, batch_size=2, root=str(root), query="rare_demand")

    assert result["scope"] == "repository queue selection and deterministic context_pack_paths, no model inference"
    assert result["sampled_files"] == 3
    assert result["cache_revision_tracking"] is True
    assert result["query_match_count"] == 1
    assert result["baseline"]["batches_to_first_query_match"] == 2
    assert result["demand"]["batches_to_first_query_match"] == 1
    assert result["demand"]["query_matches_selected_first_batch"] == 1
    assert result["demand"]["completed_files"] == 3
    assert result["demand"]["unprocessed_files"] == 0
    assert result["demand"]["selection_p95_ms"] >= 0
    assert result["useful_context_verified"] is True
    assert result["baseline"]["batches_to_first_useful_context"] == 2
    assert result["demand"]["batches_to_first_useful_context"] == 1
    assert result["baseline"]["files_processed_to_useful_context"] == 3
    assert result["demand"]["files_processed_to_useful_context"] == 2
    assert result["baseline"]["useful_context_evidence_count"] > 0
    assert result["demand"]["useful_context_evidence_count"] > 0
    assert result["demand"]["useful_context_chars"] > 0
    assert result["useful_context_work_saved"] == {"batches": 1, "files": 1}


def test_repository_benchmark_treats_invalid_context_pack_as_unverified(tmp_path, monkeypatch):
    class InvalidContextRepositoryTools:
        def __init__(self, _config):
            pass

        @staticmethod
        def _terms(query):
            return query.split()

        @staticmethod
        def context_pack_paths(*_args, **_kwargs):
            return None

    monkeypatch.setitem(run.__globals__, "RepositoryTools", InvalidContextRepositoryTools)
    root = tmp_path / "invalid-context-repo"
    root.mkdir()
    (root / "a.py").write_text("rare_demand", encoding="utf-8")
    (root / "b.py").write_text("ordinary", encoding="utf-8")

    result = run(files=2, batch_size=2, root=str(root), query="rare_demand")

    assert result["useful_context_verified"] is False
    assert result["useful_context_work_saved"] is None
    assert result["baseline"]["useful_context_evidence_count"] is None
    assert result["demand"]["useful_context_evidence_count"] is None


def test_learned_priority_cache_invalidates_on_query_or_index_change(tmp_path, monkeypatch):
    from local_ai_hub import preprocess as preprocess_module

    root = str(tmp_path / "repo")
    db = tmp_path / "pre.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE VIRTUAL TABLE source_fts USING fts5(root UNINDEXED, path UNINDEXED, content)")
        con.execute("CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, size INTEGER, generation INTEGER, updated_at REAL)")
        _ensure_file_refs_revision_tracking(con)
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
    # Rename the indexed file while preserving every aggregate statistic from
    # the old signature. The cached mapping must follow the current FTS path.
    with closing(connect()) as con:
        con.execute("DELETE FROM source_fts WHERE root=?", (root,))
        con.execute("INSERT INTO source_fts VALUES(?,?,?)", (root, "new.py", "old_demand"))
        con.execute("DELETE FROM file_refs WHERE root=?", (root,))
        con.execute("INSERT INTO file_refs VALUES(?,?,?,?,?,?)", (root, "new.py", "old", 10, 1, 1.0))
        con.commit()
    assert pre._learned_priority_paths(root) == ("new.py",)

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


def test_file_ref_revision_tracks_source_identity_not_card_state(tmp_path):
    db = tmp_path / "pre.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute(
            "CREATE TABLE file_refs(root TEXT, path TEXT, content_hash TEXT, card_key TEXT, size INTEGER, mtime_ns INTEGER, needs_hash INTEGER)"
        )
        _ensure_file_refs_revision_tracking(con)
        con.execute("DROP TRIGGER file_refs_revision_update")
        con.executescript(
            """
            CREATE TRIGGER file_refs_revision_update
            AFTER UPDATE OF root,path,content_hash ON file_refs
            WHEN OLD.root IS NOT NEW.root OR OLD.path IS NOT NEW.path OR OLD.content_hash IS NOT NEW.content_hash
            BEGIN
                INSERT INTO file_refs_revision(root,revision) VALUES(NEW.root,1)
                ON CONFLICT(root) DO UPDATE SET revision=revision+1;
                INSERT INTO file_refs_revision(root,revision)
                SELECT OLD.root,1 WHERE OLD.root IS NOT NEW.root
                ON CONFLICT(root) DO UPDATE SET revision=revision+1;
            END;
            """
        )
        _ensure_file_refs_revision_tracking(con)
        con.execute("INSERT INTO file_refs VALUES('repo','a.py','hash-a',NULL,10,1,0)")

        def revision(root):
            row = con.execute("SELECT revision FROM file_refs_revision WHERE root=?", (root,)).fetchone()
            return int(row[0]) if row else 0

        assert revision("repo") == 1
        con.execute("UPDATE file_refs SET card_key='card' WHERE root='repo'")
        assert revision("repo") == 1
        con.execute("UPDATE file_refs SET size=11 WHERE root='repo'")
        assert revision("repo") == 2
        con.execute("UPDATE file_refs SET mtime_ns=2 WHERE root='repo'")
        assert revision("repo") == 3
        con.execute("UPDATE file_refs SET needs_hash=1 WHERE root='repo'")
        assert revision("repo") == 4
        con.execute("UPDATE file_refs SET content_hash='hash-b' WHERE root='repo'")
        assert revision("repo") == 5
        con.execute("UPDATE file_refs SET path='b.py' WHERE root='repo'")
        assert revision("repo") == 6
        con.execute("UPDATE file_refs SET root='other' WHERE root='repo'")
        assert revision("repo") == 7
        assert revision("other") == 1
        con.execute("DELETE FROM file_refs WHERE root='other'")
        assert revision("other") == 2


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


def test_repository_benchmark_uses_scoped_learned_query_without_emitting_it(tmp_path):
    root = tmp_path / "learned-repo"
    root.mkdir()
    (root / "a_cold.py").write_text("ordinary source path", encoding="utf-8")
    (root / "z_hot.py").write_text("private learned query appears here", encoding="utf-8")
    other_root = tmp_path / "other-repo"
    other_root.mkdir()
    state_dir = tmp_path / "state"
    learner = UsageLearner({"server": {"state_dir": str(state_dir)}})
    learner.record(str(root), "private learned query")
    learner.record(str(other_root), "other repository query")

    query = _read_learned_query(state_dir / "learning.sqlite3", str(root))
    result = run(files=2, batch_size=2, root=str(root), query=query, query_source="learned")

    assert result["query_source"] == "learned"
    assert result["query_length"] == len(query)
    assert result["query_sha256"] == hashlib.sha256(query.encode("utf-8")).hexdigest()
    assert "private learned query" not in repr(result)
