from __future__ import annotations

import fnmatch
import sqlite3
import subprocess
import sys
import threading
from contextlib import closing
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.rag import RAGStore
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.repo_tools import RepositoryTools


def _install_policy(monkeypatch, *, skip_phases=()):
    settings = SimpleNamespace(
        exclude_paths=("private/secret.py",),
        force_include_paths=("private/keep.py", "private/secret.py", "blocked/keep.py"),
        preprocess_exclude_paths=("build/**",),
        text_extensions=(".mdx",),
        binary_extensions=(".binx",),
        max_file_size_bytes=8,
        skip_phases=tuple(skip_phases),
    )

    def relative(root, path):
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()

    def matches(path, patterns):
        return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)

    module = types.ModuleType("local_ai_hub.project_config")
    module.resolve_project_context = lambda root, _state_dir=None: SimpleNamespace(
        root=Path(root), settings=settings, config_digest="test-config-digest"
    )
    module.custom_extension_kind = lambda name, _settings: (
        "binary" if str(name).lower().endswith(".binx")
        else "text" if str(name).lower().endswith(".mdx")
        else None
    )

    def phase_is_allowed(_settings, phase):
        return phase not in settings.skip_phases

    module.phase_is_allowed = phase_is_allowed
    module.phase_enabled = phase_is_allowed

    def path_is_allowed(root, path, _settings, *, phase, soft_ignored=False,
                        hard_denied=False, binary=False, size_bytes=None):
        if hard_denied or binary or phase in settings.skip_phases:
            return False
        rel = relative(root, path)
        if phase == "preprocess" and matches(rel, settings.preprocess_exclude_paths):
            return False
        forced = matches(rel, settings.force_include_paths)
        if matches(rel, settings.exclude_paths):
            return False
        if size_bytes is not None and size_bytes > settings.max_file_size_bytes:
            return False
        return not soft_ignored or forced

    def may_descend(root, directory, _settings, *, phase, soft_ignored=False,
                    hard_denied=False):
        if hard_denied or phase in settings.skip_phases:
            return False
        rel = relative(root, directory)
        if phase == "preprocess" and matches(rel, settings.preprocess_exclude_paths):
            return False
        if matches(rel, settings.exclude_paths):
            return False
        return True

    module.path_is_allowed = path_is_allowed
    module.may_descend = may_descend
    monkeypatch.setitem(sys.modules, "local_ai_hub.project_config", module)
    return SimpleNamespace(settings=settings, api=module)


def _files(root: Path) -> None:
    (root / "src").mkdir(parents=True)
    (root / "private").mkdir()
    (root / "build").mkdir()
    (root / "src" / "app.py").write_text("x=1\n", encoding="utf-8")
    (root / "private" / "secret.py").write_text("secret\n", encoding="utf-8")
    (root / "private" / "keep.py").write_text("keep\n", encoding="utf-8")
    (root / "guide.mdx").write_text("guide\n", encoding="utf-8")
    (root / "build" / "generated.py").write_text("x\n", encoding="utf-8")
    (root / "payload.binx").write_bytes(b"binary")
    (root / "large.py").write_text("x" * 12, encoding="utf-8")


def _config(tmp_path: Path) -> dict:
    return {
        "server": {"state_dir": str(tmp_path / "state")},
        "models": {},
        "search": {"max_files": 100},
        "rag": {
            "extensions": [".py"],
            "ignore_dirs": [],
            "ignore_extensions": [],
            "max_file_bytes": 128,
        },
        "features": {"reranker": False},
    }


