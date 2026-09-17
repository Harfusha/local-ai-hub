from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import threading
import time

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.config import load_config
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


def _cfg(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text(
        f'''[server]\nstate_dir="{(tmp_path / "state").as_posix()}"\n[hardware]\nprofile="cpu"\n[preprocessing]\nenabled=false\nfs_watcher_enabled=false\n''',
        encoding="utf-8",
    )
    return load_config(str(p))


class _Rag:
    index_reset = False

    @staticmethod
    def workspace_id(root):
        return "workspace"


class _EmptyIndexRag:
    index_reset = False

    def index_paths_step(self, *args, **kwargs):
        return {"success": True, "processed_paths": []}

    def remove_paths(self, *args, **kwargs):
        return 0

    def prune_missing(self, *args, **kwargs):
        return 0


class _Noop:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _RecordingCodeIndex:
    def __init__(self):
        self.pending = []

    def prune(self, root, paths):
        return None

    def _connect(self):
        return sqlite3.connect(":memory:")

    def update_files_batch(self, root, pending):
        self.pending.extend(pending)
        return {"files_processed": len(pending), "cached": 0}


class _IdleScheduler:
    def background_allowed(self):
        return True

    def foreground_busy(self):
        return False


class _FailingExternalTools:
    def index(self, backend, root):
        raise RuntimeError(f"{backend} unavailable")


class _MalformedExternalTools:
    def index(self, backend, root):
        return None


class _StaleProjectExternalTools:
    def __init__(self):
        self.calls = 0

    def index(self, backend, root):
        self.calls += 1
        return {
            "success": False,
            "error": "Project configuration auto-generation failed: no associated project configuration",
        }


class _TimedOutExternalTools:
    def __init__(self):
        self.calls = 0

    def index(self, backend, root):
        self.calls += 1
        return {"success": False, "error": f"{backend} indexing exceeded 30s"}


class _AvailableTimedOutExternalTools(_TimedOutExternalTools):
    def backend_available(self, backend):
        return True


class _SuccessfulExternalTools:
    def __init__(self):
        self.calls = 0

    def index(self, backend, root):
        self.calls += 1
        return {"success": True}

    def backend_available(self, backend):
        return True


class _ObservingExternalTools(_SuccessfulExternalTools):
    def __init__(self):
        super().__init__()
        self.pre = None
        self.state_during_index = None

    def index(self, backend, root):
        self.calls += 1
        with closing(self.pre._connect()) as con:
            self.state_during_index = con.execute(
                "SELECT status,error FROM external_index_state WHERE root=? AND backend=?",
                (root, backend),
            ).fetchone()
        return {"success": True}


def test_cached_external_unavailability_is_retried_when_backend_is_available(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = RepositoryTools(cfg)
    external = _SuccessfulExternalTools()
    pre = ProjectPreprocessor(
        cfg,
        _Noop(),
        _Rag(),
        _IdleScheduler(),
        _Noop(),
        tools,
        external_tools=external,
    )
    try:
        revision = pre._external_revision(str(repo))
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO external_index_state(root,backend,revision_hash,status,updated_at,error) VALUES(?,?,?,?,?,?)",
                (str(repo), "codegraph", revision, "unavailable", 0.0, "codegraph indexing exceeded 120s"),
            )
            con.commit()
        row = {"root": str(repo), "workspace": "test", "generation": 0}

        assert pre._step_external_index(row, "codegraph", "lexical") is True
        assert external.calls == 1
        with closing(pre._connect()) as con:
            state = con.execute(
                "SELECT status FROM external_index_state WHERE root=? AND backend=?",
                (str(repo), "codegraph"),
            ).fetchone()
        assert state[0] == "ready"
    finally:
        pre.close()


def test_startup_requeues_complete_project_with_available_external_backend(tmp_path: Path):
    cfg = _cfg(tmp_path)
    cfg["preprocessing"]["reject_temp_projects"] = False
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = RepositoryTools(cfg)
    external = _SuccessfulExternalTools()
    now = time.time()
    pre = ProjectPreprocessor(cfg, _Noop(), _Rag(), _IdleScheduler(), _Noop(), tools, external_tools=external)
    try:
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO projects(root,workspace,status,phase,registered_at,updated_at,next_check_at,retry_after,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (str(repo), "test", "complete", "complete", now, now, now + 1000, 0, 0, now, "test"),
            )
            con.execute(
                "INSERT INTO external_index_state(root,backend,revision_hash,status,updated_at,error) VALUES(?,?,?,?,?,?)",
                (str(repo), "codegraph", "same", "skipped", now, "codegraph indexing exceeded 120s"),
            )
            con.commit()
    finally:
        pre.close()

    reopened = ProjectPreprocessor(cfg, _Noop(), _Rag(), _IdleScheduler(), _Noop(), tools, external_tools=external)
    try:
        with closing(reopened._connect()) as con:
            state = con.execute("SELECT status,phase FROM projects WHERE root=?", (str(repo),)).fetchone()
        assert tuple(state) == ("waiting", "codegraph")
    finally:
        reopened.close()


def test_worktree_discovery_does_not_recurse_from_linked_worktree(tmp_path: Path, monkeypatch):
    root = tmp_path / "worktree"
    root.mkdir()
    (root / ".git").write_text("gitdir: C:/repo/.git/worktrees/sample\n", encoding="utf-8")
    prep = ProjectPreprocessor(
        _cfg(tmp_path),
        services=_Noop(),
        rag=_Rag(),
        scheduler=_IdleScheduler(),
        runtime=_Noop(),
        repo_tools=RepositoryTools(_cfg(tmp_path)),
    )
    try:
        monkeypatch.setattr(prep, "_related_worktrees", lambda *_args: (_ for _ in ()).throw(AssertionError("recursive discovery")))
        prep._register_discovered_worktrees(str(root))
    finally:
        prep.close()


def test_cleanup_orphaned_index_roots_removes_derived_rows_only(tmp_path: Path):
    class _IndexDb:
        def __init__(self, path: Path):
            self._lock = threading.RLock()
            self.path = path
            with closing(sqlite3.connect(path)) as con:
                con.executescript("CREATE TABLE files(root TEXT, path TEXT); CREATE TABLE symbols(root TEXT, path TEXT);")
                con.executemany("INSERT INTO files VALUES(?,?)", [("active", "a.py"), ("orphan", "o.py")])
                con.executemany("INSERT INTO symbols VALUES(?,?)", [("active", "a.py"), ("orphan", "o.py")])
                con.commit()

        def _connect(self):
            return sqlite3.connect(self.path)

    prep = ProjectPreprocessor(
        _cfg(tmp_path),
        services=_Noop(),
        rag=_Rag(),
        scheduler=_IdleScheduler(),
        runtime=_Noop(),
        repo_tools=RepositoryTools(_cfg(tmp_path)),
        code_index=_IndexDb(tmp_path / "code.sqlite3"),
    )
    try:
        with prep._db_lock, closing(prep._connect()) as con:
            con.execute(
                "INSERT INTO projects(root,workspace,status,phase,registered_at,updated_at,next_check_at) VALUES(?,?,?,?,?,?,?)",
                ("active", "ws", "complete", "complete", time.time(), time.time(), 0),
            )
            con.commit()

        result = prep.cleanup_orphaned_indexes(max_roots=4)

        assert result["success"] is True
        with closing(sqlite3.connect(tmp_path / "code.sqlite3")) as con:
            assert con.execute("SELECT count(*) FROM files WHERE root='active'").fetchone()[0] == 1
            assert con.execute("SELECT count(*) FROM files WHERE root='orphan'").fetchone()[0] == 0
    finally:
        prep.close()


def test_preprocessor_pause_resume_status_regressions(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo_tools = RepositoryTools(cfg)
    code_index = CodeIndex(cfg, repo_tools)
    pre = ProjectPreprocessor(cfg, _Noop(), _Rag(), _Noop(), _Noop(), repo_tools, code_index=code_index)
    try:
        assert pre.pause()["success"] is True
        assert pre.resume()["success"] is True
        status = pre.status()
        assert status["success"] is True
        assert isinstance(status["projects"], list)
    finally:
        pre.close()


def test_successful_preprocess_step_clears_stale_error_state(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    repo_tools = RepositoryTools(cfg)
    pre = ProjectPreprocessor(cfg, _Noop(), _Rag(), _Noop(), _Noop(), repo_tools)
    try:
        root = str(repo.resolve())
        now = time.time()
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO projects(root,workspace,status,phase,generation,registered_at,updated_at,next_check_at,stats_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (root, "workspace", "queued", "inventory", 0, now, now, now, "{}"),
            )
            con.commit()
        pre._set_project(
            root,
            status="error",
            last_error="stale embedding prewarm failure",
            retry_after=time.time() + 300,
            stats_json='{"consecutive_errors":7,"changed_files":2}',
        )

        pre._mark_step_recovered(root)

        with closing(pre._connect()) as con:
            row = con.execute(
                "SELECT status,last_error,retry_after,stats_json FROM projects WHERE root=?",
                (root,),
            ).fetchone()
        assert row[0] == "error"
        assert row[1] is None
        assert row[2] == 0
        assert json.loads(row[3]) == {"changed_files": 2}
    finally:
        pre.close()


def test_external_index_failure_degrades_and_advances_preprocessing(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = RepositoryTools(cfg)
    pre = ProjectPreprocessor(
        cfg,
        _Noop(),
        _Rag(),
        _IdleScheduler(),
        _Noop(),
        tools,
        external_tools=_FailingExternalTools(),
    )
    try:
        row = {"root": str(repo), "workspace": "test", "generation": 0}
        assert pre._step_external_index(row, "serena", "codegraph") is True
        with closing(pre._connect()) as con:
            state = con.execute(
                "SELECT status,error FROM external_index_state WHERE root=? AND backend=?",
                (str(repo), "serena"),
            ).fetchone()
        assert state[0] == "degraded"
        assert state[1] == "RuntimeError: serena unavailable"
    finally:
        pre.close()


def test_malformed_external_index_response_degrades_and_advances_preprocessing(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = RepositoryTools(cfg)
    pre = ProjectPreprocessor(
        cfg,
        _Noop(),
        _Rag(),
        _IdleScheduler(),
        _Noop(),
        tools,
        external_tools=_MalformedExternalTools(),
    )
    try:
        row = {"root": str(repo), "workspace": "test", "generation": 0}
        assert pre._step_external_index(row, "codegraph", "lexical") is True
        with closing(pre._connect()) as con:
            state = con.execute(
                "SELECT status,error FROM external_index_state WHERE root=? AND backend=?",
                (str(repo), "codegraph"),
            ).fetchone()
        assert state[0] == "degraded"
        assert state[1] == "invalid codegraph index response"
    finally:
        pre.close()


def test_stale_external_project_configuration_is_skipped_once_per_revision(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = RepositoryTools(cfg)
    external = _StaleProjectExternalTools()
    pre = ProjectPreprocessor(
        cfg,
        _Noop(),
        _Rag(),
        _IdleScheduler(),
        _Noop(),
        tools,
        external_tools=external,
    )
    try:
        row = {"root": str(repo), "workspace": "test", "generation": 0}
        assert pre._step_external_index(row, "serena", "codegraph") is True
        assert pre._step_external_index(row, "serena", "codegraph") is True
        with closing(pre._connect()) as con:
            state = con.execute(
                "SELECT status,error FROM external_index_state WHERE root=? AND backend=?",
                (str(repo), "serena"),
            ).fetchone()
        assert external.calls == 1
        assert state[0] == "unavailable"
        assert "Project configuration" in state[1]
    finally:
        pre.close()


def test_time_bounded_external_index_is_skipped_once_per_revision(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = RepositoryTools(cfg)
    external = _TimedOutExternalTools()
    pre = ProjectPreprocessor(
        cfg,
        _Noop(),
        _Rag(),
        _IdleScheduler(),
        _Noop(),
        tools,
        external_tools=external,
    )
    try:
        row = {"root": str(repo), "workspace": "test", "generation": 0}
        assert pre._step_external_index(row, "codegraph", "lexical") is True
        assert pre._step_external_index(row, "codegraph", "lexical") is True
        with closing(pre._connect()) as con:
            state = con.execute(
                "SELECT status,error FROM external_index_state WHERE root=? AND backend=?",
                (str(repo), "codegraph"),
            ).fetchone()
        assert external.calls == 1
        assert state[0] == "unavailable"
        assert state[1] == "codegraph indexing exceeded 30s"
    finally:
        pre.close()


def test_available_backend_timeout_is_not_retried_forever(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = RepositoryTools(cfg)
    external = _AvailableTimedOutExternalTools()
    pre = ProjectPreprocessor(
        cfg,
        _Noop(),
        _Rag(),
        _IdleScheduler(),
        _Noop(),
        tools,
        external_tools=external,
    )
    try:
        row = {"root": str(repo), "workspace": "test", "generation": 0}
        assert pre._step_external_index(row, "codegraph", "lexical") is True
        assert pre._step_external_index(row, "codegraph", "lexical") is True
        assert external.calls == 1
    finally:
        pre.close()


def test_external_index_publishes_running_state_before_invocation(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = RepositoryTools(cfg)
    external = _ObservingExternalTools()
    pre = ProjectPreprocessor(
        cfg,
        _Noop(),
        _Rag(),
        _IdleScheduler(),
        _Noop(),
        tools,
        external_tools=external,
    )
    external.pre = pre
    try:
        row = {"root": str(repo), "workspace": "test", "generation": 0}
        assert pre._step_external_index(row, "codegraph", "lexical") is True
        assert tuple(external.state_during_index) == ("running", "")
    finally:
        pre.close()


def test_force_refresh_retries_cached_external_index(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = RepositoryTools(cfg)
    external = _SuccessfulExternalTools()
    pre = ProjectPreprocessor(
        cfg,
        _Noop(),
        _Rag(),
        _IdleScheduler(),
        _Noop(),
        tools,
        external_tools=external,
    )
    try:
        revision = pre._external_revision(str(repo))
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO external_index_state(root,backend,revision_hash,status,updated_at,error) VALUES(?,?,?,?,?,?)",
                (str(repo), "codegraph", revision, "unavailable", 0.0, "codegraph indexing exceeded 30s"),
            )
            con.commit()
        row = {"root": str(repo), "workspace": "test", "generation": 0, "force_refresh": 1}
        assert pre._step_external_index(row, "codegraph", "lexical") is True
        with closing(pre._connect()) as con:
            state = con.execute(
                "SELECT status FROM external_index_state WHERE root=? AND backend=?",
                (str(repo), "codegraph"),
            ).fetchone()
        assert external.calls == 1
        assert state[0] == "ready"
    finally:
        pre.close()


def test_force_refresh_requeues_complete_project_from_inventory(tmp_path: Path):
    cfg = _cfg(tmp_path)
    cfg["preprocessing"]["enabled"] = True
    cfg["preprocessing"]["reject_temp_projects"] = False
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname='sample'\nversion='0.1.0'\n", encoding="utf-8")
    tools = RepositoryTools(cfg)
    pre = ProjectPreprocessor(cfg, _Noop(), _Rag(), _IdleScheduler(), _Noop(), tools)
    try:
        now = time.time()
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(repo), "test", "complete", "complete", 4, 0, now, now, now + 1800, 0, now, "test"),
            )
            con.execute(
                "INSERT INTO external_index_state(root,backend,revision_hash,status,updated_at,error) VALUES(?,?,?,?,?,?)",
                (str(repo), "codegraph", "old", "skipped", now, "old timeout"),
            )
            con.commit()
        pre.refresh(str(repo))
        with closing(pre._connect()) as con:
            state = con.execute(
                "SELECT status,phase,force_refresh FROM projects WHERE root=?",
                (str(repo),),
            ).fetchone()
            external_state = con.execute(
                "SELECT 1 FROM external_index_state WHERE root=?",
                (str(repo),),
            ).fetchone()
        assert tuple(state) in (("queued", "inventory", 1), ("running", "hash", 1), ("running", "inventory", 1), ("running", "code_index", 1))
        assert external_state is None
    finally:
        pre.close()


def test_existing_timed_out_external_index_is_promoted_to_revision_scoped_skip(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = RepositoryTools(cfg)
    external = _TimedOutExternalTools()
    pre = ProjectPreprocessor(
        cfg,
        _Noop(),
        _Rag(),
        _IdleScheduler(),
        _Noop(),
        tools,
        external_tools=external,
    )
    try:
        revision = pre._external_revision(str(repo))
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO external_index_state(root,backend,revision_hash,status,updated_at,error) VALUES(?,?,?,?,?,?)",
                (str(repo), "serena", revision, "degraded", 0.0, "serena indexing exceeded 30s"),
            )
            con.commit()
        row = {"root": str(repo), "workspace": "test", "generation": 0}
        assert pre._step_external_index(row, "serena", "codegraph") is True
        with closing(pre._connect()) as con:
            state = con.execute(
                "SELECT status FROM external_index_state WHERE root=? AND backend=?",
                (str(repo), "serena"),
            ).fetchone()
        assert external.calls == 0
        assert state[0] == "unavailable"
    finally:
        pre.close()


def test_external_state_is_preserved_across_restart(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = RepositoryTools(cfg)
    pre = ProjectPreprocessor(cfg, _Noop(), _Rag(), _IdleScheduler(), _Noop(), tools)
    try:
        revision = pre._external_revision(str(repo))
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO external_index_state(root,backend,revision_hash,status,updated_at,error) VALUES(?,?,?,?,?,?)",
                (str(repo), "codegraph", revision, "degraded", 0.0, "codegraph indexing exceeded 30s"),
            )
            con.commit()
    finally:
        pre.close()

    reopened = ProjectPreprocessor(cfg, _Noop(), _Rag(), _IdleScheduler(), _Noop(), tools)
    try:
        with closing(reopened._connect()) as con:
            state = con.execute(
                "SELECT status FROM external_index_state WHERE root=? AND backend=?",
                (str(repo), "codegraph"),
            ).fetchone()
        assert state[0] == "degraded"
    finally:
        reopened.close()


def test_missing_project_root_is_unregistered_from_any_preprocessing_phase(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "deleted-repo"
    tools = RepositoryTools(cfg)
    pre = ProjectPreprocessor(cfg, _Noop(), _Rag(), _Noop(), _Noop(), tools)
    try:
        assert pre._step({"root": str(repo), "workspace": "test", "phase": "rag"}) is True
        assert pre._project_row(str(repo)) is None
    finally:
        pre.close()


def test_code_index_phase_removes_deleted_files_instead_of_spinning(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    deleted = repo / "deleted.py"
    deleted.write_text("value = 1\n", encoding="utf-8")
    tools = RepositoryTools(cfg)
    code_index = CodeIndex(cfg, tools)
    pre = ProjectPreprocessor(cfg, _Noop(), _Rag(), _Noop(), _Noop(), tools, code_index=code_index)
    try:
        now = time.time()
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(repo), "test", "running", "code_index", 0, 0, now, now, 0, 0, 0, "test"),
            )
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (str(repo), "deleted.py", "hash", 10, 1, 0, None, 0, now),
            )
            con.commit()
        deleted.unlink()

        assert pre._step_code_index({"root": str(repo), "generation": 0}) is True
        with closing(pre._connect()) as con:
            assert con.execute(
                "SELECT 1 FROM file_refs WHERE root=? AND path=?",
                (str(repo), "deleted.py"),
            ).fetchone() is None
    finally:
        pre.close()


def test_code_index_phase_skips_ignored_refs_left_by_previous_inventory(tmp_path: Path):
    cfg = _cfg(tmp_path)
    cfg["rag"]["ignore_dirs"] = ["Library"]
    repo = tmp_path / "repo"
    (repo / "Assets").mkdir(parents=True)
    (repo / "Library").mkdir()
    (repo / "Assets" / "main.cs").write_text("class Main {}\n", encoding="utf-8")
    (repo / "Library" / "generated.cs").write_text("class Generated {}\n", encoding="utf-8")
    tools = RepositoryTools(cfg)
    code_index = _RecordingCodeIndex()
    pre = ProjectPreprocessor(cfg, _Noop(), _Rag(), _Noop(), _Noop(), tools, code_index=code_index)
    try:
        now = time.time()
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (str(repo), "Assets/main.cs", "main-hash", 10, 1, 0, None, 0, now),
            )
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (str(repo), "Library/generated.cs", "generated-hash", 10, 1, 0, None, 0, now),
            )
            con.commit()

        assert pre._step_code_index({"root": str(repo), "generation": 0}) is True
        assert code_index.pending == [("Assets/main.cs", "main-hash")]
    finally:
        pre.close()


def test_rag_phase_removes_deleted_files_instead_of_spinning(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    deleted = repo / "deleted.py"
    deleted.write_text("value = 1\n", encoding="utf-8")
    tools = RepositoryTools(cfg)
    pre = ProjectPreprocessor(cfg, _Noop(), _EmptyIndexRag(), _IdleScheduler(), _Noop(), tools)
    try:
        now = time.time()
        with closing(pre._connect()) as con:
            con.execute(
                "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(repo), "test", "running", "rag", 0, 0, now, now, 0, 0, 0, "test"),
            )
            con.execute(
                "INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (str(repo), "deleted.py", "hash", 10, 1, 0, None, 0, now),
            )
            con.commit()
        deleted.unlink()

        row = {"root": str(repo), "workspace": "test", "phase": "rag", "generation": 0}
        assert pre._step_rag(row) is True
        with closing(pre._connect()) as con:
            assert con.execute(
                "SELECT 1 FROM file_refs WHERE root=? AND path=?",
                (str(repo), "deleted.py"),
            ).fetchone() is None

        assert pre._step_rag(row) is True
        assert pre._project_row(str(repo))["phase"] == "files"
    finally:
        pre.close()


def test_deterministic_prune_removes_stale_facts_and_fts_rows(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    tools = RepositoryTools(cfg)
    engine = DeterministicEngine(cfg, tools, None)
    root = str(repo.resolve())
    with closing(engine._connect()) as con:
        con.execute(
            "INSERT INTO files(root,path,content_hash,language,is_test,updated_at) VALUES(?,?,?,?,?,?)",
            (root, "keep.py", "keep", "python", 0, time.time()),
        )
        con.execute(
            "INSERT INTO files(root,path,content_hash,language,is_test,updated_at) VALUES(?,?,?,?,?,?)",
            (root, "gone.py", "gone", "python", 0, time.time()),
        )
        con.execute(
            "INSERT INTO facts(root,path,kind,name,value,line,extra_json) VALUES(?,?,?,?,?,?,?)",
            (root, "gone.py", "symbol", "gone", "gone", 1, "{}"),
        )
        try:
            con.execute(
                "INSERT INTO fact_fts(root,path,kind,name,value) VALUES(?,?,?,?,?)",
                (root, "gone.py", "symbol", "gone", "gone"),
            )
        except Exception:
            pass
        con.commit()

    assert engine.prune(root, ["keep.py"]) == 1

    with closing(engine._connect()) as con:
        assert con.execute(
            "SELECT 1 FROM files WHERE root=? AND path=?", (root, "gone.py")
        ).fetchone() is None
        assert con.execute(
            "SELECT 1 FROM facts WHERE root=? AND path=?", (root, "gone.py")
        ).fetchone() is None
        try:
            assert con.execute(
                "SELECT 1 FROM fact_fts WHERE root=? AND path=?", (root, "gone.py")
            ).fetchone() is None
        except Exception:
            pass


def test_security_audit_uses_repository_iterator(tmp_path: Path):
    cfg = _cfg(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text('password = "not-a-real-secret"\n', encoding="utf-8")
    tools = RepositoryTools(cfg)
    index = CodeIndex(cfg, tools)
    engine = DeterministicEngine(cfg, tools, index)
    result = engine.security_audit(str(repo), limit=10)
    assert result["success"] is True
    assert "findings" in result
