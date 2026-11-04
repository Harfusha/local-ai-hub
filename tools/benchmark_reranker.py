"""Offline, labeled quality/latency benchmark for the configured local reranker.

Uses only already-cached model files; no model download or RAG candidate generation.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
from typing import Any

from local_ai_hub.config import load_config
from local_ai_hub.reranker import Reranker


CASES: list[dict[str, Any]] = [
    {
        "query": "Local AI Hub installation",
        "candidates": [
            {"id": "search", "text": "Repository search supports lexical, RAG, and hybrid modes."},
            {"id": "index", "text": "Code-index SQLite budget controls storage and eviction."},
            {"id": "install", "text": "Install Local AI Hub with tools/hubctl.py generate --install, then restart the Hub."},
        ],
        "relevant_ids": ["install"],
    },
    {
        "query": "Jak nainstaluji Local AI Hub?",
        "candidates": [
            {"id": "update", "text": "Update Local AI Hub components and refresh installed agent instructions."},
            {"id": "search", "text": "Search source files by exact text, symbols, or semantic meaning."},
            {"id": "install", "text": "Install Local AI Hub with tools/hubctl.py generate --install, then restart the Hub."},
        ],
        "relevant_ids": ["install"],
    },
    {
        "query": "Jak omezit velikost code indexu?",
        "candidates": [
            {"id": "search", "text": "Search combines exact lexical matches with semantic candidates."},
            {"id": "mcp", "text": "MCP exposes repository tools and search modes to coding agents."},
            {"id": "index", "text": "Set code_index.max_index_bytes; cold unused index rows are evicted and SQLite pages reclaimed."},
        ],
        "relevant_ids": ["index"],
    },
    {
        "query": "Find source files by intent and exact keywords",
        "candidates": [
            {"id": "install", "text": "Install and update Local AI Hub agent configuration."},
            {"id": "index", "text": "Set a size budget for the SQLite code index."},
            {"id": "hybrid", "text": "Hybrid search fuses lexical and semantic candidates, deduplicates paths, and ranks agreement."},
        ],
        "relevant_ids": ["hybrid"],
    },
    {
        "query": "repo_search",
        "candidates": [
            {"id": "mcp", "text": "MCP schema for repo_search and search_mode."},
            {"id": "services", "text": "LocalAIServices.repo_search implements lexical, rag, and hybrid modes."},
            {"id": "docs", "text": "Documentation explains repository search behavior."},
        ],
        "relevant_ids": ["services", "mcp"],
    },
]


def validate_cases(cases: list[dict[str, Any]]) -> None:
    if not cases:
        raise ValueError("benchmark query set must not be empty")
    seen_queries: set[str] = set()
    for case in cases:
        query = case.get("query")
        candidates = case.get("candidates")
        relevant_ids = case.get("relevant_ids")
        if type(query) is not str or not query.strip() or query in seen_queries:
            raise ValueError("queries must be unique non-empty strings")
        seen_queries.add(query)
        if not isinstance(candidates, list) or not candidates:
            raise ValueError(f"{query!r}: candidates must be a non-empty list")
        ids = [item.get("id") for item in candidates if isinstance(item, dict)]
        if len(ids) != len(candidates) or any(type(value) is not str or not value for value in ids):
            raise ValueError(f"{query!r}: candidate ids and text are required")
        if len(set(ids)) != len(ids):
            raise ValueError(f"{query!r}: candidate ids must be unique")
        if any(type(item.get("text")) is not str or not item["text"] for item in candidates):
            raise ValueError(f"{query!r}: candidate text must be non-empty")
        if not isinstance(relevant_ids, list) or any(value not in ids for value in relevant_ids):
            raise ValueError(f"{query!r}: every relevant id must name a candidate")


def evaluate_ranking(ranked_ids: list[str], relevant_ids: list[str]) -> dict[str, Any]:
    ranked = list(dict.fromkeys(ranked_ids))
    relevant = set(relevant_ids)
    if not relevant:
        return {
            "recall_at_k": None,
            "precision_at_k": None,
            "reciprocal_rank": None,
            "ndcg_at_k": None,
        }
    found = relevant.intersection(ranked)
    first_rank = next((rank for rank, item in enumerate(ranked, 1) if item in relevant), None)
    dcg = sum(1.0 / math.log2(rank + 1) for rank, item in enumerate(ranked, 1) if item in relevant)
    ideal_count = min(len(relevant), len(ranked))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return {
        "recall_at_k": len(found) / len(relevant),
        "precision_at_k": len(found) / len(ranked) if ranked else 0.0,
        "reciprocal_rank": 1.0 / first_rank if first_rank else 0.0,
        "ndcg_at_k": dcg / idcg if idcg else 0.0,
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def run(*, repeats: int = 3, config_path: str | None = None) -> dict[str, Any]:
    if type(repeats) is not int or not 1 <= repeats <= 50:
        raise ValueError("repeats must be between 1 and 50")
    validate_cases(CASES)
    offline_vars = {key: os.environ.get(key) for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")}
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    reranker: Reranker | None = None
    try:
        config = load_config(config_path, probe_hardware=False)
        models = config.setdefault("models", {})
        models["allow_hf_downloads"] = False
        reranker = Reranker(config)
        rows: list[dict[str, Any]] = []
        for case in CASES:
            documents = [item["text"] for item in case["candidates"]]
            ids = [item["id"] for item in case["candidates"]]
            baseline = evaluate_ranking(ids, case["relevant_ids"])
            samples: list[dict[str, Any]] = []
            last_ranked = ids
            for _ in range(repeats):
                cache_hits_before = int(getattr(reranker, "_cache_hits", 0))
                started = time.perf_counter()
                result = reranker.rerank(case["query"], documents, top_k=len(documents), priority=1)
                elapsed_ms = (time.perf_counter() - started) * 1000
                cache_hit = int(getattr(reranker, "_cache_hits", 0)) > cache_hits_before
                ranked_rows = result.get("results", []) if isinstance(result, dict) else []
                valid = [item for item in ranked_rows if isinstance(item, dict) and type(item.get("index")) is int]
                valid.sort(key=lambda item: -float(item.get("score", 0.0)))
                last_ranked = [ids[item["index"]] for item in valid if 0 <= item["index"] < len(ids)]
                samples.append({
                    "latency_ms": round(elapsed_ms, 3),
                    "cache_state": "warm_hit" if cache_hit else "inference_or_cold",
                    "success": isinstance(result, dict) and result.get("success") is True,
                })
            rows.append({
                "query": case["query"],
                "relevant_ids": case["relevant_ids"],
                "baseline_order": ids,
                "baseline": baseline,
                "reranked_order": last_ranked,
                "reranked": evaluate_ranking(last_ranked, case["relevant_ids"]),
                "reranker_success": all(item["success"] for item in samples),
                "samples": samples,
                "median_ms": statistics.median(item["latency_ms"] for item in samples),
                "p95_ms": _percentile([item["latency_ms"] for item in samples], 0.95),
            })
        return {
            "scope": "synthetic manually labeled reranker candidates; no candidate generation or HTTP/MCP",
            "hardware_profile": config.get("hardware", {}).get("profile"),
            "model": reranker.model_name,
            "reranker_enabled": reranker.is_enabled(),
            "requested_device": reranker.device,
            "active_backend": reranker.active_backend,
            "active_device": reranker.active_device,
            "model_downloads_allowed": False,
            "repeats": repeats,
            "cases": rows,
        }
    finally:
        if reranker is not None and reranker.is_loaded():
            reranker.release()
        for key, value in offline_vars.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--config")
    args = parser.parse_args()
    try:
        print(json.dumps(run(repeats=args.repeats, config_path=args.config), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({"success": False, "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