def test_repo_inventory_applies_project_paths_types_and_file_limit(
    tmp_path: Path, monkeypatch
):
    _install_policy(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    _files(root)
    tools = RepositoryTools(_config(tmp_path))

    result = tools.file_inventory(str(root), include_hashes=False)

    assert result["success"] is True
    assert result["project_config_digest"] == "test-config-digest"
    assert {item["path"] for item in result["files"]} == {
        "src/app.py", "private/keep.py", "guide.mdx"
    }


def test_rag_inventory_applies_project_paths_types_and_file_limit(
    tmp_path: Path, monkeypatch
):
    context = _install_policy(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    _files(root)
    store = RAGStore(_config(tmp_path))
    project_context = store.project_context(root)

    indexed = {
        path.relative_to(root).as_posix()
        for path in store._iter_files(root, project_context)
    }

    assert indexed == {
        "src/app.py", "private/keep.py", "guide.mdx", "build/generated.py"
    }
    assert project_context.config_digest == "test-config-digest"


def test_rag_force_include_cannot_override_hard_denied_directory(
    tmp_path: Path, monkeypatch
):
    _install_policy(monkeypatch)
    root = tmp_path / "project"
    (root / "blocked").mkdir(parents=True)
    (root / "blocked" / "keep.py").write_text("x\n", encoding="utf-8")
    config = _config(tmp_path)
    config["rag"]["ignore_dirs"] = ["blocked"]
    store = RAGStore(config)

    assert list(store._iter_files(root, store.project_context(root))) == []


def test_project_rag_phase_skip_is_reported_without_indexing(
    tmp_path: Path, monkeypatch
):
    _install_policy(monkeypatch, skip_phases=("rag",))
    root = tmp_path / "project"
    root.mkdir()
    store = RAGStore(_config(tmp_path))
    pruned = []
    store.prune_missing = lambda root, tenant, workspace, paths: pruned.append(paths) or 3

    result = store.index(str(root), "tenant")

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["workspace"] == store.workspace_id(str(root.resolve()))
    assert result["removed_paths"] == 3
    assert pruned == [[]]


def test_rag_skip_phase_prunes_rows_and_advances_workspace_identity(
    tmp_path: Path, monkeypatch
):
    _install_policy(monkeypatch, skip_phases=("rag",))
    root = tmp_path / "project"
    root.mkdir()
    store = RAGStore(_config(tmp_path))
    workspace = store.workspace_id(str(root.resolve()))
    scope = store._scope_key("tenant")
    source = root / "secret.py"
    source.write_text("x\n", encoding="utf-8")
    stat = source.stat()
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO files VALUES(?,?,?,?,?,?)",
            (scope, workspace, "secret.py", stat.st_mtime_ns, stat.st_size, "hash"),
        )
        con.execute(
            "INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)",
            (scope, workspace, "secret.py", 0, "hash", "secret", "[]", "space"),
        )
        con.commit()

    result = store.index(str(root), "tenant")

    assert result["skipped"] is True
    assert result["removed_paths"] == 1
    with closing(store._connect()) as con:
        assert store._workspace_index_generation(con, scope, workspace) == 1
        assert con.execute(
            "SELECT COUNT(*) FROM chunks WHERE tenant=? AND workspace=?",
            (scope, workspace),
        ).fetchone()[0] == 0


def test_preprocessor_watcher_uses_project_exclusions_and_custom_text_types(
    tmp_path: Path, monkeypatch
):
    _install_policy(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    _files(root)
    preprocessor = object.__new__(ProjectPreprocessor)
    preprocessor.repo_tools = RepositoryTools(_config(tmp_path))
    preprocessor.state_dir = tmp_path / "state"

    assert preprocessor._watch_relevant(root, root / "guide.mdx") == "guide.mdx"
    assert preprocessor._watch_relevant(root, root / "private" / "secret.py") is None
    assert preprocessor._watch_relevant(root, root / "private" / "keep.py") == "private/keep.py"
    assert preprocessor._watch_relevant(root, root / "build" / "generated.py") is None


def test_preprocessor_does_not_treat_call_graph_skip_as_code_index_skip(
    tmp_path: Path, monkeypatch
):
    context = _install_policy(monkeypatch, skip_phases=("call_graph",))
    root = tmp_path / "project"
    root.mkdir()
    calls = []
    preprocessor = object.__new__(ProjectPreprocessor)
    preprocessor._yield = lambda: False
    preprocessor._project_context = lambda _root: SimpleNamespace(
        settings=context.settings, config_digest="test-config-digest"
    )
    preprocessor._set_project = lambda _root, **values: calls.append(values)
    preprocessor._step_code_index = lambda _row: calls.append({"code_index_ran": True}) or True

    assert preprocessor._step({"root": str(root), "phase": "code_index"}) is True
    assert {"code_index_ran": True} in calls


def test_preprocessor_rag_skip_prunes_old_vectors_and_advances(tmp_path: Path, monkeypatch):
    context = _install_policy(monkeypatch, skip_phases=("rag",))
    root = tmp_path / "project"
    root.mkdir()
    database = tmp_path / "preprocess.sqlite3"
    preprocessor = object.__new__(ProjectPreprocessor)
    preprocessor.state_dir = tmp_path / "state"
    preprocessor._yield = lambda: False
    preprocessor._project_context = lambda _root: SimpleNamespace(
        settings=context.settings, config_digest="test-config-digest"
    )
    preprocessor._db_lock = threading.RLock()
    preprocessor._connect = lambda: sqlite3.connect(database)
    calls = []
    preprocessor._set_project = lambda _root, **values: calls.append(values)
    pruned = []
    preprocessor.rag = SimpleNamespace(
        prune_missing=lambda *args: pruned.append(args) or 1
    )
    preprocessor._step_rag = lambda _row: (_ for _ in ()).throw(AssertionError("skip ignored"))
    with closing(sqlite3.connect(database)) as con:
        con.execute(
            "CREATE TABLE file_refs(root TEXT, content_hash TEXT, rag_hash TEXT, needs_hash INTEGER)"
        )
        con.execute(
            "INSERT INTO file_refs VALUES(?,?,?,?)", (str(root), "digest", "old", 0)
        )
        con.commit()

    assert preprocessor._step(
        {"root": str(root), "phase": "rag", "workspace": "workspace-id"}
    ) is True
    assert pruned == [(str(root), "__preprocess__", "workspace-id", [])]
    assert {"phase": "files"} in calls
    with closing(sqlite3.connect(database)) as con:
        assert con.execute("SELECT rag_hash FROM file_refs").fetchone()[0] == "digest"


def test_preprocessor_skips_modules_and_clears_derived_cards(tmp_path: Path, monkeypatch):
    context = _install_policy(monkeypatch, skip_phases=("modules",))
    root = tmp_path / "project"
    root.mkdir()
    preprocessor = object.__new__(ProjectPreprocessor)
    preprocessor._yield = lambda: False
    preprocessor._project_context = lambda _root: SimpleNamespace(
        settings=context.settings, config_digest="test-config-digest"
    )
    preprocessor._set_project = lambda _root, **values: calls.append(values)
    calls = []
    database = tmp_path / "preprocess.sqlite3"
    preprocessor._db_lock = threading.RLock()
    preprocessor._connect = lambda: sqlite3.connect(database)
    with closing(sqlite3.connect(database)) as con:
        con.executescript(
            "CREATE TABLE module_cards(root TEXT);"
            "CREATE TABLE project_cards(root TEXT);"
            "CREATE TABLE hot_query_state(root TEXT);"
            "CREATE TABLE task_capsules(root TEXT);"
        )
        for table in ("module_cards", "project_cards", "hot_query_state", "task_capsules"):
            con.execute(f"INSERT INTO {table}(root) VALUES(?)", (str(root),))
        con.commit()
    preprocessor._step_module = lambda _row: (_ for _ in ()).throw(AssertionError("skip ignored"))

    assert preprocessor._step({"root": str(root), "phase": "modules"}) is True
    assert {"phase": "project"} in calls
    with closing(sqlite3.connect(database)) as con:
        assert all(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
                   for table in ("module_cards", "project_cards", "hot_query_state", "task_capsules"))


def test_call_graph_skip_returns_empty_deterministic_result(tmp_path: Path, monkeypatch):
    _install_policy(monkeypatch, skip_phases=("call_graph",))
    engine = object.__new__(DeterministicEngine)
    engine.db_path = tmp_path / "state" / "deterministic.sqlite3"

    result = engine.call_graph_diff(tmp_path, diff="+def changed(value):\n+    return value\n")

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["breaking_callers"] == []


def test_rag_policy_digest_prunes_excluded_chunks_and_invalidates_identity(
    tmp_path: Path, monkeypatch
):
    context = _install_policy(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    _files(root)
    store = RAGStore(_config(tmp_path))
    workspace = store.workspace_id(str(root.resolve()))
    scope = store._scope_key("tenant")
    digest_key = store._workspace_project_config_key(
        scope, workspace, store._project_root_identity(root)
    )
    source_stat = (root / "private" / "secret.py").stat()
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO rag_meta(key,value) VALUES(?,?)", (digest_key, "old-policy-digest")
        )
        con.execute(
            "INSERT INTO files VALUES(?,?,?,?,?,?)",
            (scope, workspace, "private/secret.py", source_stat.st_mtime_ns,
             source_stat.st_size, "secret-hash"),
        )
        con.execute(
            "INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)",
            (scope, workspace, "private/secret.py", 0, "secret-hash", "secret source", "[]", "space"),
        )
        con.commit()

    result = store.index_paths_step(str(root), "tenant", workspace, [])

    assert result["success"] is True
    with closing(store._connect()) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM files WHERE tenant=? AND workspace=? AND path=?",
            (scope, workspace, "private/secret.py"),
        ).fetchone()[0] == 0
        assert con.execute(
            "SELECT COUNT(*) FROM chunks WHERE tenant=? AND workspace=? AND path=?",
            (scope, workspace, "private/secret.py"),
        ).fetchone()[0] == 0
        assert store._workspace_index_generation(con, scope, workspace) == 1
        assert con.execute("SELECT value FROM rag_meta WHERE key=?", (digest_key,)).fetchone()[0] == "test-config-digest"

    context.api.resolve_project_context = lambda root, _state_dir=None: SimpleNamespace(
        root=Path(root), settings=context.settings, config_digest="changed-policy-digest"
    )
    result = store.index_paths_step(str(root), "tenant", workspace, [])

    assert result["success"] is True
    with closing(store._connect()) as con:
        assert store._workspace_index_generation(con, scope, workspace) == 2
        assert con.execute("SELECT value FROM rag_meta WHERE key=?", (digest_key,)).fetchone()[0] == "changed-policy-digest"
        metadata = [str(row[0]) + str(row[1]) for row in con.execute("SELECT key,value FROM rag_meta")]
        assert all("secret source" not in item and str(root) not in item for item in metadata)


def test_explicit_rag_ingestion_removes_policy_rejected_source_paths(
    tmp_path: Path, monkeypatch
):
    _install_policy(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    _files(root)
    store = RAGStore(_config(tmp_path))
    workspace = store.workspace_id(str(root.resolve()))
    scope = store._scope_key("tenant")
    digest_key = store._workspace_project_config_key(
        scope, workspace, store._project_root_identity(root)
    )
    rejected = ["private/secret.py", "payload.binx", "large.py"]
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO rag_meta(key,value) VALUES(?,?)",
            (digest_key, "test-config-digest"),
        )
        for rel in rejected:
            stat = (root / rel).stat()
            file_hash = "hash-" + rel
            con.execute(
                "INSERT INTO files VALUES(?,?,?,?,?,?)",
                (scope, workspace, rel, stat.st_mtime_ns, stat.st_size, file_hash),
            )
            con.execute(
                "INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)",
                (scope, workspace, rel, 0, file_hash, "private source", "[]", "space"),
            )
        con.commit()

    result = store.index_paths_step(str(root), "tenant", workspace, rejected)

    assert result["success"] is True
    assert set(result["deleted_paths"]) == set(rejected)
    with closing(store._connect()) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM files WHERE tenant=? AND workspace=?",
            (scope, workspace),
        ).fetchone()[0] == 0
        assert con.execute(
            "SELECT COUNT(*) FROM chunks WHERE tenant=? AND workspace=?",
            (scope, workspace),
        ).fetchone()[0] == 0


