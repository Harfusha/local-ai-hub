from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.rag import RAGStore


class CountingEmbeddings:
    space_id = "unit-embedder:v1:384"

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str], **_kwargs):
        self.calls += 1
        return {
            "success": True,
            "embedding_space_id": self.space_id,
            "embeddings": [[0.1] * 384 for _ in texts],
        }


@pytest.mark.parametrize("incremental", [False, True], ids=["full-index", "path-step"])
def test_rag_content_cas_survives_source_workspace_removal(tmp_path: Path, incremental: bool):
    services = CountingEmbeddings()
    rag = RAGStore({"server": {"state_dir": str(tmp_path / "state")}}, services)
    root_a = tmp_path / "worktree-a"
    root_b = tmp_path / "worktree-b"
    root_a.mkdir()
    root_b.mkdir()
    source = "def shared():\n    return 'same content'\n"
    (root_a / "shared.py").write_text(source, encoding="utf-8")
    (root_b / "shared.py").write_text(source, encoding="utf-8")

    def index(root: Path, workspace: str):
        if incremental:
            return rag.index_paths_step(str(root), workspace=workspace, paths=["shared.py"])
        return rag.index(str(root), workspace=workspace)

    first = index(root_a, "workspace-a")
    assert first["success"] is True
    assert first["embedded_chunks"] == 1
    assert services.calls == 1

    with closing(sqlite3.connect(rag.db_path)) as con:
        row = con.execute(
            "SELECT content_hash, embedding_space, chunk_index, chunk_text, embedding_blob "
            "FROM content_rag_chunks"
        ).fetchone()
    assert row is not None and row[1] == services.space_id and row[2] == 0
    assert row[3] and row[4]

    assert rag.remove_paths(workspace="workspace-a", paths=["shared.py"]) == 1
    second = index(root_b, "workspace-b")
    assert second["success"] is True
    assert second["embedded_chunks"] == 0
    assert second["reused_chunks"] == 1
    assert services.calls == 1
