from __future__ import annotations

import argparse
import gc
import hashlib
import json
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

# Pin imports to this checkout instead of an installed package.
_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if not (_SOURCE_ROOT / "local_ai_hub").is_dir():
    raise RuntimeError(f"repository source package not found: {_SOURCE_ROOT}")
sys.path.insert(0, str(_SOURCE_ROOT))

from local_ai_hub.agent_context import CompiledContext, ContextElement


def _context(element_count: int) -> CompiledContext:
    elements = [
        ContextElement(
            element_id=f"element-{index}",
            source_kind="preload",
            content=f"Unicode payload {index}: café — 雪",
            estimated_tokens=24,
            reason="legacy digest streaming benchmark",
            confidence=0.75,
            freshness=float(index),
            provenance={
                "source": "benchmark",
                "index": index,
                "details": {
                    "label": f"élément-{index}-🧪",
                    "tags": ["nested", "雪", index],
                    "mapping": {"z": index, "a": {"β": index, "α": True}},
                },
            },
        )
        for index in range(element_count)
    ]
    context = CompiledContext(
        elements=elements,
        estimated_tokens=24 * element_count,
        token_budget=4096,
        phase="review",
        repo_revision="benchmark-revision",
    )
    object.__setattr__(context, "request_identity_digest", "benchmark-request-digest")
    return context


def _legacy_etag(context: CompiledContext) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(context.phase.encode("utf-8"))
    digest.update(context.repo_revision.encode("utf-8"))
    digest.update(getattr(context, "request_identity_digest", "").encode("ascii", errors="ignore"))
    for element in context.elements:
        serialized = json.dumps(
            element.to_dict(compact=False),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        digest.update(serialized.encode("utf-8", errors="replace"))
    return digest.hexdigest()[:12]


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))]


def _paired_latency(baseline, candidate, iterations: int) -> dict[str, float]:
    baseline_us: list[float] = []
    candidate_us: list[float] = []
    for index in range(iterations):
        calls = ((baseline, baseline_us), (candidate, candidate_us))
        if index % 2:
            calls = tuple(reversed(calls))
        for operation, values in calls:
            started = time.perf_counter_ns()
            operation()
            values.append((time.perf_counter_ns() - started) / 1_000)
    return {
        "legacy_p50_us": statistics.median(baseline_us),
        "legacy_p95_us": _p95(baseline_us),
        "stream_p50_us": statistics.median(candidate_us),
        "stream_p95_us": _p95(candidate_us),
    }


def _peak_allocation(operation, samples: int) -> dict[str, float]:
    peaks: list[float] = []
    for _ in range(samples):
        gc.collect()
        tracemalloc.start()
        operation()
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peaks.append(float(peak))
    return {"median_peak_bytes": statistics.median(peaks), "p95_peak_bytes": _p95(peaks)}


def _measure(element_count: int, iterations: int, allocation_samples: int) -> dict[str, object]:
    context = _context(element_count)
    legacy = lambda: _legacy_etag(context)
    streamed = context.etag
    legacy_id = legacy()
    streamed_id = streamed()
    if legacy_id != streamed_id:
        raise AssertionError(f"legacy ETag mismatch: {legacy_id} != {streamed_id}")
    return {
        "elements": element_count,
        "etag": legacy_id,
        "latency": _paired_latency(legacy, streamed, iterations),
        "peak_allocations": {
            "legacy": _peak_allocation(legacy, allocation_samples),
            "stream": _peak_allocation(streamed, allocation_samples),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Paired legacy/streamed context ETag benchmark")
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--allocation-samples", type=int, default=20)
    args = parser.parse_args()
    if args.iterations < 100:
        parser.error("--iterations must be at least 100 for useful p95")
    if args.allocation_samples < 5:
        parser.error("--allocation-samples must be at least 5")
    result = {
        "benchmark": "context-etag-legacy-streaming",
        "paired": True,
        "latency_unit": "microseconds",
        "allocation_unit": "bytes",
        "no_speedup_claim": True,
        "iterations_per_phase": args.iterations,
        "allocation_samples_per_phase": args.allocation_samples,
        "fixed_contexts": {
            "small": _measure(4, args.iterations, args.allocation_samples),
            "large": _measure(64, args.iterations, args.allocation_samples),
        },
        "source_file": CompiledContext.etag.__code__.co_filename,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
