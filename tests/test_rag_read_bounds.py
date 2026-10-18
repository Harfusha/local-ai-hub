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

    def embed(self, texts, **kwargs):
        if not kwargs.get("query", False):
            self.document_calls.extend(str(text) for text in texts)
        return {
            "success": True,
            "embedding_space_id": "shared-test-space",
            "embeddings": [[1.0, 0.0] for _ in texts],
        }


def _store(
    tmp_path: Path,
    *,
    max_file_bytes: int = 32,
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
            },
            "resilience": {"singleflight_wait_timeout_seconds": 2},
            "features": {"reranker": False},
        },
        services=_VectorServices(),
    )


def _indexed_counts(store: RAGStore, workspace: str, path: str):
    with closing(store._connect()) as con:
        return tuple(
            con.execute(
                f"SELECT COUNT(*) FROM {table} WHERE workspace=? AND path=?",
                (workspace, path),
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
    workspace = "workspace"
    assert store.index_paths_step(str(root), workspace=workspace, paths=["module.py"])["success"]
    assert _indexed_counts(store, workspace,  "module.py") == (1, 1, 1)
    committed = store.search("value before", use_reranker=False, workspace=workspace)
    assert committed["results"][0]["text"].replace("\r\n", "\n") == "value = 'before'\n"

    path.write_text("value = 'changed'\n", encoding="utf-8")
    original_open = Path.open

    def grow_after_stat(candidate: Path, mode="r", *args, **kwargs):
        if candidate.resolve() == path.resolve() and mode == "rb":
            return io.BytesIO(b"x" * 33)
        return original_open(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", grow_after_stat)
    if entrypoint == "index":
        result = store.index(str(root), workspace=workspace)
    else:
        result = store.index_paths_step(str(root), workspace=workspace, paths=["module.py"])

    assert result["success"] is True, result
    assert _indexed_counts(store, workspace,  "module.py") == (1, 1, 1)
    uncertain = store.search("value before", use_reranker=False, workspace=workspace)
    assert uncertain["results"] == []
    assert uncertain["fallback"] == "source_read_uncertain"

    monkeypatch.setattr(Path, "open", original_open)
    if entrypoint == "index":
        recovered = store.index(str(root), workspace=workspace)
    else:
        recovered = store.index_paths_step(str(root), workspace=workspace, paths=["module.py"])

    assert recovered["success"] is True
    refreshed = store.search("value before", use_reranker=False, workspace=workspace)
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
    workspace = "workspace"
    assert store.index(str(root), workspace=workspace)["success"]
    unreadable.write_text("private_new_marker = 2\n", encoding="utf-8")
    changed.write_text("changed_new_marker = 2\n", encoding="utf-8")
    original_open = Path.open

    def fail_selected_read(candidate: Path, mode="r", *args, **kwargs):
        if candidate.resolve() == unreadable.resolve() and mode == "rb":
            raise PermissionError("forced source read failure")
        return original_open(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_selected_read)
    original_embed = store.services.embed

    def fail_document_embedding(texts, **kwargs):
        if not kwargs.get("query", False):
            return {"success": False, "error": "forced embedding failure"}
        return original_embed(texts, **kwargs)

    monkeypatch.setattr(store.services, "embed", fail_document_embedding)
    if entrypoint == "index":
        result = store.index(str(root), workspace=workspace)
    else:
        result = store.index_paths_step(str(root), workspace=workspace, paths=["unreadable.py", "changed.py"])

    assert result["success"] is False
    exposed = store.search("private_old_marker", use_reranker=False, workspace=workspace)
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
    workspace = "workspace"
    assert store.index(str(root), workspace=workspace)["success"]
    old_stat = path.stat()
    path.write_text("value = 'after!'\n", encoding="utf-8")
    original_open = Path.open

    def fail_read(candidate: Path, mode="r", *args, **kwargs):
        if candidate.resolve() == path.resolve() and mode == "rb":
            raise PermissionError("forced source read failure")
        return original_open(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_read)
    failed = store.index(str(root), workspace=workspace)
    assert failed["success"] is True
    os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    monkeypatch.setattr(Path, "open", original_open)

    recovered = store.index(str(root), workspace=workspace)

    assert recovered["success"] is True
    result = store.search("value after", use_reranker=False, workspace=workspace)
    assert [row["text"].replace("\r\n", "\n") for row in result["results"]] == ["value = 'after!'\n"]


def test_content_override_obeys_configured_file_limit(tmp_path: Path):
    store = _store(tmp_path, max_file_bytes=32)
    root = tmp_path / "project"
    root.mkdir()
    path = root / "module.py"
    path.write_text("value = 1\n", encoding="utf-8")
    workspace = "workspace"
    assert store.index_paths_step(str(root), workspace=workspace, paths=["module.py"])["success"]
    assert _indexed_counts(store, workspace,  "module.py") == (1, 1, 1)

    result = store.index_paths_step(str(root), content_overrides={"module.py": "x" * 33}, workspace=workspace, paths=["module.py"])

    assert result["success"] is True
    assert _indexed_counts(store, workspace,  "module.py") == (0, 0, 0)


def test_oversized_stat_removes_previous_incremental_snapshot(tmp_path: Path):
    store = _store(tmp_path, max_file_bytes=32)
    root = tmp_path / "project"
    root.mkdir()
    path = root / "module.py"
    path.write_text("value = 1\n", encoding="utf-8")
    workspace = "workspace"
    assert store.index_paths_step(str(root), workspace=workspace, paths=["module.py"])["success"]
    assert _indexed_counts(store, workspace,  "module.py") == (1, 1, 1)

    path.write_text("x" * 33, encoding="utf-8")
    result = store.index_paths_step(str(root), workspace=workspace, paths=["module.py"])

    assert result["success"] is True
    assert _indexed_counts(store, workspace,  "module.py") == (0, 0, 0)


def test_workspace_identity_separates_root_search_results(tmp_path: Path):
    store = _store(tmp_path)
    root_a = tmp_path / "repository-a"
    root_b = tmp_path / "repository-b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "secret.py").write_text("needle private marker\n", encoding="utf-8")
    (root_b / "public.py").write_text("ordinary public content\n", encoding="utf-8")
    workspace_a = "repository:a"
    workspace_b = "repository:b"

    assert store.index(str(root_a), workspace=workspace_a)["success"] is True
    assert store.index(str(root_b), workspace=workspace_b)["success"] is True
    private = store.search("needle", workspace=workspace_a, use_reranker=False)
    public = store.search("needle", workspace=workspace_b, use_reranker=False)

    assert any(row["path"] == "secret.py" for row in private["results"])
    assert all(row["path"] != "secret.py" for row in public["results"])
    assert store.revision(workspace=workspace_a) != store.revision(workspace=workspace_b)


def test_incremental_index_retries_uncertain_path_when_metadata_matches_old_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = _store(tmp_path, max_file_bytes=256)
    root = tmp_path / "project"
    root.mkdir()
    path = root / "module.py"
    path.write_text("value = 'before'\n", encoding="utf-8")
    workspace = "workspace"
    assert store.index_step(str(root), workspace=workspace)["success"] is True
    old_stat = path.stat()
    path.write_text("value = 'after!'\n", encoding="utf-8")
    original_open = Path.open

    def fail_read(candidate: Path, mode="r", *args, **kwargs):
        if candidate.resolve() == path.resolve() and mode == "rb":
            raise PermissionError("forced source read failure")
        return original_open(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_read)
    failed = store.index_step(str(root), workspace=workspace)
    assert failed["success"] is True
    os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    monkeypatch.setattr(Path, "open", original_open)

    recovered = store.index_step(str(root), workspace=workspace)

    assert recovered["success"] is True
    assert recovered["processed_files"] == 1
    result = store.search("value after", use_reranker=False, workspace=workspace)
    assert [row["text"].replace("\r\n", "\n") for row in result["results"]] == ["value = 'after!'\n"]

def test_incremental_preemption_publishes_uncertainty_from_prior_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = _store(tmp_path, max_file_bytes=256)
    root = tmp_path / "project"
    root.mkdir()
    unreadable = root / "unreadable.py"
    next_path = root / "next.py"
    unreadable.write_text("private_old_marker = 1\n", encoding="utf-8")
    next_path.write_text("next_value = 1\n", encoding="utf-8")
    workspace = "workspace"
    assert store.index_paths_step(str(root), workspace=workspace, paths=["unreadable.py", "next.py"])["success"]
    initial = store.search("private_old_marker", use_reranker=False, workspace=workspace)
    assert any(row["path"] == "unreadable.py" for row in initial["results"])
    unreadable.write_text("private_new_marker = 2\n", encoding="utf-8")
    original_open = Path.open

    def fail_selected_read(candidate: Path, mode="r", *args, **kwargs):
        if candidate.resolve() == unreadable.resolve() and mode == "rb":
            raise PermissionError("forced source read failure")
        return original_open(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_selected_read)
    yield_checks = 0

    def yield_before_next_path():
        nonlocal yield_checks
        yield_checks += 1
        return yield_checks == 2

    result = store.index_paths_step(str(root), should_yield=yield_before_next_path, workspace=workspace, paths=["unreadable.py", "next.py"])

    assert result["preempted"] is True
    exposed = store.search("private_old_marker", use_reranker=False, workspace=workspace)
    assert all(row["path"] != "unreadable.py" for row in exposed["results"])
