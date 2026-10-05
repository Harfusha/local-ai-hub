from __future__ import annotations

import io
import os
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.rag import RAGStore


class _VectorServices:
    def __init__(self):
        self.document_calls: list[str] = []

    def embed(self, texts, tenant, **kwargs):
        if not kwargs.get("query", False):
            self.document_calls.append(tenant)
        return {
            "success": True,
            "embedding_space_id": "shared-test-space",
            "embeddings": [[1.0, 0.0] for _ in texts],
        }


def _store(
    tmp_path: Path,
    *,
    max_file_bytes: int = 32,
    scope: str = "shared",
) -> RAGStore:
    return RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {},
            "cpu_retrieval": {},
            "workspace_cache": {},
            "rag": {
                "extensions": [".py"],
                "ignore_dirs": [],
                "max_file_bytes": max_file_bytes,
                "scope": scope,
            },
            "resilience": {"singleflight_wait_timeout_seconds": 2},
            "features": {"reranker": False},
        },
        services=_VectorServices(),
    )


def _indexed_counts(store: RAGStore, tenant: str, workspace: str, path: str):
    scope_key = store._scope_key(tenant)
    with closing(store._connect()) as con:
        return tuple(
            con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE tenant=? AND workspace=? AND path=?",
                (scope_key, workspace, path),
            ).fetchone()[0]
            for table in ("files", "chunks", "chunk_fts")
        )


@pytest.mark.parametrize("entrypoint", ["index", "index_paths_step"])
def test_file_growth_preserves_snapshot_and_suppresses_results_until_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entrypoint: str
):
    store = _store(tmp_path, max_file_bytes=32)
    root = tmp_path / "project"
    root.mkdir()
    path = root / "module.py"
    path.write_text("value = 'before'\n", encoding="utf-8")
    tenant, workspace = "tenant", "workspace"
    assert store.index_paths_step(str(root), tenant, workspace, ["module.py"])["success"]
    assert _indexed_counts(store, tenant, workspace, "module.py") == (1, 1, 1)
    committed = store.search("value before", tenant, workspace, use_reranker=False)
    assert committed["results"][0]["text"].replace("\r\n", "\n") == "value = 'before'\n"

    path.write_text("value = 'changed'\n", encoding="utf-8")
    original_open = Path.open

    def grow_after_stat(candidate: Path, mode="r", *args, **kwargs):
        if candidate.resolve() == path.resolve() and mode == "rb":
            return io.BytesIO(b"x" * 33)
        return original_open(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", grow_after_stat)
    if entrypoint == "index":
        result = store.index(str(root), tenant, workspace)
    else:
        result = store.index_paths_step(str(root), tenant, workspace, ["module.py"])

    assert result["success"] is True
    assert _indexed_counts(store, tenant, workspace, "module.py") == (1, 1, 1)
    uncertain = store.search("value before", tenant, workspace, use_reranker=False)
    assert uncertain["results"] == []
    assert uncertain["fallback"] == "source_read_uncertain"

    monkeypatch.setattr(Path, "open", original_open)
    if entrypoint == "index":
        recovered = store.index(str(root), tenant, workspace)
    else:
        recovered = store.index_paths_step(str(root), tenant, workspace, ["module.py"])

    assert recovered["success"] is True
    refreshed = store.search("value before", tenant, workspace, use_reranker=False)
    assert [row["text"].replace("\r\n", "\n") for row in refreshed["results"]] == ["value = 'changed'\n"]


@pytest.mark.parametrize("entrypoint", ["index", "index_paths_step"])
def test_read_uncertainty_published_before_mixed_embed_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entrypoint: str
):
    store = _store(tmp_path, max_file_bytes=256)
    root = tmp_path / "project"
    root.mkdir()
    unreadable = root / "unreadable.py"
    changed = root / "changed.py"
    unreadable.write_text("private_old_marker = 1\n", encoding="utf-8")
    changed.write_text("changed_old_marker = 1\n", encoding="utf-8")
    tenant, workspace = "tenant", "workspace"
    assert store.index(str(root), tenant, workspace)["success"]
    unreadable.write_text("private_new_marker = 2\n", encoding="utf-8")
    changed.write_text("changed_new_marker = 2\n", encoding="utf-8")
    original_open = Path.open

    def fail_selected_read(candidate: Path, mode="r", *args, **kwargs):
        if candidate.resolve() == unreadable.resolve() and mode == "rb":
            raise PermissionError("forced source read failure")
        return original_open(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_selected_read)
    original_embed = store.services.embed

    def fail_document_embedding(texts, tenant_arg, **kwargs):
        if not kwargs.get("query", False):
            return {"success": False, "error": "forced embedding failure"}
        return original_embed(texts, tenant_arg, **kwargs)

    monkeypatch.setattr(store.services, "embed", fail_document_embedding)
    if entrypoint == "index":
        result = store.index(str(root), tenant, workspace)
    else:
        result = store.index_paths_step(
            str(root), tenant, workspace, ["unreadable.py", "changed.py"]
        )

    assert result["success"] is False
    exposed = store.search("private_old_marker", tenant, workspace, use_reranker=False)
    assert all(row["path"] != "unreadable.py" for row in exposed["results"])
    assert all("private_old_marker" not in row.get("text", "") for row in exposed["results"])