def test_explicit_rag_ingestion_reconciles_hard_ignored_paths(
    tmp_path: Path, monkeypatch
):
    _install_policy(monkeypatch)
    root = tmp_path / "project"
    target = root / "blocked" / "keep.py"
    target.parent.mkdir(parents=True)
    target.write_text("x=1\n", encoding="utf-8")
    config = _config(tmp_path)
    services = SimpleNamespace(
        embed=lambda texts, _tenant, **_kwargs: {
            "success": True,
            "embedding_space_id": "test-space",
            "embeddings": [[1.0, 0.0] for _ in texts],
        }
    )
    store = RAGStore(config, services=services)
    workspace = store.workspace_id(str(root.resolve()))
    scope = store._scope_key("tenant")

    indexed = store.index_paths_step(str(root), "tenant", workspace, ["blocked/keep.py"])
    assert indexed["success"] is True
    with closing(store._connect()) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM files WHERE tenant=? AND workspace=? AND path=?",
            (scope, workspace, "blocked/keep.py"),
        ).fetchone()[0] == 1

    config["rag"]["ignore_dirs"] = ["blocked"]
    reconciled = store.index_paths_step(str(root), "tenant", workspace, ["blocked/keep.py"])

    assert reconciled["success"] is True
    with closing(store._connect()) as con:
        for table in ("files", "chunks", "chunk_fts"):
            assert con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE tenant=? AND workspace=? AND path=?",
                (scope, workspace, "blocked/keep.py"),
            ).fetchone()[0] == 0


