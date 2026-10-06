"""Opt-in synthetic performance and quality baseline for Local AI Hub surfaces.

The default run is deliberately small and never invokes a model. Large synthetic
matrices and inference require explicit CLI flags; generated data stays in
temporary storage, timing samples/metrics persist under --state-dir.
"""

from __future__ import annotations

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
import socket
import tempfile
import threading
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen


_REPO_ROOT = Path(__file__).resolve().parents[1]
_FULL_FILE_SIZES = {100, 10_000, 100_000}
_FULL_RAG_SIZES = {10_000, 100_000}
_MAX_CONCURRENCY = 256
_MAX_REPETITIONS = 1_000
_PLAN_GRADE_CONCURRENCY = {1, 4, 16, 32}
_REGRESSION_TOLERANCE = 0.10
_REQUIRED_MATRIX_CASES = {
    (file_count, rag_chunk_count)
    for file_count in _FULL_FILE_SIZES
    for rag_chunk_count in _FULL_RAG_SIZES
}
_REQUIRED_GOLDEN_OPERATIONS = {
    "symbols", "graph", "affected_tests", "retrieval_relevance",
    "code_generation", "vision", "speech", "context_pack",
}
_REQUIRED_COMPARISON_STAGES = {
    "transport", "hub_health", "hub_validation", "hub_sqlite_index",
    "hub_sqlite_db_read", "hub_code_index", "hub_context_pack",
    "hub_queue_admission", "hub_rag_chunking",
}


@dataclass(frozen=True)
class _HTTPObservation:
    status: int
    body: bytes
    payload: Any


def _resolve_outside_repo(path: Path, name: str) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == _REPO_ROOT or _REPO_ROOT in resolved.parents:
        raise ValueError(f"{name} must be outside the repository")
    return resolved


def _cleanup_benchmark_scratch(
    scratch_path: Path,
    *,
    server_thread: threading.Thread | None,
    workers: list[threading.Thread],
    dispatchers: list[threading.Thread],
    errors: list[str],
    grace_seconds: float = 0.5,
) -> dict[str, Any]:
    """Remove invocation-owned scratch only after all threads using it stop."""
    deadline = time.monotonic() + max(0.0, grace_seconds)
    threads = workers + dispatchers
    for worker in threads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if worker.is_alive():
            worker.join(timeout=remaining)

    alive_workers = sum(worker.is_alive() for worker in workers)
    alive_dispatchers = sum(worker.is_alive() for worker in dispatchers)
    server_alive = bool(server_thread and server_thread.is_alive())
    if not errors and not server_alive and not alive_workers and not alive_dispatchers:
        try:
            shutil.rmtree(scratch_path)
            return {
                "status": "cleaned",
                "live_workers": 0,
                "live_dispatchers": 0,
                "server_thread_alive": False,
            }
        except OSError as exc:
            errors.append(f"scratch_cleanup:{type(exc).__name__}")

    return {
        "status": "preserved_incomplete",
        "live_workers": alive_workers,
        "live_dispatchers": alive_dispatchers,
        "server_thread_alive": server_alive,
        "errors": errors,
    }


def _percentile(sorted_values: list[float], percentile: float) -> float | None:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * percentile / 100.0
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return round(sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight, 3)


def summarize_samples(samples_ms: list[float]) -> dict[str, Any]:
    """Summarize measured operation latencies using linearly interpolated quantiles."""
    values = sorted(float(value) for value in samples_ms if value >= 0)
    total_ms = sum(values)
    return {
        "count": len(values),
        "p50_ms": _percentile(values, 50),
        "p95_ms": _percentile(values, 95),
        "p99_ms": _percentile(values, 99),
        "min_ms": round(values[0], 3) if values else None,
        "max_ms": round(values[-1], 3) if values else None,
        "mean_ms": round(total_ms / len(values), 3) if values else None,
        "throughput_per_second": round(len(values) * 1000.0 / total_ms, 3) if total_ms else None,
    }


