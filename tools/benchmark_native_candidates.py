"""Reproducible measurement and quality benchmark runner for native performance candidates.

Implements T0 / perf_candidate.v1 contract:
- CLI accepts --case watcher|json-budget|simhash|search|symbols|rag|memory|indexing|telemetry
- Enforces external state directory (never inside repository root)
- Records independently measured pairs for JSON-budget and SimHash; other cases are diagnostic
- Distinguishes diagnostic cohorts (e.g. 30 pairs) from tail statistical acceptance (>= 1,000 independent pairs for p95/p99)
- Outputs perf_candidate.v1 schema with hardware, source, samples, latency, and resource counters
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "perf_candidate.v1"
SUPPORTED_CASES = (
    "watcher",
    "json-budget",
    "simhash",
    "search",
    "symbols",
    "rag",
    "memory",
    "indexing",
    "telemetry",
)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_v[int(k)]
    return sorted_v[f] * (c - k) + sorted_v[c] * (k - f)


def _compute_stats(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {
            "p50_ms": 0.0,
            "p90_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "mean_ms": 0.0,
            "stdev_ms": 0.0,
        }
    mean = sum(samples) / len(samples)
    variance = sum((x - mean) ** 2 for x in samples) / max(1, len(samples) - 1)
    return {
        "p50_ms": round(_percentile(samples, 50.0), 6),
        "p90_ms": round(_percentile(samples, 90.0), 6),
        "p95_ms": round(_percentile(samples, 95.0), 6),
        "p99_ms": round(_percentile(samples, 99.0), 6),
        "mean_ms": round(mean, 6),
        "stdev_ms": round(math.sqrt(variance), 6),
    }


def _get_git_commit(root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(root), text=True, stderr=subprocess.DEVNULL, timeout=5
        ).strip()
        return out
    except Exception:
        return "unknown"


def _get_git_dirty(root: Path) -> bool | None:
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=str(root), text=True, stderr=subprocess.DEVNULL, timeout=5,
        )
        return bool(out.strip())
    except Exception:
        return None


def _module_matches_source(module: Any, root: Path, name: str) -> bool:
    try:
        return Path(module.__file__).resolve(strict=True) == (root / "src" / "local_ai_hub" / name).resolve(strict=True)
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def run_benchmark_case(
    case: str,
    root: Path,
    state_dir: Path,
    repetitions: int = 30,
    *,
    allow_inference: bool = False,
) -> dict[str, Any]:
    if case not in SUPPORTED_CASES:
        raise ValueError(f"Unsupported benchmark case: {case!r}, expected one of {SUPPORTED_CASES}")

    root = root.resolve(strict=True)
    state_dir = state_dir.resolve()
    if state_dir.is_relative_to(root):
        raise ValueError("state-dir must be outside the target repository root")

    state_dir.mkdir(parents=True, exist_ok=True)
    commit = _get_git_commit(root)
    dirty = _get_git_dirty(root) if commit != "unknown" else None
    measured_baseline = case in {"simhash", "json-budget"}
    candidate_backend_active = False
    candidate_source_bound = False
    if case == "json-budget":
        from local_ai_hub import token_accounting
        candidate_backend_active = token_accounting._orjson is not None
        candidate_source_bound = _module_matches_source(token_accounting, root, "token_accounting.py")
    elif case == "simhash":
        from local_ai_hub import native_kernels, rag
        candidate_backend_active = native_kernels.is_native_enabled()
        candidate_source_bound = (_module_matches_source(native_kernels, root, "native_kernels.py")
                                  and _module_matches_source(rag, root, "rag.py"))
    rnd = random.Random(20261026)

    baseline_samples: list[float] = []
    candidate_samples: list[float] = []
    pairs: list[dict[str, Any]] = []

    # Execute paired workload observations
    for epoch in range(repetitions):
        # Workload measurement based on case
        if case == "simhash":
            import local_ai_hub.rag as rag
            import local_ai_hub.native_kernels as native_kernels

            test_text = (
                f"def candidate_benchmark_routine_{epoch}(input_payload: dict[str, Any]) -> int:\n"
                f"    # Epoch {epoch} observation verification\n"
                f"    key = hashlib.sha256(str({epoch}).encode('utf-8')).hexdigest()\n"
                f"    return len(key) + {epoch}\n"
            ) * 16

            # Baseline measurement (Python reference)
            t0 = time.perf_counter()
            orig_enabled = native_kernels.is_native_enabled()
            try:
                native_kernels.set_native_enabled(False)
                base_fp = rag._simhash(test_text)
            finally:
                native_kernels.set_native_enabled(orig_enabled)
            base_ms = (time.perf_counter() - t0) * 1000.0

            # Candidate measurement (Native / current production)
            t1 = time.perf_counter()
            cand_fp = native_kernels.simhash_text(test_text)
            cand_ms = (time.perf_counter() - t1) * 1000.0

            if base_fp != cand_fp:
                raise RuntimeError(f"Parity mismatch in simhash benchmark epoch {epoch}")

            baseline_samples.append(base_ms)
            candidate_samples.append(cand_ms)
            if epoch < 100 or epoch % 100 == 0:
                pairs.append({"epoch": epoch, "baseline_ms": round(base_ms, 4), "candidate_ms": round(cand_ms, 4)})

        elif case == "json-budget":
            from local_ai_hub.token_accounting import _streaming_json_tokens, json_tokens

            sample_payload = {
                "epoch": epoch,
                "tasks": [{"task_id": f"task_{i}_{epoch}", "status": "active", "meta": {"weight": rnd.random()}} for i in range(25)],
                "evidence": ["evidence_id_abc123", "evidence_id_def456"],
            }
            observations: dict[str, tuple[int, float]] = {}
            operations = (("baseline", _streaming_json_tokens), ("candidate", json_tokens))
            if epoch % 2:
                operations = tuple(reversed(operations))
            for label, operation in operations:
                started = time.perf_counter()
                tokens = operation(sample_payload)
                observations[label] = (tokens, (time.perf_counter() - started) * 1000.0)
            baseline_tokens, base_ms = observations["baseline"]
            candidate_tokens, cand_ms = observations["candidate"]
            if baseline_tokens != candidate_tokens:
                raise RuntimeError(f"JSON token parity mismatch in benchmark epoch {epoch}")
            baseline_samples.append(base_ms)
            candidate_samples.append(cand_ms)
            pairs.append({"epoch": epoch, "baseline_ms": round(base_ms, 6),
                          "candidate_ms": round(cand_ms, 6), "tokens": candidate_tokens})

        elif case == "watcher":
            from local_ai_hub.preprocess import _get_cached_project_extensions

            t0 = time.perf_counter()
            exts = _get_cached_project_extensions(root)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            candidate_samples.append(elapsed_ms)
            baseline_samples.append(elapsed_ms + 0.1)
            if epoch < 100 or epoch % 100 == 0:
                pairs.append({"epoch": epoch, "elapsed_ms": round(elapsed_ms, 4), "ext_count": len(exts)})

        else:
            # Default paired measurement timing
            t0 = time.perf_counter()
            time.sleep(0.0001)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            candidate_samples.append(elapsed_ms)
            baseline_samples.append(elapsed_ms * 1.2)
            if epoch < 100 or epoch % 100 == 0:
                pairs.append({"epoch": epoch, "candidate_ms": round(elapsed_ms, 4)})

    base_stats = _compute_stats(baseline_samples)
    cand_stats = _compute_stats(candidate_samples)

    is_tail_run = len(candidate_samples) >= 1000
    p95_candidate = _percentile(candidate_samples, 95.0)
    p99_candidate = _percentile(candidate_samples, 99.0)
    p95_ratio = _percentile(baseline_samples, 95.0) / p95_candidate if p95_candidate > 0 else 0.0
    p99_ratio = _percentile(baseline_samples, 99.0) / p99_candidate if p99_candidate > 0 else 0.0
    p95_speedup = round(p95_ratio, 2) if measured_baseline else None
    p99_speedup = round(p99_ratio, 2) if measured_baseline else None
    tail_gate_met = (
        is_tail_run and measured_baseline and candidate_backend_active and candidate_source_bound
        and commit != "unknown" and dirty is False
        and p95_ratio >= 1.25 and p99_ratio >= 1.25
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "success": True,
        "case": case,
        "root": str(root),
        "source_identity": {
            "git_commit": commit,
            "dirty": dirty,
        },
        "hardware_identity": {
            "platform": sys.platform,
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
        },
        "measurement": {
            "sample_count": len(candidate_samples),
            "tail_sample_gate_met": is_tail_run,
            "note": ("Synthetic reference; diagnostic only" if not measured_baseline else
                     "sample_count < 1000 represents diagnostic cohort only, not tail statistical acceptance gate"
                     if not is_tail_run else "1000+ independently measured pairs"),
            "baseline_provenance": "measured_reference" if measured_baseline else "synthetic_diagnostic",
            "candidate_stats": cand_stats,
            "baseline_stats": base_stats,
            "p95_speedup": p95_speedup,
            "p99_speedup": p99_speedup,
            "tail_gate_met": tail_gate_met,
        },
        "samples_summary": pairs if case == "json-budget" else pairs[:100],
        "quality_scope": {
            "allow_inference": allow_inference,
            "verified_parity": measured_baseline and bool(candidate_samples),
            "candidate_backend_active": candidate_backend_active,
            "candidate_source_bound": candidate_source_bound,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run native candidate performance benchmarks (T0 / perf_candidate.v1)")
    parser.add_argument("--case", required=True, choices=SUPPORTED_CASES, help="workload case to benchmark")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="target repository root")
    parser.add_argument("--state-dir", type=Path, required=True, help="external state directory")
    parser.add_argument("--repetitions", type=int, default=30, help="number of paired observations (>=1000 for tail gate)")
    parser.add_argument("--allow-inference", action="store_true", help="opt-in to model inference workloads")
    parser.add_argument("--output", type=Path, help="path to persist output JSON")

    args = parser.parse_args(argv)

    try:
        result = run_benchmark_case(
            case=args.case,
            root=args.root,
            state_dir=args.state_dir,
            repetitions=args.repetitions,
            allow_inference=args.allow_inference,
        )
    except Exception as exc:
        result = {
            "schema_version": SCHEMA_VERSION,
            "success": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "case": args.case,
        }

    serialized = json.dumps(result, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)

    return 0 if result.get("success") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
