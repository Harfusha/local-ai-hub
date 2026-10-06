from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.repo_tools import RepositoryTools  # noqa: E402


QUERY = "tenant policy identity context request"
RELEVANT = {"src/tenant_policy.py", "src/context_identity.py"}


def _fixture(root: Path) -> None:
    files = {
        "src/tenant_policy.py": (
            "def enforce_tenant_policy(tenant_id: str, allowed: set[str]) -> bool:\n"
            "    return tenant_id in allowed\n"
        ),
        "src/context_identity.py": (
            "def build_context_identity(tenant_id: str, context_id: str) -> tuple[str, str]:\n"
            "    return tenant_id, context_id\n"
        ),
        "src/unrelated.py": "# rendering utilities\ndef render(value): return value\n",
        "docs/history.md": "Old migration notes for an unrelated cache.\n",
        "vendor/private.py": "tenant policy identity context request secret fixture marker\n",
    }
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percentile + 0.999)))
    return round(ordered[index], 3)


def _concurrency_scenarios(result: dict[str, Any], repetitions: int) -> dict[str, Any]:
    scenarios: dict[str, Any] = {}
    request_count = max(8, repetitions)
    retrieved = {
        str(item.get("path", ""))
        for item in result.get("evidence", [])[:3]
        if isinstance(item, dict)
    }
    true_positives = len(retrieved & RELEVANT)
    precision = round(true_positives / max(1, len(retrieved)), 3)
    recall = round(true_positives / len(RELEVANT), 3)
    for workers in (1, 4, 16):
        cache_lock = Lock()
        cache = {"fixture": result}
        counts = {"hits": 0, "misses": 0}
        latencies: list[float] = []

        def cached_request(_: int) -> tuple[float, dict[str, Any]]:
            started = time.perf_counter()
            with cache_lock:
                value = cache.get("fixture")
                if value is None:
                    counts["misses"] += 1
                    value = result
                    cache["fixture"] = value
                else:
                    counts["hits"] += 1
            return (time.perf_counter() - started) * 1000, value

        with ThreadPoolExecutor(max_workers=workers) as pool:
            responses = list(pool.map(cached_request, range(request_count)))
        latencies.extend(elapsed for elapsed, _ in responses)
        scenarios[str(workers)] = {
            "requests": request_count,
            "latency_ms": {"p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95)},
            "cache": {"layer": "benchmark_response_cache", **counts},
            "visited_files": int(result.get("scanned_files", 0) or 0),
            "output_bytes": len(str(result.get("context", "")).encode("utf-8")),
            "output_tokens_est": int(result.get("estimated_tokens", 0) or 0),
            "precision_at_3": precision,
            "recall_at_3": recall,
        }
    return scenarios


def run_benchmark(*, repetitions: int = 7) -> dict[str, Any]:
    """Run deterministic fixture retrieval; no models or external backends are used."""
    repetitions = max(3, min(int(repetitions), 31))
    with tempfile.TemporaryDirectory(prefix="lah-context-pack-fixture-") as temp:
        root = Path(temp)
        _fixture(root)
        candidates = ["src", "docs", "vendor"]
        kwargs = {
            "directory_hints": ["src", "docs", "vendor"],
            "exclude_paths": ["vendor/private.py"],
            "max_directory_files": 16,
            "max_tokens": 512,
            "top_k": 8,
        }

        # Each cold sample gets a fresh RepositoryTools instance. Warm samples
        # traverse the same in-memory benchmark response cache used by this tool.
        cold_ms: list[float] = []
        sample_result: dict[str, Any] | None = None
        for _ in range(repetitions):
            tools = RepositoryTools({"rag": {"extensions": [".py", ".md"]}, "search": {"max_files": 32}})
            started = time.perf_counter()
            result = tools.context_pack_paths(str(root), QUERY, candidates, **kwargs)
            cold_ms.append((time.perf_counter() - started) * 1000)
            if not result.get("success"):
                raise RuntimeError(str(result.get("error", "context pack failed")))
            sample_result = result

        assert sample_result is not None
        response_cache: dict[str, dict[str, Any]] = {}
        cache_key = json.dumps([QUERY, candidates, kwargs], sort_keys=True)
        response_cache[cache_key] = sample_result
        warm_ms: list[float] = []
        cache_hits = 0
        for _ in range(repetitions):
            started = time.perf_counter()
            cached = response_cache.get(cache_key)
            if cached is None:
                cached = RepositoryTools({"rag": {"extensions": [".py", ".md"]}, "search": {"max_files": 32}}).context_pack_paths(
                    str(root), QUERY, candidates, **kwargs,
                )
                response_cache[cache_key] = cached
            else:
                cache_hits += 1
            warm_ms.append((time.perf_counter() - started) * 1000)

        evidence_paths = [str(item.get("path", "")) for item in sample_result.get("evidence", [])]
        retrieved = set(evidence_paths[:3])
        true_positives = len(retrieved & RELEVANT)
        precision = true_positives / max(1, len(retrieved))
        recall = true_positives / len(RELEVANT)
        context = str(sample_result.get("context", ""))
        return {
            "success": True,
            "fixture_semantics": "five synthetic files; two labeled relevant; no external model/backend",
            "backend_behavior": "Serena/RAG disabled; timeout and degraded-backend behavior not exercised",
            "query": QUERY,
            "precision_at_3": round(precision, 3),
            "recall_at_3": round(recall, 3),
            "cold_ms": {"p50": _percentile(cold_ms, 0.50), "p95": _percentile(cold_ms, 0.95)},
            "warm_ms": {"p50": _percentile(warm_ms, 0.50), "p95": _percentile(warm_ms, 0.95)},
            "warm_cache": {"layer": "benchmark_response_cache", "hits": cache_hits, "requests": repetitions},
            "visited_files": int(sample_result.get("scanned_files", 0) or 0),
            "output_bytes": len(context.encode("utf-8")),
            "output_tokens_est": int(sample_result.get("estimated_tokens", 0) or 0),
            "evidence_paths": evidence_paths,
            "excluded_path_present": "vendor/private.py" in evidence_paths or "secret fixture marker" in context,
            "concurrency": _concurrency_scenarios(sample_result, repetitions),
            "repetitions": repetitions,
        }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), ensure_ascii=False, sort_keys=True))
