from __future__ import annotations

import os
from contextlib import closing
from pathlib import Path

from local_ai_hub.rag import RAGStore


class _Services:
    def embed(self, texts, **_kwargs):
        return {
            "success": True,
            "embedding_space_id": "root-freshness-test-v1",
            "embeddings": [[1.0, 0.0] for _ in texts],
        }


def _store(tmp_path: Path) -> RAGStore:
    return RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "rag": {"extensions": [".py"], "chunk_chars": 4096, "chunk_overlap_chars": 0},
            "features": {"reranker": False},
        },
        _Services(),
    )


def _indexed_text(store: RAGStore, workspace: str, path: str) -> str:
    with closing(store._connect()) as con:
        rows = con.execute(
            "SELECT text FROM chunks WHERE workspace=? AND path=?",
            (workspace, path),
        ).fetchall()
    return " ".join(str(row[0]) for row in rows)


def test_same_named_files_remain_root_scoped_after_same_stat_edit_and_restart(tmp_path: Path) -> None:
    first_root = tmp_path / "project-alpha"
    second_root = tmp_path / "project-bravo"
    first_root.mkdir()
    second_root.mkdir()
    first_path = first_root / "same.py"
    second_path = second_root / "same.py"
    first_path.write_text("alpha_marker = 'alpha'  # unique A\n", encoding="utf-8")
    second_path.write_text("bravo_marker = 'bravo'  # unique B\n", encoding="utf-8")

    store = _store(tmp_path)
    first_workspace = store.workspace_id(str(first_root))
    second_workspace = store.workspace_id(str(second_root))
    assert first_workspace != second_workspace
    assert store.index(str(first_root), workspace=first_workspace)["success"] is True
    assert store.index(str(second_root), workspace=second_workspace)["success"] is True

    assert "alpha_marker" in _indexed_text(store, first_workspace, "same.py")
    assert "bravo_marker" not in _indexed_text(store, first_workspace, "same.py")
    assert "bravo_marker" in _indexed_text(store, second_workspace, "same.py")
    assert "alpha_marker" not in _indexed_text(store, second_workspace, "same.py")

    original_stat = first_path.stat()
    first_path.write_text("gamma_marker = 'gamma'  # unique A\n", encoding="utf-8")
    os.utime(first_path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert first_path.stat().st_size == original_stat.st_size
    assert first_path.stat().st_mtime_ns == original_stat.st_mtime_ns

    # New store instance retains the SQLite workspace index while rebuilding the edited snapshot.
    restarted_store = _store(tmp_path)
    updated = restarted_store.index(str(first_root), workspace=first_workspace)
    assert updated["success"] is True
    assert updated["changed_files"] == 1
    assert restarted_store.index(str(second_root), workspace=second_workspace)["success"] is True

    first_search = restarted_store.search("gamma_marker", top_k=5, workspace=first_workspace)
    second_search = restarted_store.search("bravo_marker", top_k=5, workspace=second_workspace)
    assert first_search["success"] is True and first_search["results"]
    assert second_search["success"] is True and second_search["results"]
    assert "gamma_marker" in _indexed_text(restarted_store, first_workspace, "same.py")
    assert "alpha_marker" not in _indexed_text(restarted_store, first_workspace, "same.py")
    assert "bravo_marker" in _indexed_text(restarted_store, second_workspace, "same.py")
    assert "gamma_marker" not in _indexed_text(restarted_store, second_workspace, "same.py")
