"""RAG repository-root binding contract (authored, not executed here)."""

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from local_ai_hub.rag import RAGStore
from local_ai_hub.process_utils import canonical_workspace_id


def _store(tmp_path, *, files=(), chunks=(), binding=None):
    db_path = tmp_path / "rag.sqlite3"
    with closing(sqlite3.connect(db_path)) as con, con:
        con.executescript(
            "CREATE TABLE rag_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE files (workspace TEXT NOT NULL, path TEXT NOT NULL);"
            "CREATE TABLE chunks (workspace TEXT NOT NULL, path TEXT NOT NULL);"
        )
        if binding is not None:
            con.execute("INSERT INTO rag_meta(key,value) VALUES(?,?)", binding)
        con.executemany("INSERT INTO files(workspace,path) VALUES(?,?)", files)
        con.executemany("INSERT INTO chunks(workspace,path) VALUES(?,?)", chunks)
    store = RAGStore.__new__(RAGStore)
    store._connect = lambda: sqlite3.connect(db_path)
    store.project_context = lambda _root: None
    store.config = {"rag": {"max_file_bytes": 100_000}}
    return store, db_path


def test_empty_unbound_workspace_allows_read_without_persisting_binding(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    workspace = canonical_workspace_id(str(root))
    store, db_path = _store(tmp_path)

    store.require_workspace_root(workspace=workspace, root=str(root))

    with closing(sqlite3.connect(db_path)) as con, con:
        assert con.execute("SELECT COUNT(*) FROM rag_meta").fetchone()[0] == 0


def test_bound_workspace_rejects_a_different_stored_repository_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    workspace = canonical_workspace_id(str(root))
    store, _db_path = _store(
        tmp_path,
        binding=(
            RAGStore._workspace_root_identity_key(workspace),
            "wrong-root-identity",
        ),
    )

    with pytest.raises(ValueError, match="already bound"):
        store.require_workspace_root(workspace=workspace, root=str(root))


@pytest.mark.parametrize("populated_table", ["files", "chunks"])
def test_populated_unbound_workspace_requires_offline_rebuild(tmp_path, populated_table):
    root = tmp_path / "repo"
    root.mkdir()
    workspace = canonical_workspace_id(str(root))
    rows = ((workspace, "a.py"),)
    store, db_path = _store(
        tmp_path,
        files=rows if populated_table == "files" else (),
        chunks=rows if populated_table == "chunks" else (),
    )

    with pytest.raises(ValueError, match="explicit offline rebuild"):
        store.require_workspace_root(workspace=workspace, root=str(root))

    with closing(sqlite3.connect(db_path)) as con, con:
        count = con.execute(f"SELECT COUNT(*) FROM {populated_table}").fetchone()[0]
    assert count == 1


def test_custom_workspace_label_is_preserved_but_root_binding_is_exact(tmp_path):
    root = tmp_path / "repo"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()
    workspace = "explicit-project-workspace"
    store, _db_path = _store(
        tmp_path,
        binding=(
            RAGStore._workspace_root_identity_key(workspace),
            RAGStore._project_root_identity(root),
        ),
    )

    store.require_workspace_root(workspace=workspace, root=str(root))
    with pytest.raises(ValueError, match="already bound"):
        store.require_workspace_root(workspace=workspace, root=str(other))


def test_file_symlinks_are_not_indexed_outside_repository_root(tmp_path):
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "inside.txt").write_text("inside", encoding="utf-8")
    target = outside / "secret.txt"
    target.write_text("outside", encoding="utf-8")
    link = root / "linked.txt"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"file symlinks unavailable in this environment: {exc}")

    store = RAGStore.__new__(RAGStore)
    store.config = {"rag": {"extensions": [".txt"]}}

    assert list(store._iter_files(root)) == [root / "inside.txt"]


def test_document_ingest_rejects_workspace_bound_to_another_root_before_writes(tmp_path):
    root = tmp_path / "repo"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()
    workspace = "explicit-project-workspace"
    store, db_path = _store(
        tmp_path,
        binding=(
            RAGStore._workspace_root_identity_key(workspace),
            RAGStore._project_root_identity(other),
        ),
    )

    result = store.ingest_document(
        root=str(root), workspace=workspace, content="must not be indexed"
    )

    assert result["success"] is False
    assert "different repository root" in result["error"]
    with closing(sqlite3.connect(db_path)) as con, con:
        assert con.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0


def test_diagram_ingest_rejects_paths_outside_authorized_root(tmp_path):
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    external_image = outside / "architecture.png"
    external_image.write_bytes(b"not-read")
    workspace = "explicit-project-workspace"
    store, db_path = _store(tmp_path)

    result = store.ingest_diagram(
        root=str(root), workspace=workspace, image_path=str(external_image)
    )

    assert result["success"] is False
    assert "inside the authorized repository root" in result["error"]
    with closing(sqlite3.connect(db_path)) as con, con:
        assert con.execute("SELECT COUNT(*) FROM rag_meta").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
