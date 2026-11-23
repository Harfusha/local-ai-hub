from contextlib import closing
import hashlib
import sqlite3
import threading
from types import SimpleNamespace

from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


class _Noop:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def test_file_phase_respects_configured_file_batch_size(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "preprocessing": {
            "enabled": False,
            "model": "configured-model",
            "disable_llm_card_synthesis": False,
            "prefer_deterministic_cards": False,
            "exclusive": {"enrich_stub_cards": True},
        },
        "background_gpu": {"enabled": True, "file_batch_size": 2},
    }
    submitted_batches = []

    def generate_many(tasks, **_kwargs):
        submitted_batches.append(list(tasks))
        return [{"success": False, "error": "test deferral"} for _ in tasks]

    gpu = SimpleNamespace(ready=lambda: True, generate_many=generate_many)
    prep = ProjectPreprocessor(
        config,
        _Noop(),
        SimpleNamespace(index_reset=False),
        _Noop(),
        _Noop(),
        RepositoryTools(config),
        background_gpu=gpu,
    )
    try:
        with closing(prep._connect()) as con:
            for index in range(3):
                name = f"part_{index}.py"
                source = f"def function_{index}():\n    return {index}\n".encode("utf-8")
                (root / name).write_bytes(source)
                digest = hashlib.sha256(source).hexdigest()
                con.execute(
                    """INSERT INTO file_refs(
                           root,path,content_hash,size,needs_hash,generation,card_key,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?)""",
                    (str(root), name, digest, len(source), 0, 1, None, 0),
                )
            con.commit()

        prep._step_file_card({"root": str(root), "phase": "files"})
        assert len(submitted_batches) == 1
        assert len(submitted_batches[0]) == config["background_gpu"]["file_batch_size"]
    finally:
        prep.close()


def test_rag_phase_disabled_advances_instead_of_reselecting_same_files(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = b"def example():\n    return 1\n"
    (root / "example.py").write_bytes(source)
    digest = hashlib.sha256(source).hexdigest()
    database = tmp_path / "projects.sqlite"

    def connect():
        con = sqlite3.connect(database)
        con.row_factory = sqlite3.Row
        return con

    with closing(connect()) as con:
        con.execute(
            """CREATE TABLE file_refs (
                root TEXT, path TEXT, content_hash TEXT, needs_hash INTEGER,
                rag_hash TEXT, size INTEGER, last_accessed_at REAL,
                centrality_score REAL, PRIMARY KEY(root,path)
            )"""
        )
        con.execute("CREATE TABLE source_index (root TEXT, path TEXT, content_hash TEXT, text_origin TEXT, text TEXT)")
        con.execute(
            "INSERT INTO file_refs VALUES(?,?,?,?,?,?,?,?)",
            (str(root), "example.py", digest, 0, "", len(source), 0, 0),
        )
        con.commit()

    class _DisabledRag:
        def index_paths_step(self, *_args, **_kwargs):
            return {"success": True, "skipped": True, "reason": "project phase disabled", "processed_paths": []}

    prep = ProjectPreprocessor.__new__(ProjectPreprocessor)
    prep.cfg = {"rag_files_per_step": 1}
    prep.rag = _DisabledRag()
    prep.deterministic = None
    prep.repo_tools = None
    prep._db_lock = threading.RLock()
    prep._stats_lock = threading.Lock()
    prep._stats = {"rag_steps": 0}
    prep._connect = connect
    prep._yield = lambda: False
    prep._learned_priority_paths = lambda _root: ()
    prep._record_progress = lambda *_args: None
    phase_updates = []
    prep._set_project = lambda _root, **kwargs: phase_updates.append(kwargs)

    assert prep._step_rag({"root": str(root), "workspace": "project-workspace"})
    assert phase_updates == [{"phase": "files"}]
    assert prep._stats["rag_steps"] == 1