def test_explicit_rag_ingestion_accepts_project_custom_text_extension(
    tmp_path: Path, monkeypatch
):
    _install_policy(monkeypatch)
    root = tmp_path / "project"
    root.mkdir()
    (root / "guide.mdx").write_text("guide\n", encoding="utf-8")
    config = _config(tmp_path)
    services = SimpleNamespace(
        embed=lambda texts, _tenant, **_kwargs: {
            "success": True,
            "embedding_space_id": "test-space",
            "embeddings": [[1.0, 0.0] for _ in texts],
        }
    )
    store = RAGStore(config, services=services)
    workspace = store.workspace_id(str(root.resolve()))

    result = store.index_paths_step(str(root), "tenant", workspace, ["guide.mdx"])

    assert result["success"] is True
    with closing(store._connect()) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM files WHERE tenant=? AND workspace=? AND path=?",
            (store._scope_key("tenant"), workspace, "guide.mdx"),
        ).fetchone()[0] == 1


def test_explicit_rag_ingestion_normalizes_windows_path_before_policy_and_storage(
    tmp_path: Path, monkeypatch
):
    _install_policy(monkeypatch)
    root = tmp_path / "project"
    (root / "private").mkdir(parents=True)
    (root / "private" / "keep.py").write_text("keep\n", encoding="utf-8")
    services = SimpleNamespace(
        embed=lambda texts, _tenant, **_kwargs: {
            "success": True,
            "embedding_space_id": "test-space",
            "embeddings": [[1.0, 0.0] for _ in texts],
        }
    )
    store = RAGStore(_config(tmp_path), services=services)
    workspace = store.workspace_id(str(root.resolve()))

    result = store.index_paths_step(
        str(root), "tenant", workspace, [r"private\keep.py"]
    )

    assert result["success"] is True
    assert result["processed_paths"] == ["private/keep.py"]
    with closing(store._connect()) as con:
        row = con.execute(
            "SELECT path,text FROM chunks WHERE tenant=? AND workspace=?",
            (store._scope_key("tenant"), workspace),
        ).fetchone()
    assert row == ("private/keep.py", "keep\n")


