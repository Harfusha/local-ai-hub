from local_ai_hub.evidence import EvidenceStore
from local_ai_hub.code_index_demand import one_hop_python_imports
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.preprocess import ProjectPreprocessor
from contextlib import closing
from types import SimpleNamespace
import sqlite3
import threading
import hashlib


def test_evidence_demand_is_root_scoped_and_counts_real_usage(tmp_path):
    store = EvidenceStore(tmp_path / "state")
    root_a = str(tmp_path / "a")
    root_b = str(tmp_path / "b")
    a = {"path": "a.py", "text": "a", "content_hash": "hash-a"}
    b = {"path": "b.py", "text": "b", "content_hash": "hash-b"}
    store.put(root_a, a)
    store.put(root_a, a)
    store.put(root_a, b)
    store.put(root_b, {"path": "foreign.py", "text": "foreign", "content_hash": "hash-c"})
    rows = store.recent_paths(root_a, limit=10)
    assert {row["path"] for row in rows} == {"a.py", "b.py"}
    assert next(row for row in rows if row["path"] == "a.py")["uses"] == 2
    assert all("text" not in row for row in rows)


def test_one_hop_python_imports_does_not_recurse_or_escape_eligible_paths(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "a.py").write_text("from . import b\n", encoding="utf-8")
    (package / "b.py").write_text("from . import c\n", encoding="utf-8")
    (package / "c.py").write_text("VALUE = 1\n", encoding="utf-8")
    eligible = {"pkg/a.py", "pkg/b.py", "pkg/c.py"}
    neighbors = one_hop_python_imports(tmp_path, ["pkg/a.py"], eligible, RepositoryTools({}))
    assert neighbors == ["pkg/b.py"]
    assert one_hop_python_imports(tmp_path, ["pkg/a.py"], {"pkg/a.py", "pkg/c.py"}, RepositoryTools({})) == []


def test_one_hop_ignores_ambiguous_module_names(tmp_path):
    (tmp_path / "a.py").write_text("import duplicate\n", encoding="utf-8")
    for folder in ("first", "second"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "duplicate.py").write_text("pass\n", encoding="utf-8")
    eligible = {"a.py", "first/duplicate.py", "second/duplicate.py"}
    assert one_hop_python_imports(tmp_path, ["a.py"], eligible, RepositoryTools({})) == []


def test_preprocessing_indexes_used_files_and_one_hop_only(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    pkg = root / "pkg"
    pkg.mkdir()
    for name, content in (("a.py", "from . import b\n"), ("b.py", "from . import c\n"), ("c.py", "VALUE=1\n")):
        (pkg / name).write_text(content, encoding="utf-8")
    db = tmp_path / "pre.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE file_refs(root TEXT,path TEXT,content_hash TEXT,size INTEGER,needs_hash INTEGER)")
        con.executemany("INSERT INTO file_refs VALUES(?,?,?,20,0)",
                        [(str(root), f"pkg/{name}.py", name) for name in ("a", "b", "c")])
        con.commit()

    def connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        return con

    class Index:
        def __init__(self):
            self.pending = []
            self.usage = []
            self.budget_checks = 0
        def prune(self, root, paths):
            return {"success": True}
        def record_usage(self, root, paths):
            self.usage.extend((root, item) for item in paths)
        def enforce_size_limit(self):
            self.budget_checks += 1
            return {"success": True, "within_budget": True}
        def files_needing_reindex(self, root, refs):
            return refs
        def update_files_batch(self, root, pending):
            self.pending.extend(pending)
            return {"files_processed": len(pending), "cached": 0}

    evidence = EvidenceStore(tmp_path / "state")
    evidence.put(str(root), {"path": "pkg/a.py", "text": "a", "content_hash": "a"})
    pre = ProjectPreprocessor.__new__(ProjectPreprocessor)
    pre._db_lock, pre._stats_lock = threading.RLock(), threading.RLock()
    pre._connect, pre._stats = connect, {"code_index_files": 0}
    pre._missing_refs_checked_generations = {(str(root), 1)}
    pre._project_settings = lambda root: None
    pre._project_path_allowed = lambda *args, **kwargs: True
    pre._set_project = lambda *args, **kwargs: None
    pre._record_progress = lambda *args: None
    pre.cfg, pre.repo_tools, pre.code_index = {"code_index_files_per_step": 32}, RepositoryTools({}), Index()
    pre.services = SimpleNamespace(evidence_store=evidence)
    assert pre._step_code_index({"root": str(root), "generation": 1})
    assert {path for path, _ in pre.code_index.pending} == {"pkg/a.py", "pkg/b.py"}
    assert [(root, item["path"]) for root, item in pre.code_index.usage] == [(str(root), "pkg/a.py")]
    assert pre.code_index.budget_checks == 0


def test_existing_only_reindex_selection_does_not_admit_new_paths(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    indexed = root / "used.py"
    unindexed = root / "new.py"
    indexed.write_text("def used(): return 1\n", encoding="utf-8")
    unindexed.write_text("def new(): return 1\n", encoding="utf-8")
    code_index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}}, RepositoryTools({})
    )
    first_hash = hashlib.sha256(indexed.read_bytes()).hexdigest()
    assert code_index.update_file(str(root), "used.py", first_hash)["success"] is True

    pending = code_index.files_needing_reindex(
        str(root), [("used.py", "changed-hash"), ("new.py", "new-hash")],
        only_existing=True,
    )

    assert pending == [("used.py", "changed-hash")]
