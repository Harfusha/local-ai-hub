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
_REPO_SOURCE = (_REPO_ROOT / "src").resolve()
sys.path[:] = [
    entry
    for entry in sys.path
    if Path(entry or os.getcwd()).resolve() != _REPO_SOURCE
]
sys.path.insert(0, str(_REPO_SOURCE))
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
    package_root = _REPO_ROOT / "src" / "local_ai_hub"
    tracked_runtime = {
        path.relative_to(_REPO_ROOT).as_posix()
        for path in package_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    } if package_root.is_dir() else set()
    tracked_runtime.update({"pyproject.toml", "tools/benchmark_surfaces.py"})
    digest = hashlib.sha256()
    for relative in sorted(tracked_runtime):
        source_path = _REPO_ROOT / relative
        digest.update(relative.encode("utf-8"))
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


def _queue_probe_failure_category(
    stage: str,
    *,
    response: Any = None,
    exception: Exception | None = None,
) -> str | None:
    if stage not in {"submit", "cancel"}:
        raise ValueError(f"unsupported queue probe stage: {stage}")
    if exception is not None:
        return f"{stage}_exception"
    if not isinstance(response, dict) or response.get("success") is not True:
        return f"{stage}_rejected"
    if stage == "submit":
        return None if response.get("job_id") else "submit_missing_job_id"
    return None if response.get("state") == "cancelled" else "cancel_not_cancelled"


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

    output_dir = _resolve_outside_repo(Path(state_dir), "state_dir")
    output_dir.mkdir(parents=True, exist_ok=True)
    if scratch_dir is None:
        owned_scratch = tempfile.TemporaryDirectory(prefix="local-ai-hub-benchmark-")
    else:
        scratch_parent = _resolve_outside_repo(Path(scratch_dir), "scratch_dir")
        scratch_parent.mkdir(parents=True, exist_ok=True)
        owned_scratch = tempfile.TemporaryDirectory(prefix="local-ai-hub-benchmark-", dir=scratch_parent)
    scratch = Path(owned_scratch.name)
    started = time.perf_counter()
    stages: dict[str, Any] = {}
    inference_vram_samples: list[int] = []
    app: Any = None
    server: Any = None
    server_thread: threading.Thread | None = None
    http_server_module: Any = None
    previous_http_app: Any = None
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
            "enabled = false\n\n"
            "[resilience]\n"
            "watchdog_enabled = false\n\n"
            "[debug_traces]\n"
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

        def queue_admission_attempt(_value: int) -> tuple[float, str | None, str | None]:
            queued_at = time.perf_counter()
            error_type: str | None = None
            error_category: str | None = None
            probe_stage = "submit"
            try:
                task_id = f"benchmark-{uuid.uuid4().hex}"
                submitted = app.async_jobs.submit(
                    "benchmark", "reason", {"task_id": task_id, "task": "T02 queue admission probe"},
                    dispatch_delay_seconds=30.0,
                )
                error_category = _queue_probe_failure_category("submit", response=submitted)
                if error_category:
                    error_type = "RuntimeError"
                else:
                    probe_stage = "cancel"
                    cancelled = app.async_jobs.cancel("benchmark", str(submitted["job_id"]))
                    error_category = _queue_probe_failure_category("cancel", response=cancelled)
                    if error_category:
                        error_type = "RuntimeError"
            except Exception as exc:
                error_type = type(exc).__name__
                error_category = _queue_probe_failure_category(probe_stage, exception=exc)
            return (time.perf_counter() - queued_at) * 1000.0, error_type, error_category

        queue_samples: list[float] = []
        queue_cold_samples: list[float] = []
        queue_warm_samples: list[float] = []
        queue_error_types: set[str] = set()
        queue_error_categories: dict[str, int] = {}
        queue_error_count = 0
        queue_measurements: dict[str, Any] = {}
        total_admissions = 0
        total_batch_seconds = 0.0
        for level in concurrency:
            level_samples: list[float] = []
            level_errors = 0
            level_error_categories: dict[str, int] = {}
            level_batch_seconds = 0.0
            for repetition_index in range(light_repetitions):
                batch_started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=level) as pool:
                    outcomes = list(pool.map(queue_admission_attempt, range(level)))
                batch_seconds = time.perf_counter() - batch_started
                level_batch_seconds += batch_seconds
                total_batch_seconds += batch_seconds
                total_admissions += level
                for elapsed_ms, error_type, error_category in outcomes:
                    level_samples.append(elapsed_ms)
                    queue_samples.append(elapsed_ms)
                    (queue_cold_samples if repetition_index == 0 else queue_warm_samples).append(elapsed_ms)
                    if error_category:
                        level_errors += 1
                        queue_error_count += 1
                        queue_error_categories[error_category] = queue_error_categories.get(error_category, 0) + 1
                        level_error_categories[error_category] = level_error_categories.get(error_category, 0) + 1
                    if error_type:
                        queue_error_types.add(error_type)
            queue_measurements[str(level)] = {
                **summarize_samples(level_samples),
                "error_count": level_errors,
                "error_categories": dict(sorted(level_error_categories.items())),
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
            "error_categories": dict(sorted(queue_error_categories.items())),
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
            "inference_model": inference_model,
            "hub_app": {
                "prewarm_enabled": False,
                "observability_enabled": False,
                "watchdog_enabled": False,
                "debug_traces_enabled": False,
            },
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
            "benchmark_scope": "hub_app_synthetic_repo_plus_hardware_inference" if include_inference else "hub_app_synthetic_repo",
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
            "watchdog_enabled": False,
            "debug_traces_enabled": False,
            "http_response_body_bytes_scope": "HTTP response body bytes only; excludes HTTP headers, transfer framing, and transport bytes. Internal operations have no HTTP body.",
            "whitespace_token_estimate": "Whitespace split count from HTTP response bodies; not model tokenization.",
            "matrix_aggregation": "not_performed_single_case_record",
            "baseline_readiness": "per_case",
            "golden_operations": {
                name: golden.get(name, {}).get("passed") is True
                for name in sorted(_REQUIRED_GOLDEN_OPERATIONS)
            },
            "inference": "requested" if include_inference else "skipped_not_requested",
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
        return {**record, "record_path": str(record_path)}
    finally:
        try:
            if server is not None:
                try:
                    if server_thread is not None and server_thread.is_alive():
                        server.shutdown()
                finally:
                    server.server_close()
                    if server_thread is not None and server_thread.is_alive():
                        server_thread.join(timeout=2)
        finally:
            try:
                if app is not None:
                    app.close()
            finally:
                try:
                    if http_server_module is not None:
                        http_server_module.APP = previous_http_app
                finally:
                    owned_scratch.cleanup()


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
    parser.add_argument("--config", type=Path, help="Hub config required by --inference")
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
        if args.inference:
            if args.config is None:
                raise ValueError("--inference requires --config")
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
