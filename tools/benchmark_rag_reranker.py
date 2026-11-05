"""Compare active Hub reranking, baseline retrieval, and offline CPU reranking.

The live endpoint is measured with reranking off and on. An isolated CPU
cross-encoder runs with downloads disabled. Labels name one verified relevant
path per query; they are not exhaustive relevance judgments.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import tempfile
import time
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from local_ai_hub.client import HubClient
from local_ai_hub.process_utils import canonical_workspace_id
from local_ai_hub.reranker import Reranker


CASES = [
    ("How to install the local AI hub on Windows", "docs/INSTALLATION.md"),
    ("Jak nainstalovat a spustit Local AI Hub", "docs/INSTALLATION.md"),
    ("How do I update an existing Local AI Hub installation?", "docs/UPDATE_PROMPT.md"),
]


def rank_of_path(items: list[dict], path: str) -> int | None:
    return next((index for index, item in enumerate(items, 1) if item.get("path") == path), None)


def latency_summary(samples: list[dict]) -> dict:
    values = sorted(float(sample["latency_ms"]) for sample in samples)
    if not values:
        return {"median_ms": None, "p95_ms": None}
    p95_index = max(0, math.ceil(len(values) * 0.95) - 1)
    return {"median_ms": statistics.median(values), "p95_ms": values[p95_index]}


def _search_variant(client: HubClient, root: Path, workspace: str, query: str,
                    *, use_reranker: bool, repeats: int) -> tuple[dict, list[dict]]:
    samples: list[dict] = []
    response: dict = {}
    for _ in range(repeats):
        started = time.perf_counter()
        response = client.post("/api/rag/search", {
            "root": str(root), "workspace": workspace, "query": query,
            "top_k": 8, "use_reranker": use_reranker,
        }, timeout=30)
        elapsed = (time.perf_counter() - started) * 1000
        if response.get("success") is not True:
            raise RuntimeError(f"RAG search failed: {response.get('error')}")
        cache = response.get("search_cache")
        samples.append({
            "latency_ms": round(elapsed, 3),
            "cache_hit": cache.get("hit") if isinstance(cache, dict) else None,
            "reranked": response.get("reranked"),
            "degraded": response.get("degraded"),
            "fallbacks": response.get("fallbacks"),
        })
    return response, samples


def run(root: Path, config_path: Path, *, repeats: int = 3) -> dict:
    if type(repeats) is not int or not 1 <= repeats <= 20:
        raise ValueError("repeats must be between 1 and 20")
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
                source, baseline_samples = _search_variant(
                    client, root, workspace, query, use_reranker=False, repeats=repeats,
                )
                active_reranked, active_samples = _search_variant(
                    client, root, workspace, query, use_reranker=True, repeats=repeats,
                )
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
                             "active_hub_reranker_rank": rank_of_path(active_reranked.get("results", []), expected),
                             "baseline_latency": latency_summary(baseline_samples),
                             "active_hub_latency": latency_summary(active_samples),
                             "baseline_samples": baseline_samples,
                             "active_hub_samples": active_samples,
                             "active_hub_reranked": active_reranked.get("reranked"),
                             "active_hub_degraded": active_reranked.get("degraded"),
                             "active_hub_fallbacks": active_reranked.get("fallbacks"),
                             "active_hub_cache": active_reranked.get("search_cache"),
                             "offline_cpu_rerank_ms": rerank_ms,
                             "candidate_paths": [item.get("path") for item in candidates],
                             "reranked_paths": [item.get("path") for item in reordered],
                             "rag_degraded": source.get("degraded"), "rag_hybrid": source.get("hybrid")})
        finally:
            client.close()
        return {"scope": "active Hub reranker plus isolated CPU cross-encoder; no downloads; labels not exhaustive",
                "model": config["models"]["reranker"], "device": "cpu", "max_length": 512,
                "repeats": repeats, "cases": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    config_path = args.config or args.root / "config.toml"
    print(json.dumps(run(args.root, config_path, repeats=args.repeats), ensure_ascii=False, indent=2))