def test_rag_worktree_consumer_inherits_committed_project_path_policy(tmp_path: Path):
    pytest.importorskip("local_ai_hub.project_config")
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktrees" / "feature"
    primary.mkdir()
    worktree.parent.mkdir(parents=True)

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(primary), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()

    git("init", "--quiet")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    _files(primary)
    (primary / ".local-ai.toml").write_text(
        'exclude_paths = ["private/secret.py"]\n'
        'force_include_paths = ["private/keep.py", "private/secret.py"]\n'
        '[preprocess]\nexclude_paths = ["build/**"]\n'
        '[custom_extensions]\ntext = [".mdx"]\n'
        '[file_limits]\nmax_file_size_bytes = 8\n',
        encoding="utf-8",
    )
    git("add", ".")
    git("commit", "--quiet", "-m", "project policy fixture")
    git("worktree", "add", "--quiet", "--detach", str(worktree), "HEAD")

    cfg = _config(tmp_path)
    rag_store = RAGStore(cfg)
    rag_paths = {
        path.relative_to(worktree).as_posix()
        for path in rag_store._iter_files(
            worktree,
            rag_store.project_context(worktree),
        )
    }
    expected_rag = {"src/app.py", "private/keep.py", "guide.mdx", "build/generated.py"}

    assert rag_paths == expected_rag
    assert rag_store.project_context(worktree).settings.force_include_paths == (
        "private/keep.py", "private/secret.py"
    )


