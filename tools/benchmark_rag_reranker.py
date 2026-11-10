"""Compare active Hub reranking, baseline retrieval, and offline CPU/CUDA reranking.

The live endpoint is measured with reranking off and on. CPU cross-encoder runs
use isolated state; CUDA runs use the configured shared Hub state so admission
retains its cross-process fence. Downloads are disabled. Labels name one verified
relevant path per query; they are not exhaustive judgments.
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
import tomllib
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


def local_embedding_model_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError("embedding model must be an existing local directory") from exc
    if not path.is_absolute() or not resolved.is_dir():
        raise ValueError("embedding model must be an absolute existing local directory")
    return resolved


def rank_embeddings(query_vector: list[float], vectors: list[list[float]],
                    candidates: list[dict]) -> list[dict]:
    if len(vectors) != len(candidates):
        raise ValueError("embedding vectors and candidates must have equal length")
    if not vectors:
        return []
    dimension = len(query_vector)
    if dimension == 0 or any(len(vector) != dimension for vector in vectors):
        raise ValueError("query and document vectors must have the same nonzero dimension")
    all_vectors = [query_vector, *vectors]
    if any(
        type(value) not in (int, float) or not math.isfinite(value)
        for vector in all_vectors for value in vector
    ):
        raise ValueError("embedding vectors must contain finite numbers")
    query_norm = math.sqrt(sum(value * value for value in query_vector))
    if query_norm == 0 or not math.isfinite(query_norm):
        raise ValueError("embedding vectors must have a finite nonzero norm")
    query = [value / query_norm for value in query_vector]
    scored = []
    for vector, candidate in zip(vectors, candidates):
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0 or not math.isfinite(norm):
            raise ValueError("embedding vectors must have a finite nonzero norm")
        score = sum(a * b / norm for a, b in zip(query, vector))
        scored.append({**candidate, "score": score})
    return sorted(scored, key=lambda item: -item["score"])


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


def offline_device_metrics(requested_device: str, result: dict, samples: list[dict],
                           candidate_count: int) -> dict:
    has_candidates = type(candidate_count) is int and candidate_count > 0
    actual_device = result.get("device") if has_candidates and type(result.get("device")) is str else None
    backend = result.get("backend") if has_candidates and type(result.get("backend")) is str else None
    successful = [sample for sample in samples if sample.get("success") is True] if has_candidates else []
    latencies = latency_summary(successful)
    elapsed_ms = sum(float(sample["latency_ms"]) for sample in successful)
    throughput = (
        candidate_count * len(successful) * 1000 / elapsed_ms
        if successful and elapsed_ms > 0 else None
    )
    fallback = None
    if requested_device == "cuda" and actual_device is not None:
        fallback = not actual_device.lower().startswith("cuda")
    warm_samples = [sample for sample in successful if sample.get("phase") == "warm"]
    cold_sample = next((sample for sample in successful if sample.get("phase") == "cold"), None)
    return {
        "requested_device": requested_device,
        "actual_device": actual_device,
        "backend": backend,
        "fallback_observed": fallback,
        "latency": latencies,
        "cold_latency_ms": cold_sample.get("latency_ms") if cold_sample else None,
        "warm_latency": latency_summary(warm_samples),
        "candidates_per_second": throughput,
        "successful_repeats": len(successful),
    }


def offline_embedding_metrics(requested_device: str, query_result: dict,
                              document_result: dict, samples: list[dict],
                              candidate_count: int) -> dict:
    successful = [sample for sample in samples if sample.get("success") is True]
    observed_result = document_result if document_result.get("success") is True else query_result
    device = observed_result.get("device") if observed_result.get("success") is True else None
    backend = observed_result.get("backend") if observed_result.get("success") is True else None
    elapsed_ms = sum(float(sample["latency_ms"]) for sample in successful)
    fallback = None
    if requested_device == "cuda" and type(device) is str:
        fallback = not device.lower().startswith("cuda")
    cold = next((sample for sample in successful if sample.get("phase") == "cold"), None)
    return {
        "requested_device": requested_device,
        "actual_device": device,
        "backend": backend,
        "model": observed_result.get("model"),
        "model_digest": observed_result.get("model_digest"),
        "model_revision": observed_result.get("model_revision"),
        "embedding_space_id": (
            query_result.get("embedding_space_id")
            if query_result.get("success") is True and document_result.get("success") is True else None
        ),
        "normalized": observed_result.get("normalized"),
        "fallback_observed": fallback,
        "embedding_space_match": (
            query_result.get("embedding_space_id") == document_result.get("embedding_space_id")
            if query_result.get("success") is True and document_result.get("success") is True else None
        ),
        "latency": latency_summary(successful),
        "cold_latency_ms": cold.get("latency_ms") if cold else None,
        "warm_latency": latency_summary([sample for sample in successful if sample.get("phase") == "warm"]),
        "embeddings_per_second": (
            (candidate_count + 1) * len(successful) * 1000 / elapsed_ms
            if successful and elapsed_ms > 0 else None
        ),
        "successful_repeats": len(successful),
    }


def benchmark_state_dir(config_path: Path, requested_device: str, isolated_state_dir: str) -> str:
    if requested_device == "cpu":
        return isolated_state_dir
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError("CUDA benchmark requires a readable Hub config with an explicit shared state_dir") from exc
    server = config.get("server")
    state_dir = server.get("state_dir") if isinstance(server, dict) else None
    if type(state_dir) is not str or not Path(state_dir).expanduser().is_absolute():
        raise ValueError("CUDA benchmark requires an absolute server.state_dir so GPU admission shares the Hub fence")
    return str(Path(state_dir).expanduser())


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


def _benchmark_embeddings(model, query: str, candidates: list[dict], *,
                          repeats: int, requested_device: str,
                          cold_inference_recorded: bool = False) -> tuple[list[dict], list[dict], dict, bool]:
    samples: list[dict] = []
    ranked: list[dict] = []
    query_result: dict = {}
    document_result: dict = {}
    if not candidates:
        sample = {"latency_ms": 0.0, "phase": "rejected", "success": False, "error": "no_candidates"}
        failure = {"success": False, "error": "no_candidates"}
        metrics = offline_embedding_metrics(requested_device, failure, failure, [sample], candidate_count=0)
        return ranked, [sample], metrics, cold_inference_recorded
    texts = [str(item.get("text", "")) for item in candidates]
    for repeat in range(repeats):
        started = time.perf_counter()
        query_result = model.encode([query], query=True)
        if query_result.get("success") is True:
            document_result = model.encode(texts, query=False) if texts else {
                **query_result, "embeddings": [],
            }
        else:
            document_result = {"success": False, "error": query_result.get("error")}
        elapsed = (time.perf_counter() - started) * 1000
        succeeded = query_result.get("success") is True and document_result.get("success") is True
        sample = {
            "latency_ms": round(elapsed, 3),
            "phase": "cold" if not cold_inference_recorded else "warm",
            "success": succeeded,
        }
        if succeeded:
            if query_result.get("embedding_space_id") != document_result.get("embedding_space_id"):
                succeeded = False
                sample["success"] = False
                sample["error"] = "query and document embedding spaces differ"
            else:
                try:
                    ranked = rank_embeddings(
                        query_result["embeddings"][0], document_result["embeddings"], candidates,
                    )
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    succeeded = False
                    sample["success"] = False
                    sample["error"] = str(exc)
        samples.append(sample)
        if query_result.get("success") is True or document_result.get("success") is True:
            cold_inference_recorded = True
        if not succeeded:
            ranked = []
            break
    metrics = offline_embedding_metrics(
        requested_device, query_result, document_result, samples, len(candidates),
    )
    return ranked, samples, metrics, cold_inference_recorded


def run(root: Path, config_path: Path, *, repeats: int = 3, offline_device: str = "cpu",
        embedding_model_path: Path | None = None, embedding_device: str = "cpu") -> dict:
    if type(repeats) is not int or not 1 <= repeats <= 20:
        raise ValueError("repeats must be between 1 and 20")
    if type(offline_device) is not str or offline_device not in {"cpu", "cuda"}:
        raise ValueError("offline_device must be 'cpu' or 'cuda'")
    if type(embedding_device) is not str or embedding_device not in {"cpu", "cuda"}:
        raise ValueError("embedding_device must be 'cpu' or 'cuda'")
    model_path = local_embedding_model_path(embedding_model_path) if embedding_model_path is not None else None
    root = root.resolve(strict=True)
    dataset, cases = load_benchmark_dataset(root)
    client = HubClient(config_path=str(config_path), auto_start=False)
    workspace = canonical_workspace_id(root)
    with tempfile.TemporaryDirectory(prefix="hub-reranker-eval-") as directory:
        state_dir = benchmark_state_dir(config_path, offline_device, directory)
        embedding_state_dir = (
            benchmark_state_dir(config_path, embedding_device, directory) if model_path is not None else state_dir
        )
        config = {"server": {"state_dir": state_dir}, "features": {"reranker": True},
                  "models": {"reranker": "BAAI/bge-reranker-v2-m3", "reranker_device": offline_device,
                             "reranker_backend": "torch", "allow_hf_downloads": False},
                  "cpu_retrieval": {"reranker_batch_size": 4, "reranker_max_length": 512},
                  "cache": {"reranker": False}}
        reranker = Reranker(config)
        embedding_model = None
        if model_path is not None:
            from local_ai_hub.embeddings import EmbeddingModel

            embedding_model = EmbeddingModel({
                "server": {"state_dir": embedding_state_dir},
                "features": {"rag": True},
                "models": {
                    "embedding": str(model_path),
                    "embedding_device": embedding_device,
                    "embedding_backend": "sentence-transformers",
                    "allow_hf_downloads": False,
                },
                "cpu_retrieval": {"embedding_batch_size": 16},
                "cache": {"embeddings": False},
            })
        cold_inference_recorded = False
        embedding_cold_inference_recorded = False
        offline_all_samples: list[dict] = []
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
                offline_samples = []
                ranked = {
                    "success": False,
                    "error": "no_candidates" if not candidates else "reranker did not run",
                    "results": [],
                }
                embedding_ranked: list[dict] = []
                embedding_samples: list[dict] = []
                embedding_metrics = None
                candidate_texts = [str(item.get("text", "")) for item in candidates]
                for _ in range(repeats if candidates else 0):
                    started = time.perf_counter()
                    attempt_result = reranker.rerank(query, candidate_texts, top_k=len(candidates))
                    elapsed = (time.perf_counter() - started) * 1000
                    succeeded = attempt_result.get("success") is True
                    sample = {
                        "latency_ms": round(elapsed, 3),
                        "phase": ("cold" if not cold_inference_recorded else "warm") if succeeded else "rejected",
                        "success": succeeded,
                    }
                    offline_samples.append(sample)
                    offline_all_samples.append(sample)
                    if succeeded:
                        ranked = attempt_result
                    else:
                        ranked = attempt_result
                        break
                    cold_inference_recorded = True
                offline_metrics = offline_device_metrics(
                    offline_device, ranked, offline_samples, len(candidates),
                )
                if embedding_model is not None:
                    (embedding_ranked, embedding_samples, embedding_metrics,
                     embedding_cold_inference_recorded) = _benchmark_embeddings(
                        embedding_model, query, candidates, repeats=repeats,
                        requested_device=embedding_device,
                        cold_inference_recorded=embedding_cold_inference_recorded,
                    )
                rerank_ms = offline_metrics["latency"]["median_ms"]
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
                             "offline_rerank_metrics": offline_metrics,
                             "offline_rerank_samples": offline_samples,
                             "offline_rerank_median_ms": rerank_ms,
                             "offline_reranker_available": offline_reranker_available,
                              "offline_reranker_error": offline_error,
                              "offline_embedding_rank": rank_of_paths(embedding_ranked, expected_paths),
                              "offline_embedding_ranked_paths": [item.get("path") for item in embedding_ranked],
                              "offline_embedding_metrics": embedding_metrics,
                              "offline_embedding_samples": embedding_samples,
                             "candidate_paths": [item.get("path") for item in candidates],
                             "reranked_paths": [item.get("path") for item in reordered],
                             "rag_degraded": source.get("degraded"), "rag_hybrid": source.get("hybrid")})
        finally:
            client.close()
        final_device = next((row["offline_rerank_metrics"]["actual_device"] for row in reversed(rows)
                             if row["offline_rerank_metrics"]["actual_device"]), None)
        successful_samples = [sample for sample in offline_all_samples if sample["success"]]
        total_successful_ms = sum(float(sample["latency_ms"]) for sample in successful_samples)
        total_candidate_items = sum(
            len(row["candidate_paths"]) * row["offline_rerank_metrics"]["successful_repeats"]
            for row in rows
        )
        device_fallback = (
            None if final_device is None else offline_device == "cuda"
            and not final_device.lower().startswith("cuda")
        )
        return {"scope": "active Hub search plus optional offline CPU/CUDA cross-encoder and local embedding model; CPU state isolated, CUDA admission shared; no downloads; labels not exhaustive",
                "model": config["models"]["reranker"], "device": offline_device, "max_length": 512,
                "requested_device": offline_device, "actual_device": final_device,
                "device_fallback_observed": device_fallback,
                "offline_latency": latency_summary(successful_samples),
                "offline_cold_latency_ms": next(
                    (sample["latency_ms"] for sample in successful_samples if sample["phase"] == "cold"), None
                ),
                "offline_warm_latency": latency_summary([
                    sample for sample in successful_samples if sample["phase"] == "warm"
                ]),
                "offline_successful_repeats": len(successful_samples),
                "offline_candidates_per_second": (
                    total_candidate_items * 1000 / total_successful_ms if total_successful_ms > 0 else None
                ),
                "peak_vram_mb": None,
                "peak_vram_measurement": "not captured outside the shared GPU admission lease",
                "offline_embedding_model": str(model_path) if model_path else None,
                "offline_embedding_device": embedding_device if model_path else None,
                "case_set": dataset.get("case_set"),
                "negative_cases_excluded": sum(case.get("negative") is True for case in dataset["cases"]),
                "repeats": repeats, "metrics": {
                    "baseline": rank_summary([row["baseline_rank"] for row in rows]),
                    "offline_reranked": rank_summary([
                        row["reranked_rank"] for row in rows if row["offline_reranker_available"]
                    ]),
                    "active_hub_reranker": rank_summary([row["active_hub_reranker_rank"] for row in rows]),
                    "offline_embeddings": (
                        rank_summary([row["offline_embedding_rank"] for row in rows]) if model_path else None
                    ),
                }, "cases": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--offline-device", choices=("cpu", "cuda"), default="cpu",
                        help="Device for the cross-encoder. CUDA requires absolute server.state_dir in --config to share Hub GPU admission.")
    parser.add_argument("--embedding-model-dir", type=Path,
                        help="Optional absolute local SentenceTransformers model directory; no downloads are allowed.")
    parser.add_argument("--embedding-device", choices=("cpu", "cuda"), default="cpu",
                        help="Device for the optional local embedding model; CUDA requires shared Hub state_dir.")
    args = parser.parse_args()
    config_path = args.config or args.root / "config.toml"
    print(json.dumps(run(args.root, config_path, repeats=args.repeats,
                         offline_device=args.offline_device,
                         embedding_model_path=args.embedding_model_dir,
                         embedding_device=args.embedding_device), ensure_ascii=False, indent=2))
