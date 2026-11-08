from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from local_ai_hub.reranker import Reranker
from local_ai_hub.rag import RAGStore


class _Embeddings:
    space_id = "reranker-cuda-fallback-test"

    def embed(self, texts, **kwargs):
        return {
            "success": True,
            "embeddings": [[1.0, 0.0] for _ in texts],
            "embedding_space_id": self.space_id,
        }


def test_reranker_cuda_includes_cpu_candidate_spec() -> None:
    rr = Reranker({"models": {"reranker_device": "cuda", "reranker_backend": "torch"}})
    specs = rr._candidate_specs()
    assert specs == [("torch", "cuda"), ("torch", "cpu")]


def test_reranker_cuda_prediction_failure_falls_back_to_cpu() -> None:
    rr = Reranker({"models": {"reranker_device": "cuda", "reranker_backend": "torch"}})
    
    cuda_model = MagicMock()
    cuda_model.predict.side_effect = RuntimeError("CUDA illegal instruction in matmul")
    
    cpu_model = MagicMock()
    cpu_model.predict.return_value = [0.95, 0.12]

    models = [cuda_model, cpu_model]
    candidates = [("torch", "cuda"), ("torch", "cpu")]
    
    def fake_load_candidate(index: int) -> bool:
        if index < len(models):
            rr._model = models[index]
            rr.active_backend = "torch"
            rr.active_device = "cuda" if index == 0 else "cpu"
            rr._candidates = candidates
            rr._candidate_index = index
            return True
        return False

    rr._candidate_specs = lambda: candidates
    rr._load_candidate = fake_load_candidate

    pairs = [("query", "doc1"), ("query", "doc2")]
    scores = rr._predict(pairs, priority=1, allow_cpu_fallback=True)

    assert scores == [0.95, 0.12]
    assert rr.active_device == "cpu"


def test_rag_store_uses_reranker_on_cpu(tmp_path: Path) -> None:
    mock_reranker = MagicMock()
    mock_reranker.active_device = "cpu"
    mock_reranker.device = "cpu"
    mock_reranker.rerank.return_value = {
        "success": True,
        "results": [{"index": 1, "score": 0.88}, {"index": 0, "score": 0.22}],
    }

    config = {
        "server": {"state_dir": str(tmp_path)},
        "features": {"reranker": True, "rag": True},
        "models": {"reranker_device": "cpu"},
    }
    rag = RAGStore(config, _Embeddings(), reranker=mock_reranker)
    root = tmp_path / "workspace-root"
    root.mkdir()
    (root / "binding.txt").write_text("", encoding="utf-8")
    indexed = rag.index_paths_step(str(root), workspace="test_workspace", paths=["binding.txt"])
    assert indexed["success"], indexed
    with closing(rag._connect()) as con:
        con.executemany(
            "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) "
            "VALUES(?,?,?,?,?,?,?)",
            [
                ("test_workspace", f"doc{index}.py", 0, f"hash-{index}", f"text {index}",
                 json.dumps([1.0, 0.0]), _Embeddings.space_id)
                for index in range(2)
            ],
        )
        con.commit()

    res = rag._search_uncached("test query", "test_workspace", top_k=2, use_reranker=True)

    assert mock_reranker.rerank.called
    args, kwargs = mock_reranker.rerank.call_args
    assert kwargs.get("allow_cpu_fallback") is True
    assert res["results"][0]["path"] == "doc1.py"
    assert res["results"][0]["rerank_score"] == 0.88
    assert res["results"][1]["path"] == "doc0.py"
    assert res["results"][1]["rerank_score"] == 0.22
