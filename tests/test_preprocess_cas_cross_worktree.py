from pathlib import Path
from unittest.mock import MagicMock
from local_ai_hub.rag import RAGStore


def test_rag_chunks_reused_across_workspaces_without_embedding_calls(tmp_path: Path):
    cfg = {"server": {"state_dir": str(tmp_path / "state")}}
    services = MagicMock()
    # Mock embed return
    services.embed.return_value = {
        "success": True,
        "embeddings": [[0.1] * 384],
    }

    rag = RAGStore(cfg, services)

    ws_a = "workspace_a"
    ws_b = "workspace_b"
    file_a = tmp_path / "a/file.py"
    file_b = tmp_path / "b/file.py"
    file_a.parent.mkdir(parents=True)
    file_b.parent.mkdir(parents=True)
    file_a.write_text("def hello(): return 123\n", encoding="utf-8")
    file_b.write_text("def hello(): return 123\n", encoding="utf-8")

    # Index in workspace A
    res_a = rag.index_paths_step(str(file_a.parent), workspace=ws_a, paths=["file.py"])
    assert res_a.get("success") is True
    assert res_a.get("embedded_chunks") == 1
    assert res_a.get("reused_chunks") == 0
    assert services.embed.call_count == 1

    # Now index in workspace B with identical content
    res_b = rag.index_paths_step(str(file_b.parent), workspace=ws_b, paths=["file.py"])
    assert res_b.get("success") is True
    # Should reuse chunks from workspace A via CAS matching content_hash
    assert res_b.get("embedded_chunks") == 0
    assert res_b.get("reused_chunks") == 1
    # embed should NOT have been called a second time!
    assert services.embed.call_count == 1