def test_full_index_retries_uncertain_path_when_metadata_matches_old_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = _store(tmp_path, max_file_bytes=256)
    root = tmp_path / "project"
    root.mkdir()
    path = root / "module.py"
    path.write_text("value = 'before'\n", encoding="utf-8")
    tenant, workspace = "tenant", "workspace"
    assert store.index(str(root), tenant, workspace)["success"]
    old_stat = path.stat()
    path.write_text("value = 'after!'\n", encoding="utf-8")
    original_open = Path.open

    def fail_read(candidate: Path, mode="r", *args, **kwargs):
        if candidate.resolve() == path.resolve() and mode == "rb":
            raise PermissionError("forced source read failure")
        return original_open(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_read)
    failed = store.index(str(root), tenant, workspace)
    assert failed["success"] is True
    os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    monkeypatch.setattr(Path, "open", original_open)

    recovered = store.index(str(root), tenant, workspace)

    assert recovered["success"] is True
    result = store.search("value after", tenant, workspace, use_reranker=False)
    assert [row["text"].replace("\r\n", "\n") for row in result["results"]] == ["value = 'after!'\n"]


def test_incremental_index_retries_uncertain_path_when_metadata_matches_old_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = _store(tmp_path, max_file_bytes=256)
    root = tmp_path / "project"
    root.mkdir()
    path = root / "module.py"
    path.write_text("value = 'before'\n", encoding="utf-8")
    tenant, workspace = "tenant", "workspace"
    assert store.index_step(str(root), tenant, workspace)["success"] is True
    old_stat = path.stat()
    path.write_text("value = 'after!'\n", encoding="utf-8")
    original_open = Path.open

    def fail_read(candidate: Path, mode="r", *args, **kwargs):
        if candidate.resolve() == path.resolve() and mode == "rb":
            raise PermissionError("forced source read failure")
        return original_open(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_read)
    failed = store.index_step(str(root), tenant, workspace)
    assert failed["success"] is True
    os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    monkeypatch.setattr(Path, "open", original_open)

    recovered = store.index_step(str(root), tenant, workspace)

    assert recovered["success"] is True
    assert recovered["processed_files"] == 1
    result = store.search("value after", tenant, workspace, use_reranker=False)
    assert [row["text"].replace("\r\n", "\n") for row in result["results"]] == ["value = 'after!'\n"]


def test_content_override_obeys_configured_file_limit(tmp_path: Path):
    store = _store(tmp_path, max_file_bytes=32)
    root = tmp_path / "project"
    root.mkdir()
    path = root / "module.py"
    path.write_text("value = 1\n", encoding="utf-8")
    tenant, workspace = "tenant", "workspace"
    assert store.index_paths_step(str(root), tenant, workspace, ["module.py"])["success"]
    assert _indexed_counts(store, tenant, workspace, "module.py") == (1, 1, 1)

    result = store.index_paths_step(
        str(root), tenant, workspace, ["module.py"],
        content_overrides={"module.py": "x" * 33},
    )

    assert result["success"] is True
    assert _indexed_counts(store, tenant, workspace, "module.py") == (0, 0, 0)


def test_oversized_stat_removes_previous_incremental_snapshot(tmp_path: Path):
    store = _store(tmp_path, max_file_bytes=32)
    root = tmp_path / "project"
    root.mkdir()
    path = root / "module.py"
    path.write_text("value = 1\n", encoding="utf-8")
    tenant, workspace = "tenant", "workspace"
    assert store.index_paths_step(str(root), tenant, workspace, ["module.py"])["success"]
    assert _indexed_counts(store, tenant, workspace, "module.py") == (1, 1, 1)

    path.write_text("x" * 33, encoding="utf-8")
    result = store.index_paths_step(str(root), tenant, workspace, ["module.py"])

    assert result["success"] is True
    assert _indexed_counts(store, tenant, workspace, "module.py") == (0, 0, 0)


def test_tenant_isolation_blocks_cross_tenant_chunk_reuse_and_search(
    tmp_path: Path,
):
    store = _store(tmp_path, scope="tenant")
    root_a = tmp_path / "tenant-a-project"
    root_b = tmp_path / "tenant-b-project"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "secret.py").write_text("needle tenant-a-private marker\n", encoding="utf-8")
    (root_b / "public.py").write_text("ordinary tenant-b content\n", encoding="utf-8")
    workspace = "shared-workspace"

    assert store.index(str(root_a), "tenant-a", workspace)["success"] is True
    assert store.index(str(root_b), "tenant-b", workspace)["success"] is True
    assert "tenant-a" in store.services.document_calls
    assert "tenant-b" in store.services.document_calls

    result = store.search("needle", "tenant-b", workspace, use_reranker=False)

    assert result["success"] is True
    assert all("tenant-a-private" not in row.get("text", "") for row in result["results"])