def _plan_grade_reasons(metadata: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    repetitions = metadata.get("stage_repetitions", {})
    light = repetitions.get("light") if isinstance(repetitions, dict) else None
    paired = repetitions.get("paired") if isinstance(repetitions, dict) else None
    if not isinstance(light, int) or isinstance(light, bool) or light < 1_000:
        reasons.append("light_repetitions_below_1000")
    if not isinstance(paired, int) or isinstance(paired, bool) or paired < 30:
        reasons.append("paired_repetitions_below_30")
    concurrency = metadata.get("concurrency", [])
    concurrency_levels = {
        level for level in concurrency
        if isinstance(level, int) and not isinstance(level, bool)
    } if isinstance(concurrency, list) else set()
    if not _PLAN_GRADE_CONCURRENCY.issubset(concurrency_levels):
        reasons.append("concurrency_must_include_1_4_16_32")
    matrix = metadata.get("completed_matrix")
    observed_cases: list[tuple[int, int]] = []
    rows = matrix if isinstance(matrix, list) else []
    matrix_complete = len(rows) == len(_REQUIRED_MATRIX_CASES)
    golden_complete = matrix_complete
    for row in rows:
        if not isinstance(row, dict):
            matrix_complete = False
            golden_complete = False
            continue
        file_count, rag_chunk_count = row.get("file_count"), row.get("rag_chunk_count")
        if (
            not isinstance(file_count, int) or isinstance(file_count, bool)
            or not isinstance(rag_chunk_count, int) or isinstance(rag_chunk_count, bool)
        ):
            matrix_complete = False
            golden_complete = False
            continue
        observed_cases.append((file_count, rag_chunk_count))
        if row.get("status") != "completed":
            matrix_complete = False
        goldens = row.get("golden_operations")
        if not isinstance(goldens, dict) or any(goldens.get(name) is not True for name in _REQUIRED_GOLDEN_OPERATIONS):
            golden_complete = False
    matrix_complete = matrix_complete and len(observed_cases) == len(_REQUIRED_MATRIX_CASES) and set(observed_cases) == _REQUIRED_MATRIX_CASES
    if not matrix_complete:
        reasons.append("completed_matrix_missing_or_incomplete")
    if not golden_complete:
        reasons.append("required_golden_operations_incomplete")
    if metadata.get("inference") == "requested" and _normalize_model_digest(metadata.get("inference_model_digest")) is None:
        reasons.append("inference_model_digest_missing_or_invalid")
    return reasons


def _normalize_model_digest(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    digest = value[7:] if value.startswith("sha256:") else value
    if len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
        return None
    return digest.lower()


def _paired_repetition_count(metadata: dict[str, Any]) -> int:
    repetitions = metadata.get("stage_repetitions")
    paired = repetitions.get("paired") if isinstance(repetitions, dict) else None
    return paired if isinstance(paired, int) and not isinstance(paired, bool) and paired > 0 else 0


def _quality_comparison(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    def checks(record: dict[str, Any]) -> dict[str, bool]:
        golden = record.get("golden", {})
        if not isinstance(golden, dict):
            return {}
        return {
            name: item["passed"]
            for name, item in golden.items()
            if isinstance(item, dict) and isinstance(item.get("passed"), bool)
        }

    old, new = checks(baseline), checks(candidate)
    names = sorted(set(old) | set(new))
    changes = {
        name: {
            "baseline_passed": old.get(name),
            "candidate_passed": new.get(name),
            "status": "unchanged" if old.get(name) == new.get(name) else "changed",
        }
        for name in names
    }
    old_score = round(sum(old.values()) * 100.0 / len(old), 3) if old else None
    new_score = round(sum(new.values()) * 100.0 / len(new), 3) if new else None
    return {
        "baseline_score_pct": old_score,
        "candidate_score_pct": new_score,
        "delta_pct_points": round(new_score - old_score, 3) if old_score is not None and new_score is not None else None,
        "operations": changes,
    }


def compare_records(
    baseline: dict[str, Any], candidate: dict[str, Any], *, regression_tolerance: float = _REGRESSION_TOLERANCE,
) -> dict[str, Any]:
    """Compare paired operation samples; smoke comparisons remain provisional."""
    if not 0 <= regression_tolerance < 1:
        raise ValueError("regression_tolerance must be in [0, 1)")
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        return {"status": "incomparable", "reason": "benchmark record must be a JSON object"}
    if baseline.get("success") is not True or candidate.get("success") is not True:
        return {"status": "incomparable", "reason": "both benchmark records must pass supported golden and stage gates"}
    baseline_meta = baseline.get("metadata", {})
    candidate_meta = candidate.get("metadata", {})
    if not isinstance(baseline_meta, dict) or not isinstance(candidate_meta, dict):
        return {"status": "incomparable", "reason": "benchmark metadata is missing or malformed"}
    if any(
        not baseline_meta.get(field) or baseline_meta.get(field) != candidate_meta.get(field)
        for field in ("benchmark_scope", "config_fingerprint", "hardware_fingerprint")
    ):
        return {"status": "incomparable", "reason": "benchmark scope, configuration, or hardware differs"}
    if baseline_meta.get("inference") == "requested" or candidate_meta.get("inference") == "requested":
        baseline_digest = _normalize_model_digest(baseline_meta.get("inference_model_digest"))
        candidate_digest = _normalize_model_digest(candidate_meta.get("inference_model_digest"))
        if baseline_digest is None or baseline_digest != candidate_digest:
            return {"status": "incomparable", "reason": "inference model digest is unavailable or differs"}

    compared: dict[str, Any] = {}
    incomplete: list[str] = []
    baseline_stages, candidate_stages = baseline.get("stages"), candidate.get("stages")
    if not isinstance(baseline_stages, dict) or not isinstance(candidate_stages, dict):
        return {"status": "incomparable", "reason": "benchmark stages are missing or malformed"}
    required_stages = set(_REQUIRED_COMPARISON_STAGES)
    if baseline_meta.get("inference") == "requested" or candidate_meta.get("inference") == "requested":
        required_stages.update(("model_load", "inference"))
    missing_required = {
        label: sorted(required_stages - set(stages))
        for label, stages in (("baseline", baseline_stages), ("candidate", candidate_stages))
    }
    missing_required = {label: names for label, names in missing_required.items() if names}
    if missing_required:
        return {
            "status": "incomparable",
            "reason": "required benchmark stages are missing",
            "missing_required_stages": missing_required,
        }
    unpassed_required = {
        label: sorted(
            name for name in required_stages
            if not isinstance(stages.get(name), dict) or stages[name].get("status") != "passed"
        )
        for label, stages in (("baseline", baseline_stages), ("candidate", candidate_stages))
    }
    unpassed_required = {label: names for label, names in unpassed_required.items() if names}
    if unpassed_required:
        return {
            "status": "incomparable",
            "reason": "required benchmark stages did not pass",
            "unpassed_required_stages": unpassed_required,
        }
    for name in sorted(set(baseline_stages) & set(candidate_stages)):
        before, after = baseline_stages[name], candidate_stages[name]
        if not isinstance(before, dict) or not isinstance(after, dict):
            incomplete.append(name)
            continue
        if before.get("status") != "passed" or after.get("status") != "passed":
            continue
        old_regimes, new_regimes = before.get("samples_by_regime"), after.get("samples_by_regime")
        if not isinstance(old_regimes, dict) or not isinstance(new_regimes, dict):
            incomplete.append(name)
            continue
        valid = True
        for regime in ("cold", "warm"):
            old_values, new_values = old_regimes.get(regime), new_regimes.get(regime)
            if not isinstance(old_values, list) or not isinstance(new_values, list) or len(old_values) != len(new_values):
                valid = False
                break
            if any(
                not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0 or not math.isfinite(value)
                for value in old_values + new_values
            ):
                valid = False
                break
        if not valid:
            incomplete.append(name)
            continue

        regimes: dict[str, Any] = {}
        stage_regression = False
        for regime in ("cold", "warm"):
            old = [float(value) for value in old_regimes[regime]]
            new = [float(value) for value in new_regimes[regime]]
            if not old:
                regimes[regime] = {"paired_count": 0, "regression": False, "latency": {}, "paired_delta_pct_percentile_range_95": {"low": None, "high": None}}
                continue
            old_summary, new_summary = summarize_samples(old), summarize_samples(new)
            changes: dict[str, Any] = {}
            regime_regression = False
            for metric in ("p50_ms", "p95_ms", "p99_ms", "throughput_per_second"):
                old_value, new_value = old_summary[metric], new_summary[metric]
                delta_pct = ((new_value - old_value) / old_value * 100.0) if old_value else None
                changes[metric] = {
                    "baseline": old_value, "candidate": new_value,
                    "delta_pct": round(delta_pct, 3) if delta_pct is not None else None,
                }
                if metric in {"p95_ms", "p99_ms"} and delta_pct is not None and delta_pct > regression_tolerance * 100.0:
                    stage_regression = True
                    regime_regression = True
            paired_delta_pct = [
                (new_value - old_value) / old_value * 100.0
                for old_value, new_value in zip(old, new)
                if old_value > 0
            ]
            paired_sorted = sorted(paired_delta_pct)
            regimes[regime] = {
                "paired_count": len(old),
                "regression": regime_regression,
                "latency": changes,
                "paired_delta_pct_percentile_range_95": {
                    "low": _percentile(paired_sorted, 2.5),
                    "high": _percentile(paired_sorted, 97.5),
                },
            }
        compared[name] = {"regression": stage_regression, **regimes}

    if incomplete or not compared:
        return {"status": "incomparable", "reason": "no complete paired stage samples", "incomplete_stages": incomplete}
    provisional = {
        "status": "regression" if any(stage["regression"] for stage in compared.values()) else "within_tolerance",
        "regression_tolerance_pct": round(regression_tolerance * 100.0, 3),
        "baseline_revision": baseline_meta.get("revision"),
        "candidate_revision": candidate_meta.get("revision"),
        "compared_stage_count": len(compared),
        "stages": compared,
        "quality": _quality_comparison(baseline, candidate),
    }
    reasons = list(dict.fromkeys(_plan_grade_reasons(baseline_meta) + _plan_grade_reasons(candidate_meta)))
    if baseline_meta.get("baseline_readiness") != "plan_grade":
        reasons.append("baseline_is_not_aggregated_plan_grade")
    if candidate_meta.get("baseline_readiness") != "plan_grade":
        reasons.append("candidate_is_not_aggregated_plan_grade")
    paired_target = min(_paired_repetition_count(baseline_meta), _paired_repetition_count(candidate_meta))
    minimum_samples = max(30, paired_target)
    for name in compared:
        before, after = baseline_stages[name], candidate_stages[name]
        for regime in ("cold", "warm"):
            old_count = len(before["samples_by_regime"][regime])
            new_count = len(after["samples_by_regime"][regime])
            if old_count < minimum_samples:
                reasons.append(f"paired_samples_below_{minimum_samples}:{name}:{regime}:baseline")
            if new_count < minimum_samples:
                reasons.append(f"paired_samples_below_{minimum_samples}:{name}:{regime}:candidate")
    if reasons:
        return {
            "status": "inconclusive",
            "reason": ";".join(dict.fromkeys(reasons)),
            "baseline_readiness": baseline_meta.get("baseline_readiness", "smoke_only"),
            "candidate_readiness": candidate_meta.get("baseline_readiness", "smoke_only"),
            "provisional": provisional,
        }
    return provisional


def _cold_warm_summary(samples: list[float]) -> dict[str, Any]:
    return {
        "cold": summarize_samples(samples[:1]),
        "warm": summarize_samples(samples[1:]),
        "definition": "first operation invocation is cold; remaining invocations are warm; no OS cache flush",
    }


def _measure_stage(
    name: str, operation: Callable[[], Any], repetitions: int, *, before_each: Callable[[int], Any] | None = None,
    indexed: bool = False,
) -> dict[str, Any]:
    samples: list[float] = []
    errors = 0
    http_response_body_bytes = 0
    whitespace_token_estimate = 0
    error_types: set[str] = set()
    response_measurement = "not_applicable_no_http_response"
    for index in range(repetitions):
        started = time.perf_counter()
        try:
            if before_each is not None:
                before_each(index)
            started = time.perf_counter()
            result = operation(index) if indexed else operation()
            if isinstance(result, _HTTPObservation):
                response_measurement = "exact_http_response_body_bytes"
                http_response_body_bytes = max(http_response_body_bytes, len(result.body))
                whitespace_token_estimate = max(
                    whitespace_token_estimate,
                    len(result.body.decode("utf-8", errors="replace").split()),
                )
            elif isinstance(result, dict) and result.get("success") is False:
                raise RuntimeError("operation returned an unsuccessful result")
        except Exception as exc:  # capture failures per stage; never serialize exception text
            errors += 1
            error_types.add(type(exc).__name__)
        samples.append((time.perf_counter() - started) * 1000.0)
    return {
        "status": "passed" if errors == 0 else "failed",
        **summarize_samples(samples),
        "samples_ms": samples,
        "samples_by_regime": {"cold": samples[:1], "warm": samples[1:]},
        "cold_warm": _cold_warm_summary(samples),
        "error_count": errors,
        "error_rate_pct": round(errors * 100.0 / len(samples), 3) if samples else 0.0,
        "error_types": sorted(error_types),
        "http_response_body_bytes": http_response_body_bytes,
        "whitespace_token_estimate": whitespace_token_estimate,
        "response_measurement": response_measurement,
        "measurement": name,
    }


def _measure_stage_regimes(
    name: str,
    cold_operation: Callable[[int], Any],
    warm_operation: Callable[[int], Any],
    repetitions: int,
    *,
    warm_prepare: Callable[[int], Any] | None = None,
    definition: str,
) -> dict[str, Any]:
    cold = _measure_stage(name, cold_operation, repetitions, indexed=True)
    warm = _measure_stage(name, warm_operation, repetitions, before_each=warm_prepare, indexed=True)
    samples = cold["samples_ms"] + warm["samples_ms"]
    cold_warm = {
        "cold": summarize_samples(cold["samples_ms"]),
        "warm": summarize_samples(warm["samples_ms"]),
        "definition": definition,
    }
    return {
        "status": "passed" if cold["status"] == warm["status"] == "passed" else "failed",
        **summarize_samples(samples),
        "samples_ms": samples,
        "samples_by_regime": {"cold": cold["samples_ms"], "warm": warm["samples_ms"]},
        "cold_warm": cold_warm,
        "error_count": cold["error_count"] + warm["error_count"],
        "error_rate_pct": round((cold["error_count"] + warm["error_count"]) * 100.0 / max(1, len(samples)), 3),
        "error_types": sorted(set(cold["error_types"] + warm["error_types"])),
        "http_response_body_bytes": max(cold["http_response_body_bytes"], warm["http_response_body_bytes"]),
        "http_response_body_bytes_by_regime": {
            "cold": cold["http_response_body_bytes"], "warm": warm["http_response_body_bytes"],
        },
        "whitespace_token_estimate": max(cold["whitespace_token_estimate"], warm["whitespace_token_estimate"]),
        "whitespace_token_estimate_by_regime": {
            "cold": cold["whitespace_token_estimate"], "warm": warm["whitespace_token_estimate"],
        },
        "response_measurement": cold["response_measurement"],
        "measurement": name,
    }


def _skipped_stage(reason: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        **summarize_samples([]),
        "samples_ms": [],
        "samples_by_regime": {"cold": [], "warm": []},
        "cold_warm": _cold_warm_summary([]),
        "error_count": 0,
        "error_rate_pct": 0.0,
        "error_types": [],
        "http_response_body_bytes": 0,
        "whitespace_token_estimate": 0,
        "response_measurement": "not_applicable_no_http_response",
        "reason": reason,
    }


def _synthetic_source(index: int) -> str:
    source = f"def symbol_{index}(value: int = 1) -> int:\n    return value + {index}\n"
    if index == 0:
        source += "\ndef graph_target() -> int:\n    return 1\n\ndef graph_caller() -> int:\n    return graph_target()\n"
    return source


def _build_synthetic_repo(root: Path, file_count: int, rag_chunks: int) -> tuple[list[Path], Path, Path]:
    source_root = root / "repo" / "src"
    test_root = root / "repo" / "tests"
    source_root.mkdir(parents=True, exist_ok=True)
    test_root.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for index in range(file_count):
        path = source_root / f"module_{index:06d}.py"
        path.write_text(_synthetic_source(index), encoding="utf-8")
        files.append(path)
    test_path = test_root / "test_graph_target.py"
    test_path.write_text(
        "from src.module_000000 import graph_target\n\ndef test_graph_target_returns_value():\n    assert graph_target() == 1\n",
        encoding="utf-8",
    )
    corpus_path = root / "synthetic-rag.jsonl"
    with corpus_path.open("w", encoding="utf-8", newline="\n") as stream:
        for index in range(rag_chunks):
            relevant = index % 997 == 7
            chunk = {
                "id": index,
                "text": f"synthetic {'needle' if relevant else 'filler'} chunk {index}",
                "relevant": relevant,
            }
            stream.write(json.dumps(chunk, separators=(",", ":")) + "\n")
    return files, test_path, corpus_path


def _ast_index(files: list[Path]) -> dict[str, str]:
    index: dict[str, str] = {}
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                index[node.name] = path.name
    return index


def _call_graph(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
    edges: set[tuple[str, str]] = set()
    for function in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                edges.add((function.name, node.func.id))
    return edges


def _affected_tests(test_path: Path, changed_symbol: str) -> list[str]:
    tree = ast.parse(test_path.read_text(encoding="utf-8"), filename=test_path.name)
    return sorted(
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_") and changed_symbol in node.name
    )


def _retrieve_relevant(corpus_path: Path, query: str) -> list[int]:
    matches: list[int] = []
    with corpus_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            chunk = json.loads(line)
            if query in chunk["text"]:
                matches.append(int(chunk["id"]))
    return matches


def _transport_sample(server: ThreadingHTTPServer) -> dict[str, bool]:
    with socket.create_connection(("127.0.0.1", server.server_port), timeout=2):
        return {"connected": True}


def _http_request(
    server: ThreadingHTTPServer, path: str, payload: dict[str, Any] | None = None,
) -> _HTTPObservation:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if payload is not None else None
    request = Request(
        f"http://127.0.0.1:{server.server_port}{path}", data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        response = urlopen(request, timeout=15)
    except HTTPError as exc:
        response = exc
    with response:
        body = response.read()
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = None
        return _HTTPObservation(status=int(response.status), body=body, payload=parsed)


def _revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=_REPO_ROOT,
            capture_output=True, text=True, timeout=2, check=False,
        )
        value = result.stdout.strip()
        return value if result.returncode == 0 and value else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _implementation_fingerprint() -> str:
    tracked_runtime = (
        "src/local_ai_hub/app.py",
        "src/local_ai_hub/http_server.py",
        "src/local_ai_hub/services.py",
        "src/local_ai_hub/code_index.py",
        "src/local_ai_hub/rag.py",
        "src/local_ai_hub/async_jobs.py",
        "src/local_ai_hub/repo_tools.py",
        "src/local_ai_hub/benchmark.py",
        "tools/benchmark_surfaces.py",
    )
    digest = hashlib.sha256()
    for relative in tracked_runtime:
        source_path = _REPO_ROOT / relative
        digest.update(Path(relative).name.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(hashlib.sha256(source_path.read_bytes()).digest())
        except OSError:
            digest.update(b"unavailable")
    return digest.hexdigest()


def _peak_rss_bytes() -> int | None:
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCountersEx(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCountersEx()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            get_memory = psapi.GetProcessMemoryInfo
            get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCountersEx), wintypes.DWORD]
            get_memory.restype = wintypes.BOOL
            if get_memory(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return int(counters.PeakWorkingSetSize)
            return None

        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return peak if sys.platform == "darwin" else peak * 1024
    except (AttributeError, ImportError, OSError, ValueError):
        return None


def _total_memory_bytes() -> int | None:
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatusEx()
            status.dwLength = ctypes.sizeof(status)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            get_memory_status = kernel32.GlobalMemoryStatusEx
            get_memory_status.argtypes = [ctypes.POINTER(MemoryStatusEx)]
            get_memory_status.restype = wintypes.BOOL
            return int(status.ullTotalPhys) if get_memory_status(ctypes.byref(status)) else None

        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None


def _vram_usage_bytes(snapshot: Any) -> int | None:
    if not isinstance(snapshot, dict):
        return None
    value = snapshot.get("vram_used_mb")
    if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
        return int(value * 1024 * 1024)
    return None


_T12_PROFILE_CORPUS: dict[str, tuple[dict[str, Any], ...]] = {
    "reason": ({
        "case_id": "reason-latency-triage-01",
        "prompt": "Given only these measurements: queue_wait_ms=250 and generation_duration_ms=80, determine the dominant stage and total measured time. Return one JSON object with keys dominant_stage, total_measured_ms, and evidence_paths. Available evidence: benchmarks/t12/reason-latency.json.",
        "num_tokens": 96,
        "evidence_paths": ["benchmarks/t12/reason-latency.json"],
        "expected": {
            "dominant_stage": "queue_wait",
            "total_measured_ms": 330,
            "evidence_paths": ["benchmarks/t12/reason-latency.json"],
        },
    },),
    "review": ({
        "case_id": "review-edge-case-01",
        "prompt": "Review `def first_item(items): return items[0]` for an edge case. Identify the edge case and propose a minimal fix. Return one JSON object with keys edge_case, minimal_fix, and evidence_paths. Available evidence: benchmarks/t12/review.py.",
        "num_tokens": 128,
        "evidence_paths": ["benchmarks/t12/review.py"],
        "expected": {
            "edge_case": "empty_list",
            "minimal_fix": "check empty input before indexing",
            "evidence_paths": ["benchmarks/t12/review.py"],
        },
    },),
    "compress": ({
        "case_id": "compress-incident-notes-01",
        "prompt": "Compress these incident notes while preserving all evidence and uncertainty: queue age rose to 400 ms; generation stayed near 90 ms; peak VRAM was not sampled during generation. Return one JSON object with keys facts, evidence_paths, and unknowns. Available evidence: benchmarks/t12/incident.json.",
        "num_tokens": 96,
        "evidence_paths": ["benchmarks/t12/incident.json"],
        "expected": {
            "facts": ["queue age rose to 400 ms", "generation stayed near 90 ms"],
            "evidence_paths": ["benchmarks/t12/incident.json"],
            "unknowns": ["peak VRAM was not sampled during generation"],
        },
    },),
    "complete": ({
        "case_id": "complete-empty-mean-01",
        "prompt": "Complete the behavior of mean(values): return None for empty input and the arithmetic mean otherwise. Evaluate [] and [2,4]. Return one JSON object with keys empty_result, mean_2_4, and evidence_paths; no source file is provided.",
        "num_tokens": 96,
        "evidence_paths": [],
        "expected": {"empty_result": None, "mean_2_4": 3, "evidence_paths": []},
    },),
    "scaffold": ({
        "case_id": "scaffold-parser-tests-01",
        "prompt": "Write a minimal unittest scaffold plan for parse_record(text), covering a valid record and malformed input. Do not invent parser behavior. Return one JSON object with keys test_cases, implementation_invented, and evidence_paths; no source evidence is provided.",
        "num_tokens": 128,
        "evidence_paths": [],
        "expected": {
            "test_cases": ["valid record", "malformed input"],
            "implementation_invented": False,
            "evidence_paths": [],
        },
    },),
}
_T12_QUALITY_EVALUATOR_ID = "model_quality.evaluate_case:t12.v1"
_T12_QUALITY_DIAGNOSTIC_FIELDS = (
    "structured_json_valid",
    "quality_schema_pass",
    "quality_expected_match",
    "quality_paths_grounded",
)
_T12_PROFILE_MODEL_KEYS = {
    "reason": "reasoning",
    "review": "heavy_code",
    "compress": "fast_code",
    "complete": "fast_code",
    "scaffold": "heavy_code",
}
_T12_SCENARIO_FIELDS: dict[str, tuple[str, ...]] = {
    "scheduler": (
        "queue_age_ms", "fairness_wait_ms", "bucket_id", "batch_size", "batch_item_count",
        "prefill_tokens", "vram_admission", "vram_budget_bytes", "vram_available_bytes", "vram_required_bytes",
        "vram_admission_budget_bytes", "vram_incremental_required_bytes", "vram_estimate_source",
    ),
    "batch": (
        "input_item_ids", "result_item_ids", "item_statuses", "partial_failure_count",
        "max_concurrency", "concurrency_limit", "failure_probe_item_id", "failure_probe_observed",
    ),
    "deadline": (
        "deadline_ms", "stages", "stage_timings_ms", "deadline_stage", "completed_within_deadline",
        "request_succeeded",
    ),
    "overload": (
        "overloaded", "queue_depth", "queue_admission", "queued_count", "rejected_count",
        "resource_rejected_count",
    ),
    "cancel": ("cancel_requested", "cancelled", "cleanup_complete", "cancel_to_stop_ms"),
    "fallback": (
        "fallback_used", "fallback_visible", "source_profile", "fallback_profile",
        "source_model", "fallback_model", "source_backend", "fallback_backend",
        "source_quality_pct", "source_quality_status", "quality_floor_pct",
        "fallback_quality_pct", "source_max_tokens", "fallback_max_tokens", "quality_floor_met",
    ),
}
_T12_PROFILE_METRICS = (
    "ttft_ms", "end_to_end_latency_ms", "tokens_per_second", "load_duration_ms",
    "queue_age_ms", "queue_wait_ms", "prefill_tokens",
    "vram_budget_bytes", "vram_required_bytes", "deadline_queue_ms", "deadline_model_load_ms",
    "deadline_generation_ms", "peak_vram_bytes",
)


def _summarize_t12_metric(name: str, samples: list[float]) -> dict[str, Any]:
    """Summarize T12 measurements without mislabeling non-time units as milliseconds."""
    unit = (
        "ms" if name.endswith("_ms")
        else "bytes" if name.endswith("_bytes")
        else "tokens/second" if name == "tokens_per_second"
        else "tokens" if name.endswith("_tokens")
        else "count"
    )
    summary = summarize_samples(samples)
    return {
        "count": summary["count"],
        "unit": unit,
        "p50": summary["p50_ms"],
        "p95": summary["p95_ms"],
        "p99": summary["p99_ms"],
        "min": summary["min_ms"],
        "max": summary["max_ms"],
        "mean": summary["mean_ms"],
    }


def _summarize_t12_signed_metric(name: str, samples: list[float]) -> dict[str, Any]:
    """Summarize signed deltas such as memory reclaimed during a model switch."""
    values = sorted(float(value) for value in samples if math.isfinite(value))
    return {
        "count": len(values),
        "unit": "bytes" if name.endswith("_bytes") else "count",
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
        "min": round(values[0], 3) if values else None,
        "max": round(values[-1], 3) if values else None,
        "mean": round(sum(values) / len(values), 3) if values else None,
    }


def _t12_fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _t12_hardware_identity(detected: Any = None) -> tuple[dict[str, Any], str]:
    hardware = {
        "system": platform.system(), "release": platform.release(), "machine": platform.machine(),
        "processor": platform.processor() or None, "cpu_count": os.cpu_count(),
        "total_memory_bytes": _total_memory_bytes(),
    }
    if isinstance(detected, dict):
        profile = detected.get("profile")
        hardware["profile"] = profile if isinstance(profile, str) else None
        device_fields = (
            "name", "gpu_name", "vendor", "vram_total_mb", "unified_memory_mb",
            "integrated", "shared_memory", "backend",
        )
        for device_kind in ("gpus", "npus"):
            devices = detected.get(device_kind)
            if isinstance(devices, list):
                hardware[device_kind] = [
                    {
                        key: device[key]
                        for key in device_fields
                        if isinstance(device, dict)
                        and key in device
                        and isinstance(device[key], (str, int, float, bool))
                    }
                    for device in devices[:8]
                    if isinstance(device, dict)
                ]
    return hardware, _t12_fingerprint(hardware)


def _t12_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _t12_scenario_report(
    runner: Any,
    name: str,
    *,
    concurrency_limit: int,
    quality_floor_pct: float,
    live_hardware: bool,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "not_measured", "contract_passed": False,
        "accepted": False, "live_hardware": live_hardware,
    }
    run_scenario = getattr(runner, "run_benchmark_scenario", None)
    if not callable(run_scenario):
        report["reason"] = "runner_has_no_scenario_hook"
        return report

    runner_config = getattr(runner, "config", {})
    runner_config = runner_config if isinstance(runner_config, dict) else {}
    configured_models = runner_config.get("models", {})
    configured_models = configured_models if isinstance(configured_models, dict) else {}
    model = configured_models.get("reasoning")
    if not isinstance(model, str) or not model.strip():
        report["reason"] = "scenario_model_not_configured"
        return report
    hardware = runner_config.get("_hardware", {})
    scenario_profile = hardware.get("profile") if isinstance(hardware, dict) else None
    if not isinstance(scenario_profile, str) or not scenario_profile.strip():
        scenario_profile = "reasoning"
    fallback_model = None
    fallback_profile = None
    candidate_profiles = (
        ("heavy_code", "fast_code", "general")
        if scenario_profile == "integrated"
        else ("fast_code", "heavy_code", "general")
    )
    for candidate_profile in candidate_profiles:
        candidate_model = configured_models.get(candidate_profile)
        if (
            isinstance(candidate_model, str)
            and candidate_model.strip()
            and candidate_model.strip() != model.strip()
        ):
            fallback_model = candidate_model
            fallback_profile = candidate_profile
            break
    bounded_concurrency = concurrency_limit if isinstance(concurrency_limit, int) and not isinstance(concurrency_limit, bool) else 1
    bounded_concurrency = max(1, min(8, bounded_concurrency))
    item_count = max(2, min(8, bounded_concurrency * 2))
    scenario_inputs = {
        "model": model,
        "profile": scenario_profile,
        "items": [
            {
                "id": f"t12-{name}-{index + 1}",
                "tenant": f"t12-tenant-{index % 2 + 1}",
                "prompt": 'Return exactly the JSON object {"answer":"READY"} and no extra text.',
            }
            for index in range(item_count)
        ],
        "max_tokens": 32,
        "max_concurrency": bounded_concurrency,
        "deadline_ms": 30_000,
        "cancel_after_ms": 100,
        "fallback_model": fallback_model,
        "fallback_profile": fallback_profile,
        "expected": {"answer": "READY"},
        "quality_floor_pct": quality_floor_pct,
        "source_max_tokens": 2,
        "fallback_max_tokens": 32,
        "overload_count": item_count,
    }
    if name == "batch":
        scenario_inputs["failure_probe_item_id"] = f"t12-{name}-{item_count}"
    if name == "fallback":
        scenario_inputs["max_tokens"] = 64
        scenario_inputs["fallback_max_tokens"] = 64

    contract = {
        "scenario": name,
        "required_fields": list(_T12_SCENARIO_FIELDS[name]),
        "concurrency_limit": concurrency_limit,
        "quality_floor_pct": quality_floor_pct,
        "scenario_inputs": scenario_inputs,
    }
    try:
        result = run_scenario(name=name, contract=contract)
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__)
        return report
    if not isinstance(result, dict) or result.get("success") is False:
        error_type = result.get("error_type") if isinstance(result, dict) else None
        if not isinstance(error_type, str) or not error_type.isidentifier():
            error_type = "invalid_scenario_result"
        missing_fields = result.get("missing_fields") if isinstance(result, dict) else None
        safe_missing = [
            field for field in missing_fields
            if isinstance(field, str) and field and len(field) <= 128
        ] if isinstance(missing_fields, list) else []
        report.update(status="failed", error_type=error_type)
        if safe_missing:
            report["missing_fields"] = sorted(set(safe_missing))
        return report

    allowed_fields = set(_T12_SCENARIO_FIELDS[name])
    measurements = {key: result[key] for key in allowed_fields if key in result}
    receipt_id = result.get("receipt_id")
    missing = [key for key in _T12_SCENARIO_FIELDS[name] if key not in measurements]
    passed = False
    if not missing and name == "scheduler":
        batch_size = _t12_number(measurements["batch_size"])
        batch_item_count = _t12_number(measurements["batch_item_count"])
        vram_budget = _t12_number(measurements["vram_budget_bytes"])
        vram_available = _t12_number(measurements["vram_available_bytes"])
        vram_required = _t12_number(measurements["vram_required_bytes"])
        vram_admission_budget = _t12_number(measurements["vram_admission_budget_bytes"])
        vram_incremental_required = _t12_number(measurements["vram_incremental_required_bytes"])
        passed = (
            _t12_number(measurements["queue_age_ms"]) is not None
            and _t12_number(measurements["fairness_wait_ms"]) is not None
            and isinstance(measurements["bucket_id"], str) and bool(measurements["bucket_id"])
            and batch_size is not None and batch_size > 0
            and batch_item_count is not None and batch_size <= batch_item_count
            and _t12_number(measurements["prefill_tokens"]) is not None
            and measurements["vram_admission"] in (True, "admitted")
            and vram_budget is not None
            and vram_available is not None
            and vram_required is not None and vram_required > 0
            and vram_available <= vram_budget
            and vram_required <= vram_budget
            and vram_admission_budget is not None
            and vram_incremental_required is not None
            and vram_incremental_required <= vram_admission_budget
            and vram_required <= vram_admission_budget
            and measurements["vram_estimate_source"] in {"measured", "configured", "resident", "mixed"}
        )
    elif not missing and name == "batch":
        statuses = measurements["item_statuses"]
        failures = sum(status in ("failed", "error") for status in statuses) if isinstance(statuses, list) else -1
        successes = sum(status in ("success", "succeeded") for status in statuses) if isinstance(statuses, list) else 0
        passed = (
            isinstance(measurements["input_item_ids"], list)
            and measurements["input_item_ids"] == measurements["result_item_ids"]
            and isinstance(statuses, list)
            and len(statuses) == len(measurements["input_item_ids"])
            and all(status in {"success", "succeeded", "failed", "error"} for status in statuses)
            and _t12_number(measurements["partial_failure_count"]) == failures
            and successes > 0
            and failures > 0
            and isinstance(measurements["failure_probe_item_id"], str)
            and measurements["failure_probe_item_id"] in measurements["input_item_ids"]
            and measurements["failure_probe_item_id"] == scenario_inputs.get("failure_probe_item_id")
            and measurements["failure_probe_observed"] is True
            and statuses[measurements["input_item_ids"].index(measurements["failure_probe_item_id"])] in {"failed", "error"}
            and _t12_number(measurements["max_concurrency"]) is not None
            and _t12_number(measurements["concurrency_limit"]) is not None
            and measurements["max_concurrency"] <= measurements["concurrency_limit"]
            and measurements["concurrency_limit"] <= concurrency_limit
        )
    elif not missing and name == "deadline":
        stages = measurements["stages"]
        stage_timings = measurements["stage_timings_ms"]
        passed = (
            _t12_number(measurements["deadline_ms"]) is not None
            and isinstance(stages, list)
            and {"queue", "model_load", "generation"}.issubset(
                {stage for stage in stages if isinstance(stage, str)} if isinstance(stages, list) else set()
            )
            and isinstance(stage_timings, dict)
            and all(_t12_number(stage_timings.get(stage)) is not None for stage in ("queue", "model_load", "generation"))
            and measurements["deadline_stage"] in {"queue", "model_load", "generation"}
            and measurements["completed_within_deadline"] is True
            and measurements["request_succeeded"] is True
        )
    elif not missing and name == "overload":
        queued = _t12_number(measurements["queued_count"])
        rejected = _t12_number(measurements["rejected_count"])
        resource_rejected = _t12_number(measurements["resource_rejected_count"])
        passed = (
            measurements["overloaded"] is True
            and _t12_number(measurements["queue_depth"]) is not None
            and queued is not None and queued >= 0
            and rejected is not None and rejected >= 0
            and resource_rejected is not None and resource_rejected >= 0
            and queued + rejected > 0
            and measurements["queue_admission"] in {"queued", "rejected"}
        )
    elif not missing and name == "cancel":
        passed = (
            measurements["cancel_requested"] is True
            and measurements["cancelled"] is True
            and measurements["cleanup_complete"] is True
            and _t12_number(measurements["cancel_to_stop_ms"]) is not None
        )
    elif not missing and name == "fallback":
        floor = _t12_number(measurements["quality_floor_pct"])
        source_quality = _t12_number(measurements["source_quality_pct"])
        fallback_quality = _t12_number(measurements["fallback_quality_pct"])
        source_tokens = _t12_number(measurements["source_max_tokens"])
        fallback_tokens = _t12_number(measurements["fallback_max_tokens"])
        source_model = measurements["source_model"]
        fallback_model = measurements["fallback_model"]
        source_backend = measurements["source_backend"]
        fallback_backend = measurements["fallback_backend"]
        passed = (
            measurements["fallback_used"] is True
            and measurements["fallback_visible"] is True
            and bool(measurements["source_profile"])
            and bool(measurements["fallback_profile"])
            and source_model == scenario_inputs.get("model")
            and fallback_model == scenario_inputs.get("fallback_model")
            and isinstance(source_model, str) and bool(source_model.strip())
            and isinstance(fallback_model, str) and bool(fallback_model.strip())
            and source_model != fallback_model
            and isinstance(source_backend, str) and bool(source_backend.strip())
            and isinstance(fallback_backend, str) and bool(fallback_backend.strip())
            and measurements["quality_floor_met"] is True
            and measurements["source_quality_status"] in {"scored", "no_valid_response"}
            and floor is not None and fallback_quality is not None
            and source_quality is not None and source_quality < floor
            and source_tokens == _t12_number(scenario_inputs.get("source_max_tokens"))
            and fallback_tokens == _t12_number(scenario_inputs.get("fallback_max_tokens"))
            and source_tokens is not None and source_tokens > 0
            and fallback_tokens is not None and source_tokens < fallback_tokens
            and fallback_tokens <= _t12_number(scenario_inputs.get("max_tokens"))
            and floor >= quality_floor_pct
            and fallback_quality >= floor
        )

    receipt_value = receipt_id.strip() if isinstance(receipt_id, str) else ""
    has_receipt = bool(receipt_value)
    passed = passed and has_receipt
    status = "measured" if not missing else "partial"
    report.update(
        status=status,
        contract_passed=passed,
        accepted=bool(live_hardware and passed),
        measurements=measurements,
        missing_fields=missing,
    )
    if passed and has_receipt:
        report["runner_receipt_id"] = receipt_value
    return report


def _run_t12_matrix(
    inference_runner: Any,
    *,
    repetitions: int,
    concurrency_limit: int,
    quality_floor_pct: float = 80.0,
    live_hardware: bool = False,
) -> dict[str, Any]:
    """Collect an opt-in T12 profile matrix; prompts and generated output stay out of records."""
    runner_config = getattr(inference_runner, "config", {})
    runner_config = runner_config if isinstance(runner_config, dict) else {}
    configured_models = runner_config.get("models", {})
    configured_models = configured_models if isinstance(configured_models, dict) else {}
    profile_configs = runner_config.get("profile_configs", runner_config.get("profiles", {}))
    profile_configs = profile_configs if isinstance(profile_configs, dict) else {}
    hardware, hardware_fingerprint = _t12_hardware_identity(runner_config.get("_hardware"))
    cases_by_task_role = {
        profile: [case["case_id"] for case in cases]
        for profile, cases in _T12_PROFILE_CORPUS.items()
    }
    corpus_fingerprint = _t12_fingerprint({
        profile: [
            {key: case[key] for key in ("case_id", "prompt", "num_tokens", "evidence_paths", "expected")}
            for case in cases
        ]
        for profile, cases in _T12_PROFILE_CORPUS.items()
    })
    task_roles: dict[str, Any] = {}

    for profile, cases in _T12_PROFILE_CORPUS.items():
        model_key = profile if profile in configured_models else _T12_PROFILE_MODEL_KEYS.get(profile, profile)
        model = configured_models.get(model_key)
        if not isinstance(model, str) or not model.strip():
            task_roles[profile] = {
                "status": "not_configured", "accepted": False, "contract_passed": False,
                "identity": {
                    "task_role": profile, "hardware_profile": hardware.get("profile"),
                    "model_key": model_key, "model": None, "model_digest": None,
                    "config_fingerprint": None, "hardware_fingerprint": hardware_fingerprint,
                },
                "quality": {"status": "not_measured", "score_pct": None, "sample_count": 0},
                "metrics": {name: _summarize_t12_metric(name, []) for name in _T12_PROFILE_METRICS},
                "missing_acceptance": ["profile_model_not_configured"],
                "samples": [],
            }
            continue

        profile_config = profile_configs.get(profile, profile_configs.get(model_key, {}))
        config_fingerprint = _t12_fingerprint({
            "task_role": profile, "model_key": model_key, "model": model, "config": profile_config,
        })
        samples: list[dict[str, Any]] = []
        metric_samples: dict[str, list[float]] = {name: [] for name in _T12_PROFILE_METRICS}
        quality_scores: list[float] = []
        load_event_count = 0
        reuse_event_count = 0
        event_observations = 0
        quality_evaluator_ids: list[str] = []
        quality_diagnostic_samples = 0
        routed_profiles: list[str] = []
        reported_models: list[str] = []
        model_digests: list[str] = []
        deadline_stage_counts: dict[str, int] = {}
        admission_counts = {"admitted": 0, "rejected": 0, "unknown": 0}
        boundary_peak_samples = 0
        peak_scope_counts: dict[str, int] = {}
        switch_event_count = 0
        switch_success_count = 0
        eviction_count_total = 0
        switch_vram_delta_samples: list[float] = []
        switch_duration_samples: list[float] = []
        switch_vram_before_samples: list[float] = []
        switch_vram_after_samples: list[float] = []
        failed_runs = 0

        for case in cases:
            for repetition in range(repetitions):
                call_started = time.perf_counter()
                try:
                    run_t12_case = getattr(inference_runner, "run_t12_case", None)
                    if callable(run_t12_case):
                        result = run_t12_case(
                            task=profile, model=model, prompt=case["prompt"],
                            num_tokens=case["num_tokens"], expected=case["expected"],
                            evidence_paths=case["evidence_paths"],
                        )
                    else:
                        result = inference_runner.run(
                            model=model, prompt=case["prompt"], num_tokens=case["num_tokens"],
                        )
                    if not isinstance(result, dict) or result.get("success") is not True:
                        failed_runs += 1
                        failure_code = result.get("failure_code") if isinstance(result, dict) else None
                        if not isinstance(failure_code, str) or not failure_code.isidentifier():
                            failure_code = "runner_reported_failure"
                        failure_sample: dict[str, Any] = {
                            "case_id": case["case_id"], "repetition": repetition,
                            "status": "failed", "error_type": failure_code,
                        }
                        diagnostics: dict[str, Any] = {}
                        if isinstance(result, dict):
                            load_event = result.get("model_load_event")
                            reuse_event = result.get("model_reuse_event")
                            if isinstance(load_event, bool) and isinstance(reuse_event, bool):
                                event_observations += 1
                                load_event_count += int(load_event)
                                reuse_event_count += int(reuse_event)
                            admission = result.get("vram_admitted")
                            if admission is True or admission == "admitted":
                                admission_counts["admitted"] += 1
                            elif admission is False or admission == "rejected":
                                admission_counts["rejected"] += 1
                            else:
                                admission_counts["unknown"] += 1
                            diagnostic_fields = (
                                *_T12_PROFILE_METRICS,
                                "vram_available_bytes", "vram_admission_budget_bytes",
                                "vram_incremental_required_bytes",
                            )
                            for field in diagnostic_fields:
                                value = result.get(field)
                                if _t12_number(value) is not None:
                                    diagnostics[field] = value
                            vram_admitted = result.get("vram_admitted")
                            if isinstance(vram_admitted, bool) or (
                                isinstance(vram_admitted, str)
                                and vram_admitted in {"admitted", "rejected"}
                            ):
                                diagnostics["vram_admitted"] = vram_admitted
                            estimate_source = result.get("vram_estimate_source")
                            if isinstance(estimate_source, str) and estimate_source in {
                                "measured", "configured", "resident", "mixed", "unknown",
                            }:
                                diagnostics["vram_estimate_source"] = estimate_source
                        if diagnostics:
                            failure_sample["diagnostics"] = diagnostics
                        samples.append(failure_sample)
                        continue
                except Exception as exc:
                    failed_runs += 1
                    samples.append({
                        "case_id": case["case_id"], "repetition": repetition,
                        "status": "failed", "error_type": type(exc).__name__,
                    })
                    continue
                outer_elapsed_ms = max(0.0, (time.perf_counter() - call_started) * 1000.0)
                elapsed_ms = _t12_number(result.get("end_to_end_latency_ms"))
                if elapsed_ms is None:
                    elapsed_ms = outer_elapsed_ms
                routed_profile = result.get("routed_profile", result.get("profile"))
                if isinstance(routed_profile, str):
                    routed_profiles.append(routed_profile)
                reported_model = result.get("model")
                normalized_reported_model = (
                    reported_model.strip()
                    if isinstance(reported_model, str) and reported_model.strip()
                    else None
                )
                if normalized_reported_model is not None:
                    reported_models.append(normalized_reported_model)
                model_digest = _normalize_model_digest(result.get("model_digest"))
                if model_digest is not None:
                    model_digests.append(model_digest)
                reported_score = _t12_number(result.get("quality_score_pct"))
                evaluator_id = result.get("quality_evaluator_id")
                if reported_score is not None and reported_score <= 100.0 and (
                    not live_hardware or evaluator_id == _T12_QUALITY_EVALUATOR_ID
                ):
                    score = reported_score
                    quality_scores.append(score)
                else:
                    score = None
                if isinstance(evaluator_id, str) and evaluator_id.strip():
                    quality_evaluator_ids.append(evaluator_id.strip())
                if all(isinstance(result.get(name), bool) for name in _T12_QUALITY_DIAGNOSTIC_FIELDS):
                    quality_diagnostic_samples += 1

                row: dict[str, Any] = {
                    "case_id": case["case_id"], "repetition": repetition, "status": "measured",
                    "task_role": profile, "routed_profile": routed_profile,
                    "model": normalized_reported_model,
                    "model_digest": model_digest,
                    "quality_score_pct": score,
                    "structured_json_valid": result.get("structured_json_valid") if isinstance(result.get("structured_json_valid"), bool) else None,
                    "quality_schema_pass": result.get("quality_schema_pass") if isinstance(result.get("quality_schema_pass"), bool) else None,
                    "quality_expected_match": result.get("quality_expected_match") if isinstance(result.get("quality_expected_match"), bool) else None,
                    "quality_paths_grounded": result.get("quality_paths_grounded") if isinstance(result.get("quality_paths_grounded"), bool) else None,
                    "config_fingerprint": config_fingerprint,
                    "hardware_fingerprint": hardware_fingerprint,
                }
                values = {
                    "ttft_ms": _t12_number(result.get("ttft_ms")),
                    "end_to_end_latency_ms": elapsed_ms,
                    "tokens_per_second": _t12_number(result.get("tokens_per_second")),
                    "load_duration_ms": _t12_number(result.get("load_duration_ms")),
                    "queue_age_ms": _t12_number(result.get("queue_age_ms")),
                    "queue_wait_ms": _t12_number(result.get("queue_wait_ms")),
                    "prefill_tokens": _t12_number(result.get("prefill_tokens")),
                    "vram_budget_bytes": _t12_number(result.get("vram_budget_bytes")),
                    "vram_required_bytes": _t12_number(result.get("vram_required_bytes")),
                }
                values["deadline_queue_ms"] = _t12_number(result.get("deadline_queue_ms"))
                values["deadline_model_load_ms"] = _t12_number(result.get("deadline_model_load_ms"))
                values["deadline_generation_ms"] = _t12_number(result.get("deadline_generation_ms"))
                direct_peak = _t12_number(result.get("peak_vram_bytes"))
                if direct_peak is None:
                    boundary_values = [
                        value for value in (
                            _vram_usage_bytes(result.get("initial_vram")),
                            _vram_usage_bytes(result.get("final_vram")),
                        ) if value is not None
                    ]
                    peak_vram = float(max(boundary_values)) if boundary_values else None
                    peak_scope = "inference_boundary_samples"
                    boundary_peak_samples += int(peak_vram is not None)
                else:
                    peak_vram = direct_peak
                    peak_scope_value = result.get("peak_vram_scope")
                    peak_scope = peak_scope_value if isinstance(peak_scope_value, str) and peak_scope_value else "runtime_reported_peak"
                values["peak_vram_bytes"] = peak_vram
                row["peak_vram_scope"] = peak_scope
                if peak_vram is not None:
                    peak_scope_counts[peak_scope] = peak_scope_counts.get(peak_scope, 0) + 1
                bucket = result.get("batch_bucket")
                row["batch_bucket"] = bucket if isinstance(bucket, str) else None
                row.update(values)
                for name, value in values.items():
                    if value is not None:
                        metric_samples[name].append(value)

                load_event = result.get("model_load_event")
                reuse_event = result.get("model_reuse_event")
                if isinstance(load_event, bool) and isinstance(reuse_event, bool):
                    event_observations += 1
                    load_event_count += int(load_event)
                    reuse_event_count += int(reuse_event)
                row["model_load_event"] = load_event if isinstance(load_event, bool) else None
                row["model_reuse_event"] = reuse_event if isinstance(reuse_event, bool) else None
                admission = result.get("vram_admitted")
                if admission is True or admission == "admitted":
                    admission_counts["admitted"] += 1
                    row["vram_admission"] = "admitted"
                elif admission is False or admission == "rejected":
                    admission_counts["rejected"] += 1
                    row["vram_admission"] = "rejected"
                else:
                    admission_counts["unknown"] += 1
                    row["vram_admission"] = None
                deadline_stage = result.get("deadline_stage")
                if isinstance(deadline_stage, str):
                    deadline_stage_counts[deadline_stage] = deadline_stage_counts.get(deadline_stage, 0) + 1
                row["deadline_ms"] = _t12_number(result.get("deadline_ms"))
                row["deadline_stage"] = deadline_stage if isinstance(deadline_stage, str) else None
                row["deadline_exceeded"] = result.get("deadline_exceeded") if isinstance(result.get("deadline_exceeded"), bool) else None
                switch_event_id = result.get("switch_event_id")
                row["switch_event_id"] = (
                    switch_event_id
                    if (
                        isinstance(switch_event_id, int)
                        and not isinstance(switch_event_id, bool)
                        and switch_event_id >= 0
                    )
                    else None
                )
                if row["switch_event_id"] is not None:
                    switch_event_count += 1
                switch_success = result.get("model_switch_success")
                row["model_switch_success"] = switch_success if isinstance(switch_success, bool) else None
                if switch_success is True:
                    switch_success_count += 1
                switch_duration = _t12_number(result.get("model_switch_ms"))
                row["model_switch_ms"] = switch_duration
                if switch_duration is not None:
                    switch_duration_samples.append(switch_duration)
                evicted_models = result.get("evicted_models")
                if isinstance(evicted_models, list) and all(isinstance(name, str) for name in evicted_models):
                    row["evicted_models"] = list(evicted_models)
                else:
                    row["evicted_models"] = None
                eviction_count = result.get("eviction_count")
                if isinstance(eviction_count, int) and not isinstance(eviction_count, bool) and eviction_count >= 0:
                    row["eviction_count"] = eviction_count
                    eviction_count_total += eviction_count
                else:
                    row["eviction_count"] = None
                switch_vram_before = result.get("vram_before_bytes")
                switch_vram_after = result.get("vram_after_bytes")
                valid_vram_before = (
                    switch_vram_before
                    if (
                        isinstance(switch_vram_before, int)
                        and not isinstance(switch_vram_before, bool)
                        and switch_vram_before >= 0
                    )
                    else None
                )
                valid_vram_after = (
                    switch_vram_after
                    if (
                        isinstance(switch_vram_after, int)
                        and not isinstance(switch_vram_after, bool)
                        and switch_vram_after >= 0
                    )
                    else None
                )
                row["vram_before_bytes"] = valid_vram_before
                row["vram_after_bytes"] = valid_vram_after
                if valid_vram_before is not None:
                    switch_vram_before_samples.append(float(valid_vram_before))
                if valid_vram_after is not None:
                    switch_vram_after_samples.append(float(valid_vram_after))
                if valid_vram_before is not None and valid_vram_after is not None:
                    switch_vram_delta_samples.append(float(valid_vram_after - valid_vram_before))
                samples.append(row)

        expected_count = sum(len(cases) for cases in (_T12_PROFILE_CORPUS[profile],)) * repetitions
        missing: list[str] = []
        if failed_runs or len(samples) != expected_count:
            missing.append("profile_runs_incomplete")
        if live_hardware and hardware.get("profile") not in {"integrated", "balanced", "high", "max"}:
            missing.append("active_hardware_profile_missing_or_invalid")
        if len(quality_scores) != expected_count:
            missing.append("live_quality_scores_missing")
        if len(quality_evaluator_ids) != expected_count or len(set(quality_evaluator_ids)) != 1:
            missing.append("quality_evaluator_identity_missing_or_inconsistent")
        if live_hardware and quality_diagnostic_samples != expected_count:
            missing.append("quality_diagnostics_missing")
        if live_hardware and (
            not callable(getattr(inference_runner, "run_t12_case", None))
            or set(quality_evaluator_ids) != {_T12_QUALITY_EVALUATOR_ID}
        ):
            missing.append("trusted_structured_evaluator_required")
        if quality_scores and any(score < quality_floor_pct for score in quality_scores):
            missing.append("quality_floor_not_met")
        if len(model_digests) != expected_count or len(set(model_digests)) != 1:
            missing.append("model_digest_missing_or_inconsistent")
        if len(routed_profiles) != expected_count or any(route != model_key for route in routed_profiles):
            missing.append("profile_route_missing_or_mismatched")
        if len(reported_models) != expected_count or any(
            actual.casefold() != model.casefold() for actual in reported_models
        ):
            missing.append("actual_model_missing_or_mismatched")
        if event_observations != expected_count:
            missing.append("load_reuse_events_missing")
        if boundary_peak_samples:
            missing.append("peak_vram_is_boundary_only")
        for name in _T12_PROFILE_METRICS:
            if len(metric_samples[name]) != expected_count:
                missing.append(f"{name}_missing")
        if admission_counts["unknown"]:
            missing.append("vram_admission_missing")
        if len(deadline_stage_counts) == 0 or any(
            not isinstance(sample.get("deadline_ms"), float)
            or sample.get("deadline_stage") not in {"queue", "model_load", "generation"}
            or not isinstance(sample.get("deadline_exceeded"), bool)
            for sample in samples if sample.get("status") == "measured"
        ):
            missing.append("deadline_stage_metrics_missing")

        profile_report = {
            "status": "partial" if failed_runs or missing else "measured",
            "contract_passed": not missing,
            "accepted": bool(live_hardware and not missing),
            "identity": {
                "task_role": profile, "hardware_profile": hardware.get("profile"),
                "model_key": model_key, "model": model,
                "model_digest": model_digests[0] if len(model_digests) == expected_count and len(set(model_digests)) == 1 else None,
                "config_fingerprint": config_fingerprint,
                "hardware_fingerprint": hardware_fingerprint,
            },
            "quality": {
                "status": "measured" if len(quality_scores) == expected_count else ("partial" if quality_scores else "not_measured"),
                "corpus_id": "t12-live-quality-v1",
                "case_ids": [case["case_id"] for case in cases],
                "score_pct": round(sum(quality_scores) / len(quality_scores), 3) if quality_scores else None,
                "sample_count": len(quality_scores), "quality_floor_pct": quality_floor_pct,
                "passed_count": sum(score >= quality_floor_pct for score in quality_scores),
                "evaluator_id": quality_evaluator_ids[0] if len(quality_evaluator_ids) == expected_count and len(set(quality_evaluator_ids)) == 1 else None,
            },
            "metrics": {name: _summarize_t12_metric(name, values) for name, values in metric_samples.items()},
            "events": {
                "model_load_count": load_event_count,
                "model_reuse_count": reuse_event_count,
                "observed_run_count": event_observations,
                "vram_admission_counts": admission_counts,
                "model_switch_count": switch_event_count,
                "model_switch_success_count": switch_success_count,
                "eviction_count_total": eviction_count_total,
            },
            "lifecycle_metrics": {
                "model_switch_ms": _summarize_t12_metric("model_switch_ms", switch_duration_samples),
                "switch_vram_before_bytes": _summarize_t12_metric("switch_vram_before_bytes", switch_vram_before_samples),
                "switch_vram_after_bytes": _summarize_t12_metric("switch_vram_after_bytes", switch_vram_after_samples),
                "switch_vram_delta_bytes": _summarize_t12_signed_metric(
                    "switch_vram_delta_bytes", switch_vram_delta_samples,
                ),
            },
            "deadline_stage_counts": deadline_stage_counts,
            "peak_vram_scope": (
                next(iter(peak_scope_counts)) if len(peak_scope_counts) == 1
                else "mixed" if peak_scope_counts
                else "unmeasured"
            ),
            "missing_acceptance": sorted(set(missing)),
            "samples": samples,
        }
        task_roles[profile] = profile_report

    scenarios = {
        name: _t12_scenario_report(
            inference_runner, name, concurrency_limit=concurrency_limit,
            quality_floor_pct=quality_floor_pct, live_hardware=live_hardware,
        )
        for name in _T12_SCENARIO_FIELDS
    }
    contract_passed = (
        all(task_role.get("contract_passed") is True for task_role in task_roles.values())
        and all(scenario.get("contract_passed") is True for scenario in scenarios.values())
    )
    accepted = bool(live_hardware and contract_passed)
    return {
        "run_id": f"t12-{uuid.uuid4().hex}",
        "schema_version": "t12.v1",
        "status": "accepted" if accepted else ("contract_complete_fixture_only" if contract_passed else "incomplete"),
        "live_hardware": live_hardware,
        "contract_passed": contract_passed,
        "accepted": accepted,
        "hardware": hardware,
        "hardware_profile": hardware.get("profile"),
        "corpus": {
            "corpus_id": "t12-live-quality-v1", "fingerprint": corpus_fingerprint,
            "cases_by_task_role": cases_by_task_role,
        },
        "task_roles": task_roles,
        "scenarios": scenarios,
    }


def run_benchmark(
    *,
    state_dir: Path | str,
    scratch_dir: Path | str | None = None,
    file_count: int = 100,
    rag_chunks: int = 1_000,
    repetitions: int = 3,
    light_repetitions: int | None = None,
    paired_repetitions: int | None = None,
    concurrency: tuple[int, ...] = (1, 4),
    full: bool = False,
    inference_runner: Any = None,
    include_inference: bool = False,
    include_t12_matrix: bool = False,
    baseline_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run synthetic stages and persist samples, aggregates, and optional comparison."""
    if file_count < 1 or rag_chunks < 1 or repetitions < 1:
        raise ValueError("file_count, rag_chunks, and repetitions must be positive")
    light_repetitions = repetitions if light_repetitions is None else light_repetitions
    paired_repetitions = repetitions if paired_repetitions is None else paired_repetitions
    if light_repetitions < 1 or paired_repetitions < 1:
        raise ValueError("light_repetitions and paired_repetitions must be positive")
    if not concurrency or any(level < 1 for level in concurrency):
        raise ValueError("concurrency levels must be positive")
    if len(set(concurrency)) != len(concurrency):
        raise ValueError("concurrency levels must be unique")
    if any(level > _MAX_CONCURRENCY for level in concurrency):
        raise ValueError(f"concurrency levels maximum is {_MAX_CONCURRENCY}")
    if max(repetitions, light_repetitions, paired_repetitions) > _MAX_REPETITIONS:
        raise ValueError(f"benchmark repetitions maximum is {_MAX_REPETITIONS}")
    if not full and (file_count > 100 or rag_chunks > 1_000):
        raise ValueError("large sizes require full benchmark opt-in")
    if full and (file_count not in _FULL_FILE_SIZES or rag_chunks not in _FULL_RAG_SIZES):
        raise ValueError("full benchmark sizes must use the documented file and RAG matrices")
    if include_inference and inference_runner is None:
        raise ValueError("inference opt-in requires an explicit benchmark runner")
    if include_t12_matrix and inference_runner is None:
        raise ValueError("T12 profile matrix requires an explicit benchmark runner")

    output_dir = _resolve_outside_repo(Path(state_dir), "state_dir")
    output_dir.mkdir(parents=True, exist_ok=True)
    if scratch_dir is None:
        scratch_path = Path(tempfile.mkdtemp(prefix="local-ai-hub-benchmark-")).resolve()
    else:
        scratch_parent = _resolve_outside_repo(Path(scratch_dir), "scratch_dir")
        scratch_parent.mkdir(parents=True, exist_ok=True)
        scratch_path = Path(tempfile.mkdtemp(prefix="local-ai-hub-benchmark-", dir=scratch_parent)).resolve()
    scratch = scratch_path
    started = time.perf_counter()
    stages: dict[str, Any] = {}
    inference_vram_samples: list[int] = []
    app: Any = None
    server: Any = None
    server_thread: threading.Thread | None = None
    http_server_module: Any = None
    previous_http_app: Any = None
    record: dict[str, Any] | None = None
    record_path: Path | None = None
    cleanup_status: dict[str, Any] = {"status": "not_started"}
    try:
        synthetic: dict[str, Any] = {}

        def setup_synthetic_inputs() -> dict[str, int]:
            files, test_path, corpus_path = _build_synthetic_repo(scratch, file_count, rag_chunks)
            synthetic.update(files=files, test_path=test_path, corpus_path=corpus_path)
            return {"file_count": len(files), "rag_chunk_count": rag_chunks}

        stages["synthetic_setup"] = _measure_stage("synthetic_fixture_generation", setup_synthetic_inputs, 1)
        files = synthetic["files"]
        test_path = synthetic["test_path"]
        corpus_path = synthetic["corpus_path"]

        from local_ai_hub import http_server as http_server_module
        from local_ai_hub.app import LocalAIApp

        app_state_dir = scratch / "hub-state"
        app_config_path = scratch / "hub-config.toml"
        app_config_path.write_text(
            "[server]\n"
            'bind = "127.0.0.1"\n'
            "port = 11497\n"
            f"state_dir = {json.dumps(str(app_state_dir.resolve()))}\n\n"
            "[prewarm]\n"
            "enabled = false\n\n"
            "[observability]\n"
            "enabled = false\n",
            encoding="utf-8",
        )
        previous_http_app = http_server_module.APP
        app = LocalAIApp(str(app_config_path))
        http_server_module.APP = app
        server = http_server_module.LocalAIHTTPServer(
            ("127.0.0.1", 0), http_server_module.Handler,
            max_handlers=max(64, max(concurrency)),
        )
        server_thread = threading.Thread(target=server.serve_forever, name="hub-surface-benchmark-http", daemon=True)
        server_thread.start()

        def require_http(response: _HTTPObservation, expected_status: int, expected_success: bool | None = True) -> _HTTPObservation:
            if response.status != expected_status:
                raise RuntimeError("Hub returned an unexpected HTTP status")
            if expected_success is not None:
                if not isinstance(response.payload, dict) or response.payload.get("success") is not expected_success:
                    raise RuntimeError("Hub returned an unexpected operation result")
            return response

        stages["transport"] = _measure_stage(
            "loopback_tcp_connect_to_Hub_server", lambda: _transport_sample(server), light_repetitions,
        )
        stages["hub_health"] = _measure_stage(
            "GET /health; exact HTTP response body bytes",
            lambda: require_http(_http_request(server, "/health"), 200, None), light_repetitions,
        )
        invalid_context_payload = {
            "root": str(scratch / "repo"), "query": "invalid benchmark probe", "max_tokens": "not-an-integer",
        }

        def invalid_context_request() -> _HTTPObservation:
            response = require_http(
                _http_request(server, "/api/context/pack", invalid_context_payload), 400, False,
            )
            if response.payload.get("terminal") is not True or response.payload.get("retryable") is not False:
                raise RuntimeError("Hub validation contract changed")
            return response

        stages["hub_validation"] = _measure_stage(
            "POST /api/context/pack invalid max_tokens; expected HTTP 400",
            invalid_context_request, paired_repetitions,
        )

        repo_root = scratch / "repo"
        relative_files = [path.relative_to(repo_root).as_posix() for path in files]

        def populate_code_index() -> dict[str, int]:
            result = app.code_index.update_files_batch(str(repo_root), relative_files)
            if result.get("success") is not True:
                raise RuntimeError("Hub CodeIndex did not accept synthetic files")
            return {
                "files_processed": int(result.get("files_processed", 0)),
                "symbols_indexed": int(result.get("symbols", 0)),
            }

        stages["hub_sqlite_index"] = _measure_stage(
            "CodeIndex.update_files_batch persisted to isolated Hub SQLite index",
            populate_code_index, paired_repetitions,
        )

        def sqlite_index_read() -> dict[str, int]:
            connection = app.code_index._connect()
            try:
                symbol_count = int(connection.execute("SELECT COUNT(*) FROM symbols").fetchone()[0])
            finally:
                connection.close()
            return {"symbol_rows": symbol_count}

        stages["hub_sqlite_db_read"] = _measure_stage_regimes(
            "CodeIndex SQLite symbol-row count query",
            lambda _index: sqlite_index_read(), lambda _index: sqlite_index_read(), paired_repetitions,
            definition="Fresh CodeIndex SQLite connections for both groups; no OS cache flush; database contains only synthetic source.",
        )

        def code_index_request(query: str) -> _HTTPObservation:
            payload = {"root": str(repo_root), "query": query, "limit": 10, "include_code": False}
            response = require_http(_http_request(server, "/api/repo/code-index", payload), 200, True)
            if not isinstance(response.payload.get("symbols"), list):
                raise RuntimeError("Hub CodeIndex response has no symbol list")
            return response

        cold_symbol_query = lambda index: code_index_request(f"symbol_0 coldprobe_{index}")
        warm_symbol_query = "symbol_0 warmprobe"
        symbol_response = code_index_request("symbol_0 goldenprobe")
        symbol_payload = symbol_response.payload
        symbol_passed = any(
            isinstance(item, dict) and item.get("name") == "symbol_0"
            for item in symbol_payload.get("symbols", [])
        )
        stages["hub_code_index"] = _measure_stage_regimes(
            "POST /api/repo/code-index; real CodeIndex query and service cache",
            cold_symbol_query,
            lambda _index: code_index_request(warm_symbol_query),
            paired_repetitions,
            warm_prepare=lambda _index: code_index_request(warm_symbol_query),
            definition="Cold group uses a distinct query cache key per sample. Warm group repeats a fixed query pre-seeded outside the timer. No OS cache flush.",
        )

        def context_request(query: str) -> _HTTPObservation:
            payload = {
                "root": str(repo_root), "query": query, "mode": "fast", "max_tokens": 512,
                "guarded": False,
            }
            response = require_http(_http_request(server, "/api/context/pack", payload), 200, True)
            if not isinstance(response.payload.get("context"), str):
                raise RuntimeError("Hub context response has no context text")
            return response

        context_golden_response = context_request("symbol_0 context golden")
        context_passed = (
            context_golden_response.status == 200
            and isinstance(context_golden_response.payload, dict)
            and context_golden_response.payload.get("success") is True
            and isinstance(context_golden_response.payload.get("context"), str)
        )
        warm_context_query = "symbol_0 context warmprobe"
        stages["hub_context_pack"] = _measure_stage_regimes(
            "POST /api/context/pack unguarded fast mode; exact HTTP response body bytes",
            lambda index: context_request(f"symbol_0 context coldprobe_{index}"),
            lambda _index: context_request(warm_context_query),
            paired_repetitions,
            warm_prepare=lambda _index: context_request(warm_context_query),
            definition="Cold group uses a distinct request cache key per sample. Warm group repeats a fixed request pre-seeded outside the timer. No OS cache flush.",
        )

        graph_edges = _call_graph(files[0])
        affected = _affected_tests(test_path, "graph_target")
        retrieval_matches = _retrieve_relevant(corpus_path, "needle")
        generated = "def generated_answer(value: int) -> int:\n    return value + 1\n"
        try:
            generated_tree = ast.parse(generated)
            codegen_ok = any(isinstance(node, ast.FunctionDef) and node.name == "generated_answer" for node in generated_tree.body)
        except SyntaxError:
            codegen_ok = False
        expected_relevant_count = sum(1 for index in range(rag_chunks) if index % 997 == 7)
        synthetic_checks = {
            "symbols": {"passed": "symbol_0" in _ast_index(files), "expected_name": "symbol_0"},
            "graph": {"passed": ("graph_caller", "graph_target") in graph_edges, "expected_edge": ["graph_caller", "graph_target"]},
            "affected_tests": {"passed": "test_graph_target_returns_value" in affected, "expected_test": "test_graph_target_returns_value"},
            "retrieval_relevance": {
                "passed": len(retrieval_matches) == expected_relevant_count,
                "expected_relevant_count": expected_relevant_count,
                "observed_relevant_count": len(retrieval_matches),
            },
            "code_generation": {"passed": codegen_ok, "expected_function": "generated_answer"},
        }
        golden = {
            "symbols": {"passed": symbol_passed, "expected_name": "symbol_0"},
            "context_pack": {"passed": context_passed, "expected": {"http_status": 200, "context": "string", "guarded": False}},
            "graph": {"status": "skipped_unavailable", "expected_edge": ["graph_caller", "graph_target"], "reason": "No real Hub graph endpoint is invoked; AST fixture result is isolated under synthetic_checks."},
            "affected_tests": {"status": "skipped_unavailable", "expected_test": "test_graph_target_returns_value", "reason": "No real Hub affected-tests operation is invoked; fixture result is isolated under synthetic_checks."},
            "retrieval_relevance": {"status": "skipped_unavailable", "expected_relevant_count": expected_relevant_count, "reason": "RAGStore._chunks is measured alone; no Hub retrieval, embedding, or ranking search runs."},
            "code_generation": {"status": "skipped_unavailable", "expected_function": "generated_answer", "reason": "No model-backed code generation runs; AST fixture result is isolated under synthetic_checks."},
            "vision": {"status": "skipped_unavailable", "expected": "structured vision result", "reason": "No vision request or inference backend runs in this benchmark."},
            "speech": {"status": "skipped_unavailable", "expected": "transcription result", "reason": "No speech request or inference backend runs in this benchmark."},
        }

        rag_sample = files[0].read_text(encoding="utf-8")

        def chunk_synthetic_source() -> dict[str, int]:
            return {"chunk_count": len(app.rag._chunks(rag_sample, files[0].name))}

        stages["hub_rag_chunking"] = _measure_stage_regimes(
            "RAGStore._chunks_chunker_only", lambda _index: chunk_synthetic_source(),
            lambda _index: chunk_synthetic_source(), paired_repetitions,
            definition="Direct LocalAIApp RAGStore._chunks calls on one synthetic source file; excludes retrieval, embeddings, reranking, and model inference.",
        )

        def queue_admission_attempt(_value: int) -> tuple[float, str | None]:
            queued_at = time.perf_counter()
            error_type: str | None = None
            try:
                task_id = f"benchmark-{uuid.uuid4().hex}"
                submitted = app.async_jobs.submit(
                    "benchmark", "reason", {"task_id": task_id, "task": "T02 queue admission probe"},
                    dispatch_delay_seconds=30.0,
                )
                if submitted.get("success") is not True or not submitted.get("job_id"):
                    raise RuntimeError("Hub async job admission failed")
                cancelled = app.async_jobs.cancel("benchmark", str(submitted["job_id"]))
                if cancelled.get("success") is not True or cancelled.get("state") != "cancelled":
                    raise RuntimeError("Hub async job was not cancelled before worker service")
            except Exception as exc:
                error_type = type(exc).__name__
            return (time.perf_counter() - queued_at) * 1000.0, error_type

        queue_samples: list[float] = []
        queue_cold_samples: list[float] = []
        queue_warm_samples: list[float] = []
        queue_error_types: set[str] = set()
        queue_error_count = 0
        queue_measurements: dict[str, Any] = {}
        total_admissions = 0
        total_batch_seconds = 0.0
        for level in concurrency:
            level_samples: list[float] = []
            level_errors = 0
            level_batch_seconds = 0.0
            for repetition_index in range(light_repetitions):
                batch_started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=level) as pool:
                    outcomes = list(pool.map(queue_admission_attempt, range(level)))
                batch_seconds = time.perf_counter() - batch_started
                level_batch_seconds += batch_seconds
                total_batch_seconds += batch_seconds
                total_admissions += level
                for elapsed_ms, error_type in outcomes:
                    level_samples.append(elapsed_ms)
                    queue_samples.append(elapsed_ms)
                    (queue_cold_samples if repetition_index == 0 else queue_warm_samples).append(elapsed_ms)
                    if error_type:
                        level_errors += 1
                        queue_error_count += 1
                        queue_error_types.add(error_type)
            queue_measurements[str(level)] = {
                **summarize_samples(level_samples),
                "error_count": level_errors,
                "error_rate_pct": round(level_errors * 100.0 / max(1, len(level_samples)), 3),
                "concurrent_admissions_per_second": round(level * light_repetitions / level_batch_seconds, 3) if level_batch_seconds else None,
                "cold_warm": _cold_warm_summary(level_samples),
            }
        stages["hub_queue_admission"] = {
            "status": "passed" if queue_error_count == 0 else "failed",
            **summarize_samples(queue_samples),
            "samples_ms": queue_samples,
            "samples_by_regime": {"cold": queue_cold_samples, "warm": queue_warm_samples},
            "cold_warm": {
                "cold": summarize_samples(queue_cold_samples),
                "warm": summarize_samples(queue_warm_samples),
                "definition": "Each async job uses delayed dispatch and immediate cancellation; queue returns to empty per sample. Worker service is excluded.",
            },
            "error_count": queue_error_count,
            "error_rate_pct": round(queue_error_count * 100.0 / max(1, len(queue_samples)), 3),
            "error_types": sorted(queue_error_types),
            "http_response_body_bytes": 0,
            "whitespace_token_estimate": 0,
            "response_measurement": "not_applicable_no_http_response",
            "measurement": "async_jobs_submit_cancel_admission_only",
            "concurrent_admissions_per_second": round(total_admissions / total_batch_seconds, 3) if total_batch_seconds else None,
            "by_concurrency": queue_measurements,
        }

        stages["model_load"] = _skipped_stage("not requested; runtime load time is not inferred")
        stages["inference"] = _skipped_stage("not requested")
        inference_model_digest: str | None = None
        if include_inference:
            inference_load_samples: list[float] = []
            inference_model_digests: list[str] = []
            inference_metrics: dict[str, list[float]] = {
                "ttft_ms": [], "generation_duration_ms": [], "tokens_per_second": [],
                "tokens_generated": [], "queue_wait_ms": [],
            }

            def run_inference() -> dict[str, Any]:
                result = inference_runner.run(
                    model="", prompt="Return only the word OK.", num_tokens=8,
                )
                if not isinstance(result, dict) or result.get("success") is not True:
                    raise RuntimeError("hardware benchmark runner did not report success")
                model_digest = _normalize_model_digest(result.get("model_digest"))
                if model_digest is not None:
                    inference_model_digests.append(model_digest)
                load_duration_ms = result.get("load_duration_ms")
                if isinstance(load_duration_ms, (int, float)) and math.isfinite(load_duration_ms) and load_duration_ms >= 0:
                    inference_load_samples.append(float(load_duration_ms))
                for snapshot in (result.get("initial_vram"), result.get("final_vram")):
                    vram_bytes = _vram_usage_bytes(snapshot)
                    if vram_bytes is not None:
                        inference_vram_samples.append(vram_bytes)
                observed = {name: result.get(name) for name in inference_metrics}
                for name, value in observed.items():
                    if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
                        inference_metrics[name].append(float(value))
                return {
                    "success": True, **observed, "load_duration_ms": load_duration_ms,
                    "model_digest": result.get("model_digest"),
                }
            stages["inference"] = _measure_stage("explicit_hardware_benchmark_runner", run_inference, paired_repetitions)
            stages["inference"]["reported_metrics"] = {
                name: summarize_samples(values) for name, values in inference_metrics.items()
            }
            stages["inference_queue_wait"] = _skipped_stage(
                "hardware benchmark runner does not report scheduler queue wait",
            )
            if len(inference_load_samples) == paired_repetitions:
                stages["model_load"] = {
                    "status": "passed", **summarize_samples(inference_load_samples),
                    "samples_ms": inference_load_samples,
                    "samples_by_regime": {"cold": inference_load_samples[:1], "warm": inference_load_samples[1:]},
                    "cold_warm": _cold_warm_summary(inference_load_samples),
                    "error_count": 0, "error_rate_pct": 0.0, "error_types": [], "http_response_body_bytes": 0,
                    "whitespace_token_estimate": 0, "response_measurement": "not_applicable_no_http_response",
                    "measurement": "runtime_reported_model_load_duration_ms",
                }
            else:
                stages["model_load"] = _skipped_stage(
                    "runtime did not expose model-load duration for every inference sample",
                )
            if len(inference_model_digests) == paired_repetitions and len(set(inference_model_digests)) == 1:
                inference_model_digest = f"sha256:{inference_model_digests[0]}"

        t12_acceptance = None
        if include_t12_matrix:
            t12_acceptance = _run_t12_matrix(
                inference_runner,
                repetitions=paired_repetitions,
                concurrency_limit=max(concurrency),
                live_hardware=True,
            )

        inference_model = None
        if include_inference:
            model_config = getattr(inference_runner, "config", {})
            configured_models = model_config.get("models", {}) if isinstance(model_config, dict) else {}
            inference_model = configured_models.get("fast_code") if isinstance(configured_models, dict) else None
            if not inference_model and callable(getattr(inference_runner, "_default_model", None)):
                inference_model = inference_runner._default_model()
        config = {
            "file_count": file_count, "rag_chunks": rag_chunks, "repetitions": repetitions,
            "light_repetitions": light_repetitions, "paired_repetitions": paired_repetitions,
            "concurrency": list(concurrency), "full": full, "inference": include_inference,
            "t12_matrix": include_t12_matrix,
            "inference_model": inference_model,
            "hub_app": {"prewarm_enabled": False, "observability_enabled": False},
            "context_mode": "fast",
            "code_index_cache_policy": "distinct cold keys and preseeded fixed warm key",
        }
        machine = {
            "system": platform.system(), "release": platform.release(), "machine": platform.machine(),
            "processor": platform.processor() or None, "cpu_count": os.cpu_count(),
            "total_memory_bytes": _total_memory_bytes(),
        }
        metadata = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "benchmark_scope": (
                "hub_app_synthetic_repo_plus_t12_profile_matrix" if include_t12_matrix else
                "hub_app_synthetic_repo_plus_hardware_inference" if include_inference else
                "hub_app_synthetic_repo"
            ),
            "cold_warm_policy": "Explicit cold query keys and preseeded warm keys for cached Hub routes; uncached operations use fresh calls; no OS cache flush.",
            "revision": _revision(),
            "implementation_fingerprint": _implementation_fingerprint(),
            "config_fingerprint": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
            "hardware_fingerprint": hashlib.sha256(json.dumps(machine, sort_keys=True).encode()).hexdigest(),
            "platform": machine,
            "full": full,
            "synthetic_file_count": file_count,
            "rag_chunk_count": rag_chunks,
            "repetitions": repetitions,
            "stage_repetitions": {"light": light_repetitions, "paired": paired_repetitions},
            "concurrency": list(concurrency),
            "prewarm_enabled": False,
            "observability_enabled": False,
            "http_response_body_bytes_scope": "HTTP response body bytes only; excludes HTTP headers, transfer framing, and transport bytes. Internal operations have no HTTP body.",
            "whitespace_token_estimate": "Whitespace split count from HTTP response bodies; not model tokenization.",
            "matrix_aggregation": "not_performed_single_case_record",
            "baseline_readiness": "per_case",
            "golden_operations": {
                name: golden.get(name, {}).get("passed") is True
                for name in sorted(_REQUIRED_GOLDEN_OPERATIONS)
            },
            "inference": "requested" if include_inference else "skipped_not_requested",
            "t12_matrix": "requested" if include_t12_matrix else "skipped_not_requested",
            "t12_acceptance_status": t12_acceptance.get("status") if t12_acceptance is not None else "not_requested",
            "inference_model": inference_model,
            "inference_model_digest": inference_model_digest,
        }
        metadata["baseline_readiness_reasons"] = _plan_grade_reasons(metadata)
        peak_rss = _peak_rss_bytes()
        peak_vram = max(inference_vram_samples) if inference_vram_samples else None
        resource_usage = {
            "peak_rss_bytes": peak_rss,
            "peak_vram_bytes": peak_vram,
            "availability": {
                "peak_rss_bytes": "measured" if peak_rss is not None else "platform_unavailable",
                "peak_vram_bytes": "measured_at_inference_boundaries" if peak_vram is not None else "not_measured_no_gpu_adapter",
                "peak_vram_scope": "maximum_observed_before_or_after_inference",
                "peak_rss_scope": "process_lifetime_high_water_mark",
            },
        }
        failed_stages = [name for name, stage in stages.items() if stage.get("status") == "failed"]
        success = (
            not failed_stages
            and all(item.get("passed") is True for item in golden.values() if isinstance(item.get("passed"), bool))
            and (t12_acceptance is None or t12_acceptance.get("accepted") is True)
        )
        supported_golden = {
            name: item["passed"] for name, item in golden.items()
            if isinstance(item, dict) and isinstance(item.get("passed"), bool)
        }
        record = {
            "success": success,
            "metadata": metadata,
            "stages": stages,
            "golden": golden,
            "synthetic_checks": synthetic_checks,
            "quality": {
                "score_pct": round(sum(supported_golden.values()) * 100.0 / max(1, len(supported_golden)), 3),
                "supported_check_count": len(supported_golden),
                "checks": supported_golden,
            },
            "resource_usage": resource_usage,
            "failed_stages": failed_stages,
            "total_duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
        if t12_acceptance is not None:
            record["t12_acceptance"] = t12_acceptance
    finally:
        cleanup_errors: list[str] = []
        try:
            if server is not None:
                try:
                    if server_thread is not None and server_thread.is_alive():
                        server.shutdown()
                except Exception as exc:
                    cleanup_errors.append(f"server_shutdown:{type(exc).__name__}")
                finally:
                    try:
                        server.server_close()
                    except Exception as exc:
                        cleanup_errors.append(f"server_close:{type(exc).__name__}")
                    if server_thread is not None and server_thread.is_alive():
                        server_thread.join(timeout=2)
        finally:
            try:
                if app is not None:
                    try:
                        app.close()
                    except Exception as exc:
                        cleanup_errors.append(f"app_close:{type(exc).__name__}")
            finally:
                try:
                    if http_server_module is not None:
                        http_server_module.APP = previous_http_app
                finally:
                    manager = getattr(app, "async_jobs", None) if app is not None else None
                    if manager is not None:
                        with manager._lock:
                            workers = list(manager._workers)
                            dispatchers = list(manager._dispatchers)
                    else:
                        workers = []
                        dispatchers = []
                    cleanup_status = _cleanup_benchmark_scratch(
                        scratch_path,
                        server_thread=server_thread,
                        workers=workers,
                        dispatchers=dispatchers,
                        errors=cleanup_errors,
                    )
                    if record is not None:
                        record["cleanup"] = cleanup_status
                        if cleanup_status["status"] != "cleaned":
                            record["success"] = False
                            record["failed_stages"].append("cleanup")
                        record["total_duration_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
                        if baseline_record is not None:
                            record["comparison"] = compare_records(baseline_record, record)
                        record_name = f"surface-benchmark-{time.time_ns()}.json"
                        record_path = output_dir / record_name
                        temporary_path = output_dir / f".{record_name}.tmp"
                        try:
                            temporary_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                            os.replace(temporary_path, record_path)
                        finally:
                            temporary_path.unlink(missing_ok=True)

    assert record is not None and record_path is not None
    result = {**record, "record_path": str(record_path)}
    if cleanup_status["status"] != "cleaned":
        result["scratch_recovery_path"] = str(scratch_path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True, help="configured state directory; must be outside the repository")
    parser.add_argument("--scratch-dir", type=Path, help="optional external scratch directory; otherwise a temporary directory is used")
    parser.add_argument("--files", type=int, default=100)
    parser.add_argument("--rag-chunks", type=int, default=1_000)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--light-repetitions", type=int, help="transport/queue samples; plan-grade target is 1000")
    parser.add_argument("--paired-repetitions", type=int, help="heavier paired samples; plan-grade target is 30")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 4])
    parser.add_argument("--full", action="store_true", help="allow documented large synthetic size matrix")
    parser.add_argument("--inference", action="store_true", help="explicitly run one synthetic hardware inference")
    parser.add_argument("--t12-matrix", action="store_true", help="explicitly run T12 profile, quality, and scenario measurements")
    parser.add_argument("--config", type=Path, help="Hub config required by --inference or --t12-matrix")
    parser.add_argument("--compare-with", type=Path, help="compare against a previous benchmark JSON record")
    args = parser.parse_args(argv)
    app = None
    try:
        inference_runner = None
        baseline_record = None
        if args.compare_with is not None:
            if args.compare_with.stat().st_size > 10_000_000:
                raise ValueError("baseline record exceeds 10 MB limit")
            baseline_record = json.loads(args.compare_with.read_text(encoding="utf-8"))
            if not isinstance(baseline_record, dict):
                raise ValueError("baseline record must contain a JSON object")
        if args.inference or args.t12_matrix:
            if args.config is None:
                raise ValueError("--inference and --t12-matrix require --config")
            from local_ai_hub.app import LocalAIApp

            app = LocalAIApp(str(args.config))
            inference_runner = app.benchmark_runner
            configured_state = Path(inference_runner.benchmarks_path).parent.resolve()
            if configured_state != args.state_dir.expanduser().resolve():
                raise ValueError("--state-dir must match the configured Hub state directory for inference")
        result = run_benchmark(
            state_dir=args.state_dir, scratch_dir=args.scratch_dir, file_count=args.files,
            rag_chunks=args.rag_chunks, repetitions=args.repetitions,
            light_repetitions=args.light_repetitions, paired_repetitions=args.paired_repetitions,
            concurrency=tuple(args.concurrency), full=args.full,
            inference_runner=inference_runner, include_inference=args.inference,
            include_t12_matrix=args.t12_matrix,
            baseline_record=baseline_record,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    finally:
        if app is not None:
            app.close()
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    comparison_status = result.get("comparison", {}).get("status", "within_tolerance")
    if not result["success"] or comparison_status in {"regression", "incomparable"}:
        return 1
    return 2 if comparison_status == "inconclusive" else 0


if __name__ == "__main__":
    raise SystemExit(main())
