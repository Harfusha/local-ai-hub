"""Compare live RAG ranking with an offline CPU reranker on judged queries.

The running Hub provides candidates without reranking. Reranking runs in this
process with temporary state and downloads disabled. Labels name one verified
relevant path per query; they are not exhaustive relevance judgments.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from local_ai_hub.client import HubClient
from local_ai_hub.process_utils import canonical_workspace_id
from local_ai_hub.reranker import Reranker


CASES = [
    ("How to install the local AI hub on Windows", "docs/INSTALL_PROMPT.md"),
    ("Jak nainstalovat a spustit Local AI Hub", "docs/INSTALL_PROMPT.md"),
    ("How do I update an existing Local AI Hub installation?", "docs/UPDATE_PROMPT.md"),
]


def rank_of_path(items: list[dict], path: str) -> int | None:
    return next((index for index, item in enumerate(items, 1) if item.get("path") == path), None)


def run(root: Path, config_path: Path) -> dict:
    root = root.resolve(strict=True)
    for _, expected in CASES:
        if not (root / expected).is_file():
            raise ValueError(f"labeled source missing: {expected}")
    client = HubClient(config_path=str(config_path), auto_start=False)
    workspace = canonical_workspace_id(root)
    with tempfile.TemporaryDirectory(prefix="hub-reranker-eval-") as directory:
        config = {"server": {"state_dir": directory}, "features": {"reranker": True},
                  "models": {"reranker": "BAAI/bge-reranker-v2-m3", "reranker_device": "cpu",
                             "reranker_backend": "torch", "allow_hf_downloads": False},
                  "cpu_retrieval": {"reranker_batch_size": 4, "reranker_max_length": 512},
                  "cache": {"reranker": False}}
        reranker = Reranker(config)
        rows = []
        try:
            for query, expected in CASES:
                started = time.perf_counter()
                source = client.post("/api/rag/search", {"root": str(root), "workspace": workspace,
                                     "query": query, "top_k": 8, "use_reranker": False}, timeout=30)
                retrieval_ms = (time.perf_counter() - started) * 1000
                if source.get("success") is not True:
                    raise RuntimeError(f"RAG search failed: {source.get('error')}")
                candidates = source.get("results", [])
                started = time.perf_counter()
                ranked = reranker.rerank(query, [str(item.get("text", "")) for item in candidates], top_k=len(candidates))
                rerank_ms = (time.perf_counter() - started) * 1000
                if ranked.get("success") is not True:
                    raise RuntimeError(f"offline reranker failed: {ranked.get('error')}")
                reordered = [candidates[int(item["index"])] for item in ranked.get("results", [])]
                rows.append({"query": query, "expected_path": expected,
                             "baseline_rank": rank_of_path(candidates, expected),
                             "reranked_rank": rank_of_path(reordered, expected),
                             "retrieval_ms": retrieval_ms, "rerank_ms": rerank_ms,
                             "candidate_paths": [item.get("path") for item in candidates],
                             "reranked_paths": [item.get("path") for item in reordered],
                             "rag_degraded": source.get("degraded"), "rag_hybrid": source.get("hybrid")})
        finally:
            client.close()
        return {"scope": "live RAG candidates plus isolated CPU cross-encoder; no downloads; labels not exhaustive",
                "model": config["models"]["reranker"], "device": "cpu", "max_length": 512, "cases": rows}


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[1]
    print(json.dumps(run(repo, repo / "config.toml"), ensure_ascii=False, indent=2))