def test_rag_reindexes_same_head_worktree_after_local_config_change(tmp_path: Path):
    pytest.importorskip("local_ai_hub.project_config")

    class _EmbeddingServices:
        space_id = "worktree-config-reindex-space"

        def __init__(self):
            self.calls = 0

        def embed(self, texts, _tenant, **_kwargs):
            self.calls += len(texts)
            return {
                "success": True,
                "embeddings": [[1.0, 0.0] for _ in texts],
                "embedding_space_id": self.space_id,
            }

    primary = tmp_path / "primary"
    worktree = tmp_path / "worktrees" / "feature"
    primary.mkdir()
    worktree.parent.mkdir(parents=True)

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(primary), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()

    git("init", "--quiet")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (primary / "module.py").write_text("def useful():\n    return 42\n", encoding="utf-8")
    git("add", "module.py")
    git("commit", "--quiet", "-m", "tracked source")
    git("worktree", "add", "--quiet", "--detach", str(worktree), "HEAD")

    def head(path: Path) -> str:
        return subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()

    store = RAGStore(_config(tmp_path), services=_EmbeddingServices())
    workspace = store.workspace_id(str(worktree.resolve()))
    initial_head = head(worktree)
    initial = store.index(str(worktree), "tenant", workspace)
    assert initial["success"] is True
    assert initial["files"] == 1
    assert store.services.calls > 0
    initial_embed_calls = store.services.calls
    before_config_change = store.search("useful", "tenant", workspace, use_reranker=False)
    cached_before_config_change = store.search("useful", "tenant", workspace, use_reranker=False)
    assert [row["path"] for row in before_config_change["results"]] == ["module.py"]
    assert cached_before_config_change["search_cache"]["hit"] is True

    override = worktree / ".local-ai.worktree.toml"
    override.write_text("[file_limits]\nmax_file_size_bytes = 1\n", encoding="utf-8")
    restricted = store.index(str(worktree), "tenant", workspace)
    with closing(store._connect()) as con:
        restricted_counts = tuple(
                con.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE tenant=? AND workspace=?",
                    (store._scope_key("tenant"), workspace),
                ).fetchone()[0]
                for table in ("files", "chunks", "chunk_fts")
        )

    assert restricted["success"] is True
    assert restricted_counts == (0, 0, 0)
    after_config_change = store.search("useful", "tenant", workspace, use_reranker=False)
    assert after_config_change["search_cache"]["hit"] is False
    assert after_config_change["results"] == []
    assert head(primary) == head(worktree) == initial_head

    override.unlink()
    restored = store.index(str(worktree), "tenant", workspace)
    with closing(store._connect()) as con:
        restored_paths = [
            row[0]
            for row in con.execute(
                "SELECT path FROM files WHERE tenant=? AND workspace=?",
                (store._scope_key("tenant"), workspace),
            )
        ]

    assert restored["success"] is True
    assert restored_paths == ["module.py"]
    assert store.services.calls > initial_embed_calls
    after_config_restore = store.search("useful", "tenant", workspace, use_reranker=False)
    assert after_config_restore["search_cache"]["hit"] is False
    assert [row["path"] for row in after_config_restore["results"]] == ["module.py"]
    assert head(worktree) == initial_head


def test_rag_policy_change_invalidates_cached_search_results(tmp_path: Path, monkeypatch):
    class _EmbeddingServices:
        space_id = "policy-cache-test-space"

        def embed(self, texts, _tenant, **_kwargs):
            return {
                "success": True,
                "embeddings": [[float(len(text)), 1.0] for text in texts],
                "embedding_space_id": "policy-cache-test-space",
            }

    context = _install_policy(monkeypatch)
    context.settings.exclude_paths = ()
    digest = {"value": "allow-policy"}
    context.api.resolve_project_context = lambda root, _state_dir=None: SimpleNamespace(
        root=Path(root), settings=context.settings, config_digest=digest["value"]
    )
    root = tmp_path / "project"
    (root / "private").mkdir(parents=True)
    (root / "private" / "secret.py").write_text("secret\n", encoding="utf-8")
    store = RAGStore(_config(tmp_path), services=_EmbeddingServices())
    workspace = store.workspace_id(str(root.resolve()))

    indexed = store.index(str(root), "tenant", workspace)
    before = store.search("secret", "tenant", workspace, use_reranker=False)
    warm = store.search("secret", "tenant", workspace, use_reranker=False)

    assert indexed["success"] is True
    assert [item["path"] for item in before["results"]] == ["private/secret.py"]
    assert before["search_cache"]["hit"] is False
    assert warm["search_cache"]["hit"] is True

    context.settings.exclude_paths = ("private/secret.py",)
    digest["value"] = "deny-policy"
    pruned = store.index_paths_step(str(root), "tenant", workspace, [])
    after = store.search("secret", "tenant", workspace, use_reranker=False)

    assert pruned["success"] is True
    assert after["search_cache"]["hit"] is False
    assert all(item["path"] != "private/secret.py" for item in after["results"])
