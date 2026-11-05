"""Compare active Hub reranking, baseline retrieval, and offline CPU reranking.

The live endpoint is measured with reranking off and on. An isolated CPU
cross-encoder runs with downloads disabled. Labels name one verified relevant
path per query; they are not exhaustive relevance judgments.
"""
from __future__ import annotations

import argparse
import base64
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
from tools.benchmark_live_search import validate_cases


CASE_FILE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "search_benchmark_cases.json"


def load_benchmark_dataset(root: Path) -> tuple[dict, list[dict]]:
    """Load source-anchored labels and return positive cases for ranking."""
    data = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("unsupported search benchmark case schema")
    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ValueError("benchmark cases must be a list")
    for case in cases:
        if isinstance(case, dict) and "query_b64" in case:
            encoded = case.pop("query_b64")
            if type(encoded) is not str:
                raise ValueError("query_b64 must be a string")
            try:
                case["query"] = base64.b64decode(encoded, validate=True).decode("utf-8")
            except (ValueError, UnicodeError) as exc:
                raise ValueError("query_b64 must encode UTF-8 text") from exc
    validate_cases(root, cases)
    return data, [case for case in cases if case.get("negative") is not True]


def load_benchmark_cases(root: Path) -> list[dict]:
    return load_benchmark_dataset(root)[1]


def rank_of_path(items: list[dict], path: str) -> int | None:
    return next((index for index, item in enumerate(items, 1) if item.get("path") == path), None)


def rank_of_paths(items: list[dict], paths: list[str]) -> int | None:
    relevant = set(paths)
    seen: set[str] = set()
    unique_rank = 0
    for item in items:
        path = item.get("path")
        if type(path) is not str or path in seen:
            continue
        seen.add(path)
        unique_rank += 1
        if path in relevant:
            return unique_rank
    return None


def rank_summary(ranks: list[int | None], *, k: int = 8) -> dict:
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")
    hits = [rank for rank in ranks if rank is not None]
    return {
        f"recall_at_{k}": sum(rank <= k for rank in hits) / len(ranks) if ranks else None,
        "mrr": sum(1 / rank for rank in hits) / len(ranks) if ranks else None,
        "cases": len(ranks),
        "hits": len(hits),
    }


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
    dataset, cases = load_benchmark_dataset(root)
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
            for case in cases:
                query = case["query"]
                expected_paths = case["expected_paths"]
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
                offline_reranker_available = ranked.get("success") is True
                offline_error = None if offline_reranker_available else ranked.get("error")
                reordered = ([candidates[int(item["index"])] for item in ranked.get("results", [])]
                             if offline_reranker_available else [])
                rows.append({"case_id": case["id"], "language": case.get("language"),
                             "query": query, "expected_paths": expected_paths,
                             "baseline_rank": rank_of_paths(candidates, expected_paths),
                             "reranked_rank": rank_of_paths(reordered, expected_paths),
                             "active_hub_reranker_rank": rank_of_paths(active_reranked.get("results", []), expected_paths),
                             "baseline_latency": latency_summary(baseline_samples),
                             "active_hub_latency": latency_summary(active_samples),
                             "baseline_samples": baseline_samples,
                             "active_hub_samples": active_samples,
                             "active_hub_reranked": active_reranked.get("reranked"),
                             "active_hub_degraded": active_reranked.get("degraded"),
                             "active_hub_fallbacks": active_reranked.get("fallbacks"),
                             "active_hub_cache": active_reranked.get("search_cache"),
                             "offline_cpu_rerank_ms": rerank_ms,
                             "offline_reranker_available": offline_reranker_available,
                             "offline_reranker_error": offline_error,
                             "candidate_paths": [item.get("path") for item in candidates],
                             "reranked_paths": [item.get("path") for item in reordered],
                             "rag_degraded": source.get("degraded"), "rag_hybrid": source.get("hybrid")})
        finally:
            client.close()
        return {"scope": "active Hub reranker plus isolated CPU cross-encoder; no downloads; labels not exhaustive",
                "model": config["models"]["reranker"], "device": "cpu", "max_length": 512,
                "case_set": dataset.get("case_set"),
                "negative_cases_excluded": sum(case.get("negative") is True for case in dataset["cases"]),
                "repeats": repeats, "metrics": {
                    "baseline": rank_summary([row["baseline_rank"] for row in rows]),
                    "offline_reranked": rank_summary([
                        row["reranked_rank"] for row in rows if row["offline_reranker_available"]
                    ]),
                    "active_hub_reranker": rank_summary([row["active_hub_reranker_rank"] for row in rows]),
                }, "cases": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    config_path = args.config or args.root / "config.toml"
    print(json.dumps(run(args.root, config_path, repeats=args.repeats), ensure_ascii=False, indent=2))
