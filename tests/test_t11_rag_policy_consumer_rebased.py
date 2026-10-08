from __future__ import annotations

import fnmatch
import sys
import types
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub.rag import RAGStore

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
            con.execute(
                "INSERT INTO chunk_fts(tenant,workspace,path,chunk_no,text) VALUES(?,?,?,?,?)",
                (scope, workspace, rel, 0, "private source"),
            )
        con.commit()

    result = store.index_paths_step(str(root), "tenant", workspace, rejected)

    assert result["success"] is True
    with closing(store._connect()) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM files WHERE tenant=? AND workspace=?",
            (scope, workspace),
        ).fetchone()[0] == 0
        assert con.execute(
            "SELECT COUNT(*) FROM chunks WHERE tenant=? AND workspace=?",
            (scope, workspace),
        ).fetchone()[0] == 0
        assert con.execute(
            "SELECT COUNT(*) FROM chunk_fts WHERE tenant=? AND workspace=?",
            (scope, workspace),
        ).fetchone()[0] == 0

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
def test_rag_inventory_uses_live_project_config_api(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    _files(root)
    (root / ".local-ai.toml").write_text(
        'exclude_paths = ["private/secret.py"]\n'
        'force_include_paths = ["private/keep.py", "private/secret.py"]\n'
        '[preprocess]\nexclude_paths = ["build/**"]\n'
        '[custom_extensions]\ntext = [".mdx"]\n'
        '[file_limits]\nmax_file_size_bytes = 8\n',
        encoding="utf-8",
    )
    store = RAGStore(_config(tmp_path))
    project_context = store.project_context(root)
    indexed = {path.relative_to(root).as_posix() for path in store._iter_files(root, project_context)}
    assert project_context.config_digest
    assert indexed == {"src/app.py", "private/keep.py", "guide.mdx", "build/generated.py"}
