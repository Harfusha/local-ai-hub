"""Opt-in synthetic performance and quality baseline for Local AI Hub surfaces.

The default run is deliberately small and never invokes a model. Large synthetic
matrices and inference require explicit CLI flags; generated data stays in
temporary storage, timing samples/metrics persist under --state-dir.
"""

from __future__ import annotations

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor, wait as wait_futures
from datetime import datetime, timezone
from functools import wraps
import hashlib
from http.server import ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import socket
import tempfile
import threading
import time
import tracemalloc
import uuid
from contextlib import closing
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

if __package__:
    from tools.t02_queue_diagnostics import admission_failure_code, cancellation_failure_code
else:  # Direct script execution puts tools/, not the repository root, on sys.path.
    from t02_queue_diagnostics import admission_failure_code, cancellation_failure_code


_REPO_ROOT = Path(__file__).resolve().parents[1]
_REPO_SOURCE = (_REPO_ROOT / "src").resolve()
sys.path[:] = [
    entry
    for entry in sys.path
    if Path(entry or os.getcwd()).resolve() != _REPO_SOURCE
]
sys.path.insert(0, str(_REPO_SOURCE))
_SOURCE_ROOT = _REPO_SOURCE
_FULL_FILE_SIZES = {100, 10_000, 100_000}
_FULL_RAG_SIZES = {10_000, 100_000}
_MAX_CONCURRENCY = 256
_MAX_REPETITIONS = 1_000
_MAX_MATRIX_RECORD_BYTES = 50_000_000
_DEFAULT_CLI_TIMEOUT_SECONDS = 900.0
_MAX_CLI_TIMEOUT_SECONDS = 3_600.0
_CONCURRENT_REQUEST_BATCH_TIMEOUT_SECONDS = 20.0
_MINIMUM_PAIRED_TAIL_SAMPLES = 1_000
_PLAN_GRADE_CONCURRENCY = {1, 4, 16, 32}
_BENCHMARK_REAPER_WAIT_SECONDS = 0.5
_AsyncThreadGroups = tuple[tuple[threading.Thread, ...], ...]
_RetainedBenchmarkScratch = tuple[
    Any, Any, _AsyncThreadGroups, tuple[threading.Thread, ...], Any,
]
# One retained scratch owner is allowed; the next run reaps it or fails before allocating another.
_BENCHMARK_RUN_LOCK = threading.Lock()
_RETAINED_BENCHMARK_SCRATCH: list[_RetainedBenchmarkScratch] = []
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
_SAMPLE_INDEPENDENCE_PROTOCOL = "runner_verified_cache_epochs_v1"
_SAMPLE_STATELESS_PROTOCOL = "runner_verified_stateless_cases_v1"
_REQUIRED_COMPARISON_STAGES = {
    "transport", "hub_health", "hub_validation", "hub_sqlite_index",
    "hub_sqlite_db_read", "hub_code_index", "hub_context_pack",
    "hub_call_graph_query", "hub_call_graph_callees",
    "hub_rag_batch_index", "hub_rag_search", "hub_rag_fixture_relevance",
    "hub_queue_admission", "hub_rag_chunking", "parent_worktree_seed",
}
_QUEUE_ERROR_TYPES = frozenset({"Exception", "OSError", "RuntimeError", "TimeoutError", "ValueError"})
_QUEUE_STATES = frozenset({
    "queued", "running", "done", "failed", "cancelled", "expired",
    "outcome_unknown", "rejected", "conflict",
})
_QUEUE_REASONS = frozenset({
    "capacity_available", "resource_pressure", "queue_limit",
    "duplicate_active_job", "idempotent_request_replay",
})
_QUEUE_PRESSURE_LEVELS = frozenset({"nominal", "moderate", "high", "critical"})


def _safe_queue_label(value: object, allowed: frozenset[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "unknown"

_REQUIRED_LIGHT_SAMPLE_STAGES = {
    "transport", "hub_health", "hub_validation", "hub_queue_admission",
}
_REQUIRED_PAIRED_COMPARISON_STAGES = _REQUIRED_COMPARISON_STAGES - _REQUIRED_LIGHT_SAMPLE_STAGES


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


def _async_job_thread_groups(app: Any) -> tuple[tuple[threading.Thread, ...], ...]:
    manager = getattr(app, "async_jobs", None)
    if manager is None:
        return ((), (), ())

    def snapshot(handles: Any) -> tuple[threading.Thread, ...]:
        try:
            values = tuple(handles)
        except (RuntimeError, TypeError):
            return ()
        return tuple(value for value in values if isinstance(value, threading.Thread))

    lock = getattr(manager, "_lock", None)
    if lock is None:
        delayed = getattr(manager, "_delayed_dispatch", {})
        delayed_handles = delayed.values() if hasattr(delayed, "values") else ()
        dispatchers = getattr(manager, "_dispatchers", ())
        workers = getattr(manager, "_workers", ())
    else:
        with lock:
            delayed = getattr(manager, "_delayed_dispatch", {})
            delayed_handles = tuple(delayed.values()) if hasattr(delayed, "values") else ()
            dispatchers = tuple(getattr(manager, "_dispatchers", ()))
            workers = tuple(getattr(manager, "_workers", ()))
    return (
        snapshot(delayed_handles),
        snapshot(dispatchers),
        snapshot(workers),
    )


def _benchmark_owned_thread_groups(app: Any) -> _AsyncThreadGroups:
    groups = list(_async_job_thread_groups(app))
    if app is None:
        return tuple(groups)

    app_threads: list[threading.Thread] = []
    for owner, names in (
        (app, ("_prewarm_thread", "_watchdog_thread")),
        (getattr(app, "telemetry", None), ("_thread",)),
        (getattr(app, "preprocessor", None), ("_cpu_thread", "_gpu_thread", "_fs_watcher_thread")),
    ):
        app_threads.extend(
            thread for name in names
            if isinstance(thread := getattr(owner, name, None), threading.Thread)
        )
    groups.append(tuple(app_threads))

    scheduler = getattr(app, "scheduler", None)
    dispatcher = getattr(scheduler, "_dispatcher", None)
    groups.append((dispatcher,) if isinstance(dispatcher, threading.Thread) else ())
    for owner, pool_name in (
        (scheduler, "_executor"),
        (getattr(app, "background_gpu", None), "_executor"),
        (getattr(app, "preprocessor", None), "_cpu_pool"),
    ):
        pool = getattr(owner, pool_name, None)
        try:
            workers = tuple(getattr(pool, "_threads", ()))
        except (RuntimeError, TypeError):
            workers = ()
        groups.append(tuple(thread for thread in workers if isinstance(thread, threading.Thread)))
    return tuple(groups)


def _merge_thread_groups(*snapshots: _AsyncThreadGroups) -> _AsyncThreadGroups:
    group_count = max((len(groups) for groups in snapshots), default=0)
    return tuple(
        tuple(dict.fromkeys(
            thread for groups in snapshots if index < len(groups) for thread in groups[index]
        ))
        for index in range(group_count)
    )


def _http_request_handlers_active(server: Any) -> bool:
    if server is None:
        return False
    stats_reader = getattr(server, "concurrency_stats", None)
    if not callable(stats_reader):
        return True
    try:
        stats = stats_reader()
    except Exception:
        return True
    if not isinstance(stats, dict):
        return True
    active = stats.get("active")
    if not isinstance(active, int) or isinstance(active, bool) or active < 0:
        return True
    return active > 0


def _wait_for_http_request_handlers(server: Any, timeout: float) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    waiter = threading.Event()
    while _http_request_handlers_active(server):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        waiter.wait(min(0.01, remaining))
    return True


def _cleanup_scratch_after_benchmark_threads(
    owned_scratch: tempfile.TemporaryDirectory[str],
    app: Any,
    thread_groups: _AsyncThreadGroups,
    related_threads: tuple[threading.Thread, ...] = (),
    http_server: Any = None,
) -> None:
    current_groups = _benchmark_owned_thread_groups(app)
    retained_groups = _merge_thread_groups(thread_groups, current_groups)
    if related_threads:
        retained_groups = _merge_thread_groups(retained_groups, (related_threads,))
    observed_threads = tuple(thread for group in retained_groups for thread in group)
    if not _http_request_handlers_active(http_server):
        handlers_stopped = True
    else:
        handlers_stopped = _wait_for_http_request_handlers(http_server, _BENCHMARK_REAPER_WAIT_SECONDS)
    if not any(thread.is_alive() for thread in observed_threads) and handlers_stopped:
        owned_scratch.cleanup()
        return

    # Async workers and HTTP handlers lack a guaranteed stop bound; retain scratch without a watcher thread.
    _RETAINED_BENCHMARK_SCRATCH.append(
        (owned_scratch, app, retained_groups, related_threads, http_server),
    )


def _reap_retained_benchmark_scratch() -> None:
    retained: list[_RetainedBenchmarkScratch] = []
    deadline = time.monotonic() + _BENCHMARK_REAPER_WAIT_SECONDS
    current = threading.current_thread()
    for owned_scratch, app, prior_groups, related_threads, http_server in _RETAINED_BENCHMARK_SCRATCH:
        observed_groups = prior_groups
        while True:
            observed_groups = _merge_thread_groups(
                observed_groups, _benchmark_owned_thread_groups(app),
            )
            observed_threads = tuple(dict.fromkeys(
                (*related_threads, *(thread for group in observed_groups for thread in group)),
            ))
            live_threads = tuple(thread for thread in observed_threads if thread.is_alive())
            handlers_active = _http_request_handlers_active(http_server)
            if not live_threads and not handlers_active:
                # A dispatcher can register its worker just before it exits. Confirm the
                # manager snapshot after the parent thread has stopped before deleting files.
                observed_groups = _merge_thread_groups(
                    observed_groups, _benchmark_owned_thread_groups(app),
                )
                observed_threads = tuple(dict.fromkeys(
                    (*related_threads, *(thread for group in observed_groups for thread in group)),
                ))
                if any(thread.is_alive() for thread in observed_threads) or _http_request_handlers_active(http_server):
                    continue
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                observed_groups = _merge_thread_groups(
                    observed_groups, _benchmark_owned_thread_groups(app),
                )
                break
            joinable = False
            for thread in live_threads:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if thread is not current and thread.ident is not None:
                    thread.join(timeout=min(0.05, remaining))
                    joinable = True
            if not joinable:
                threading.Event().wait(min(0.01, remaining))
        observed_threads = tuple(dict.fromkeys(
            (*related_threads, *(thread for group in observed_groups for thread in group)),
        ))
        if any(thread.is_alive() for thread in observed_threads) or _http_request_handlers_active(http_server):
            retained.append((owned_scratch, app, observed_groups, related_threads, http_server))
        else:
            owned_scratch.cleanup()
    _RETAINED_BENCHMARK_SCRATCH[:] = retained
    if retained:
        live_names = sorted({
            thread.name
            for _, _, groups, related_threads, _ in retained
            for thread in (*related_threads, *(thread for group in groups for thread in group))
            if thread.is_alive()
        })
        detail = ", ".join(live_names) if live_names else "active HTTP handler"
        raise RuntimeError(f"benchmark scratch cleanup is still pending: {detail}")


def _serialize_benchmark_runs(
    function: Callable[..., dict[str, Any]],
) -> Callable[..., dict[str, Any]]:
    @wraps(function)
    def guarded(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if not _BENCHMARK_RUN_LOCK.acquire(blocking=False):
            raise RuntimeError("another benchmark run is already in progress")
        try:
            _reap_retained_benchmark_scratch()
            return function(*args, **kwargs)
        finally:
            _BENCHMARK_RUN_LOCK.release()

    return guarded


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


_SAMPLE_IDENTITY_CONTRACT = "benchmark_surfaces.explicit_workload_case_blocks.v1"
_SAMPLE_IDENTITY_RUNNER = "benchmark_surfaces"
_T95_CRITICAL_95 = (
    12.7062047364, 4.30265272975, 3.18244630528, 2.7764451052, 2.57058183564,
    2.44691185114, 2.36462425101, 2.3060041352, 2.26215716274, 2.22813885196,
    2.20098516008, 2.17881282966, 2.16036865646, 2.14478668792, 2.13144954556,
    2.11990529922, 2.10981557783, 2.10092204024, 2.09302405441, 2.08596344727,
    2.07961384473, 2.0738730679, 2.06865761042, 2.06389856163, 2.05953855275,
    2.05552943864, 2.05183051648, 2.0484071418, 2.04522964213, 2.0422724563,
)


def _stable_fingerprint(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _config_fingerprint(config: dict[str, Any]) -> str:
    # Matrix size is a workload dimension, not a runner configuration change.
    stable_config = {
        name: value for name, value in config.items()
        if name not in {"file_count", "rag_chunks"}
    }
    return _stable_fingerprint(stable_config)


def _sample_identity_provenance(workload_fingerprint: str) -> dict[str, str]:
    return {
        "runner": _SAMPLE_IDENTITY_RUNNER,
        "contract": _SAMPLE_IDENTITY_CONTRACT,
        "workload_fingerprint": workload_fingerprint,
    }


def _build_sample_independence_proof(
    *,
    protocol: str,
    workload_fingerprint: str,
    sample_ids_by_regime: dict[str, list[str]],
    cache_epoch_ids_by_regime: dict[str, list[str]],
    preparation_status_by_regime: dict[str, list[str]],
    preparation_receipt_sample_ids_by_regime: dict[str, list[str]],
    preparation_state_fingerprints_by_regime: dict[str, list[str]],
) -> dict[str, Any]:
    return {
        "protocol": protocol,
        "workload_fingerprint": workload_fingerprint,
        "case_set_fingerprint": _stable_fingerprint({
            "workload_fingerprint": workload_fingerprint,
            "sample_ids_by_regime": sample_ids_by_regime,
        }),
        "sample_ids_by_regime": sample_ids_by_regime,
        "preparation_receipt_sample_ids_by_regime": preparation_receipt_sample_ids_by_regime,
        "preparation_state_fingerprints_by_regime": preparation_state_fingerprints_by_regime,
        "cache_epoch_ids_by_regime": cache_epoch_ids_by_regime,
        "preparation_status_by_regime": preparation_status_by_regime,
    }


def _preparation_receipt(
    sample_id: str, preparation_status: str,
) -> dict[str, Any]:
    return {
        "success": True,
        "sample_id": sample_id,
        "preparation_status": preparation_status,
    }


def _preparation_observation(
    sample_id: str,
    preparation_status: str,
    observed_state: dict[str, Any],
) -> dict[str, Any]:
    if not observed_state:
        return {"success": False}
    state_fingerprint = _stable_fingerprint({
        "sample_id": sample_id,
        "preparation_status": preparation_status,
        "observed_state": observed_state,
    })
    return {
        "success": True,
        "sample_id": sample_id,
        "cache_epoch_id": state_fingerprint,
        "preparation_status": preparation_status,
        "observed_state_fingerprint": state_fingerprint,
    }


def _sample_independence_proof_is_valid(stage: dict[str, Any]) -> bool:
    proof = stage.get("sample_independence_proof")
    workload_fingerprint = stage.get("workload_fingerprint")
    sample_ids = stage.get("sample_ids_by_regime")
    if (
        not isinstance(proof, dict)
        or proof.get("protocol") not in {_SAMPLE_INDEPENDENCE_PROTOCOL, _SAMPLE_STATELESS_PROTOCOL}
        or not isinstance(workload_fingerprint, str)
        or not isinstance(sample_ids, dict)
        or set(sample_ids) != {"cold", "warm"}
        or proof.get("workload_fingerprint") != workload_fingerprint
        or proof.get("sample_ids_by_regime") != sample_ids
        or proof.get("preparation_receipt_sample_ids_by_regime") != sample_ids
        or not _has_sample_identity_provenance(
            stage.get("sample_identity_provenance"), workload_fingerprint,
        )
    ):
        return False
    expected_fingerprint = _stable_fingerprint({
        "workload_fingerprint": workload_fingerprint,
        "sample_ids_by_regime": sample_ids,
    })
    if proof.get("case_set_fingerprint") != expected_fingerprint:
        return False

    epoch_ids = proof.get("cache_epoch_ids_by_regime")
    preparation = proof.get("preparation_status_by_regime")
    state_fingerprints = proof.get("preparation_state_fingerprints_by_regime")
    if (
        not isinstance(epoch_ids, dict)
        or set(epoch_ids) != {"cold", "warm"}
        or not isinstance(preparation, dict)
        or set(preparation) != {"cold", "warm"}
        or not isinstance(state_fingerprints, dict)
        or set(state_fingerprints) != {"cold", "warm"}
    ):
        return False
    all_epochs: list[str] = []
    for regime in ("cold", "warm"):
        ids = sample_ids.get(regime)
        epochs = epoch_ids.get(regime)
        statuses = preparation.get(regime)
        fingerprints = state_fingerprints.get(regime)
        if proof.get("protocol") == _SAMPLE_STATELESS_PROTOCOL:
            expected_status = "stateless_case"
        else:
            expected_status = "cold_case_unseen" if regime == "cold" else "warm_exact_case_primed"
        if (
            not isinstance(ids, list)
            or not ids
            or any(not isinstance(value, str) or not value.strip() for value in ids)
            or len(set(ids)) != len(ids)
            or not isinstance(epochs, list)
            or len(epochs) != len(ids)
            or any(not isinstance(value, str) or not value.strip() for value in epochs)
            or (
                proof.get("protocol") == _SAMPLE_INDEPENDENCE_PROTOCOL
                and epochs != fingerprints
            )
            or not isinstance(statuses, list)
            or statuses != [expected_status] * len(ids)
            or not isinstance(fingerprints, list)
            or len(fingerprints) != len(ids)
            or any(
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
                for value in fingerprints
            )
        ):
            return False
        all_epochs.extend(epochs)
    return len(set(all_epochs)) == len(all_epochs)


def _has_sample_identity_provenance(value: Any, workload_fingerprint: str) -> bool:
    return (
        isinstance(value, dict)
        and value.get("runner") == _SAMPLE_IDENTITY_RUNNER
        and value.get("contract") == _SAMPLE_IDENTITY_CONTRACT
        and value.get("workload_fingerprint") == workload_fingerprint
    )


def _contains_identifier(text: str, identifier: str) -> bool:
    pattern = rf"(?<!\w){re.escape(identifier)}(?!\w)"
    return re.search(pattern, text) is not None


def _graph_edge_found(
    result: Any, *, collection: str, caller: str, callee: str,
) -> bool:
    if collection not in {"callers", "callees"} or not isinstance(result, dict) or result.get("success") is not True:
        return False
    edges = result.get(collection)
    return isinstance(edges, list) and any(
        isinstance(edge, dict) and edge.get("caller") == caller and edge.get("callee") == callee
        for edge in edges
    )


def _sample_values_by_id(samples: Any, sample_ids: Any) -> tuple[dict[str, float], list[str], bool]:
    if not isinstance(samples, list) or not isinstance(sample_ids, list):
        return {}, [], False
    valid_ids = [item for item in sample_ids if isinstance(item, str) and item.strip()]
    unique_ids = sorted(set(valid_ids))
    valid = (
        len(samples) == len(sample_ids)
        and len(valid_ids) == len(sample_ids)
        and len(unique_ids) == len(sample_ids)
    )
    if not valid:
        return {}, unique_ids, False
    return {sample_id: float(value) for sample_id, value in zip(sample_ids, samples)}, unique_ids, True


def _paired_delta_pct_by_id(
    baseline_by_id: dict[str, float], candidate_by_id: dict[str, float],
) -> dict[str, float | None]:
    return {
        sample_id: (
            (candidate_by_id[sample_id] - baseline_by_id[sample_id]) / baseline_by_id[sample_id] * 100.0
            if baseline_by_id[sample_id] > 0 else None
        )
        for sample_id in sorted(set(baseline_by_id) & set(candidate_by_id))
    }


def _paired_mean_delta_pct_summary(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    deltas_pct = [
        (candidate - baseline) / baseline * 100.0
        for baseline, candidate in pairs
        if baseline > 0
    ]
    estimate = sum(deltas_pct) / len(deltas_pct) if len(deltas_pct) == len(pairs) and deltas_pct else None
    interval: dict[str, Any] = {
        "low": None,
        "high": None,
        "method": "paired_sample_t_interval",
    }
    unrounded_interval: dict[str, float | None] = {"low": None, "high": None}
    if estimate is not None and len(deltas_pct) >= 2:
        count = len(deltas_pct)
        variance = sum((value - estimate) ** 2 for value in deltas_pct) / (count - 1)
        degrees = count - 1
        if degrees <= len(_T95_CRITICAL_95):
            critical = _T95_CRITICAL_95[degrees - 1]
        else:
            z = 1.959963984540054
            critical = (
                z + (z ** 3 + z) / (4 * degrees)
                + (5 * z ** 5 + 16 * z ** 3 + 3 * z) / (96 * degrees ** 2)
                + (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / (384 * degrees ** 3)
            )
        margin = critical * math.sqrt(max(0.0, variance) / count)
        low = estimate - margin
        high = estimate + margin
        unrounded_interval = {"low": low, "high": high}
        interval = {
            "low": round(low, 3),
            "high": round(high, 3),
            "method": "paired_sample_t_interval",
        }
    return {
        "estimate_pct": round(estimate, 3) if estimate is not None else None,
        "interval_95_pct": interval,
        "interval_95_unrounded_pct": unrounded_interval,
    }


def _interpolated_quantile(sorted_values: list[float], percentile: float) -> float | None:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * percentile / 100.0
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _paired_quantile_delta_pct_summary(
    pairs: list[tuple[float, float]], percentile: float, *, bootstrap_repetitions: int = 2_000,
) -> dict[str, Any]:
    """Estimate paired latency-quantile change and its deterministic bootstrap interval."""
    method = "paired_percentile_bootstrap_95"
    result: dict[str, Any] = {
        "estimate_pct": None,
        "interval_95_pct": {"low": None, "high": None, "method": method},
        "interval_95_unrounded_pct": {"low": None, "high": None},
        "bootstrap_repetitions": bootstrap_repetitions,
        "valid_bootstrap_repetitions": 0,
    }
    if len(pairs) < 2 or any(baseline <= 0 for baseline, _candidate in pairs):
        return result

    baseline_values = sorted(baseline for baseline, _candidate in pairs)
    candidate_values = sorted(candidate for _baseline, candidate in pairs)
    baseline_quantile = _interpolated_quantile(baseline_values, percentile)
    candidate_quantile = _interpolated_quantile(candidate_values, percentile)
    if baseline_quantile is None or baseline_quantile <= 0 or candidate_quantile is None:
        return result
    estimate = (candidate_quantile - baseline_quantile) / baseline_quantile * 100.0
    result["estimate_pct"] = round(estimate, 3)

    if all(pair == pairs[0] for pair in pairs):
        result["valid_bootstrap_repetitions"] = bootstrap_repetitions
        result["interval_95_unrounded_pct"] = {"low": estimate, "high": estimate}
        result["interval_95_pct"] = {
            "low": round(estimate, 3), "high": round(estimate, 3), "method": method,
        }
        return result

    seed_material = json.dumps(pairs, separators=(",", ":"), allow_nan=False).encode("ascii")
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
    rng = random.Random(seed)
    count = len(pairs)
    bootstrap_deltas: list[float] = []
    for _ in range(bootstrap_repetitions):
        sample = [pairs[rng.randrange(count)] for _ in range(count)]
        sampled_baseline = sorted(baseline for baseline, _candidate in sample)
        sampled_candidate = sorted(candidate for _baseline, candidate in sample)
        sampled_baseline_quantile = _interpolated_quantile(sampled_baseline, percentile)
        sampled_candidate_quantile = _interpolated_quantile(sampled_candidate, percentile)
        if sampled_baseline_quantile is None or sampled_baseline_quantile <= 0 or sampled_candidate_quantile is None:
            continue
        bootstrap_deltas.append(
            (sampled_candidate_quantile - sampled_baseline_quantile) / sampled_baseline_quantile * 100.0
        )

    result["valid_bootstrap_repetitions"] = len(bootstrap_deltas)
    if len(bootstrap_deltas) < math.ceil(bootstrap_repetitions * 0.95):
        return result
    bootstrap_deltas.sort()
    low = _interpolated_quantile(bootstrap_deltas, 2.5)
    high = _interpolated_quantile(bootstrap_deltas, 97.5)
    if low is None or high is None:
        return result
    result["interval_95_unrounded_pct"] = {"low": low, "high": high}
    result["interval_95_pct"] = {"low": round(low, 3), "high": round(high, 3), "method": method}
    return result


def _paired_cluster_quantile_delta_pct_summary(
    baseline_by_batch: dict[str, list[float]],
    candidate_by_batch: dict[str, list[float]],
    percentile: float,
    *,
    bootstrap_repetitions: int = 2_000,
) -> dict[str, Any]:
    """Bootstrap request latency quantiles by independent synchronized batch."""
    method = "paired_batch_cluster_percentile_bootstrap_95"
    result: dict[str, Any] = {
        "estimate_pct": None,
        "interval_95_pct": {"low": None, "high": None, "method": method},
        "interval_95_unrounded_pct": {"low": None, "high": None},
        "bootstrap_repetitions": bootstrap_repetitions,
        "valid_bootstrap_repetitions": 0,
        "independent_unit": "synchronized_batch",
    }
    batch_ids = sorted(set(baseline_by_batch) & set(candidate_by_batch))
    if len(batch_ids) < 2:
        return result
    if any(
        not baseline_by_batch[batch_id]
        or len(baseline_by_batch[batch_id]) != len(candidate_by_batch[batch_id])
        for batch_id in batch_ids
    ):
        return result
    baseline_values = [value for batch_id in batch_ids for value in baseline_by_batch[batch_id]]
    candidate_values = [value for batch_id in batch_ids for value in candidate_by_batch[batch_id]]
    if any(
        not isinstance(value, (int, float)) or isinstance(value, bool)
        or not math.isfinite(value) or value < 0
        for value in baseline_values + candidate_values
    ):
        return result
    baseline_quantile = _interpolated_quantile(sorted(baseline_values), percentile)
    candidate_quantile = _interpolated_quantile(sorted(candidate_values), percentile)
    if baseline_quantile is None or baseline_quantile <= 0 or candidate_quantile is None:
        return result
    estimate = (candidate_quantile - baseline_quantile) / baseline_quantile * 100.0
    result["estimate_pct"] = round(estimate, 3)

    paired_batches = [
        (batch_id, baseline_by_batch[batch_id], candidate_by_batch[batch_id])
        for batch_id in batch_ids
    ]
    if all(old == new for _batch_id, old, new in paired_batches):
        result["valid_bootstrap_repetitions"] = bootstrap_repetitions
        result["interval_95_unrounded_pct"] = {"low": estimate, "high": estimate}
        result["interval_95_pct"] = {
            "low": round(estimate, 3), "high": round(estimate, 3), "method": method,
        }
        return result

    seed_material = json.dumps(paired_batches, separators=(",", ":"), allow_nan=False).encode("ascii")
    rng = random.Random(int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big"))
    bootstrap_deltas: list[float] = []
    for _ in range(bootstrap_repetitions):
        sampled_batches = [paired_batches[rng.randrange(len(paired_batches))] for _ in paired_batches]
        sampled_baseline = sorted(value for _batch_id, old, _new in sampled_batches for value in old)
        sampled_candidate = sorted(value for _batch_id, _old, new in sampled_batches for value in new)
        old_quantile = _interpolated_quantile(sampled_baseline, percentile)
        new_quantile = _interpolated_quantile(sampled_candidate, percentile)
        if old_quantile is not None and old_quantile > 0 and new_quantile is not None:
            bootstrap_deltas.append((new_quantile - old_quantile) / old_quantile * 100.0)

    result["valid_bootstrap_repetitions"] = len(bootstrap_deltas)
    if len(bootstrap_deltas) < math.ceil(bootstrap_repetitions * 0.95):
        return result
    bootstrap_deltas.sort()
    low = _interpolated_quantile(bootstrap_deltas, 2.5)
    high = _interpolated_quantile(bootstrap_deltas, 97.5)
    if low is not None and high is not None:
        result["interval_95_unrounded_pct"] = {"low": low, "high": high}
        result["interval_95_pct"] = {"low": round(low, 3), "high": round(high, 3), "method": method}
    return result


def _paired_tail_sample_reasons(
    stages: Any, *, minimum_samples: int | None = _MINIMUM_PAIRED_TAIL_SAMPLES,
    stage_names: set[str] | frozenset[str] | None = None,
) -> list[str]:
    """Check proposed paired-tail quality rule or sample identity only.

    The 1,000-pair threshold is a T20 proposal, not a T02 master-plan requirement.
    """
    reasons: list[str] = []
    if not isinstance(stages, dict):
        return ["paired_tail_stages_missing"]
    required_stages = _REQUIRED_COMPARISON_STAGES if stage_names is None else stage_names
    for stage_name in sorted(required_stages):
        stage = stages.get(stage_name)
        samples_by_regime = stage.get("samples_by_regime") if isinstance(stage, dict) else None
        workload_fingerprint = stage.get("workload_fingerprint") if isinstance(stage, dict) else None
        if (
            not isinstance(workload_fingerprint, str)
            or not _has_sample_identity_provenance(
                stage.get("sample_identity_provenance"), workload_fingerprint,
            )
        ):
            reasons.append(f"paired_tail_sample_identity_missing:{stage_name}")
        for regime in ("cold", "warm"):
            samples = samples_by_regime.get(regime) if isinstance(samples_by_regime, dict) else None
            if not isinstance(samples, list) or not samples:
                if minimum_samples is None:
                    reasons.append(f"paired_tail_samples_missing:{stage_name}:{regime}")
                else:
                    reasons.append(
                        f"paired_tail_samples_below_{minimum_samples}:{stage_name}:{regime}"
                    )
            elif minimum_samples is not None and len(samples) < minimum_samples:
                reasons.append(
                    f"paired_tail_samples_below_{minimum_samples}:{stage_name}:{regime}"
                )
            ids_by_regime = stage.get("sample_ids_by_regime") if isinstance(stage, dict) else None
            sample_ids = ids_by_regime.get(regime) if isinstance(ids_by_regime, dict) else None
            ids_valid = (
                isinstance(samples, list)
                and isinstance(sample_ids, list)
                and len(sample_ids) == len(samples)
                and all(isinstance(sample_id, str) and sample_id.strip() for sample_id in sample_ids)
                and len(set(sample_ids)) == len(sample_ids)
            )
            if not ids_valid:
                reasons.append(f"paired_tail_sample_ids_incomplete:{stage_name}:{regime}")
    return reasons


def _paired_sample_count_reasons(stages: Any, minimum_samples: int) -> list[str]:
    if not isinstance(stages, dict):
        return ["paired_sample_stages_missing"]
    reasons: list[str] = []
    for stage_name in sorted(_REQUIRED_PAIRED_COMPARISON_STAGES):
        stage = stages.get(stage_name)
        samples_by_regime = stage.get("samples_by_regime") if isinstance(stage, dict) else None
        for regime in ("cold", "warm"):
            samples = samples_by_regime.get(regime) if isinstance(samples_by_regime, dict) else None
            if not isinstance(samples, list) or len(samples) < minimum_samples:
                reasons.append(
                    f"paired_tail_samples_below_{minimum_samples}:{stage_name}:{regime}"
                )
    return reasons


def _sample_independence_reasons(
    stages: Any, *, stage_names: set[str] | frozenset[str] | None = None,
) -> list[str]:
    if not isinstance(stages, dict):
        return ["sample_independence_stages_missing"]
    required_stages = _REQUIRED_PAIRED_COMPARISON_STAGES if stage_names is None else stage_names
    reasons: list[str] = []
    for stage_name in sorted(required_stages):
        stage = stages.get(stage_name)
        if not isinstance(stage, dict) or stage.get("sample_independence_status") != "established":
            reasons.append(f"sample_independence_not_established:{stage_name}")
        elif not _sample_independence_proof_is_valid(stage):
            reasons.append(f"sample_independence_proof_invalid:{stage_name}")
    return reasons


def _service_concurrency_reasons(stages: Any, repetitions: int) -> list[str]:
    context_stage = stages.get("hub_context_pack") if isinstance(stages, dict) else None
    measured = context_stage.get("service_concurrency") if isinstance(context_stage, dict) else None
    by_concurrency = measured.get("by_concurrency") if isinstance(measured, dict) else None
    if not isinstance(by_concurrency, dict):
        return ["service_concurrency_measurements_missing"]
    reasons: list[str] = []
    for level in sorted(_PLAN_GRADE_CONCURRENCY):
        record = by_concurrency.get(str(level))
        minimum_requests = max(30, repetitions) * level
        batch_observations_valid = (
            _service_batch_observations(record, level)[2]
            if isinstance(record, dict) else False
        )
        batch_ids = record.get("batch_sample_ids") if isinstance(record, dict) else None
        minimum_batches = max(30, repetitions)
        if (
            not isinstance(record, dict)
            or record.get("status") != "passed"
            or record.get("error_count") != 0
            or record.get("response_measurement") != "exact_http_response_body_bytes"
            or not isinstance(record.get("http_response_body_bytes"), int)
            or record.get("http_response_body_bytes", 0) < 1
            or not isinstance(record.get("request_count"), int)
            or isinstance(record.get("request_count"), bool)
            or record.get("request_count", 0) < minimum_requests
            or not batch_observations_valid
            or not isinstance(batch_ids, list)
            or len(batch_ids) < minimum_batches
        ):
            reasons.append(f"service_concurrency_incomplete:{level}")
    return reasons


def _light_stage_sample_reasons(metadata: Any, stages: Any) -> list[str]:
    repetitions = metadata.get("stage_repetitions") if isinstance(metadata, dict) else None
    target = repetitions.get("light") if isinstance(repetitions, dict) else None
    if not isinstance(target, int) or isinstance(target, bool) or target < 1:
        target = 1_000
    reasons: list[str] = []
    for stage_name in sorted(_REQUIRED_LIGHT_SAMPLE_STAGES):
        stage = stages.get(stage_name) if isinstance(stages, dict) else None
        samples_by_regime = stage.get("samples_by_regime") if isinstance(stage, dict) else None
        total = sum(
            len(samples_by_regime.get(regime, []))
            for regime in ("cold", "warm")
            if isinstance(samples_by_regime, dict)
            and isinstance(samples_by_regime.get(regime), list)
        )
        if total < target:
            reasons.append(f"light_samples_below_{target}:{stage_name}")
    return reasons


def _plan_grade_reasons(metadata: dict[str, Any], stages: Any = None) -> list[str]:
    reasons: list[str] = []
    repetitions = metadata.get("stage_repetitions", {})
    light = repetitions.get("light") if isinstance(repetitions, dict) else None
    comparison = repetitions.get("comparison") if isinstance(repetitions, dict) else None
    if not isinstance(light, int) or isinstance(light, bool) or light < 1_000:
        reasons.append("light_repetitions_below_1000")
    if not isinstance(comparison, int) or isinstance(comparison, bool) or comparison < 30:
        reasons.append("comparison_repetitions_below_30")
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
    if stages is not None:
        reasons.extend(_sample_independence_reasons(stages))
        reasons.extend(_paired_tail_sample_reasons(stages, minimum_samples=None))
        reasons.extend(_light_stage_sample_reasons(metadata, stages))
        comparison_target = (
            comparison if isinstance(comparison, int) and not isinstance(comparison, bool) else 30
        )
        reasons.extend(_paired_sample_count_reasons(stages, comparison_target))
        reasons.extend(_service_concurrency_reasons(stages, comparison_target))
    return reasons


def _normalize_model_digest(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    digest = value[7:] if value.startswith("sha256:") else value
    if len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
        return None
    return digest.lower()


def _comparison_repetition_count(metadata: dict[str, Any]) -> int:
    repetitions = metadata.get("stage_repetitions")
    comparison = repetitions.get("comparison") if isinstance(repetitions, dict) else None
    return comparison if isinstance(comparison, int) and not isinstance(comparison, bool) and comparison > 0 else 0


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


def _code_generation_matches_golden(result: Any) -> bool:
    if not isinstance(result, dict) or result.get("success") is not True:
        return False
    text = result.get("text")
    if not isinstance(text, str) or not text.strip():
        return False
    match = re.fullmatch(r"\s*```(?:python)?\s*\n?(.*?)\n?```\s*", text, flags=re.IGNORECASE | re.DOTALL)
    source = match.group(1) if match else text
    try:
        module = ast.parse(source)
    except SyntaxError:
        return False
    if len(module.body) != 1:
        return False
    functions = [
        node for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "generated_answer"
    ]
    if len(functions) != 1:
        return False
    function = functions[0]
    if (
        isinstance(function, ast.AsyncFunctionDef)
        or len(function.args.args) != 1
        or function.args.posonlyargs
        or function.args.vararg is not None
        or function.args.kwonlyargs
        or function.args.kwarg is not None
        or function.args.defaults
        or function.args.kw_defaults
        or function.args.args[0].arg != "value"
        or not isinstance(function.args.args[0].annotation, ast.Name)
        or function.args.args[0].annotation.id != "int"
        or not isinstance(function.returns, ast.Name)
        or function.returns.id != "int"
        or len(function.body) != 1
        or not isinstance(function.body[0], ast.Return)
        or not isinstance(function.body[0].value, ast.BinOp)
        or not isinstance(function.body[0].value.op, ast.Add)
        or not isinstance(function.body[0].value.left, ast.Name)
        or function.body[0].value.left.id != "value"
        or not isinstance(function.body[0].value.right, ast.Constant)
        or function.body[0].value.right.value != 1
    ):
        return False
    return True


def _vision_matches_golden(result: Any) -> bool:
    if not isinstance(result, dict) or result.get("success") is not True:
        return False
    review = result.get("review")
    summary = review.get("summary") if isinstance(review, dict) else None
    if not isinstance(summary, str):
        return False
    normalized = re.sub(r"[^a-z0-9]+", " ", summary.casefold()).strip()
    return "green" in normalized and "square" in normalized


def _transcription_matches_golden(result: Any, expected_text: str) -> bool:
    if (
        not isinstance(result, dict)
        or result.get("success") is not True
        or result.get("degraded") is True
    ):
        return False
    actual_text = result.get("text")
    if not isinstance(actual_text, str):
        return False
    normalize = lambda value: re.findall(r"[a-z0-9]+", value.casefold())
    expected = normalize(expected_text)
    return bool(expected) and normalize(actual_text) == expected


def _green_square_image_data_url() -> str:
    import base64
    import struct
    import zlib

    width = height = 32
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            inside = 6 <= x < 26 and 6 <= y < 26
            rows.extend((0, 220, 0, 255) if inside else (255, 255, 255, 255))

    def png_chunk(name: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload)) + name + payload
            + struct.pack(">I", zlib.crc32(name + payload) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(bytes(rows)))
        + png_chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _measure_quality_golden(
    operation: Callable[[], Any],
    verifier: Callable[[Any], bool],
    *,
    expected: dict[str, Any],
    measurement: str,
    response_text: Callable[[Any], Any],
    sample_vram: bool = False,
    vram_samples: list[int] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    observed_vram = [
        value for value in ([_sample_dedicated_vram_bytes()] if sample_vram else [])
        if value is not None
    ]
    result: Any = None
    exception_type: str | None = None
    try:
        result = operation()
        passed = verifier(result)
    except Exception as exc:
        passed = False
        exception_type = type(exc).__name__
    if sample_vram:
        after_vram = _sample_dedicated_vram_bytes()
        if after_vram is not None:
            observed_vram.append(after_vram)
        if vram_samples is not None:
            vram_samples.extend(observed_vram)
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    text = response_text(result)
    response_bytes = len(text.encode("utf-8")) if isinstance(text, str) else 0
    response_tokens = len(text.split()) if isinstance(text, str) else 0
    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "expected": expected,
        "measurement": measurement,
        "sample_count": 1,
        "model": result.get("model") if isinstance(result, dict) and isinstance(result.get("model"), str) else None,
        "peak_vram_bytes": max(observed_vram) if observed_vram else None,
        "p50_ms": elapsed_ms,
        "p95_ms": elapsed_ms,
        "p99_ms": elapsed_ms,
        "throughput_per_second": round(1000.0 / elapsed_ms, 3) if elapsed_ms else None,
        "response_bytes": response_bytes,
        "whitespace_token_estimate": response_tokens,
        "response_measurement": "model response text only; excludes HTTP framing and model tokenization",
        "error_count": 0 if passed else 1,
        "error_types": [exception_type or ("golden_mismatch" if isinstance(result, dict) and result.get("success") is True else "operation_failed")]
        if not passed else [],
    }


def _run_model_quality_goldens(
    services: Any,
    *,
    speech_fixture: Path | None,
    speech_expected_text: str | None,
    sample_vram: bool = False,
    vram_samples: list[int] | None = None,
) -> dict[str, dict[str, Any]]:
    code_task = (
        "Write a Python function named generated_answer with signature "
        "generated_answer(value: int) -> int. It must return value + 1. "
        "Return only the function source code."
    )
    code = _measure_quality_golden(
        lambda: services.delegate(
            {"task": code_task, "max_tokens": 160, "temperature": 0.0}, "benchmark",
        ),
        _code_generation_matches_golden,
        expected={"function": "generated_answer", "input": "value: int", "return": "value + 1"},
        measurement="LocalAIServices.delegate over deterministic code-generation task",
        response_text=lambda result: result.get("text") if isinstance(result, dict) else None,
        sample_vram=sample_vram,
        vram_samples=vram_samples,
    )
    vision = _measure_quality_golden(
        lambda: services.vision(
            {
                "image": _green_square_image_data_url(),
                "prompt": "Describe the central shape and its color in English. Use the visible image as evidence.",
                "max_tokens": 256,
            },
            "benchmark",
        ),
        _vision_matches_golden,
        expected={"visible_shape": "square", "visible_color": "green"},
        measurement="LocalAIServices.vision over generated green-square image",
        response_text=lambda result: result.get("response") if isinstance(result, dict) else None,
        sample_vram=sample_vram,
        vram_samples=vram_samples,
    )
    if speech_fixture is None or speech_expected_text is None:
        speech = {
            "status": "skipped_unavailable",
            "expected": {"transcript": "external known-audio fixture required"},
            "error_count": 0,
            "error_types": [],
            "reason": "Provide --speech-fixture and --speech-expected-text for a real local transcription golden.",
        }
    else:
        speech = _measure_quality_golden(
            lambda: services.transcribe({"audio": str(speech_fixture), "model": "whisper"}, "benchmark"),
            lambda result: _transcription_matches_golden(result, speech_expected_text),
            expected={
                "transcript_sha256": hashlib.sha256(speech_expected_text.encode("utf-8")).hexdigest(),
                "word_count": len(speech_expected_text.split()),
            },
            measurement="LocalAIServices.transcribe over caller-provided known-audio fixture",
            response_text=lambda result: result.get("text") if isinstance(result, dict) else None,
            sample_vram=sample_vram,
            vram_samples=vram_samples,
        )
    return {"code_generation": code, "vision": vision, "speech": speech}


def _speech_golden_identity(
    fixture: Path | str | None,
    expected_text: str | None,
) -> dict[str, Any] | None:
    if fixture is None and expected_text is None:
        return None
    if fixture is None or expected_text is None or not expected_text.strip():
        raise ValueError("speech golden requires both an audio fixture and expected transcript")
    resolved = Path(fixture).expanduser().resolve()
    if not resolved.is_file():
        raise ValueError("speech golden audio fixture must be an existing file")
    size = resolved.stat().st_size
    if size < 1 or size > 100_000_000:
        raise ValueError("speech golden audio fixture must be between 1 byte and 100 MB")
    digest = hashlib.sha256()
    with resolved.open("rb") as audio_file:
        for block in iter(lambda: audio_file.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "fixture_sha256": digest.hexdigest(),
        "fixture_size_bytes": size,
        "expected_transcript_sha256": hashlib.sha256(expected_text.encode("utf-8")).hexdigest(),
        "expected_word_count": len(expected_text.split()),
    }


def _stage_speech_golden_fixture(fixture: Path, scratch_dir: Path) -> Path:
    staged = scratch_dir / f"speech-golden{fixture.suffix}"
    if fixture.resolve() == staged.resolve():
        return staged
    shutil.copyfile(fixture, staged)
    return staged


def _benchmark_inference_config(runner: Any) -> str:
    source = getattr(runner, "config", {})
    if not isinstance(source, dict):
        return ""
    sections: list[str] = []
    for section_name, allowed_keys in (
        ("models", None),
        ("ollama", {"base_url", "keep_alive"}),
    ):
        values = source.get(section_name)
        if not isinstance(values, dict):
            continue
        entries: list[str] = []
        for key, value in sorted(values.items(), key=lambda item: str(item[0])):
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
                continue
            if allowed_keys is not None and key not in allowed_keys:
                continue
            if isinstance(value, str):
                encoded = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, bool):
                encoded = "true" if value else "false"
            elif isinstance(value, int):
                encoded = str(value)
            elif isinstance(value, float) and math.isfinite(value):
                encoded = repr(value)
            else:
                continue
            entries.append(f"{key} = {encoded}")
        if entries:
            sections.append(f"[{section_name}]\n" + "\n".join(entries))
    return "\n\n".join(sections)


def _benchmark_inference_server_url(runner: Any) -> str | None:
    source = getattr(runner, "config", {})
    server = source.get("server") if isinstance(source, dict) else None
    url = server.get("ollama_url") if isinstance(server, dict) else None
    return url.strip() if isinstance(url, str) and url.strip() else None


def _service_batch_observations(
    record: dict[str, Any], level: int,
) -> tuple[dict[str, list[float]], dict[str, float], bool]:
    request_samples = record.get("samples_ms")
    request_ids = record.get("sample_ids")
    batch_ids = record.get("batch_sample_ids")
    latency_groups = record.get("request_latency_samples_by_batch_ms")
    request_id_groups = record.get("request_sample_ids_by_batch")
    throughput_samples = record.get("batch_throughput_samples_per_second")
    if not all(isinstance(value, list) for value in (
        request_samples, request_ids, batch_ids, latency_groups, request_id_groups, throughput_samples,
    )):
        return {}, {}, False
    if (
        len(batch_ids) < 1
        or any(not isinstance(value, str) or not value.strip() for value in batch_ids)
        or len(set(batch_ids)) != len(batch_ids)
        or len(latency_groups) != len(batch_ids)
        or len(request_id_groups) != len(batch_ids)
        or len(throughput_samples) != len(batch_ids)
        or len(request_ids) != len(request_samples)
        or any(not isinstance(value, str) or not value.strip() for value in request_ids)
        or len(set(request_ids)) != len(request_ids)
    ):
        return {}, {}, False
    flattened_latencies: list[float] = []
    flattened_request_ids: list[str] = []
    latency_by_batch: dict[str, list[float]] = {}
    throughput_by_batch: dict[str, float] = {}
    for batch_id, latencies, sample_ids, throughput in zip(
        batch_ids, latency_groups, request_id_groups, throughput_samples,
    ):
        batch_prefix = f"context-pack-concurrency:{level}:batch:"
        repetition = batch_id.removeprefix(batch_prefix) if isinstance(batch_id, str) else ""
        expected_request_ids = (
            {f"context-pack-concurrency:{level}:{repetition}:{slot}" for slot in range(level)}
            if repetition.isdecimal() else set()
        )
        if (
            not isinstance(batch_id, str) or not batch_id.strip()
            or not batch_id.startswith(batch_prefix)
            or not expected_request_ids
            or not isinstance(latencies, list) or len(latencies) != level
            or not isinstance(sample_ids, list) or len(sample_ids) != level
            or any(not isinstance(sample_id, str) or not sample_id.strip() for sample_id in sample_ids)
            or set(sample_ids) != expected_request_ids
            or not isinstance(throughput, (int, float)) or isinstance(throughput, bool)
            or not math.isfinite(throughput) or throughput <= 0
            or any(
                not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value) or value < 0
                for value in latencies
            )
        ):
            return {}, {}, False
        latency_by_batch[batch_id] = list(latencies)
        throughput_by_batch[batch_id] = float(throughput)
        flattened_latencies.extend(latencies)
        flattened_request_ids.extend(sample_ids)
    if (
        len(set(flattened_request_ids)) != len(flattened_request_ids)
        or set(flattened_request_ids) != set(request_ids)
        or any(
            not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or value < 0
            for value in request_samples
        )
        or sorted(flattened_latencies) != sorted(request_samples)
    ):
        return {}, {}, False
    return latency_by_batch, throughput_by_batch, True


def _compare_service_concurrency(
    baseline_stages: dict[str, Any],
    candidate_stages: dict[str, Any],
    *,
    regression_tolerance: float,
    minimum_repetitions: int,
) -> dict[str, Any]:
    baseline_context = baseline_stages.get("hub_context_pack")
    candidate_context = candidate_stages.get("hub_context_pack")
    baseline_load = baseline_context.get("service_concurrency") if isinstance(baseline_context, dict) else None
    candidate_load = candidate_context.get("service_concurrency") if isinstance(candidate_context, dict) else None
    baseline_levels = baseline_load.get("by_concurrency") if isinstance(baseline_load, dict) else None
    candidate_levels = candidate_load.get("by_concurrency") if isinstance(candidate_load, dict) else None
    results: dict[str, Any] = {}
    reasons: list[str] = []
    assessments: list[str] = []
    tolerance_pct = regression_tolerance * 100.0

    if not isinstance(baseline_levels, dict) or not isinstance(candidate_levels, dict):
        return {
            "status": "inconclusive",
            "reason": "service concurrency measurements are missing",
            "by_concurrency": results,
        }

    for level in sorted(_PLAN_GRADE_CONCURRENCY):
        key = str(level)
        before, after = baseline_levels.get(key), candidate_levels.get(key)
        if not isinstance(before, dict) or not isinstance(after, dict):
            reasons.append(f"service_concurrency_pair_missing:{level}")
            continue
        old_raw, new_raw = before.get("samples_ms"), after.get("samples_ms")
        old_by_batch, old_throughput_by_batch, old_batches_valid = _service_batch_observations(before, level)
        new_by_batch, new_throughput_by_batch, new_batches_valid = _service_batch_observations(after, level)
        if before.get("status") != "passed" or after.get("status") != "passed" or not old_batches_valid or not new_batches_valid:
            reasons.append(f"service_concurrency_samples_invalid:{level}")
            continue
        before_workload = before.get("workload_fingerprint")
        after_workload = after.get("workload_fingerprint")
        same_workload = (
            isinstance(before_workload, str)
            and bool(before_workload.strip())
            and before_workload == after_workload
            and _has_sample_identity_provenance(before.get("sample_identity_provenance"), before_workload)
            and _has_sample_identity_provenance(after.get("sample_identity_provenance"), after_workload)
        )
        old_batch_ids = set(old_by_batch)
        new_batch_ids = set(new_by_batch)
        paired_ids = sorted(old_batch_ids & new_batch_ids) if same_workload else []
        throughput_pairs = [
            (old_throughput_by_batch[batch_id], new_throughput_by_batch[batch_id])
            for batch_id in paired_ids
        ]
        complete = (
            same_workload
            and old_batch_ids == set(paired_ids)
            and new_batch_ids == set(paired_ids)
        )
        minimum_batches = max(30, minimum_repetitions)
        if len(paired_ids) < minimum_batches:
            reasons.append(f"service_concurrency_batches_below_{minimum_batches}:{level}")
        if not complete:
            reasons.append(f"service_concurrency_batch_identity_incomplete:{level}")

        old_summary, new_summary = summarize_samples(old_raw), summarize_samples(new_raw)
        latency_changes: dict[str, Any] = {}
        for metric in ("p50_ms", "p95_ms", "p99_ms"):
            old_value, new_value = old_summary[metric], new_summary[metric]
            delta_pct = ((new_value - old_value) / old_value * 100.0) if old_value else None
            latency_changes[metric] = {
                "baseline": old_value,
                "candidate": new_value,
                "delta_pct": round(delta_pct, 3) if delta_pct is not None else None,
            }
        quantiles = {
            f"p{percentile}": _paired_cluster_quantile_delta_pct_summary(
                {batch_id: old_by_batch[batch_id] for batch_id in paired_ids},
                {batch_id: new_by_batch[batch_id] for batch_id in paired_ids},
                percentile,
            )
            for percentile in (95, 99)
        }
        quantiles["batch_p50_throughput"] = _paired_quantile_delta_pct_summary(
            throughput_pairs, 50,
        )
        old_throughput = _interpolated_quantile(
            sorted(old_throughput_by_batch[batch_id] for batch_id in paired_ids), 50,
        )
        new_throughput = _interpolated_quantile(
            sorted(new_throughput_by_batch[batch_id] for batch_id in paired_ids), 50,
        )
        throughput_delta = (
            (new_throughput - old_throughput) / old_throughput * 100.0
            if old_throughput is not None and old_throughput > 0 and new_throughput is not None
            else None
        )
        quantile_assessments: list[str] = []
        for metric, summary in quantiles.items():
            interval = summary["interval_95_unrounded_pct"]
            low, high = interval["low"], interval["high"]
            higher_is_better = metric == "batch_p50_throughput"
            if low is None or high is None:
                quantile_assessments.append("inconclusive")
            elif higher_is_better and high < -tolerance_pct:
                quantile_assessments.append("regression")
            elif higher_is_better and low > tolerance_pct:
                quantile_assessments.append("improved")
            elif not higher_is_better and low > tolerance_pct:
                quantile_assessments.append("regression")
            elif not higher_is_better and high < -tolerance_pct:
                quantile_assessments.append("improved")
            elif low >= -tolerance_pct and high <= tolerance_pct:
                quantile_assessments.append("within_tolerance")
            else:
                quantile_assessments.append("inconclusive")
        if not complete or len(paired_ids) < minimum_batches or "inconclusive" in quantile_assessments:
            assessment = "inconclusive"
        elif "regression" in quantile_assessments:
            assessment = "regression"
        elif all(value == "improved" for value in quantile_assessments):
            assessment = "improved"
        else:
            assessment = "within_tolerance"
        assessments.append(assessment)
        results[key] = {
            "status": "passed" if complete and len(paired_ids) >= minimum_batches else "incomplete",
            "concurrency": level,
            "baseline_count": len(old_raw),
            "candidate_count": len(new_raw),
            "independent_unit": "synchronized_batch",
            "paired_count": len(paired_ids),
            "paired_request_count": sum(len(old_by_batch[batch_id]) for batch_id in paired_ids),
            "minimum_paired_batches": minimum_batches,
            "sample_identity_complete": complete,
            "tolerance_assessment": assessment,
            "latency": latency_changes,
            "batch_throughput": {
                "measurement": "requests_per_second_from_batch_wall_time",
                "statistic": "paired_median",
                "baseline": round(old_throughput, 3) if old_throughput is not None else None,
                "candidate": round(new_throughput, 3) if new_throughput is not None else None,
                "delta_pct": round(throughput_delta, 3) if throughput_delta is not None else None,
            },
            "paired_quantile_delta_pct": quantiles,
        }

    if reasons or not results:
        status = "inconclusive"
    elif "regression" in assessments:
        status = "regression"
    elif "inconclusive" in assessments:
        status = "inconclusive"
    elif assessments and all(value == "improved" for value in assessments):
        status = "improved"
    else:
        status = "within_tolerance"
    return {
        "status": status,
        "reason": ";".join(dict.fromkeys(reasons)) if reasons else None,
        "regression_tolerance_pct": round(tolerance_pct, 3),
        "by_concurrency": results,
    }


def compare_records(
    baseline: dict[str, Any], candidate: dict[str, Any], *, regression_tolerance: float = _REGRESSION_TOLERANCE,
) -> dict[str, Any]:
    """Compare only explicitly identified workload case/block samples."""
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
    fingerprint_mismatches = [
        field for field in (
            "benchmark_scope", "workload_fingerprint", "config_fingerprint", "hardware_fingerprint",
        )
        if (
            not isinstance(baseline_meta.get(field), str)
            or not baseline_meta[field].strip()
            or baseline_meta.get(field) != candidate_meta.get(field)
        )
    ]
    if fingerprint_mismatches:
        return {
            "status": "inconclusive",
            "reason": "benchmark workload, configuration, or hardware fingerprint differs or is missing",
            "fingerprint_mismatches": fingerprint_mismatches,
        }
    if not (
        _has_sample_identity_provenance(
            baseline_meta.get("sample_identity_provenance"), baseline_meta["workload_fingerprint"],
        )
        and _has_sample_identity_provenance(
            candidate_meta.get("sample_identity_provenance"), candidate_meta["workload_fingerprint"],
        )
    ):
        return {
            "status": "inconclusive",
            "reason": "workload-runner sample identity provenance is missing or incompatible",
            "fingerprint_mismatches": ["sample_identity_provenance"],
        }
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
    stage_fingerprint_mismatches: list[str] = []
    regime_assessments: list[str] = []
    for name in sorted(set(baseline_stages) & set(candidate_stages)):
        before, after = baseline_stages[name], candidate_stages[name]
        if not isinstance(before, dict) or not isinstance(after, dict):
            incomplete.append(name)
            continue
        before_workload = before.get("workload_fingerprint")
        after_workload = after.get("workload_fingerprint")
        if (
            not isinstance(before_workload, str) or not before_workload.strip()
            or before_workload != after_workload
        ):
            stage_fingerprint_mismatches.append(f"{name}:workload_fingerprint")
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
            if not isinstance(old_values, list) or not isinstance(new_values, list):
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

        before_ids_by_regime = before.get("sample_ids_by_regime")
        after_ids_by_regime = after.get("sample_ids_by_regime")
        identity_provenance_valid = (
            _has_sample_identity_provenance(
                before.get("sample_identity_provenance"), before_workload,
            )
            and _has_sample_identity_provenance(
                after.get("sample_identity_provenance"), after_workload,
            )
        )
        regimes: dict[str, Any] = {}
        stage_regression = False
        for regime in ("cold", "warm"):
            old_raw, new_raw = old_regimes[regime], new_regimes[regime]
            old = [float(value) for value in old_raw]
            new = [float(value) for value in new_raw]
            old_summary, new_summary = summarize_samples(old), summarize_samples(new)
            changes: dict[str, Any] = {}
            for metric in ("p50_ms", "p95_ms", "p99_ms", "throughput_per_second"):
                old_value, new_value = old_summary[metric], new_summary[metric]
                delta_pct = ((new_value - old_value) / old_value * 100.0) if old_value else None
                changes[metric] = {
                    "baseline": old_value, "candidate": new_value,
                    "delta_pct": round(delta_pct, 3) if delta_pct is not None else None,
                }

            old_ids = before_ids_by_regime.get(regime) if isinstance(before_ids_by_regime, dict) else None
            new_ids = after_ids_by_regime.get(regime) if isinstance(after_ids_by_regime, dict) else None
            old_by_id, old_id_values, old_ids_valid = _sample_values_by_id(old_raw, old_ids)
            new_by_id, new_id_values, new_ids_valid = _sample_values_by_id(new_raw, new_ids)
            ids_valid = identity_provenance_valid and old_ids_valid and new_ids_valid
            paired_ids = sorted(set(old_by_id) & set(new_by_id)) if ids_valid else []
            pairs = [(old_by_id[sample_id], new_by_id[sample_id]) for sample_id in paired_ids]
            unmatched_old = sorted(set(old_id_values) - set(paired_ids))
            unmatched_new = sorted(set(new_id_values) - set(paired_ids))
            delta_summary = _paired_mean_delta_pct_summary(pairs)
            interval = delta_summary["interval_95_pct"]
            tolerance_pct = regression_tolerance * 100.0
            quantile_summaries = {
                f"p{percentile}": _paired_quantile_delta_pct_summary(pairs, percentile)
                for percentile in (95, 99)
            }
            quantile_assessments: dict[str, str] = {}
            for metric, summary in quantile_summaries.items():
                low = summary["interval_95_unrounded_pct"]["low"]
                high = summary["interval_95_unrounded_pct"]["high"]
                if low is not None and high is not None and low > tolerance_pct:
                    assessment = "regression"
                elif (
                    low is not None and high is not None
                    and low >= -tolerance_pct and high <= tolerance_pct
                ):
                    assessment = "within_tolerance"
                elif high is not None and high < -tolerance_pct:
                    assessment = "improved"
                else:
                    assessment = "inconclusive"
                quantile_assessments[metric] = assessment
                quantile_summaries[metric]["tolerance_assessment"] = assessment

            sample_identity_complete = ids_valid and not unmatched_old and not unmatched_new
            if not sample_identity_complete:
                interval_assessment = "inconclusive"
            elif "regression" in quantile_assessments.values():
                interval_assessment = "regression"
            elif "inconclusive" in quantile_assessments.values():
                interval_assessment = "inconclusive"
            elif all(value == "improved" for value in quantile_assessments.values()):
                interval_assessment = "improved"
            else:
                interval_assessment = "within_tolerance"
            regime_assessments.append(interval_assessment)
            regime_regression = interval_assessment == "regression"
            stage_regression = stage_regression or regime_regression
            regimes[regime] = {
                "sample_comparison": "paired" if len(pairs) >= 2 else "inconclusive",
                "sample_identity_valid": ids_valid,
                "sample_identity_complete": sample_identity_complete,
                "baseline_count": len(old),
                "candidate_count": len(new),
                "paired_count": len(pairs),
                "unmatched_baseline_count": len(unmatched_old),
                "unmatched_candidate_count": len(unmatched_new),
                "unmatched_baseline_ids": unmatched_old,
                "unmatched_candidate_ids": unmatched_new,
                "regression": regime_regression,
                "tolerance_assessment": interval_assessment,
                "latency": changes,
                "paired_mean_delta_pct": delta_summary["estimate_pct"],
                "paired_mean_delta_pct_interval_95": interval,
                "paired_quantile_delta_pct": quantile_summaries,
            }
        compared[name] = {"regression": stage_regression, **regimes}

    service_concurrency = _compare_service_concurrency(
        baseline_stages,
        candidate_stages,
        regression_tolerance=regression_tolerance,
        minimum_repetitions=min(
            _comparison_repetition_count(baseline_meta),
            _comparison_repetition_count(candidate_meta),
        ),
    )
    if service_concurrency.get("status") == "inconclusive":
        incomplete.append("hub_context_pack.service_concurrency")
    else:
        regime_assessments.append(str(service_concurrency["status"]))

    if incomplete or not compared:
        overall_status = "inconclusive"
    elif any(assessment == "regression" for assessment in regime_assessments):
        overall_status = "regression"
    elif regime_assessments and all(assessment == "within_tolerance" for assessment in regime_assessments):
        overall_status = "within_tolerance"
    elif (
        regime_assessments
        and all(assessment in {"within_tolerance", "improved"} for assessment in regime_assessments)
        and any(assessment == "improved" for assessment in regime_assessments)
    ):
        overall_status = "improved"
    else:
        overall_status = "inconclusive"
    provisional = {
        "status": overall_status,
        "regression_tolerance_pct": round(regression_tolerance * 100.0, 3),
        "baseline_revision": baseline_meta.get("revision"),
        "candidate_revision": candidate_meta.get("revision"),
        "compared_stage_count": len(compared),
        "stages": compared,
        "service_concurrency": service_concurrency,
        "quality": _quality_comparison(baseline, candidate),
    }
    reasons = list(dict.fromkeys(
        _plan_grade_reasons(baseline_meta, baseline.get("stages"))
        + _plan_grade_reasons(candidate_meta, candidate.get("stages"))
    ))
    reasons.extend(f"incomplete_stage:{name}" for name in incomplete)
    if not compared:
        reasons.append("no_complete_compatible_paired_stage_samples")
    if baseline_meta.get("baseline_readiness") != "plan_grade":
        reasons.append("baseline_is_not_aggregated_plan_grade")
    if candidate_meta.get("baseline_readiness") != "plan_grade":
        reasons.append("candidate_is_not_aggregated_plan_grade")
    comparison_target = min(_comparison_repetition_count(baseline_meta), _comparison_repetition_count(candidate_meta))
    paired_stage_minimum = max(30, comparison_target)
    reasons.extend(stage_fingerprint_mismatches)
    for name in compared:
        minimum_samples = paired_stage_minimum if name in _REQUIRED_PAIRED_COMPARISON_STAGES else 1
        for regime in ("cold", "warm"):
            regime_result = compared[name][regime]
            if regime_result["paired_count"] < minimum_samples:
                reasons.append(f"paired_samples_below_{minimum_samples}:{name}:{regime}")
            if not regime_result["sample_identity_complete"]:
                reasons.append(f"paired_sample_identity_incomplete:{name}:{regime}")
            if regime_result["tolerance_assessment"] == "inconclusive" and regime_result["sample_identity_complete"]:
                quantile_intervals = [
                    summary["interval_95_pct"]
                    for summary in regime_result["paired_quantile_delta_pct"].values()
                ]
                if any(interval["low"] is None or interval["high"] is None for interval in quantile_intervals):
                    reasons.append(f"paired_quantile_interval_unavailable:{name}:{regime}")
                else:
                    reasons.append(f"paired_quantile_interval_overlaps_tolerance:{name}:{regime}")
    if reasons:
        result = {
            "status": "inconclusive",
            "reason": ";".join(dict.fromkeys(reasons)),
            "baseline_readiness": baseline_meta.get("baseline_readiness", "smoke_only"),
            "candidate_readiness": candidate_meta.get("baseline_readiness", "smoke_only"),
            "provisional": provisional,
        }
        if stage_fingerprint_mismatches:
            result["fingerprint_mismatches"] = stage_fingerprint_mismatches
        return result
    return provisional


def _matrix_recorded_size_key(metadata: Any) -> tuple[int, int] | None:
    if not isinstance(metadata, dict):
        return None
    file_count = metadata.get("synthetic_file_count")
    rag_chunk_count = metadata.get("rag_chunk_count")
    if (
        not isinstance(file_count, int) or isinstance(file_count, bool)
        or not isinstance(rag_chunk_count, int) or isinstance(rag_chunk_count, bool)
    ):
        return None
    return file_count, rag_chunk_count


def _matrix_case_records(record: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]] | None:
    cases = record.get("cases")
    metadata = record.get("metadata")
    completed_matrix = metadata.get("completed_matrix") if isinstance(metadata, dict) else None
    matrix_goldens = metadata.get("golden_operations") if isinstance(metadata, dict) else None
    if (
        not isinstance(cases, list) or len(cases) != len(_REQUIRED_MATRIX_CASES)
        or not isinstance(completed_matrix, list) or len(completed_matrix) != len(_REQUIRED_MATRIX_CASES)
        or not isinstance(matrix_goldens, dict)
        or any(matrix_goldens.get(name) is not True for name in _REQUIRED_GOLDEN_OPERATIONS)
    ):
        return None
    result: dict[tuple[int, int], dict[str, Any]] = {}
    for item in cases:
        if not isinstance(item, dict):
            return None
        file_count, rag_chunk_count = item.get("file_count"), item.get("rag_chunk_count")
        case_record = item.get("record")
        if (
            isinstance(file_count, int) and not isinstance(file_count, bool)
            and isinstance(rag_chunk_count, int) and not isinstance(rag_chunk_count, bool)
            and isinstance(case_record, dict)
        ):
            key = (file_count, rag_chunk_count)
            if key in result or key not in _REQUIRED_MATRIX_CASES:
                return None
            if _matrix_recorded_size_key(case_record.get("metadata")) != key:
                return None
            result[key] = case_record
        else:
            return None

    completed_keys: set[tuple[int, int]] = set()
    for row in completed_matrix:
        if not isinstance(row, dict):
            return None
        file_count, rag_chunk_count = row.get("file_count"), row.get("rag_chunk_count")
        if (
            not isinstance(file_count, int) or isinstance(file_count, bool)
            or not isinstance(rag_chunk_count, int) or isinstance(rag_chunk_count, bool)
            or row.get("status") != "completed"
        ):
            return None
        key = (file_count, rag_chunk_count)
        if key in completed_keys:
            return None
        case_metadata = result[key].get("metadata") if key in result else None
        case_goldens = case_metadata.get("golden_operations") if isinstance(case_metadata, dict) else None
        row_goldens = row.get("golden_operations")
        if (
            not isinstance(case_goldens, dict)
            or not isinstance(row_goldens, dict)
            or any(
                case_goldens.get(name) is not True or row_goldens.get(name) is not True
                or case_goldens.get(name) != row_goldens.get(name)
                or matrix_goldens.get(name) != row_goldens.get(name)
                for name in _REQUIRED_GOLDEN_OPERATIONS
            )
        ):
            return None
        if (
            "recorded_file_count" in row or "recorded_rag_chunk_count" in row
        ) and (
            row.get("recorded_file_count") != file_count
            or row.get("recorded_rag_chunk_count") != rag_chunk_count
        ):
            return None
        completed_keys.add(key)
    if set(result) != _REQUIRED_MATRIX_CASES or completed_keys != set(result):
        return None
    return result


def compare_matrix_records(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Compare corresponding cases only when both complete matrices are plan-grade."""
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        return {"status": "incomparable", "reason": "matrix records must be JSON objects"}
    baseline_meta, candidate_meta = baseline.get("metadata"), candidate.get("metadata")
    if not isinstance(baseline_meta, dict) or not isinstance(candidate_meta, dict):
        return {"status": "incomparable", "reason": "matrix metadata is missing or malformed"}
    if baseline_meta.get("baseline_readiness") != "plan_grade" or candidate_meta.get("baseline_readiness") != "plan_grade":
        return {
            "status": "inconclusive",
            "reason": "both matrix records must be plan_grade",
            "baseline_reasons": baseline_meta.get("baseline_readiness_reasons", []),
            "candidate_reasons": candidate_meta.get("baseline_readiness_reasons", []),
        }
    old_cases, new_cases = _matrix_case_records(baseline), _matrix_case_records(candidate)
    if old_cases is None or new_cases is None:
        return {
            "status": "incomparable",
            "reason": "matrix cases must have unique keys paired with matching recorded sizes and completed rows",
        }

    gate_fields = (
        "baseline_readiness", "baseline_readiness_reasons", "completed_matrix",
        "stage_repetitions", "concurrency", "full", "inference", "inference_model_digest",
    )

    def with_matrix_gate(case_record: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        case_metadata = dict(case_record.get("metadata", {}))
        for field in gate_fields:
            case_metadata[field] = metadata.get(field)
        return {**case_record, "metadata": case_metadata}

    comparisons: dict[str, Any] = {}
    statuses: list[str] = []
    for key in sorted(_REQUIRED_MATRIX_CASES):
        comparison = compare_records(
            with_matrix_gate(old_cases[key], baseline_meta),
            with_matrix_gate(new_cases[key], candidate_meta),
        )
        comparisons[f"files={key[0]},rag_chunks={key[1]}"] = comparison
        statuses.append(str(comparison.get("status")))
    if any(status == "regression" for status in statuses):
        status = "regression"
    elif statuses and all(status in {"within_tolerance", "improved"} for status in statuses):
        status = "improved" if any(status == "improved" for status in statuses) else "within_tolerance"
    elif any(status == "incomparable" for status in statuses):
        status = "incomparable"
    else:
        status = "inconclusive"
    return {
        "status": status,
        "compared_case_count": sum(
            status in {"within_tolerance", "improved", "regression"}
            for status in statuses
        ),
        "baseline_revision": baseline_meta.get("revision"),
        "candidate_revision": candidate_meta.get("revision"),
        "cases": comparisons,
    }


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
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions < 1:
        raise ValueError("repetitions must be positive")
    samples: list[float] = []
    errors = 0
    http_response_body_bytes = 0
    whitespace_token_estimate = 0
    error_types: set[str] = set()
    error_count_by_phase = {"before_each": 0, "operation": 0}
    response_measurement = "not_applicable_no_http_response"
    for index in range(repetitions):
        started = time.perf_counter()
        phase = "before_each"
        try:
            if before_each is not None:
                before_each(index)
            started = time.perf_counter()
            phase = "operation"
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
            error_count_by_phase[phase] += 1
        samples.append((time.perf_counter() - started) * 1000.0)
    workload_fingerprint = _stable_fingerprint({
        "measurement": name,
        "definition": "first operation invocation is cold; remaining invocations are warm; no OS cache flush",
        "sample_identity_unit": "request_event",
    })
    sample_ids_by_regime = {
        "cold": [f"{name}:request:{index}" for index in range(min(1, len(samples)))],
        "warm": [f"{name}:request:{index}" for index in range(1, len(samples))],
    }
    return {
        "status": "passed" if errors == 0 else "failed",
        **summarize_samples(samples),
        "samples_ms": samples,
        "samples_by_regime": {"cold": samples[:1], "warm": samples[1:]},
        "cold_warm": _cold_warm_summary(samples),
        "error_count": errors,
        "error_rate_pct": round(errors * 100.0 / len(samples), 3) if samples else 0.0,
        "error_types": sorted(error_types),
        "error_count_by_phase": error_count_by_phase,
        "http_response_body_bytes": http_response_body_bytes,
        "whitespace_token_estimate": whitespace_token_estimate,
        "response_measurement": response_measurement,
        "measurement": name,
        "workload_fingerprint": workload_fingerprint,
        "sample_ids_by_regime": sample_ids_by_regime,
        "sample_identity_provenance": _sample_identity_provenance(workload_fingerprint),
        "sample_identity_unit": "request_event",
        "sample_independence_note": "sequential events may share one cache epoch",
        "sample_independence_status": "not_established",
    }


def _measure_stage_regimes(
    name: str,
    cold_operation: Callable[[int], Any],
    warm_operation: Callable[[int], Any],
    repetitions: int,
    *,
    cold_prepare: Callable[[int], Any] | None = None,
    warm_prepare: Callable[[int], Any] | None = None,
    cold_verify: Callable[[int], Any] | None = None,
    warm_verify: Callable[[int], Any] | None = None,
    definition: str,
    workload_fingerprint: str | None = None,
    sample_ids_by_regime: dict[str, list[str]] | None = None,
    sample_independence_protocol: str | None = None,
) -> dict[str, Any]:
    if workload_fingerprint is not None and (
        not isinstance(workload_fingerprint, str) or not workload_fingerprint.strip()
    ):
        raise ValueError("workload fingerprint must be a non-empty string")
    if sample_ids_by_regime is not None and (
        not isinstance(sample_ids_by_regime, dict)
        or set(sample_ids_by_regime) != {"cold", "warm"}
    ):
        raise ValueError("sample IDs require explicit cold and warm workload case/block plans")
    if sample_ids_by_regime is not None and workload_fingerprint is None:
        raise ValueError("explicit sample IDs require an explicit shared workload fingerprint")
    if sample_independence_protocol is not None and sample_independence_protocol not in {
        _SAMPLE_INDEPENDENCE_PROTOCOL, _SAMPLE_STATELESS_PROTOCOL,
    }:
        raise ValueError("unsupported sample independence protocol")
    if sample_independence_protocol is not None and (
        sample_ids_by_regime is None or workload_fingerprint is None
    ):
        raise ValueError("verified sample independence requires sample IDs and a workload fingerprint")
    if sample_independence_protocol == _SAMPLE_INDEPENDENCE_PROTOCOL and (
        sample_ids_by_regime is None or cold_prepare is None or warm_prepare is None
    ):
        raise ValueError("verified cache epochs require sample IDs and cold/warm preparation callbacks")
    if sample_independence_protocol == _SAMPLE_STATELESS_PROTOCOL and (
        cold_prepare is not None or warm_prepare is not None
        or cold_verify is not None or warm_verify is not None
    ):
        raise ValueError("stateless sample cases cannot declare cache preparation or verification callbacks")

    preparation_statuses: dict[str, list[str]] = {"cold": [], "warm": []}
    cache_epoch_ids: dict[str, list[str]] = {"cold": [], "warm": []}
    preparation_receipt_sample_ids: dict[str, list[str]] = {"cold": [], "warm": []}
    preparation_state_fingerprints: dict[str, list[str]] = {"cold": [], "warm": []}

    def verified_prepare(
        regime: str,
        callback: Callable[[int], Any] | None,
        verifier: Callable[[int], Any] | None,
    ) -> Callable[[int], None] | None:
        if sample_independence_protocol != _SAMPLE_INDEPENDENCE_PROTOCOL:
            return callback

        def prepare(index: int) -> None:
            if callback is None:
                raise RuntimeError(f"{regime} sample preparation callback is unavailable")
            if verifier is None:
                raise RuntimeError(f"{regime} independent preparation verifier is unavailable")
            outcome = callback(index)
            observation = verifier(index)
            expected_status = "cold_case_unseen" if regime == "cold" else "warm_exact_case_primed"
            expected_sample_id = sample_ids_by_regime[regime][index]
            observed_epoch_id = observation.get("cache_epoch_id") if isinstance(observation, dict) else None
            state_fingerprint = (
                observation.get("observed_state_fingerprint") if isinstance(observation, dict) else None
            )
            if (
                not isinstance(outcome, dict)
                or outcome.get("success") is not True
                or outcome.get("sample_id") != expected_sample_id
                or outcome.get("preparation_status") != expected_status
                or not isinstance(observation, dict)
                or observation.get("success") is not True
                or observation.get("sample_id") != expected_sample_id
                or observation.get("preparation_status") != expected_status
                or not isinstance(observed_epoch_id, str)
                or not observed_epoch_id.strip()
                or not isinstance(state_fingerprint, str)
                or len(state_fingerprint) != 64
                or observed_epoch_id != state_fingerprint
                or any(character not in "0123456789abcdef" for character in state_fingerprint)
            ):
                raise RuntimeError(f"{regime} sample preparation was not independently verified")
            preparation_statuses[regime].append(expected_status)
            preparation_receipt_sample_ids[regime].append(outcome["sample_id"])
            cache_epoch_ids[regime].append(observed_epoch_id)
            preparation_state_fingerprints[regime].append(state_fingerprint)

        return prepare

    cold = _measure_stage(
        name, cold_operation, repetitions,
        before_each=verified_prepare("cold", cold_prepare, cold_verify), indexed=True,
    )
    warm = _measure_stage(
        name, warm_operation, repetitions,
        before_each=verified_prepare("warm", warm_prepare, warm_verify), indexed=True,
    )
    samples = cold["samples_ms"] + warm["samples_ms"]
    cold_warm = {
        "cold": summarize_samples(cold["samples_ms"]),
        "warm": summarize_samples(warm["samples_ms"]),
        "definition": definition,
    }
    stage_workload_fingerprint = workload_fingerprint or _stable_fingerprint({
        "measurement": name,
        "definition": definition,
    })
    result = {
        "status": "passed" if cold["status"] == warm["status"] == "passed" else "failed",
        **summarize_samples(samples),
        "samples_ms": samples,
        "samples_by_regime": {"cold": cold["samples_ms"], "warm": warm["samples_ms"]},
        "cold_warm": cold_warm,
        "error_count": cold["error_count"] + warm["error_count"],
        "error_rate_pct": round((cold["error_count"] + warm["error_count"]) * 100.0 / max(1, len(samples)), 3),
        "error_types": sorted(set(cold["error_types"] + warm["error_types"])),
        "error_count_by_regime": {
            "cold": cold["error_count"], "warm": warm["error_count"],
        },
        "error_rate_pct_by_regime": {
            "cold": round(cold["error_count"] * 100.0 / max(1, len(cold["samples_ms"])), 3),
            "warm": round(warm["error_count"] * 100.0 / max(1, len(warm["samples_ms"])), 3),
        },
        "error_types_by_regime": {
            "cold": cold["error_types"], "warm": warm["error_types"],
        },
        "error_count_by_phase": {
            phase: cold["error_count_by_phase"][phase] + warm["error_count_by_phase"][phase]
            for phase in ("before_each", "operation")
        },
        "error_count_by_phase_by_regime": {
            "cold": cold["error_count_by_phase"], "warm": warm["error_count_by_phase"],
        },
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
        "workload_fingerprint": stage_workload_fingerprint,
    }
    if sample_ids_by_regime is not None:
        identity_ids: dict[str, list[str]] = {}
        for regime, values in (("cold", cold["samples_ms"]), ("warm", warm["samples_ms"])):
            ids = sample_ids_by_regime.get(regime)
            if (
                not isinstance(ids, list)
                or len(ids) != len(values)
                or any(not isinstance(sample_id, str) or not sample_id.strip() for sample_id in ids)
                or len(set(ids)) != len(ids)
            ):
                raise ValueError(f"{regime} sample IDs must be unique explicit workload case/block IDs")
            identity_ids[regime] = list(ids)
        result["sample_ids_by_regime"] = identity_ids
        result["sample_identity_provenance"] = _sample_identity_provenance(stage_workload_fingerprint)
        result["sample_identity_unit"] = "declared_workload_label"
        result["sample_independence_status"] = "not_established"
        result["sample_independence_note"] = (
            "unique labels do not prove independent workloads or cache epochs"
        )
        if sample_independence_protocol is not None:
            run_id = uuid.uuid4().hex
            if sample_independence_protocol == _SAMPLE_STATELESS_PROTOCOL:
                preparation_statuses = {
                    regime: ["stateless_case"] * len(identity_ids[regime])
                    for regime in ("cold", "warm")
                }
                preparation_receipt_sample_ids = {
                    regime: list(identity_ids[regime]) for regime in ("cold", "warm")
                }
                preparation_state_fingerprints = {
                    regime: [
                        _stable_fingerprint({"protocol": _SAMPLE_STATELESS_PROTOCOL, "sample_id": sample_id})
                        for sample_id in identity_ids[regime]
                    ]
                    for regime in ("cold", "warm")
                }
                cache_epoch_ids = {
                    regime: [
                        f"stateless:{run_id}:{name}:{regime}:{sample_id}"
                        for sample_id in identity_ids[regime]
                    ]
                    for regime in ("cold", "warm")
                }
            preparation_complete = all(
                len(preparation_statuses[regime]) == len(identity_ids[regime])
                and len(cache_epoch_ids[regime]) == len(identity_ids[regime])
                and len(preparation_receipt_sample_ids[regime]) == len(identity_ids[regime])
                and len(preparation_state_fingerprints[regime]) == len(identity_ids[regime])
                for regime in ("cold", "warm")
            )
            if preparation_complete and result["error_count"] == 0:
                result["sample_independence_proof"] = _build_sample_independence_proof(
                    protocol=sample_independence_protocol,
                    workload_fingerprint=stage_workload_fingerprint,
                    sample_ids_by_regime=identity_ids,
                    cache_epoch_ids_by_regime=cache_epoch_ids,
                    preparation_status_by_regime=preparation_statuses,
                    preparation_receipt_sample_ids_by_regime=preparation_receipt_sample_ids,
                    preparation_state_fingerprints_by_regime=preparation_state_fingerprints,
                )
                result["sample_identity_unit"] = "runner_verified_workload_case"
                result["sample_independence_note"] = (
                    "runner measured stateless synthetic cases with no Hub cache preparation"
                    if sample_independence_protocol == _SAMPLE_STATELESS_PROTOCOL
                    else "runner independently verified observed state for each cold and warm preparation before timing"
                )
                if _sample_independence_proof_is_valid(result):
                    result["sample_independence_status"] = "established"
    return result


def _measure_concurrent_service(
    name: str,
    operation: Callable[[int, int, int], _HTTPObservation],
    *,
    concurrency: tuple[int, ...],
    repetitions: int,
) -> dict[str, Any]:
    if not concurrency or any(level < 1 for level in concurrency):
        raise ValueError("concurrency levels must be positive")
    if len(set(concurrency)) != len(concurrency):
        raise ValueError("concurrency levels must be unique")
    if repetitions < 1:
        raise ValueError("concurrent repetitions must be positive")

    by_concurrency: dict[str, dict[str, Any]] = {}
    all_samples: list[float] = []
    total_errors = 0
    all_error_types: set[str] = set()
    for level in concurrency:
        request_samples: list[float] = []
        batch_samples: list[float] = []
        batch_throughput: list[float] = []
        response_bytes: list[int] = []
        whitespace_tokens: list[int] = []
        sample_ids: list[str] = []
        batch_sample_ids: list[str] = []
        request_latency_samples_by_batch_ms: list[list[float]] = []
        request_sample_ids_by_batch: list[list[str]] = []
        error_types: set[str] = set()
        level_errors = 0

        def request_sample(barrier: threading.Barrier, repetition: int, slot: int) -> tuple[float, int, int, str | None]:
            started = time.perf_counter()
            try:
                barrier.wait(timeout=15)
                started = time.perf_counter()
                response = operation(level, repetition, slot)
                if (
                    not isinstance(response, _HTTPObservation)
                    or response.status != 200
                    or not isinstance(response.payload, dict)
                    or response.payload.get("success") is not True
                ):
                    raise RuntimeError("concurrent Hub request returned an unsuccessful response")
                return (
                    (time.perf_counter() - started) * 1000.0,
                    len(response.body),
                    len(response.body.decode("utf-8", errors="replace").split()),
                    None,
                )
            except Exception as exc:  # keep diagnostics metadata-only
                return (time.perf_counter() - started) * 1000.0, 0, 0, type(exc).__name__

        with ThreadPoolExecutor(max_workers=level) as executor:
            for repetition in range(repetitions):
                barrier = threading.Barrier(level + 1)
                batch_started = time.perf_counter()
                futures = [
                    executor.submit(request_sample, barrier, repetition, slot)
                    for slot in range(level)
                ]
                try:
                    barrier.wait(timeout=15)
                except threading.BrokenBarrierError:
                    level_errors += level
                    error_types.add("BrokenBarrierError")
                    for future in futures:
                        future.cancel()
                    continue
                results = _collect_concurrent_results(
                    futures, timeout_seconds=_CONCURRENT_REQUEST_BATCH_TIMEOUT_SECONDS,
                )
                batch_seconds = time.perf_counter() - batch_started
                batch_samples.append(batch_seconds * 1000.0)
                batch_sample_ids.append(f"context-pack-concurrency:{level}:batch:{repetition}")
                if batch_seconds > 0:
                    batch_throughput.append(level / batch_seconds)
                request_latency_samples_by_batch_ms.append([item[0] for item in results])
                batch_request_ids: list[str] = []
                for slot, (elapsed_ms, body_bytes, token_estimate, error_type) in enumerate(results):
                    request_samples.append(elapsed_ms)
                    response_bytes.append(body_bytes)
                    whitespace_tokens.append(token_estimate)
                    request_id = f"context-pack-concurrency:{level}:{repetition}:{slot}"
                    sample_ids.append(request_id)
                    batch_request_ids.append(request_id)
                    if error_type is not None:
                        level_errors += 1
                        error_types.add(error_type)
                request_sample_ids_by_batch.append(batch_request_ids)

        all_samples.extend(request_samples)
        total_errors += level_errors
        all_error_types.update(error_types)
        workload_fingerprint = _stable_fingerprint({
            "measurement": name,
            "concurrency": level,
            "repetitions": repetitions,
        })
        by_concurrency[str(level)] = {
            "status": "passed" if level_errors == 0 and len(request_samples) == level * repetitions else "failed",
            "concurrency": level,
            "repetitions": repetitions,
            "request_count": len(request_samples),
            "sample_count": len(request_samples),
            "samples_ms": request_samples,
            "sample_ids": sample_ids,
            "batch_sample_ids": batch_sample_ids,
            "request_latency_samples_by_batch_ms": request_latency_samples_by_batch_ms,
            "request_sample_ids_by_batch": request_sample_ids_by_batch,
            "workload_fingerprint": workload_fingerprint,
            "sample_identity_provenance": _sample_identity_provenance(workload_fingerprint),
            **summarize_samples(request_samples),
            "batch_latency": summarize_samples(batch_samples),
            "batch_latency_samples_ms": batch_samples,
            "batch_throughput_per_second": summarize_samples(batch_throughput),
            "batch_throughput_samples_per_second": batch_throughput,
            "error_count": level_errors,
            "error_rate_pct": round(level_errors * 100.0 / max(1, len(request_samples)), 3),
            "error_types": sorted(error_types),
            "http_response_body_bytes": max(response_bytes, default=0),
            "http_response_body_bytes_total": sum(response_bytes),
            "whitespace_token_estimate": max(whitespace_tokens, default=0),
            "response_measurement": "exact_http_response_body_bytes",
        }

    return {
        "status": "passed" if total_errors == 0 else "failed",
        "measurement": name,
        "by_concurrency": by_concurrency,
        "concurrency_levels": list(concurrency),
        "repetitions_per_level": repetitions,
        "request_count": sum(int(item["request_count"]) for item in by_concurrency.values()),
        "error_count": total_errors,
        "error_types": sorted(all_error_types),
        **summarize_samples(all_samples),
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


def _synthetic_query_symbol(index: int) -> str:
    return f"benchmarkcase{index:06d}"


def _synthetic_source(index: int) -> str:
    query_symbol = _synthetic_query_symbol(index)
    source = (
        f"def symbol_{index}(value: int = 1) -> int:\n    return value + {index}\n"
        f"\ndef {query_symbol}(value: int = 1) -> int:\n    return value + {index}\n"
    )
    if index < _MAX_REPETITIONS:
        source += (
            f"\ndef graph_target_case_{index}() -> int:\n    return {index}\n"
            f"\ndef graph_caller_case_{index}() -> int:\n    return graph_target_case_{index}()\n"
        )
    if index == 0:
        source += "\ndef graph_target() -> int:\n    return 1\n\ndef graph_caller() -> int:\n    return graph_target()\n"
    return source


_SYNTHETIC_INPUT_GENERATOR_VERSION = 1


def _synthetic_input_provenance(input_seed: int, fingerprint: str) -> dict[str, int | str]:
    if type(input_seed) is not int or input_seed < 0:
        raise ValueError("synthetic input seed must be a non-negative integer")
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        raise ValueError("synthetic input fingerprint must be a lowercase SHA-256 hex digest")
    return {
        "synthetic_input_generator_version": _SYNTHETIC_INPUT_GENERATOR_VERSION,
        "synthetic_input_seed": input_seed,
        "synthetic_input_fingerprint": fingerprint,
    }


def _build_synthetic_repo(
    root: Path, file_count: int, rag_chunks: int, *, input_seed: int = 0,
) -> tuple[list[Path], Path, Path, str]:
    if type(input_seed) is not int or input_seed < 0:
        raise ValueError("input_seed must be a non-negative integer")
    source_root = root / "repo" / "src"
    test_root = root / "repo" / "tests"
    source_root.mkdir(parents=True, exist_ok=True)
    test_root.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    fingerprint = hashlib.sha256()
    for index in range(file_count):
        path = source_root / f"module_{index:06d}.py"
        source = _synthetic_source(index)
        if input_seed:
            source = f"{source}\nINPUT_SEED = {input_seed}\n"
        path.write_text(source, encoding="utf-8")
        fingerprint.update(path.relative_to(root).as_posix().encode("utf-8"))
        fingerprint.update(b"\0")
        fingerprint.update(source.encode("utf-8"))
        fingerprint.update(b"\0")
        files.append(path)
    test_path = test_root / "test_graph_target.py"
    test_source = "from src.module_000000 import graph_target\n\ndef test_graph_target_returns_value():\n    assert graph_target() == 1\n"
    test_path.write_text(test_source, encoding="utf-8")
    fingerprint.update(test_path.relative_to(root).as_posix().encode("utf-8"))
    fingerprint.update(b"\0")
    fingerprint.update(test_source.encode("utf-8"))
    fingerprint.update(b"\0")
    corpus_path = root / "synthetic-rag.jsonl"
    with corpus_path.open("w", encoding="utf-8", newline="\n") as stream:
        for index in range(rag_chunks):
            relevant = index % 997 == 7
            chunk = {
                "id": index,
                "text": f"synthetic {'needle' if relevant else 'filler'} chunk {index}",
                "relevant": relevant,
            }
            line = json.dumps(chunk, separators=(",", ":")) + "\n"
            stream.write(line)
            fingerprint.update(line.encode("utf-8"))
    return files, test_path, corpus_path, fingerprint.hexdigest()


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


def _sample_dedicated_vram_bytes() -> int | None:
    try:
        from local_ai_hub.gpu_monitor import get_gpu_telemetry

        snapshot = get_gpu_telemetry()
    except Exception:
        return None
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("available") is not True
        or snapshot.get("integrated") is True
        or snapshot.get("shared_memory") is True
        or snapshot.get("backend") not in {"cuda", "rocm"}
    ):
        return None
    total_mb = snapshot.get("vram_total_mb")
    used = _vram_usage_bytes(snapshot)
    if (
        not isinstance(total_mb, (int, float))
        or not math.isfinite(total_mb)
        or total_mb <= 0
        or used is None
        or used <= 0
    ):
        return None
    return used


def _measure_python_allocation_peak(operation: Callable[[], Any]) -> dict[str, Any]:
    if tracemalloc.is_tracing():
        try:
            operation()
        except Exception as exc:
            return {
                "status": "failed", "peak_python_allocated_bytes": None,
                "error_type": type(exc).__name__,
            }
        return {
            "status": "skipped",
            "peak_python_allocated_bytes": None,
            "reason": "caller_tracemalloc_already_active",
        }

    started = False
    try:
        tracemalloc.start()
        started = True
        baseline_current, _baseline_peak = tracemalloc.get_traced_memory()
        operation()
        _current, peak = tracemalloc.get_traced_memory()
        return {
            "status": "passed",
            "peak_python_allocated_bytes": max(0, peak - baseline_current),
        }
    except Exception as exc:
        return {
            "status": "failed", "peak_python_allocated_bytes": None,
            "error_type": type(exc).__name__,
        }
    finally:
        if started and tracemalloc.is_tracing():
            tracemalloc.stop()


def _queue_admission_error_reason(
    submitted: Any,
    cancelled: Any = None,
) -> str | None:
    if not isinstance(submitted, dict) or submitted.get("success") is not True or not submitted.get("job_id"):
        return "submit_rejected"
    if cancelled is None:
        return "cancel_missing"
    if not isinstance(cancelled, dict):
        return "cancel_not_cancelled"
    if cancelled.get("state") == "running":
        return "cancel_running"
    if cancelled.get("success") is not True or cancelled.get("state") != "cancelled":
        return "cancel_not_cancelled"
    return None


def _queue_admission_failure_diagnostic(
    sample_id: str,
    *,
    source_revision: str | None,
    submitted: Any,
    cancelled: Any,
    status: Any,
    manager_stats: Any,
    error_type: str | None,
    error_reason: str | None,
    diagnostic_error_types: dict[str, str] | None = None,
) -> dict[str, Any]:
    def text_field(value: Any, key: str) -> str | None:
        field = value.get(key) if isinstance(value, dict) else None
        return field if isinstance(field, str) else None

    def bool_field(value: Any, key: str) -> bool | None:
        field = value.get(key) if isinstance(value, dict) else None
        return field if isinstance(field, bool) else None

    def numeric_field(value: Any, key: str) -> int | float | None:
        field = value.get(key) if isinstance(value, dict) else None
        return field if isinstance(field, (int, float)) and not isinstance(field, bool) else None

    admission = submitted.get("admission") if isinstance(submitted, dict) else None
    raw_counts = manager_stats.get("counts") if isinstance(manager_stats, dict) else None
    raw_counters = manager_stats if isinstance(manager_stats, dict) else {}
    count_keys = ("queued", "running", "done", "failed", "cancelled", "expired", "outcome_unknown")
    counter_keys = ("submitted", "coalesced", "completed", "failed", "cancelled", "recovered", "expired")
    queue_counts = {
        key: raw_counts[key] for key in count_keys
        if isinstance(raw_counts, dict) and isinstance(raw_counts.get(key), int) and not isinstance(raw_counts.get(key), bool)
    }
    queue_counters = {
        key: raw_counters[key] for key in counter_keys
        if isinstance(raw_counters.get(key), int) and not isinstance(raw_counters.get(key), bool)
    }
    status_id = text_field(status, "job_id")
    return {
        "sample_id": sample_id,
        "source_revision": source_revision,
        "job_id": text_field(submitted, "job_id"),
        "submit": {
            "success": bool_field(submitted, "success"),
            "state": text_field(submitted, "state"),
            "admission_state": text_field(submitted, "admission_state"),
            "admission_reason": text_field(admission, "reason"),
            "retryable": bool_field(submitted, "retryable"),
        },
        "cancel": {
            "success": bool_field(cancelled, "success"),
            "state": text_field(cancelled, "state"),
            "cancel_requested": bool_field(cancelled, "cancel_requested"),
            "admission_state": text_field(cancelled, "admission_state"),
            "retryable": bool_field(cancelled, "retryable"),
        },
        "observed_status": {
            "job_id": status_id,
            "state": text_field(status, "state"),
            "attempts": numeric_field(status, "attempts"),
            "cancel_requested": bool_field(status, "cancel_requested"),
            "updated_at": numeric_field(status, "updated_at"),
        },
        "manager_state_counts_after": queue_counts,
        "manager_counters_after": queue_counters,
        "manager_snapshot_scope": "shared_manager_after_probe",
        "error_type": error_type,
        "error_reason": error_reason,
        "diagnostic_error_types": dict(sorted((diagnostic_error_types or {}).items())),
    }


def _rag_workspace_document_counts(rag_store: Any, tenant: str, workspace: str) -> dict[str, int]:
    scope_key = rag_store._scope_key(tenant)
    with closing(rag_store._connect()) as con:
        files = int(con.execute(
            "SELECT COUNT(*) FROM files WHERE tenant=? AND workspace=?",
            (scope_key, workspace),
        ).fetchone()[0])
        chunks = int(con.execute(
            "SELECT COUNT(*) FROM chunks WHERE tenant=? AND workspace=?",
            (scope_key, workspace),
        ).fetchone()[0])
    return {"files": files, "chunks": chunks}


@_serialize_benchmark_runs
def run_benchmark(
    *,
    state_dir: Path | str,
    scratch_dir: Path | str | None = None,
    file_count: int = 100,
    rag_chunks: int = 1_000,
    input_seed: int = 0,
    repetitions: int = 3,
    light_repetitions: int | None = None,
    comparison_repetitions: int | None = None,
    concurrency: tuple[int, ...] = (1, 4),
    full: bool = False,
    inference_runner: Any = None,
    include_inference: bool = False,
    include_t12_matrix: bool = False,
    include_quality_goldens: bool | None = None,
    speech_fixture: Path | str | None = None,
    speech_expected_text: str | None = None,
    baseline_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run synthetic stages and persist samples, aggregates, and optional comparison."""
    if type(input_seed) is not int or input_seed < 0:
        raise ValueError("input_seed must be a non-negative integer")
    if file_count < 1 or rag_chunks < 1 or repetitions < 1:
        raise ValueError("file_count, rag_chunks, and repetitions must be positive")
    light_repetitions = repetitions if light_repetitions is None else light_repetitions
    comparison_repetitions = repetitions if comparison_repetitions is None else comparison_repetitions
    if light_repetitions < 1 or comparison_repetitions < 1:
        raise ValueError("light_repetitions and comparison_repetitions must be positive")
    if not concurrency or any(level < 1 for level in concurrency):
        raise ValueError("concurrency levels must be positive")
    if len(set(concurrency)) != len(concurrency):
        raise ValueError("concurrency levels must be unique")
    if any(level > _MAX_CONCURRENCY for level in concurrency):
        raise ValueError(f"concurrency levels maximum is {_MAX_CONCURRENCY}")
    if max(repetitions, light_repetitions, comparison_repetitions) > _MAX_REPETITIONS:
        raise ValueError(f"benchmark repetitions maximum is {_MAX_REPETITIONS}")
    if not full and (file_count > 100 or rag_chunks > 1_000):
        raise ValueError("large sizes require full benchmark opt-in")
    if full and (file_count not in _FULL_FILE_SIZES or rag_chunks not in _FULL_RAG_SIZES):
        raise ValueError("full benchmark sizes must use the documented file and RAG matrices")
    if include_inference and inference_runner is None:
        raise ValueError("inference opt-in requires an explicit benchmark runner")
    if include_t12_matrix and inference_runner is None:
        raise ValueError("T12 profile matrix requires an explicit benchmark runner")
    if include_quality_goldens is None:
        include_quality_goldens = include_inference
    if include_quality_goldens and not include_inference:
        raise ValueError("model quality goldens require explicit inference opt-in")
    if speech_fixture is not None and not include_inference:
        raise ValueError("speech golden fixture requires explicit inference opt-in")
    speech_identity = _speech_golden_identity(speech_fixture, speech_expected_text)
    speech_fixture = Path(speech_fixture).expanduser().resolve() if speech_fixture is not None else None

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
    record: dict[str, Any] | None = None
    record_path: Path | None = None
    try:
        synthetic: dict[str, Any] = {}

        def setup_synthetic_inputs() -> dict[str, int]:
            files, test_path, corpus_path, fingerprint = _build_synthetic_repo(
                scratch, file_count, rag_chunks, input_seed=input_seed,
            )
            synthetic.update(
                files=files, test_path=test_path, corpus_path=corpus_path,
                input_fingerprint=fingerprint,
            )
            return {"file_count": len(files), "rag_chunk_count": rag_chunks}

        stages["synthetic_setup"] = _measure_stage("synthetic_fixture_generation", setup_synthetic_inputs, 1)
        files = synthetic["files"]
        test_path = synthetic["test_path"]
        corpus_path = synthetic["corpus_path"]

        from local_ai_hub import http_server as http_server_module
        from local_ai_hub.app import LocalAIApp
        runtime_source_root = Path(http_server_module.__file__).resolve().parents[1]
        if runtime_source_root != _SOURCE_ROOT:
            raise RuntimeError(
                f"benchmark runtime source mismatch: expected {_SOURCE_ROOT}, got {runtime_source_root}"
            )

        app_state_dir = scratch / "hub-state"
        app_config_path = scratch / "hub-config.toml"
        inference_server_url = _benchmark_inference_server_url(inference_runner)
        inference_server_setting = (
            f"ollama_url = {json.dumps(inference_server_url)}\n"
            if inference_server_url is not None else ""
        )
        app_config_path.write_text(
            "[server]\n"
            'bind = "127.0.0.1"\n'
            "port = 11497\n"
            f"state_dir = {json.dumps(str(app_state_dir.resolve()))}\n"
            + inference_server_setting
            + "\n"
            + "[prewarm]\n"
            + "enabled = false\n\n"
            + "[observability]\n"
            + "enabled = false\n\n"
            + "[resilience]\nwatchdog_enabled = false\n\n"
            + "[debug_traces]\nenabled = false\n\n"
            + _benchmark_inference_config(inference_runner),
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
            invalid_context_request, light_repetitions,
        )

        repo_root = scratch / "repo"
        relative_files = [path.relative_to(repo_root).as_posix() for path in files]

        def populate_code_index() -> dict[str, int]:
            result = app.code_index.update_files_batch(str(repo_root), relative_files)
            if result.get("success") is not True:
                raise RuntimeError("Hub CodeIndex did not accept synthetic files")
            return {
                "files_processed": int(result.get("files_processed", 0)),
                "files_seeded": int(result.get("files_processed", 0)) + int(result.get("cached") or 0),
                "symbols_indexed": int(result.get("symbols", 0)),
            }

        sqlite_index_cases_by_regime = {
            regime: [
                {
                    "sample_id": f"sqlite-index:{regime}:{relative_files[offset + index]}",
                    "path": relative_files[offset + index],
                    "content_sha256": hashlib.sha256(files[offset + index].read_bytes()).hexdigest(),
                }
                for index in range(comparison_repetitions)
            ]
            for regime, offset in (("cold", 0), ("warm", comparison_repetitions))
            if offset + comparison_repetitions <= len(relative_files)
        }
        has_paired_sqlite_index_plan = set(sqlite_index_cases_by_regime) == {"cold", "warm"}

        def index_sqlite_case(regime: str, index: int) -> dict[str, int]:
            case = sqlite_index_cases_by_regime[regime][index]
            result = app.code_index.update_files_batch(str(repo_root), [case["path"]])
            if result.get("success") is not True:
                raise RuntimeError(f"Hub CodeIndex rejected synthetic file {case['sample_id']}")
            return {
                "files_processed": int(result.get("files_processed", 0)),
                "symbols_indexed": int(result.get("symbols", 0)),
            }

        if has_paired_sqlite_index_plan:
            sqlite_index_sample_ids_by_regime = {
                regime: [case["sample_id"] for case in cases]
                for regime, cases in sqlite_index_cases_by_regime.items()
            }
            sqlite_index_workload_fingerprint = _stable_fingerprint({
                "stage": "hub_sqlite_index_file_cases_v1",
                "root_scope": "isolated-synthetic-repository",
                "cases_by_regime": sqlite_index_cases_by_regime,
            })
            cold_sqlite_index_cases_seen: set[str] = set()

            def prepare_cold_sqlite_index_case(index: int) -> dict[str, Any]:
                case = sqlite_index_cases_by_regime["cold"][index]
                sample_id = case["sample_id"]
                if sample_id in cold_sqlite_index_cases_seen:
                    return {"success": False}
                with closing(app.code_index._connect()) as con:
                    existing = con.execute(
                        "SELECT 1 FROM files WHERE root=? AND path=? LIMIT 1",
                        (str(repo_root.resolve()), case["path"]),
                    ).fetchone()
                if existing is not None:
                    return {"success": False}
                cold_sqlite_index_cases_seen.add(sample_id)
                return _preparation_receipt(
                    sample_id, "cold_case_unseen",
                )

            def prepare_warm_sqlite_index_case(index: int) -> dict[str, Any]:
                case = sqlite_index_cases_by_regime["warm"][index]
                index_sqlite_case("warm", index)
                return _preparation_receipt(
                    case["sample_id"], "warm_exact_case_primed",
                )

            def verify_sqlite_index_case(regime: str, index: int) -> dict[str, Any]:
                case = sqlite_index_cases_by_regime[regime][index]
                with closing(app.code_index._connect()) as con:
                    existing = con.execute(
                        "SELECT 1 FROM files WHERE root=? AND path=? LIMIT 1",
                        (str(repo_root.resolve()), case["path"]),
                    ).fetchone()
                indexed = existing is not None
                expected_indexed = regime == "warm"
                if indexed != expected_indexed:
                    return {"success": False}
                status = "cold_case_unseen" if regime == "cold" else "warm_exact_case_primed"
                return _preparation_observation(
                    case["sample_id"], status,
                    {"root": str(repo_root.resolve()), "path": case["path"], "indexed": indexed},
                )

            stages["hub_sqlite_index"] = _measure_stage_regimes(
                "CodeIndex SQLite indexing of one synthetic file per sample",
                lambda index: index_sqlite_case("cold", index),
                lambda index: index_sqlite_case("warm", index),
                comparison_repetitions,
                cold_prepare=prepare_cold_sqlite_index_case,
                warm_prepare=prepare_warm_sqlite_index_case,
                cold_verify=lambda index: verify_sqlite_index_case("cold", index),
                warm_verify=lambda index: verify_sqlite_index_case("warm", index),
                definition="Cold and warm groups index distinct synthetic files. Each warm file is preindexed in its own exact workload case. No OS cache flush.",
                workload_fingerprint=sqlite_index_workload_fingerprint,
                sample_ids_by_regime=sqlite_index_sample_ids_by_regime,
                sample_independence_protocol=_SAMPLE_INDEPENDENCE_PROTOCOL,
            )
        else:
            stages["hub_sqlite_index"] = _measure_stage(
                "CodeIndex.update_files_batch persisted to isolated Hub SQLite index",
                populate_code_index, comparison_repetitions,
            )

        # Seed every synthetic file outside the measured stage for downstream queries.
        sqlite_index_seed = populate_code_index()
        stages["hub_sqlite_index"]["main_repo_seeded_files"] = sqlite_index_seed["files_seeded"]
        stages["hub_sqlite_index"]["main_repo_seeded_symbols"] = sqlite_index_seed["symbols_indexed"]

        sqlite_read_cases = [
            {
                "sample_id": f"sqlite-db-read:{relative_files[index % len(relative_files)]}:symbol_{index % len(relative_files)}"
                + (f":repeat_{index // len(relative_files)}" if index >= len(relative_files) else ""),
                "path": relative_files[index % len(relative_files)],
                "symbol": f"symbol_{index % len(relative_files)}",
                "content_sha256": hashlib.sha256(
                    files[index % len(relative_files)].read_bytes(),
                ).hexdigest(),
            }
            for index in range(comparison_repetitions)
        ]
        sqlite_read_sql = (
            "SELECT name FROM symbols WHERE root = ? AND path = ? AND name = ? LIMIT 1"
        )

        def sqlite_index_read(index: int) -> dict[str, int | str]:
            case = sqlite_read_cases[index]
            connection = app.code_index._connect()
            try:
                row = connection.execute(
                    sqlite_read_sql, (str(repo_root.resolve()), case["path"], case["symbol"]),
                ).fetchone()
            finally:
                connection.close()
            if row is None or row[0] != case["symbol"]:
                raise RuntimeError(f"CodeIndex SQLite query missed synthetic case {case['sample_id']}")
            return {"symbol_rows": 1, "symbol_name": str(row[0])}

        sqlite_read_sample_ids = [case["sample_id"] for case in sqlite_read_cases]
        has_unique_sqlite_read_cases = len({(case["path"], case["symbol"]) for case in sqlite_read_cases}) == comparison_repetitions
        sqlite_read_workload_fingerprint = _stable_fingerprint({
            "stage": "hub_sqlite_symbol_row_lookup_cases_v1",
            "sql": sqlite_read_sql,
            "root_scope": "isolated-synthetic-repository",
            "cases": sqlite_read_cases,
        })

        stages["hub_sqlite_db_read"] = _measure_stage_regimes(
            "CodeIndex SQLite exact synthetic symbol-row lookup",
            sqlite_index_read,
            sqlite_index_read,
            comparison_repetitions,
            definition="Cold and warm groups use distinct synthetic root/path/name point lookups. Each operation opens a fresh SQLite connection; no Hub result cache, no OS cache flush.",
            workload_fingerprint=sqlite_read_workload_fingerprint,
            sample_ids_by_regime={"cold": sqlite_read_sample_ids, "warm": sqlite_read_sample_ids},
            sample_independence_protocol=(
                _SAMPLE_STATELESS_PROTOCOL if has_unique_sqlite_read_cases else None
            ),
        )

        def code_index_request(query: str) -> _HTTPObservation:
            payload = {"root": str(repo_root), "query": query, "limit": 10, "include_code": False}
            response = require_http(_http_request(server, "/api/repo/code-index", payload), 200, True)
            if not isinstance(response.payload.get("symbols"), list):
                raise RuntimeError("Hub CodeIndex response has no symbol list")
            return response

        code_index_cases = [
            {
                "sample_id": f"code-index:{path.relative_to(repo_root).as_posix()}:{_synthetic_query_symbol(index)}",
                "query": _synthetic_query_symbol(index),
                "expected_symbol": _synthetic_query_symbol(index),
            }
            for index, path in enumerate(files[:comparison_repetitions])
        ]
        has_paired_code_index_plan = len(code_index_cases) == comparison_repetitions

        def code_index_request_for_regime(index: int, regime: str) -> _HTTPObservation:
            case = code_index_cases[index]
            query = f"{case['query']} t02_{regime}_sample_{index}"
            response = code_index_request(query)
            if not any(
                isinstance(item, dict) and item.get("name") == case["expected_symbol"]
                for item in response.payload.get("symbols", [])
            ):
                raise RuntimeError(f"CodeIndex query missed synthetic case {case['sample_id']}")
            return response

        cold_code_index_cases_seen: set[str] = set()

        def prepare_cold_code_index_case(index: int) -> dict[str, Any]:
            case = code_index_cases[index]
            sample_id = f"{case['sample_id']}:cold"
            if sample_id in cold_code_index_cases_seen:
                return {"success": False}
            cold_code_index_cases_seen.add(sample_id)
            return _preparation_receipt(
                f"{case['sample_id']}:cold", "cold_case_unseen",
            )

        def prepare_warm_code_index_case(index: int) -> dict[str, Any]:
            case = code_index_cases[index]
            code_index_request_for_regime(index, "warm")
            return _preparation_receipt(
                f"{case['sample_id']}:warm", "warm_exact_case_primed",
            )

        def verify_code_index_case(regime: str, index: int) -> dict[str, Any]:
            from local_ai_hub.cache import stable_hash as cache_stable_hash

            case = code_index_cases[index]
            query = f"{case['query']} t02_{regime}_sample_{index}"
            try:
                params = {
                    "terms": sorted(set(app.code_index._query_terms(query))),
                    "limit": 10,
                    "include_code": False,
                }
                state = app.services._repo_cache_state(str(repo_root))
                state_fingerprint = state.get("fingerprint") if isinstance(state, dict) else None
                if not isinstance(state_fingerprint, str) or not state_fingerprint:
                    return {"success": False}
                cache_key = cache_stable_hash({
                    "op": "code-index", "state": state_fingerprint, "params": params,
                })
                cached = app.services.repo_cache.get(cache_key)
            except Exception:
                return {"success": False}
            cache_present = cached is not None
            symbol_found = bool(
                isinstance(cached, dict)
                and cached.get("success") is True
                and any(
                    isinstance(item, dict) and item.get("name") == case["expected_symbol"]
                    for item in cached.get("symbols", [])
                )
            )
            if cache_present != (regime == "warm") or (regime == "warm" and not symbol_found):
                return {"success": False}
            status = "cold_case_unseen" if regime == "cold" else "warm_exact_case_primed"
            return _preparation_observation(
                f"{case['sample_id']}:{regime}", status,
                {
                    "query": query,
                    "operation": "code-index",
                    "cache_key": cache_key,
                    "repository_fingerprint": state_fingerprint,
                    "cache_entry_present": cache_present,
                    "expected_symbol_found": symbol_found,
                },
            )

        cold_symbol_query = lambda index: code_index_request(f"symbol_0 coldprobe_{index}")
        warm_symbol_query = "symbol_0 warmprobe"
        symbol_response = code_index_request("symbol_0 goldenprobe")
        symbol_payload = symbol_response.payload
        symbol_passed = any(
            isinstance(item, dict) and item.get("name") == "symbol_0"
            for item in symbol_payload.get("symbols", [])
        )
        if has_paired_code_index_plan:
            code_index_sample_ids_by_regime = {
                regime: [f"{case['sample_id']}:{regime}" for case in code_index_cases]
                for regime in ("cold", "warm")
            }
            code_index_workload_fingerprint = _stable_fingerprint({
                "stage": "hub_code_index_query_cases_v1",
                "cases": [
                    {
                        "sample_id": case["sample_id"],
                        "cold_query": f"{case['query']} t02_cold_sample_{index}",
                        "warm_query": f"{case['query']} t02_warm_sample_{index}",
                        "expected_symbol": case["expected_symbol"],
                    }
                    for index, case in enumerate(code_index_cases)
                ],
                "limit": 10,
            })
            stages["hub_code_index"] = _measure_stage_regimes(
                "POST /api/repo/code-index; real CodeIndex query and service cache",
                lambda index: code_index_request_for_regime(index, "cold"),
                lambda index: code_index_request_for_regime(index, "warm"),
                comparison_repetitions,
                cold_prepare=prepare_cold_code_index_case,
                warm_prepare=prepare_warm_code_index_case,
                cold_verify=lambda index: verify_code_index_case("cold", index),
                warm_verify=lambda index: verify_code_index_case("warm", index),
                definition="Cold and warm groups use distinct synthetic query keys per module path; warm primes that exact key before timing. No OS cache flush.",
                workload_fingerprint=code_index_workload_fingerprint,
                sample_ids_by_regime=code_index_sample_ids_by_regime,
                sample_independence_protocol=_SAMPLE_INDEPENDENCE_PROTOCOL,
            )
        else:
            stages["hub_code_index"] = _measure_stage_regimes(
                "POST /api/repo/code-index; real CodeIndex query and service cache",
                cold_symbol_query,
                lambda _index: code_index_request(warm_symbol_query),
                comparison_repetitions,
                warm_prepare=lambda _index: code_index_request(warm_symbol_query),
                definition="Unpaired cold/warm probes used because synthetic modules do not provide enough distinct symbol cases; no sample identities asserted. No OS cache flush.",
            )

        expected_graph_edge = ["graph_caller", "graph_target"]
        caller_edge_hits: list[bool] = []
        callee_edge_hits: list[bool] = []
        graph_cases = [
            {
                "caller": f"graph_caller_case_{index}",
                "target": f"graph_target_case_{index}",
                "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "caller_sample_id": f"callers:{path.relative_to(repo_root).as_posix()}:graph_target_case_{index}",
                "callee_sample_id": f"callees:{path.relative_to(repo_root).as_posix()}:graph_caller_case_{index}",
            }
            for index, path in enumerate(files[:comparison_repetitions])
        ]
        has_paired_graph_plan = len(graph_cases) == comparison_repetitions

        def caller_query(index: int) -> dict[str, Any]:
            case = graph_cases[index] if has_paired_graph_plan else {
                "caller": expected_graph_edge[0], "target": expected_graph_edge[1],
            }
            result = app.code_index.find_callers(str(repo_root), case["target"])
            found = _graph_edge_found(
                result, collection="callers", caller=case["caller"], callee=case["target"],
            )
            caller_edge_hits.append(found)
            if not found:
                raise RuntimeError(f"CodeIndex.find_callers missed synthetic graph edge {case['target']}")
            return result

        def callee_query(index: int) -> dict[str, Any]:
            case = graph_cases[index] if has_paired_graph_plan else {
                "caller": expected_graph_edge[0], "target": expected_graph_edge[1],
            }
            result = app.code_index.find_callees(str(repo_root), case["caller"])
            found = _graph_edge_found(
                result, collection="callees", caller=case["caller"], callee=case["target"],
            )
            callee_edge_hits.append(found)
            if not found:
                raise RuntimeError(f"CodeIndex.find_callees missed synthetic graph edge {case['caller']}")
            return result

        if has_paired_graph_plan:
            graph_case_fingerprint = _stable_fingerprint({
                "stage": "synthetic_graph_edge_cases_v1",
                "root_scope": "isolated-synthetic-repository",
                "cases": [
                    {
                        "caller": case["caller"],
                        "target": case["target"],
                        "content_sha256": case["content_sha256"],
                        "caller_sample_id": case["caller_sample_id"],
                        "callee_sample_id": case["callee_sample_id"],
                    }
                    for case in graph_cases
                ],
            })
            caller_sample_ids = [case["caller_sample_id"] for case in graph_cases]
            callee_sample_ids = [case["callee_sample_id"] for case in graph_cases]
            stages["hub_call_graph_query"] = _measure_stage_regimes(
                "CodeIndex.find_callers",
                caller_query,
                caller_query,
                comparison_repetitions,
                definition="Same explicit synthetic caller/target edge per paired observation; fresh SQLite connection per call, no cache flush.",
                workload_fingerprint=graph_case_fingerprint,
                sample_ids_by_regime={"cold": caller_sample_ids, "warm": caller_sample_ids},
                sample_independence_protocol=_SAMPLE_STATELESS_PROTOCOL,
            )
            stages["hub_call_graph_callees"] = _measure_stage_regimes(
                "CodeIndex.find_callees",
                callee_query,
                callee_query,
                comparison_repetitions,
                definition="Same explicit synthetic caller/target edge per paired observation; fresh SQLite connection per call, no cache flush.",
                workload_fingerprint=graph_case_fingerprint,
                sample_ids_by_regime={"cold": callee_sample_ids, "warm": callee_sample_ids},
                sample_independence_protocol=_SAMPLE_STATELESS_PROTOCOL,
            )
        else:
            stages["hub_call_graph_query"] = _measure_stage_regimes(
                "CodeIndex.find_callers",
                caller_query,
                caller_query,
                comparison_repetitions,
                definition="Unpaired calls on the single synthetic graph edge because repo lacks enough distinct cases; no sample identities asserted.",
            )
            stages["hub_call_graph_callees"] = _measure_stage_regimes(
                "CodeIndex.find_callees",
                callee_query,
                callee_query,
                comparison_repetitions,
                definition="Unpaired calls on the single synthetic graph edge because repo lacks enough distinct cases; no sample identities asserted.",
            )
        golden_caller_result = app.code_index.find_callers(str(repo_root), expected_graph_edge[1])
        golden_callee_result = app.code_index.find_callees(str(repo_root), expected_graph_edge[0])
        golden_graph_edge_found = (
            _graph_edge_found(
                golden_caller_result, collection="callers",
                caller=expected_graph_edge[0], callee=expected_graph_edge[1],
            )
            and _graph_edge_found(
                golden_callee_result, collection="callees",
                caller=expected_graph_edge[0], callee=expected_graph_edge[1],
            )
        )
        stages["hub_call_graph_query"].update({
            "expected_edge": expected_graph_edge,
            "golden_edge_found": golden_graph_edge_found,
            "paired_case_edges_all_found": (
                has_paired_graph_plan and bool(caller_edge_hits) and all(caller_edge_hits)
            ),
            "edge_checks_all_found": bool(caller_edge_hits) and all(caller_edge_hits),
        })
        stages["hub_call_graph_callees"].update({
            "expected_edge": expected_graph_edge,
            "golden_edge_found": golden_graph_edge_found,
            "paired_case_edges_all_found": (
                has_paired_graph_plan and bool(callee_edge_hits) and all(callee_edge_hits)
            ),
            "edge_checks_all_found": bool(callee_edge_hits) and all(callee_edge_hits),
        })
        graph_edge_found = golden_graph_edge_found

        rag_batch_root = scratch / "synthetic-rag-batch"
        rag_batch_rel = "benchmark-batch.txt"
        rag_batch_path = rag_batch_root / rag_batch_rel
        rag_batch_root.mkdir(parents=True, exist_ok=True)
        rag_batch_path.parent.mkdir(parents=True, exist_ok=True)
        rag_batch_path.write_text("synthetic RAG batch source\n", encoding="utf-8")
        original_rag_chunks = app.rag._chunks
        original_embed = app.services.embed
        had_original_service_space_id = hasattr(app.services, "space_id")
        original_service_space_id = getattr(app.services, "space_id", None)
        rag_chunk_counts: dict[str, list[int]] = {"cold": [], "warm": []}
        rag_embedded_chunk_counts: dict[str, list[int]] = {"cold": [], "warm": []}
        rag_reused_chunk_counts: dict[str, list[int]] = {"cold": [], "warm": []}
        rag_query_embedding_calls = 0
        rag_warm_workspaces = [
            f"t02-rag-warm-{uuid.uuid4().hex}"
            for _ in range(comparison_repetitions)
        ]
        rag_cold_workspaces = [
            f"t02-rag-cold-{uuid.uuid4().hex}"
            for _ in range(comparison_repetitions)
        ]
        rag_chunker_contract = "t02-synthetic-rag-chunks-v1"
        rag_embedder_contract = "t02-deterministic-embedding-fixture-v1"

        def make_rag_case(case_number: int) -> dict[str, str]:
            case_id = _stable_fingerprint({
                "stage": "hub_rag_batch_index_case_v1",
                "case_number": case_number,
                "rag_chunks": rag_chunks,
                "chunker_contract": rag_chunker_contract,
                "embedder_contract": rag_embedder_contract,
            })
            generation = case_id[:16]
            chunks = [
                f"synthetic-rag-{generation}-{index}"
                + (" needle evidence" if index < min(10, rag_chunks) else "")
                for index in range(rag_chunks)
            ]
            sample_content_fingerprint = _stable_fingerprint({
                "chunker_contract": rag_chunker_contract,
                "embedder_contract": rag_embedder_contract,
                "case_id": case_id,
                "source_generation": generation,
                "chunks": chunks,
            })
            return {
                "case_id": case_id,
                "sample_id": f"rag-batch:{sample_content_fingerprint}",
                "generation": generation,
            }

        rag_batch_cases = [make_rag_case(case_number) for case_number in range(comparison_repetitions)]
        rag_batch_cases_by_regime = {
            regime: list(rag_batch_cases)
            for regime in ("cold", "warm")
        }
        rag_batch_workload_fingerprint = _stable_fingerprint({
            "stage": "hub_rag_batch_index_case_manifest_v1",
            "chunker_contract": rag_chunker_contract,
            "embedder_contract": rag_embedder_contract,
            "rag_chunks": rag_chunks,
            "regime_contracts": {
                "cold": "same synthetic cases each in a fresh isolated workspace before first index",
                "warm": "same synthetic cases preindexed outside timing in one isolated workspace per sample",
            },
            "cases_by_regime": {
                regime: [case["sample_id"] for case in cases]
                for regime, cases in rag_batch_cases_by_regime.items()
            },
        })
        rag_batch_sample_ids_by_regime = {
            regime: [case["sample_id"] for case in cases]
            for regime, cases in rag_batch_cases_by_regime.items()
        }

        def benchmark_chunks(text: str, path: str = "") -> list[str]:
            if str(path).replace("\\", "/") == rag_batch_rel:
                generation = next(
                    (line.split("=", 1)[1] for line in text.splitlines() if line.startswith("generation=")),
                    None,
                )
                if generation is None:
                    raise ValueError("synthetic RAG batch source is missing its generation")
                return [
                    f"synthetic-rag-{generation}-{index}"
                    + (" needle evidence" if index < min(10, rag_chunks) else "")
                    for index in range(rag_chunks)
                ]
            return original_rag_chunks(text, path=path)

        def benchmark_embed(
            texts: list[str], tenant: str, query: bool = False, **_kwargs: Any,
        ) -> dict[str, Any]:
            nonlocal rag_query_embedding_calls
            if query:
                rag_query_embedding_calls += 1
            return {
                "success": True,
                "embeddings": [[0.0, 1.0] for _ in texts],
                "backend": "synthetic",
                "model": "t02-deterministic-embedding-fixture",
                "embedding_space_id": "t02-deterministic-embedding-fixture-v1",
            }

        def index_rag_batch(workspace: str) -> dict[str, Any]:
            result = app.rag.index_paths_step(
                str(rag_batch_root), "t02-benchmark", workspace, [rag_batch_rel],
            )
            if result.get("success") is not True or result.get("preempted") is True:
                raise RuntimeError("RAGStore.index_paths_step failed synthetic batch")
            return result

        def prepare_rag_case(regime: str, index: int) -> None:
            case = rag_batch_cases_by_regime[regime][index]
            rag_batch_path.write_text(f"generation={case['generation']}\n", encoding="utf-8")

        def prepare_cold_rag(index: int) -> dict[str, Any]:
            prepare_rag_case("cold", index)
            case = rag_batch_cases_by_regime["cold"][index]
            return _preparation_receipt(
                case["sample_id"], "cold_case_unseen",
            )

        def prepare_warm_rag(index: int) -> dict[str, Any]:
            prepare_rag_case("warm", index)
            index_rag_batch(rag_warm_workspaces[index])
            case = rag_batch_cases_by_regime["warm"][index]
            return _preparation_receipt(
                case["sample_id"], "warm_exact_case_primed",
            )

        def verify_rag_batch_case(regime: str, index: int) -> dict[str, Any]:
            case = rag_batch_cases_by_regime[regime][index]
            workspace = (
                rag_cold_workspaces[index] if regime == "cold" else rag_warm_workspaces[index]
            )
            marker = rag_batch_path.read_text(encoding="utf-8")
            workspace_counts = _rag_workspace_document_counts(
                app.rag, "t02-benchmark", workspace,
            )
            file_count = workspace_counts["files"]
            chunk_count = workspace_counts["chunks"]
            expected_generation = f"generation={case['generation']}\n"
            if marker != expected_generation:
                return {"success": False}
            if regime == "cold" and (file_count != 0 or chunk_count != 0):
                return {"success": False}
            if regime == "warm" and (file_count < 1 or chunk_count < 1):
                return {"success": False}
            status = "cold_case_unseen" if regime == "cold" else "warm_exact_case_primed"
            return _preparation_observation(
                case["sample_id"], status,
                {"workspace": workspace, "generation": case["generation"], "files": file_count, "chunks": chunk_count},
            )

        def record_rag_count(result: dict[str, Any], regime: str) -> dict[str, Any]:
            embedded = int(result.get("embedded_chunks", 0))
            reused = int(result.get("reused_chunks", 0))
            rag_embedded_chunk_counts[regime].append(embedded)
            rag_reused_chunk_counts[regime].append(reused)
            rag_chunk_counts[regime].append(embedded + reused)
            return result

        app.rag._chunks = benchmark_chunks
        app.services.embed = benchmark_embed
        app.services.space_id = rag_embedder_contract
        try:
            stages["hub_rag_batch_index"] = _measure_stage_regimes(
                "RAGStore.index_paths_step",
                lambda index: record_rag_count(index_rag_batch(rag_cold_workspaces[index]), "cold"),
                lambda index: record_rag_count(index_rag_batch(rag_warm_workspaces[index]), "warm"),
                comparison_repetitions,
                cold_prepare=prepare_cold_rag,
                warm_prepare=prepare_warm_rag,
                cold_verify=lambda index: verify_rag_batch_case("cold", index),
                warm_verify=lambda index: verify_rag_batch_case("warm", index),
                definition="Each cold sample indexes its paired synthetic content in a fresh workspace; each warm sample reuses same paired content after untimed preparation in a separate workspace. Deterministic embeddings are fixtures; model inference is excluded.",
                workload_fingerprint=rag_batch_workload_fingerprint,
                sample_ids_by_regime=rag_batch_sample_ids_by_regime,
                sample_independence_protocol=_SAMPLE_INDEPENDENCE_PROTOCOL,
            )
            cold_seconds = sum(stages["hub_rag_batch_index"]["samples_by_regime"]["cold"]) / 1000.0
            warm_seconds = sum(stages["hub_rag_batch_index"]["samples_by_regime"]["warm"]) / 1000.0
            stages["hub_rag_batch_index"].update({
                "chunks_per_second": round(sum(rag_chunk_counts["cold"]) / cold_seconds, 3) if cold_seconds else 0.0,
                "chunks_per_second_by_regime": {
                    "cold": round(sum(rag_chunk_counts["cold"]) / cold_seconds, 3) if cold_seconds else 0.0,
                    "warm": round(sum(rag_chunk_counts["warm"]) / warm_seconds, 3) if warm_seconds else 0.0,
                },
                "processed_chunk_count_by_regime": {
                    "cold": sum(rag_chunk_counts["cold"]),
                    "warm": sum(rag_chunk_counts["warm"]),
                },
                "embedded_chunk_count_by_regime": {
                    "cold": sum(rag_embedded_chunk_counts["cold"]),
                    "warm": sum(rag_embedded_chunk_counts["warm"]),
                },
                "reused_chunk_count_by_regime": {
                    "cold": sum(rag_reused_chunk_counts["cold"]),
                    "warm": sum(rag_reused_chunk_counts["warm"]),
                },
                "workspace_count_by_regime": {
                    "cold": len(set(rag_cold_workspaces)),
                    "warm": len(set(rag_warm_workspaces)),
                },
                "requested_chunks_per_cold_sample": rag_chunks,
                "embedding_mode": "deterministic synthetic fixture; no model inference",
            })

            try:
                rag_batch_path.write_text("generation=memory0000000\n", encoding="utf-8")
                memory_measurement = _measure_python_allocation_peak(
                    lambda: index_rag_batch(rag_warm_workspaces[0]),
                )
            except Exception as exc:
                memory_measurement = {
                    "status": "failed",
                    "peak_python_allocated_bytes": None,
                    "error_type": type(exc).__name__,
                }
            memory_error = memory_measurement.get("error_type")
            stages["hub_rag_batch_index"]["memory"] = {
                "peak_python_allocated_bytes": memory_measurement.get("peak_python_allocated_bytes"),
                "scope": "python_allocation_peak",
                "status": memory_measurement["status"],
                **({"error_type": memory_error} if isinstance(memory_error, str) else {}),
                **({"reason": memory_measurement["reason"]} if isinstance(memory_measurement.get("reason"), str) else {}),
            }
            if memory_measurement["status"] == "failed":
                stages["hub_rag_batch_index"]["status"] = "failed"
                stages["hub_rag_batch_index"]["error_count"] += 1
                stages["hub_rag_batch_index"]["error_types"] = sorted(
                    set(stages["hub_rag_batch_index"]["error_types"]) | {str(memory_error)}
                )

            relevant_chunk_count = min(10, rag_chunks)
            quality_by_regime: dict[str, list[dict[str, Any]]] = {"cold": [], "warm": []}
            search_cache_by_regime: dict[str, list[bool]] = {"cold": [], "warm": []}
            query_embedding_calls_by_regime: dict[str, list[int]] = {"cold": [], "warm": []}
            expected_path = rag_batch_rel.replace("\\", "/")
            rag_search_corpus_generation = "memory0000000"
            rag_search_corpus_chunks = [
                f"synthetic-rag-{rag_search_corpus_generation}-{index}"
                + (" needle evidence" if index < relevant_chunk_count else "")
                for index in range(rag_chunks)
            ]
            rag_search_corpus_fingerprint = _stable_fingerprint({
                "source_generation": rag_search_corpus_generation,
                "relative_path": expected_path,
                "chunker_contract": rag_chunker_contract,
                "embedder_contract": rag_embedder_contract,
                "chunks": rag_search_corpus_chunks,
            })
            rag_search_workspaces = {
                "cold": f"t02-rag-search-cold-{uuid.uuid4().hex}",
                "warm": f"t02-rag-search-warm-{uuid.uuid4().hex}",
            }
            rag_batch_path.write_text(
                f"generation={rag_search_corpus_generation}\n", encoding="utf-8",
            )
            for workspace in rag_search_workspaces.values():
                index_rag_batch(workspace)

            rag_search_cases = []
            for case_number in range(comparison_repetitions):
                query = f"needle evidence search-case-{case_number:06d}"
                sample_fingerprint = _stable_fingerprint({
                    "stage": "hub_rag_search_case_v1",
                    "corpus_fingerprint": rag_search_corpus_fingerprint,
                    "query": query,
                    "top_k": 10,
                    "use_reranker": False,
                    "expected_relevant_chunk_numbers": list(range(relevant_chunk_count)),
                })
                rag_search_cases.append({
                    "query": query,
                    "sample_id": f"rag-search:{sample_fingerprint}",
                })
            rag_search_sample_ids = [case["sample_id"] for case in rag_search_cases]
            cold_rag_search_cases_seen: set[str] = set()
            rag_search_workload_fingerprint = _stable_fingerprint({
                "stage": "hub_rag_search_workload_v1",
                "corpus_fingerprint": rag_search_corpus_fingerprint,
                "top_k": 10,
                "use_reranker": False,
                "cases": rag_search_sample_ids,
                "cache_scope": {
                    "search_results": "isolated_by_workspace_and_revision",
                    "embeddings": "bypassed_by_deterministic_fixture",
                },
                "regime_contracts": {
                    "cold": "uncached query over isolated indexed fixture corpus; count fixture embedding calls",
                    "warm": "same query preseeded outside timing; search-cache hit must bypass fixture embedding call",
                },
            })

            def is_expected_path(value: Any) -> bool:
                path = str(value).replace("\\", "/")
                return path == expected_path or path.endswith("/" + expected_path)

            def retrieval_quality(result: dict[str, Any]) -> dict[str, Any]:
                results = result.get("results")
                if not isinstance(results, list):
                    raise RuntimeError("RAGStore.search returned no results list")
                expected_ids = set(range(relevant_chunk_count))
                retrieved_ids: set[int] = set()
                correct_path_count = 0
                dcg = 0.0
                for rank, item in enumerate(results[:10]):
                    if not isinstance(item, dict):
                        continue
                    correct_path = is_expected_path(item.get("path", ""))
                    correct_path_count += int(correct_path)
                    chunk_no = item.get("chunk_no")
                    relevant = correct_path and isinstance(chunk_no, int) and chunk_no in expected_ids
                    if relevant:
                        retrieved_ids.add(chunk_no)
                        dcg += 1.0 / math.log2(rank + 2)
                ideal_dcg = sum(1.0 / math.log2(rank + 2) for rank in range(relevant_chunk_count))
                return {
                    "recall_at_10": round(len(retrieved_ids) / relevant_chunk_count, 4),
                    "ndcg_at_10": round(dcg / ideal_dcg, 4) if ideal_dcg else 0.0,
                    "file_evidence_accuracy_at_10": round(
                        correct_path_count / max(1, min(10, len(results))), 4,
                    ),
                    "line_evidence_coverage_at_10": None,
                    "line_evidence_status": "unsupported_no_line_offsets",
                    "returned_result_count": min(10, len(results)),
                }

            def rag_search(query: str, regime: str) -> dict[str, Any]:
                calls_before = rag_query_embedding_calls
                result = app.rag.search(
                    query, "t02-benchmark", rag_search_workspaces[regime], top_k=10,
                    use_reranker=False, priority=3,
                )
                if result.get("success") is True:
                    quality_by_regime[regime].append(retrieval_quality(result))
                    cache_info = result.get("search_cache")
                    search_cache_by_regime[regime].append(
                        bool(cache_info.get("hit")) if isinstance(cache_info, dict) else False
                    )
                query_embedding_calls_by_regime[regime].append(
                    rag_query_embedding_calls - calls_before
                )
                return result

            def prepare_cold_rag_search(index: int) -> dict[str, Any]:
                case = rag_search_cases[index]
                sample_id = case["sample_id"]
                if sample_id in cold_rag_search_cases_seen:
                    return {"success": False}
                cold_rag_search_cases_seen.add(sample_id)
                return _preparation_receipt(
                    sample_id, "cold_case_unseen",
                )

            def prepare_warm_rag_search(index: int) -> dict[str, Any]:
                case = rag_search_cases[index]
                result = app.rag.search(
                    case["query"], "t02-benchmark",
                    rag_search_workspaces["warm"], top_k=10, use_reranker=False, priority=3,
                )
                if result.get("success") is not True:
                    raise RuntimeError("RAG search warm preparation failed synthetic case")
                return _preparation_receipt(
                    case["sample_id"], "warm_exact_case_primed",
                )

            def verify_rag_search_cache_case(regime: str, index: int) -> dict[str, Any]:
                from local_ai_hub.cache import stable_hash as cache_stable_hash
                from local_ai_hub.normalizer import normalize_query

                case = rag_search_cases[index]
                workspace = rag_search_workspaces[regime]
                clean_query = normalize_query(case["query"])
                revision = app.rag.revision("t02-benchmark", workspace)
                scope_key = app.rag._scope_key("t02-benchmark")
                with closing(app.rag._connect()) as con:
                    generation = app.rag._workspace_index_generation(con, scope_key, workspace)
                cache_identity_known = app.rag._embedding_space_cache_identity_known()
                embedding_space = app.rag._embedding_space_id()
                embedding_dimension = app.rag._embedding_dimension_cache_identity()
                cache_key = cache_stable_hash({
                    "tenant": "t02-benchmark",
                    "scope": app.rag.scope,
                    "effective_scope": scope_key,
                    "workspace": workspace,
                    "revision": revision,
                    "generation": generation,
                    "query": clean_query,
                    "top_k": 10,
                    "reranker": False,
                    "scope_path": None,
                    "embedding_space": embedding_space if cache_identity_known else None,
                    "embedding_dimension": embedding_dimension,
                })
                l1_value = app.rag.search_cache.l1.get(cache_key)
                l2_value = app.rag.search_cache.l2.get(cache_key)
                l1_present = l1_value is not None
                l2_present = l2_value is not None
                cache_present = l1_present or l2_present
                if cache_present != (regime == "warm"):
                    return {"success": False}
                status = "cold_case_unseen" if regime == "cold" else "warm_exact_case_primed"
                return _preparation_observation(
                    case["sample_id"], status,
                    {
                        "workspace": workspace,
                        "revision": revision,
                        "query": clean_query,
                        "l1_present": l1_present,
                        "l2_present": l2_present,
                    },
                )

            stages["hub_rag_search"] = _measure_stage_regimes(
                "RAGStore.search top_k=10 without reranker; deterministic fixture embeddings",
                lambda index: rag_search(rag_search_cases[index]["query"], "cold"),
                lambda index: rag_search(rag_search_cases[index]["query"], "warm"),
                comparison_repetitions,
                cold_prepare=prepare_cold_rag_search,
                warm_prepare=prepare_warm_rag_search,
                cold_verify=lambda index: verify_rag_search_cache_case("cold", index),
                warm_verify=lambda index: verify_rag_search_cache_case("warm", index),
                definition="Cold and warm groups use identical unique query cases and identical indexed fixture corpora in separate workspaces; warm queries are preseeded outside timing. Search-result cache hits and fixture embedding calls are measured separately. The deterministic embedding fixture bypasses the persistent service embedding cache. Model inference and production relevance are excluded.",
                workload_fingerprint=rag_search_workload_fingerprint,
                sample_ids_by_regime={
                    "cold": rag_search_sample_ids,
                    "warm": list(rag_search_sample_ids),
                },
                sample_independence_protocol=_SAMPLE_INDEPENDENCE_PROTOCOL,
            )

            def average_quality(regime: str) -> dict[str, Any]:
                measured = quality_by_regime[regime]
                return {
                    field: round(sum(float(item[field]) for item in measured) / len(measured), 4)
                    if measured else None
                    for field in (
                        "recall_at_10", "ndcg_at_10", "file_evidence_accuracy_at_10",
                    )
                } | {
                    "line_evidence_coverage_at_10": None,
                    "line_evidence_status": "unsupported_no_line_offsets",
                    "sample_count": len(measured),
                    "returned_result_count": max(
                        (int(item["returned_result_count"]) for item in measured), default=0,
                    ),
                }

            combined_quality = [*quality_by_regime["cold"], *quality_by_regime["warm"]]
            stages["hub_rag_search"].update({
                "ranking_metrics": {
                    field: round(sum(float(item[field]) for item in combined_quality) / len(combined_quality), 4)
                    if combined_quality else None
                    for field in (
                        "recall_at_10", "ndcg_at_10", "file_evidence_accuracy_at_10",
                    )
                } | {
                    "line_evidence_coverage_at_10": None,
                    "line_evidence_status": "unsupported_no_line_offsets",
                    "sample_count": len(combined_quality),
                },
                "ranking_metrics_by_regime": {
                    regime: average_quality(regime) for regime in ("cold", "warm")
                },
                "search_cache_hits_by_regime": {
                    regime: sum(search_cache_by_regime[regime])
                    for regime in ("cold", "warm")
                },
                "search_cache_scope": "isolated_by_workspace_and_revision",
                "embedding_cache_scope": "bypassed_by_deterministic_fixture",
                "query_embedding_calls_by_regime": {
                    regime: sum(query_embedding_calls_by_regime[regime])
                    for regime in ("cold", "warm")
                },
                "quality_scope": "synthetic_fixture_only",
                "embedding_mode": "deterministic synthetic fixture; no model inference",
                "expected_relevant_chunk_count_at_10": relevant_chunk_count,
            })
        finally:
            app.rag._chunks = original_rag_chunks
            app.services.embed = original_embed
            if had_original_service_space_id:
                app.services.space_id = original_service_space_id
            else:
                delattr(app.services, "space_id")

        cold_seed_targets: dict[int, Path] = {}
        warm_seed_targets: dict[int, Path] = {}
        seeded_rows: dict[str, int] = {}

        def prepare_cold_seed(index: int) -> dict[str, Any]:
            target = scratch / "worktree-seed-cold" / f"target-{index}"
            target.mkdir(parents=True, exist_ok=True)
            if any(target.iterdir()):
                return {"success": False}
            cold_seed_targets[index] = target
            return _preparation_receipt(
                parent_seed_sample_ids[index], "cold_case_unseen",
            )

        def seed_parent(target: Path) -> dict[str, Any]:
            result = app.preprocessor._seed_from_parent(str(target), str(repo_root))
            seeded_rows.update({key: int(value) for key, value in result.items()})
            if int(result.get("code_index", 0)) < 1:
                raise RuntimeError("parent seed did not copy synthetic CodeIndex rows")
            return {"success": True, "seeded_rows": result}

        def prepare_warm_seed(index: int) -> dict[str, Any]:
            target = scratch / "worktree-seed-warm" / f"target-{index}"
            target.mkdir(parents=True, exist_ok=True)
            warm_seed_targets[index] = target
            seed_parent(target)
            return _preparation_receipt(
                parent_seed_sample_ids[index], "warm_exact_case_primed",
            )

        def verify_seed_case(regime: str, index: int) -> dict[str, Any]:
            target = cold_seed_targets[index] if regime == "cold" else warm_seed_targets[index]
            if target is None or not target.exists():
                return {"success": False}
            root = str(target.resolve())
            with closing(app.code_index._connect()) as con:
                file_rows = int(con.execute(
                    "SELECT COUNT(*) FROM files WHERE root=?", (root,),
                ).fetchone()[0])
            empty_target = not any(target.iterdir())
            if regime == "cold" and (file_rows != 0 or not empty_target):
                return {"success": False}
            if regime == "warm" and file_rows < 1:
                return {"success": False}
            status = "cold_case_unseen" if regime == "cold" else "warm_exact_case_primed"
            return _preparation_observation(
                parent_seed_sample_ids[index], status,
                {"root": root, "file_rows": file_rows, "empty_target": empty_target},
            )

        parent_seed_sample_ids = [
            f"parent-seed:benchmark-owned-code-index:{index:06d}"
            for index in range(comparison_repetitions)
        ]
        parent_seed_workload_fingerprint = _stable_fingerprint({
            "stage": "parent_worktree_seed_cases_v1",
            "source": "benchmark-parent-code-index",
            "cold_destination": "empty-synthetic-worktree",
            "warm_destination": "preseeded-synthetic-worktree",
            "sample_count": comparison_repetitions,
        })
        stages["parent_worktree_seed"] = _measure_stage_regimes(
            "ProjectPreprocessor._seed_from_parent",
            lambda index: seed_parent(cold_seed_targets[index]),
            lambda index: seed_parent(warm_seed_targets[index]),
            comparison_repetitions,
            cold_prepare=prepare_cold_seed,
            warm_prepare=prepare_warm_seed,
            cold_verify=lambda index: verify_seed_case("cold", index),
            warm_verify=lambda index: verify_seed_case("warm", index),
            definition="Copies only benchmark-owned parent CodeIndex rows into synthetic worktree roots; cold destinations are empty, warm destination is preseeded. Paired IDs identify same numbered copy observation.",
            workload_fingerprint=parent_seed_workload_fingerprint,
            sample_ids_by_regime={
                "cold": parent_seed_sample_ids,
                "warm": parent_seed_sample_ids,
            },
            sample_independence_protocol=_SAMPLE_INDEPENDENCE_PROTOCOL,
        )
        stages["parent_worktree_seed"]["seeded_rows"] = seeded_rows

        stages["serena_pool_latency"] = _skipped_stage(
            "No Serena session-pool adapter is exposed by the synthetic LocalAIApp benchmark."
        )
        stages["hub_backend_selection"] = _skipped_stage(
            "Optional-backend selection planner is not exposed by this LocalAIApp snapshot."
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
        context_pack_cases = [
            {
                "sample_id": f"context-pack:{path.relative_to(repo_root).as_posix()}:{_synthetic_query_symbol(index)}",
                "query": _synthetic_query_symbol(index),
                "expected_symbol": _synthetic_query_symbol(index),
            }
            for index, path in enumerate(files[:comparison_repetitions])
        ]
        has_paired_context_pack_plan = len(context_pack_cases) == comparison_repetitions
        cold_context_cases_seen: set[str] = set()

        def context_pack_request_for_regime(index: int, regime: str) -> _HTTPObservation:
            case = context_pack_cases[index]
            query = f"{case['query']} t02_{regime}_sample_{index}"
            response = context_request(query)
            context_text = response.payload.get("context")
            if not isinstance(context_text, str) or not _contains_identifier(
                context_text, case["expected_symbol"],
            ):
                raise RuntimeError(f"Context pack query missed synthetic case {case['sample_id']}")
            return response

        def prepare_cold_context_pack_case(index: int) -> dict[str, Any]:
            case = context_pack_cases[index]
            sample_id = f"{case['sample_id']}:cold"
            if sample_id in cold_context_cases_seen:
                return {"success": False}
            cold_context_cases_seen.add(sample_id)
            return _preparation_receipt(
                f"{case['sample_id']}:cold", "cold_case_unseen",
            )

        def prepare_warm_context_pack_case(index: int) -> dict[str, Any]:
            case = context_pack_cases[index]
            context_pack_request_for_regime(index, "warm")
            return _preparation_receipt(
                f"{case['sample_id']}:warm", "warm_exact_case_primed",
            )

        def verify_context_pack_case(regime: str, index: int) -> dict[str, Any]:
            from local_ai_hub.cache import stable_hash as cache_stable_hash

            case = context_pack_cases[index]
            query = f"{case['query']} t02_{regime}_sample_{index}"
            dcfg = app.config.get("deterministic", {})
            char_budget = min(
                int(dcfg.get("context_max_chars", 5200)), max(900, 512 * 4),
            )
            params = {
                "query": query,
                "max_chars": char_budget,
                "raw": int(dcfg.get("context_raw_evidence", 5)),
            }
            try:
                state = app.services._repo_cache_state(str(repo_root))
                state_fingerprint = state.get("fingerprint") if isinstance(state, dict) else None
                if not isinstance(state_fingerprint, str) or not state_fingerprint:
                    return {"success": False}
                cache_key = cache_stable_hash({
                    "op": "fast-context", "state": state_fingerprint, "params": params,
                })
                cached = app.services.repo_cache.get(cache_key)
            except Exception:
                return {"success": False}
            cache_present = cached is not None
            context_text = cached.get("context") if isinstance(cached, dict) else None
            symbol_found = isinstance(context_text, str) and _contains_identifier(
                context_text, case["expected_symbol"],
            )
            if cache_present != (regime == "warm") or (
                regime == "warm"
                and (not isinstance(cached, dict) or cached.get("success") is not True or not symbol_found)
            ):
                return {"success": False}
            status = "cold_case_unseen" if regime == "cold" else "warm_exact_case_primed"
            return _preparation_observation(
                f"{case['sample_id']}:{regime}", status,
                {
                    "query": query,
                    "operation": "fast-context",
                    "cache_key": cache_key,
                    "repository_fingerprint": state_fingerprint,
                    "cache_entry_present": cache_present,
                    "expected_symbol_found": symbol_found,
                    "context_fingerprint": _stable_fingerprint({"context": context_text})
                    if isinstance(context_text, str) else None,
                },
            )

        if has_paired_context_pack_plan:
            context_pack_sample_ids_by_regime = {
                regime: [f"{case['sample_id']}:{regime}" for case in context_pack_cases]
                for regime in ("cold", "warm")
            }
            context_pack_workload_fingerprint = _stable_fingerprint({
                "stage": "context_pack_query_cases_v1",
                "cases": [
                    {
                        "sample_id": case["sample_id"],
                        "cold_query": f"{case['query']} t02_cold_sample_{index}",
                        "warm_query": f"{case['query']} t02_warm_sample_{index}",
                        "expected_symbol": case["expected_symbol"],
                    }
                    for index, case in enumerate(context_pack_cases)
                ],
                "mode": "fast",
                "include_code": False,
            })
            stages["hub_context_pack"] = _measure_stage_regimes(
                "POST /api/context/pack unguarded fast mode; exact HTTP response body bytes",
                lambda index: context_pack_request_for_regime(index, "cold"),
                lambda index: context_pack_request_for_regime(index, "warm"),
                comparison_repetitions,
                cold_prepare=prepare_cold_context_pack_case,
                warm_prepare=prepare_warm_context_pack_case,
                cold_verify=lambda index: verify_context_pack_case("cold", index),
                warm_verify=lambda index: verify_context_pack_case("warm", index),
                definition="Cold and warm groups use distinct synthetic symbol query keys per module path; warm primes that exact key before timing. No OS cache flush.",
                workload_fingerprint=context_pack_workload_fingerprint,
                sample_ids_by_regime=context_pack_sample_ids_by_regime,
                sample_independence_protocol=_SAMPLE_INDEPENDENCE_PROTOCOL,
            )
        else:
            stages["hub_context_pack"] = _measure_stage_regimes(
                "POST /api/context/pack unguarded fast mode; exact HTTP response body bytes",
                lambda index: context_request(f"symbol_0 context coldprobe_{index}"),
                lambda _index: context_request(warm_context_query),
                comparison_repetitions,
                warm_prepare=lambda _index: context_request(warm_context_query),
                definition="Unpaired cold/warm probes used because synthetic modules do not provide enough distinct symbol cases; no sample identities asserted. No OS cache flush.",
            )

        def concurrent_context_pack_request(level: int, repetition: int, slot: int) -> _HTTPObservation:
            query = f"symbol_0 concurrency_{level}_{repetition}_{slot}"
            return context_request(query)

        stages["hub_context_pack"]["service_concurrency"] = _measure_concurrent_service(
            "concurrent valid POST /api/context/pack requests",
            concurrent_context_pack_request,
            concurrency=concurrency,
            repetitions=comparison_repetitions,
        )

        expected_affected_test = test_path.relative_to(repo_root).as_posix()
        affected_index_seed = app.code_index.update_files_batch(
            str(repo_root), [expected_affected_test],
        )
        affected_operation: dict[str, Any] = {}
        affected_operation_error: str | None = None
        try:
            affected_operation = app.services.affected_tests(
                str(repo_root), changed_paths=[relative_files[0]],
            )
        except Exception as exc:
            affected_operation_error = type(exc).__name__
        if not isinstance(affected_operation, dict):
            affected_operation_error = affected_operation_error or type(affected_operation).__name__
            affected_operation = {}
        affected_observed_tests = affected_operation.get("test_files", [])
        if not isinstance(affected_observed_tests, list):
            affected_observed_tests = []
        affected_normalized_tests = [
            str(value).replace("\\", "/").removeprefix(f"{repo_root.as_posix()}/")
            for value in affected_observed_tests
            if isinstance(value, str)
        ]
        affected_golden_passed = (
            isinstance(affected_index_seed, dict)
            and affected_index_seed.get("success") is True
            and affected_operation.get("success") is True
            and expected_affected_test in affected_normalized_tests
        )
        retrieval_matches = _retrieve_relevant(corpus_path, "needle")
        generated = "def generated_answer(value: int) -> int:\n    return value + 1\n"
        try:
            generated_tree = ast.parse(generated)
            codegen_ok = any(isinstance(node, ast.FunctionDef) and node.name == "generated_answer" for node in generated_tree.body)
        except SyntaxError:
            codegen_ok = False
        expected_relevant_count = sum(1 for index in range(rag_chunks) if index % 997 == 7)
        rag_fixture_input_fingerprint = _stable_fingerprint({
            "fixture": "synthetic-jsonl-keyword-relevance-v1",
            "rag_chunks": rag_chunks,
            "query": "needle",
            "expected_relevant_count": expected_relevant_count,
        })
        rag_fixture_sample_ids = [
            f"rag-fixture-relevance:{rag_fixture_input_fingerprint}:{index:06d}"
            for index in range(comparison_repetitions)
        ]
        rag_fixture_workload_fingerprint = _stable_fingerprint({
            "stage": "synthetic_jsonl_relevance_cases_v1",
            "fixture_ids": rag_fixture_sample_ids,
            "scope": "keyword fixture scan only",
        })

        def synthetic_retrieval_sample(_index: int) -> dict[str, Any]:
            matches = _retrieve_relevant(corpus_path, "needle")
            return {
                "success": len(matches) == expected_relevant_count,
                "expected_relevant_count": expected_relevant_count,
                "observed_relevant_count": len(matches),
            }

        stages["hub_rag_fixture_relevance"] = _measure_stage_regimes(
            "synthetic JSONL relevance fixture scan",
            synthetic_retrieval_sample,
            synthetic_retrieval_sample,
            comparison_repetitions,
            definition="Synthetic keyword fixture relevance only; no semantic retrieval, ranking, embeddings, or model quality is inferred.",
            workload_fingerprint=rag_fixture_workload_fingerprint,
            sample_ids_by_regime={
                "cold": rag_fixture_sample_ids,
                "warm": rag_fixture_sample_ids,
            },
            sample_independence_protocol=_SAMPLE_STATELESS_PROTOCOL,
        )
        stages["hub_rag_fixture_relevance"].update({
            "expected_relevant_count": expected_relevant_count,
            "observed_relevant_count": len(retrieval_matches),
            "quality_scope": "synthetic_fixture_only",
        })

        synthetic_checks = {
            "symbols": {"passed": "symbol_0" in _ast_index(files), "expected_name": "symbol_0"},
            "graph": {"passed": graph_edge_found, "expected_edge": expected_graph_edge, "measurement": "CodeIndex.find_callers_and_find_callees"},
            "affected_tests": {"passed": affected_golden_passed, "expected_test": "test_graph_target_returns_value"},
            "retrieval_relevance": {
                "passed": all(
                    stages["hub_rag_search"]["ranking_metrics"].get(metric) == 1.0
                    for metric in (
                        "recall_at_10", "ndcg_at_10", "file_evidence_accuracy_at_10",
                    )
                ),
                "expected_relevant_chunk_count_at_10": relevant_chunk_count,
                "ranking_metrics": stages["hub_rag_search"]["ranking_metrics"],
                "fixture_scan": {
                    "expected_relevant_count": expected_relevant_count,
                    "observed_relevant_count": len(retrieval_matches),
                },
                "quality_scope": "synthetic_fixture_only",
            },
            "code_generation": {"passed": codegen_ok, "expected_function": "generated_answer"},
        }
        golden = {
            "symbols": {"passed": symbol_passed, "expected_name": "symbol_0"},
            "context_pack": {"passed": context_passed, "expected": {"http_status": 200, "context": "string", "guarded": False}},
            "graph": {
                "passed": graph_edge_found,
                "expected_edge": expected_graph_edge,
                "measurement": "CodeIndex.find_callers and CodeIndex.find_callees over synthetic AST edge",
            },
            "affected_tests": {
                "status": "passed" if affected_golden_passed else "failed",
                "passed": affected_golden_passed,
                "expected_test": expected_affected_test,
                "observed_tests": affected_normalized_tests,
                "measurement": "Services.affected_tests over indexed synthetic import edge",
                **({"error_type": affected_operation_error} if affected_operation_error else {}),
            },
            "retrieval_relevance": {
                "status": "passed" if all(
                    stages["hub_rag_search"].get("ranking_metrics", {}).get(metric) == 1.0
                    for metric in ("recall_at_10", "ndcg_at_10", "file_evidence_accuracy_at_10")
                ) else "failed",
                "passed": all(
                    stages["hub_rag_search"].get("ranking_metrics", {}).get(metric) == 1.0
                    for metric in ("recall_at_10", "ndcg_at_10", "file_evidence_accuracy_at_10")
                ),
                "expected_relevant_chunk_count_at_10": relevant_chunk_count,
                "observed_relevant_chunk_count": len(retrieval_matches),
                "ranking_metrics": stages["hub_rag_search"].get("ranking_metrics", {}),
                "quality_scope": "synthetic_fixture_golden",
            },
            "code_generation": {"status": "skipped_unavailable", "expected_function": "generated_answer", "reason": "No model-backed code generation runs; AST fixture result is isolated under synthetic_checks."},
            "vision": {"status": "skipped_unavailable", "expected": "structured vision result", "reason": "No vision request or inference backend runs in this benchmark."},
            "speech": {"status": "skipped_unavailable", "expected": "transcription result", "reason": "No speech request or inference backend runs in this benchmark."},
        }
        if include_inference and include_quality_goldens:
            staged_speech_fixture = (
                _stage_speech_golden_fixture(speech_fixture, scratch)
                if speech_fixture is not None else None
            )
            golden.update(_run_model_quality_goldens(
                app.services,
                speech_fixture=staged_speech_fixture,
                speech_expected_text=speech_expected_text,
                sample_vram=True,
                vram_samples=inference_vram_samples,
            ))

        rag_chunk_cases = [
            {
                "sample_id": f"rag-chunk:{path.relative_to(repo_root).as_posix()}",
                "path": path,
                "content": path.read_text(encoding="utf-8"),
            }
            for path in files[:comparison_repetitions]
        ]
        has_paired_rag_chunk_plan = len(rag_chunk_cases) == comparison_repetitions

        def chunk_synthetic_source(index: int) -> dict[str, int]:
            case = rag_chunk_cases[index]
            return {"chunk_count": len(app.rag._chunks(case["content"], case["path"].name))}

        if has_paired_rag_chunk_plan:
            rag_chunk_sample_ids = [case["sample_id"] for case in rag_chunk_cases]
            rag_chunk_workload_fingerprint = _stable_fingerprint({
                "stage": "rag_chunk_source_cases_v1",
                "cases": [
                    {
                        "sample_id": case["sample_id"],
                        "content_sha256": hashlib.sha256(case["content"].encode("utf-8")).hexdigest(),
                    }
                    for case in rag_chunk_cases
                ],
            })
            stages["hub_rag_chunking"] = _measure_stage_regimes(
                "RAGStore._chunks_chunker_only",
                chunk_synthetic_source,
                chunk_synthetic_source,
                comparison_repetitions,
                definition="Same synthetic source file case per paired observation; direct pure chunker calls, no cache. Excludes retrieval, embeddings, reranking, and model inference.",
                workload_fingerprint=rag_chunk_workload_fingerprint,
                sample_ids_by_regime={"cold": rag_chunk_sample_ids, "warm": rag_chunk_sample_ids},
                sample_independence_protocol=_SAMPLE_STATELESS_PROTOCOL,
            )
        else:
            rag_sample = files[0].read_text(encoding="utf-8")
            stages["hub_rag_chunking"] = _measure_stage_regimes(
                "RAGStore._chunks_chunker_only",
                lambda _index: {"chunk_count": len(app.rag._chunks(rag_sample, files[0].name))},
                lambda _index: {"chunk_count": len(app.rag._chunks(rag_sample, files[0].name))},
                comparison_repetitions,
                definition="Unpaired direct LocalAIApp RAGStore._chunks calls on one synthetic source file because corpus lacks enough distinct cases; no sample identities asserted.",
            )

        def queue_admission_attempt(sample_id: str) -> tuple[float, str | None, str | None, dict[str, Any] | None, str | None]:
            queued_at = time.perf_counter()
            error_type: str | None = None
            error_reason: str | None = None
            error_code: str | None = None
            submitted: Any = None
            cancelled: Any = None
            try:
                task_id = f"benchmark-{uuid.uuid4().hex}"
                submitted = app.async_jobs.submit(
                    "benchmark", "reason", {"task_id": task_id, "task": "T02 queue admission probe"},
                    dispatch_delay_seconds=30.0,
                )
                if (
                    isinstance(submitted, dict)
                    and submitted.get("success") is True
                    and submitted.get("job_id")
                ):
                    cancelled = app.async_jobs.cancel("benchmark", str(submitted["job_id"]))
                    error_reason = _queue_admission_error_reason(submitted, cancelled)
                    error_code = cancellation_failure_code(cancelled)
                else:
                    error_reason = _queue_admission_error_reason(submitted)
                    error_code = admission_failure_code(submitted)
                if error_reason is not None:
                    error_type = "RuntimeError"
            except Exception as exc:
                error_type = type(exc).__name__
                error_reason = f"exception_{error_type}"
            elapsed_ms = (time.perf_counter() - queued_at) * 1000.0
            diagnostic: dict[str, Any] | None = None
            if error_type is not None:
                diagnostic_error_types: dict[str, str] = {}
                job_id = submitted.get("job_id") if isinstance(submitted, dict) else None
                observed_status: Any = None
                manager_stats: Any = None
                if isinstance(job_id, str) and job_id:
                    try:
                        observed_status = app.async_jobs.status("benchmark", job_id)
                    except Exception as exc:
                        diagnostic_error_types["status"] = type(exc).__name__
                try:
                    manager_stats = app.async_jobs.stats()
                except Exception as exc:
                    diagnostic_error_types["stats"] = type(exc).__name__
                try:
                    source_revision = _revision()
                except Exception as exc:
                    source_revision = None
                    diagnostic_error_types["revision"] = type(exc).__name__
                diagnostic = _queue_admission_failure_diagnostic(
                    sample_id,
                    source_revision=source_revision,
                    submitted=submitted,
                    cancelled=cancelled,
                    status=observed_status,
                    manager_stats=manager_stats,
                    error_type=error_type,
                    error_reason=error_reason,
                    diagnostic_error_types=diagnostic_error_types,
                )
            return elapsed_ms, error_type, error_reason, diagnostic, error_code

        queue_samples: list[float] = []
        queue_cold_samples: list[float] = []
        queue_warm_samples: list[float] = []
        queue_sample_ids_by_regime: dict[str, list[str]] = {"cold": [], "warm": []}
        queue_workload_fingerprint = _stable_fingerprint({
            "measurement": "async_jobs_submit_cancel_admission_only",
            "concurrency_levels": sorted(concurrency),
            "sample_identity_unit": "concurrency_repetition_slot",
            "definition": "Each async job uses delayed dispatch and immediate cancellation; queue returns to empty per sample. Worker service is excluded.",
        })
        queue_error_types: set[str] = set()
        queue_error_codes: set[str] = set()
        queue_error_reasons: dict[str, int] = {}
        queue_error_count = 0
        queue_measurements: dict[str, Any] = {}
        queue_failure_diagnostics: list[dict[str, Any]] = []
        queue_failure_diagnostic_limit = 16
        total_admissions = 0
        total_batch_seconds = 0.0
        for level in concurrency:
            level_samples: list[float] = []
            level_errors = 0
            level_error_reasons: dict[str, int] = {}
            level_codes: set[str] = set()
            level_batch_seconds = 0.0
            for repetition_index in range(light_repetitions):
                batch_started = time.perf_counter()
                sample_ids = [
                    f"queue-admission:level-{level}:iteration-{repetition_index}:slot-{slot_index}"
                    for slot_index in range(level)
                ]
                with ThreadPoolExecutor(max_workers=level) as pool:
                    outcomes = list(pool.map(queue_admission_attempt, sample_ids))
                batch_seconds = time.perf_counter() - batch_started
                level_batch_seconds += batch_seconds
                total_batch_seconds += batch_seconds
                total_admissions += level
                regime = "cold" if repetition_index == 0 else "warm"
                for sample_id, (elapsed_ms, error_type, error_reason, diagnostic, error_code) in zip(sample_ids, outcomes):
                    level_samples.append(elapsed_ms)
                    queue_samples.append(elapsed_ms)
                    (queue_cold_samples if repetition_index == 0 else queue_warm_samples).append(elapsed_ms)
                    queue_sample_ids_by_regime[regime].append(sample_id)
                    if error_code:
                        level_codes.add(error_code)
                        queue_error_codes.add(error_code)
                    if error_type:
                        level_errors += 1
                        queue_error_count += 1
                        queue_error_types.add(error_type)
                        reason = error_reason or "unknown"
                        queue_error_reasons[reason] = queue_error_reasons.get(reason, 0) + 1
                        level_error_reasons[reason] = level_error_reasons.get(reason, 0) + 1
                        if diagnostic is not None and len(queue_failure_diagnostics) < queue_failure_diagnostic_limit:
                            queue_failure_diagnostics.append(diagnostic)
            queue_measurements[str(level)] = {
                **summarize_samples(level_samples),
                "error_count": level_errors,
                "error_codes": sorted(level_codes),
                "error_rate_pct": round(level_errors * 100.0 / max(1, len(level_samples)), 3),
                "error_reasons": dict(sorted(level_error_reasons.items())),
                "concurrent_admissions_per_second": round(level * light_repetitions / level_batch_seconds, 3) if level_batch_seconds else None,
                "cold_warm": _cold_warm_summary(level_samples),
            }
        stages["hub_queue_admission"] = {
            "status": "passed" if queue_error_count == 0 else "failed",
            **summarize_samples(queue_samples),
            "samples_ms": queue_samples,
            "samples_by_regime": {"cold": queue_cold_samples, "warm": queue_warm_samples},
            "sample_ids_by_regime": queue_sample_ids_by_regime,
            "workload_fingerprint": queue_workload_fingerprint,
            "sample_identity_provenance": _sample_identity_provenance(queue_workload_fingerprint),
            "sample_identity_unit": "concurrency_repetition_slot",
            "sample_independence_status": "not_established",
            "sample_independence_note": "Stable slot labels establish pairing only; they do not prove independent scheduler or cache epochs.",
            "cold_warm": {
                "cold": summarize_samples(queue_cold_samples),
                "warm": summarize_samples(queue_warm_samples),
                "definition": "Each async job uses delayed dispatch and immediate cancellation; queue returns to empty per sample. Worker service is excluded.",
            },
            "error_count": queue_error_count,
            "error_rate_pct": round(queue_error_count * 100.0 / max(1, len(queue_samples)), 3),
            "error_types": sorted(queue_error_types),
            "error_codes": sorted(queue_error_codes),
            "error_reasons": dict(sorted(queue_error_reasons.items())),
            "failed_sample_count": queue_error_count,
            "failed_samples": queue_failure_diagnostics,
            "failed_samples_truncated": queue_error_count > len(queue_failure_diagnostics),
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
                before_vram = _sample_dedicated_vram_bytes()
                if before_vram is not None:
                    inference_vram_samples.append(before_vram)
                try:
                    result = inference_runner.run(
                        model="", prompt="Return only the word OK.", num_tokens=8,
                    )
                finally:
                    after_vram = _sample_dedicated_vram_bytes()
                    if after_vram is not None:
                        inference_vram_samples.append(after_vram)
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
            stages["inference"] = _measure_stage("explicit_hardware_benchmark_runner", run_inference, comparison_repetitions)
            stages["inference"]["reported_metrics"] = {
                name: summarize_samples(values) for name, values in inference_metrics.items()
            }
            stages["inference_queue_wait"] = _skipped_stage(
                "hardware benchmark runner does not report scheduler queue wait",
            )
            if len(inference_load_samples) == comparison_repetitions:
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
            if len(inference_model_digests) == comparison_repetitions and len(set(inference_model_digests)) == 1:
                inference_model_digest = f"sha256:{inference_model_digests[0]}"

        t12_acceptance = None
        if include_t12_matrix:
            t12_acceptance = _run_t12_matrix(
                inference_runner,
                repetitions=comparison_repetitions,
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
            "light_repetitions": light_repetitions, "comparison_repetitions": comparison_repetitions,
            "concurrency": list(concurrency), "full": full, "inference": include_inference,
            "t12_matrix": include_t12_matrix,
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
        synthetic_files = synthetic.get("files")
        recorded_file_count = len(synthetic_files) if isinstance(synthetic_files, list) else None
        recorded_rag_chunk_count: int | None = None
        corpus_path = synthetic.get("corpus_path")
        if isinstance(corpus_path, Path):
            try:
                with corpus_path.open("r", encoding="utf-8") as corpus_file:
                    recorded_rag_chunk_count = sum(1 for _ in corpus_file)
            except OSError:
                pass
        input_provenance = _synthetic_input_provenance(
            input_seed,
            synthetic["input_fingerprint"],
        )
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
            "runtime_source_root": str(runtime_source_root),
            "workload_fingerprint": _stable_fingerprint({
                "benchmark_scope": "hub_app_synthetic_repo_plus_hardware_inference" if include_inference else "hub_app_synthetic_repo",
                "synthetic_file_count": recorded_file_count,
                "rag_chunk_count": recorded_rag_chunk_count,
                **input_provenance,
                "repetitions": repetitions,
                "stage_repetitions": {"light": light_repetitions, "comparison": comparison_repetitions},
                "concurrency": list(concurrency),
                "full": full,
                "inference_model_digest": inference_model_digest,
                "quality_goldens": bool(include_quality_goldens),
                "speech_golden_fixture": speech_identity,
            }),
            "config_fingerprint": _config_fingerprint(config),
            "hardware_fingerprint": hashlib.sha256(json.dumps(machine, sort_keys=True).encode()).hexdigest(),
            "platform": machine,
            "full": full,
            "synthetic_file_count": recorded_file_count,
            "rag_chunk_count": recorded_rag_chunk_count,
            **input_provenance,
            "repetitions": repetitions,
            "stage_repetitions": {"light": light_repetitions, "comparison": comparison_repetitions},
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
            "t12_matrix": "requested" if include_t12_matrix else "skipped_not_requested",
            "t12_acceptance_status": t12_acceptance.get("status") if t12_acceptance is not None else "not_requested",
            "inference_model": inference_model,
            "inference_model_digest": inference_model_digest,
            "quality_goldens": bool(include_quality_goldens),
            "speech_golden_fixture": speech_identity,
        }
        metadata["sample_identity_provenance"] = _sample_identity_provenance(metadata["workload_fingerprint"])
        for stage_name, stage in stages.items():
            if isinstance(stage, dict) and not isinstance(stage.get("workload_fingerprint"), str):
                stage_definition = stage.get("cold_warm", {})
                stage["workload_fingerprint"] = _stable_fingerprint({
                    "workload_fingerprint": metadata["workload_fingerprint"],
                    "stage": stage_name,
                    "measurement": stage.get("measurement"),
                    "definition": stage_definition.get("definition") if isinstance(stage_definition, dict) else None,
                })
        metadata["baseline_readiness_reasons"] = _plan_grade_reasons(metadata, stages)
        peak_rss = _peak_rss_bytes()
        peak_vram = max(inference_vram_samples) if inference_vram_samples else None
        resource_usage = {
            "peak_rss_bytes": peak_rss,
            "peak_vram_bytes": peak_vram,
            "availability": {
                "peak_rss_bytes": "measured" if peak_rss is not None else "platform_unavailable",
                "peak_vram_bytes": "measured_at_inference_boundaries" if peak_vram is not None else "not_measured_no_dedicated_gpu_telemetry",
                "peak_vram_scope": "maximum_observed_before_or_after_hardware_and_model_quality_inference",
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
        skipped_golden = sorted(
            name for name, item in golden.items()
            if isinstance(item, dict) and item.get("status") == "skipped_unavailable"
        )
        record = {
            "success": success,
            "metadata": metadata,
            "stages": stages,
            "golden": golden,
            "synthetic_checks": synthetic_checks,
            "quality": {
                "score_pct": round(sum(supported_golden.values()) * 100.0 / max(1, len(supported_golden)), 3),
                "supported_check_count": len(supported_golden),
                "skipped_check_count": len(skipped_golden),
                "skipped_checks": skipped_golden,
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
        benchmark_thread_groups = _benchmark_owned_thread_groups(app)
        related_threads = (server_thread,) if isinstance(server_thread, threading.Thread) else ()
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
                    _cleanup_scratch_after_benchmark_threads(
                        owned_scratch, app, benchmark_thread_groups, related_threads, server,
                    )

    assert record is not None
    if cleanup_errors:
        record["success"] = False
        record["failed_stages"].append("cleanup")
        record["cleanup"] = {"status": "incomplete", "errors": cleanup_errors}
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
    return {**record, "record_path": str(record_path)}


def run_benchmark_matrix(
    *,
    state_dir: Path | str,
    scratch_dir: Path | str | None = None,
    input_seed: int = 0,
    light_repetitions: int | None = None,
    comparison_repetitions: int | None = None,
    concurrency: tuple[int, ...] | None = None,
    inference_runner: Any = None,
    include_inference: bool = False,
    include_t12_matrix: bool = False,
    include_quality_goldens: bool | None = None,
    speech_fixture: Path | str | None = None,
    speech_expected_text: str | None = None,
    baseline_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run and persist all six documented synthetic size pairs as one matrix record."""
    if type(input_seed) is not int or input_seed < 0:
        raise ValueError("input_seed must be a non-negative integer")
    if include_t12_matrix and inference_runner is None:
        raise ValueError("T12 profile matrix requires an explicit benchmark runner")
    if include_quality_goldens is None:
        include_quality_goldens = include_inference
    speech_identity = _speech_golden_identity(speech_fixture, speech_expected_text)
    if speech_identity is not None and not include_inference:
        raise ValueError("speech golden fixture requires explicit inference opt-in")
    if include_inference and include_quality_goldens and speech_identity is None:
        raise ValueError("plan-grade inference matrix requires a known-audio speech fixture and expected transcript")
    light_repetitions = 1_000 if light_repetitions is None else light_repetitions
    comparison_repetitions = 30 if comparison_repetitions is None else comparison_repetitions
    concurrency = tuple(sorted(_PLAN_GRADE_CONCURRENCY)) if concurrency is None else concurrency
    output_dir = _resolve_outside_repo(Path(state_dir), "state_dir")
    output_dir.mkdir(parents=True, exist_ok=True)

    case_records: list[dict[str, Any]] = []
    for file_count, rag_chunk_count in sorted(_REQUIRED_MATRIX_CASES):
        result = run_benchmark(
            state_dir=output_dir,
            scratch_dir=scratch_dir,
            file_count=file_count,
            rag_chunks=rag_chunk_count,
            input_seed=input_seed,
            repetitions=max(1, comparison_repetitions),
            light_repetitions=light_repetitions,
            comparison_repetitions=comparison_repetitions,
            concurrency=concurrency,
            full=True,
            inference_runner=inference_runner,
            include_inference=include_inference,
            include_t12_matrix=include_t12_matrix,
            include_quality_goldens=include_quality_goldens,
            speech_fixture=speech_fixture,
            speech_expected_text=speech_expected_text,
        )
        case_record = {key: value for key, value in result.items() if key != "record_path"}
        record_path = result.get("record_path")
        case_records.append({
            "file_count": file_count,
            "rag_chunk_count": rag_chunk_count,
            "record_file": Path(record_path).name if isinstance(record_path, str) else None,
            "record": case_record,
        })

    first_metadata = case_records[0]["record"].get("metadata", {}) if case_records else {}
    stable_fields = (
        "benchmark_scope", "revision", "implementation_fingerprint",
        "config_fingerprint", "hardware_fingerprint", "platform",
        "quality_goldens", "speech_golden_fixture",
    )
    inconsistent_fields = [
        field for field in stable_fields
        if any(item["record"].get("metadata", {}).get(field) != first_metadata.get(field) for item in case_records)
    ]
    completed_matrix = []
    size_mismatch = False
    for item in case_records:
        case_record = item["record"]
        metadata = case_record.get("metadata", {})
        recorded_key = _matrix_recorded_size_key(metadata)
        expected_key = (item["file_count"], item["rag_chunk_count"])
        size_matches = recorded_key == expected_key
        size_mismatch = size_mismatch or not size_matches
        completed_matrix.append({
            "file_count": item["file_count"],
            "rag_chunk_count": item["rag_chunk_count"],
            "status": "completed" if case_record.get("success") is True and size_matches else "failed",
            "golden_operations": metadata.get("golden_operations", {}),
            "recorded_file_count": recorded_key[0] if recorded_key else None,
            "recorded_rag_chunk_count": recorded_key[1] if recorded_key else None,
            "synthetic_input_generator_version": metadata.get("synthetic_input_generator_version"),
            "synthetic_input_seed": metadata.get("synthetic_input_seed"),
            "synthetic_input_fingerprint": metadata.get("synthetic_input_fingerprint"),
        })

    matrix_metadata: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        **{field: first_metadata.get(field) for field in stable_fields},
        "full": True,
        "synthetic_file_sizes": sorted(_FULL_FILE_SIZES),
        "rag_chunk_sizes": sorted(_FULL_RAG_SIZES),
        "stage_repetitions": {"light": light_repetitions, "comparison": comparison_repetitions},
        "concurrency": list(concurrency),
        "synthetic_input_generator_version": _SYNTHETIC_INPUT_GENERATOR_VERSION,
        "synthetic_input_seed": input_seed,
        "completed_matrix": completed_matrix,
        "matrix_aggregation": "complete_six_case_cross_product",
        "inference": "requested" if include_inference else "skipped_not_requested",
        "inference_model_digest": first_metadata.get("inference_model_digest"),
        "quality_goldens": first_metadata.get("quality_goldens", False),
        "speech_golden_fixture": first_metadata.get("speech_golden_fixture"),
        "golden_operations": {
            name: bool(completed_matrix) and all(
                isinstance(row.get("golden_operations"), dict)
                and row["golden_operations"].get(name) is True
                for row in completed_matrix
            )
            for name in sorted(_REQUIRED_GOLDEN_OPERATIONS)
        },
    }
    readiness_reasons = _plan_grade_reasons(matrix_metadata)
    for item in case_records:
        case_record = item["record"]
        case_prefix = f"matrix_case:{item['file_count']}:{item['rag_chunk_count']}"
        readiness_reasons.extend(
            f"{case_prefix}:{reason}"
            for reason in _sample_independence_reasons(
                case_record.get("stages"), stage_names=_REQUIRED_PAIRED_COMPARISON_STAGES,
            )
        )
        readiness_reasons.extend(
            f"{case_prefix}:{reason}"
            for reason in _paired_tail_sample_reasons(
                case_record.get("stages"),
                minimum_samples=30,
                stage_names=_REQUIRED_PAIRED_COMPARISON_STAGES,
            )
        )
        readiness_reasons.extend(
            f"{case_prefix}:{reason}"
            for reason in _service_concurrency_reasons(
                case_record.get("stages"), comparison_repetitions,
            )
        )
        readiness_reasons.extend(
            f"{case_prefix}:{reason}"
            for reason in _light_stage_sample_reasons(
                case_record.get("metadata"), case_record.get("stages"),
            )
        )
    if size_mismatch:
        readiness_reasons.append("matrix_case_sizes_do_not_match_recorded_sizes")
    readiness_reasons.extend(f"matrix_metadata_inconsistent:{field}" for field in inconsistent_fields)
    matrix_metadata["baseline_readiness"] = "plan_grade" if not readiness_reasons else "provisional"
    matrix_metadata["baseline_readiness_reasons"] = list(dict.fromkeys(readiness_reasons))

    record: dict[str, Any] = {
        "success": bool(case_records) and not size_mismatch and all(
            item["record"].get("success") is True for item in case_records
        ),
        "metadata": matrix_metadata,
        "cases": case_records,
        "failed_cases": [
            {"file_count": item["file_count"], "rag_chunk_count": item["rag_chunk_count"]}
            for item in case_records
            if item["record"].get("success") is not True
            or _matrix_recorded_size_key(item["record"].get("metadata")) != (item["file_count"], item["rag_chunk_count"])
        ],
    }
    if baseline_record is not None:
        record["comparison"] = compare_matrix_records(baseline_record, record)

    record_name = f"surface-benchmark-matrix-{time.time_ns()}.json"
    record_path = output_dir / record_name
    temporary_path = output_dir / f".{record_name}.tmp"
    serialized = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    if len(serialized.encode("utf-8")) > _MAX_MATRIX_RECORD_BYTES:
        raise ValueError("matrix benchmark record exceeds 50 MB limit")
    try:
        temporary_path.write_text(serialized, encoding="utf-8")
        os.replace(temporary_path, record_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return {**record, "record_path": str(record_path)}


def _collect_concurrent_results(futures: list[Any], *, timeout_seconds: float) -> list[Any]:
    _done, pending = wait_futures(futures, timeout=max(0.0, float(timeout_seconds)))
    if pending:
        for future in pending:
            future.cancel()
        raise TimeoutError(f"{len(pending)} concurrent requests exceeded {timeout_seconds:.3f}s")
    return [future.result() for future in futures]


def _stream_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, str):
        payload = value.encode("utf-8", errors="replace")
    else:
        payload = b""
    return {
        "byte_count": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _emit_cli_status(status: str, error: str, **details: Any) -> None:
    payload = {
        "success": False,
        "status": status,
        "error": error,
        "record_complete": False,
        **details,
    }
    print(json.dumps(payload, separators=(",", ":")), flush=True)


class _BenchmarkArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        _emit_cli_status(
            "failed",
            "invalid_cli_arguments",
            error_detail=message,
            return_code=2,
        )
        super().error(message)


def _is_cancel_return_code(return_code: int) -> bool:
    return return_code in {130, -2, 3221225786, -1073741510}


def _run_cli_worker(command: list[str], *, timeout_seconds: float) -> int:
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _emit_cli_status(
            "incomplete",
            "benchmark_timeout",
            timeout_seconds=timeout_seconds,
            return_code=124,
            stdout=_stream_metadata(exc.stdout),
            stderr=_stream_metadata(exc.stderr),
        )
        return 124
    except KeyboardInterrupt:
        _emit_cli_status(
            "cancelled",
            "benchmark_cancelled",
            timeout_seconds=timeout_seconds,
            return_code=130,
        )
        return 130
    except Exception as exc:
        _emit_cli_status(
            "failed",
            "benchmark_worker_launch_failed",
            error_type=type(exc).__name__,
            return_code=126,
        )
        return 126

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    try:
        result = json.loads(stdout)
    except (TypeError, json.JSONDecodeError):
        result = None

    record_path_valid = (
        isinstance(result, dict)
        and isinstance(result.get("record_path"), str)
        and bool(result["record_path"].strip())
    )
    if completed.returncode == 0:
        if not record_path_valid:
            _emit_cli_status(
                "incomplete",
                "benchmark_worker_missing_or_invalid_record",
                return_code=1,
                stdout=_stream_metadata(stdout),
                stderr=_stream_metadata(stderr),
            )
            if stderr:
                sys.stderr.write(stderr)
            return 1
        if result.get("success") is not True:
            result["success"] = False
            if result.get("status") not in {"incomplete", "cancelled", "failed"}:
                result["status"] = "failed"
            result.setdefault("error", "benchmark_worker_reported_failure")
            result["worker_return_code"] = 0
            sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
            if stderr:
                sys.stderr.write(stderr)
            return 1
        if stderr:
            sys.stderr.write(stderr)
        sys.stdout.write(stdout)
        return 0

    cancelled = _is_cancel_return_code(completed.returncode)
    if record_path_valid:
        if cancelled:
            result["success"] = False
            result["status"] = "cancelled"
            result.setdefault("error", "benchmark_cancelled")
        elif result.get("success") is not True:
            result["success"] = False
            if result.get("status") not in {"incomplete", "cancelled", "failed"}:
                result["status"] = "failed"
            result.setdefault("error", "benchmark_worker_reported_failure")
        else:
            comparison = result.get("comparison")
            comparison_status = comparison.get("status") if isinstance(comparison, dict) else None
            if comparison_status in {"regression", "incomparable", "inconclusive"}:
                result["status"] = f"completed_{comparison_status}"
            else:
                result["success"] = False
                result["status"] = "failed"
                result.setdefault("error", "benchmark_worker_nonzero_exit")
        result["worker_return_code"] = completed.returncode
        sys.stdout.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    else:
        _emit_cli_status(
            "cancelled" if cancelled else "failed",
            "benchmark_cancelled" if cancelled else "benchmark_worker_failed",
            return_code=completed.returncode,
            stdout=_stream_metadata(stdout),
            stderr=_stream_metadata(stderr),
        )
    if stderr:
        sys.stderr.write(stderr)
    if cancelled:
        return 130
    return completed.returncode if 0 < completed.returncode < 256 else 1


def main(argv: list[str] | None = None) -> int:
    parser = _BenchmarkArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True, help="configured state directory; must be outside the repository")
    parser.add_argument("--scratch-dir", type=Path, help="optional external scratch directory; otherwise a temporary directory is used")
    parser.add_argument("--files", type=int)
    parser.add_argument("--rag-chunks", type=int)
    parser.add_argument("--input-seed", type=int, default=0, help="deterministic synthetic input seed")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--light-repetitions", type=int, help="transport/queue samples; plan-grade target is 1000")
    parser.add_argument("--comparison-repetitions", type=int, help="heavier independent samples per record; plan-grade target is 30")
    parser.add_argument("--concurrency", type=int, nargs="+")
    parser.add_argument("--full", action="store_true", help="allow documented large synthetic size matrix")
    parser.add_argument("--full-matrix", action="store_true", help="run all six documented repository/RAG size pairs with plan-grade defaults")
    parser.add_argument("--inference", action="store_true", help="explicitly run model inference and code/vision quality goldens")
    parser.add_argument("--t12-matrix", action="store_true", help="explicitly run T12 profile, quality, and scenario measurements")
    parser.add_argument("--config", type=Path, help="Hub config required by --inference or --t12-matrix")
    parser.add_argument("--speech-fixture", type=Path, help="known local audio fixture for the speech golden; requires --inference")
    parser.add_argument("--speech-expected-text", help="expected transcript for --speech-fixture; not saved in the benchmark record")
    parser.add_argument("--compare-with", type=Path, help="compare against a previous benchmark JSON record")
    parser.add_argument("--timeout-seconds", type=float, default=_DEFAULT_CLI_TIMEOUT_SECONDS,
                        help="maximum wall time for the benchmark process (1..3600 seconds)")
    parser.add_argument("--_benchmark-worker", action="store_true", help=argparse.SUPPRESS)
    raw_argv = list(argv if argv is not None else sys.argv[1:])
    args = parser.parse_args(raw_argv)
    if not math.isfinite(args.timeout_seconds) or not 0 < args.timeout_seconds <= _MAX_CLI_TIMEOUT_SECONDS:
        parser.error("--timeout-seconds must be finite and between 0 and 3600")
    if not args._benchmark_worker:
        worker_command = [
            sys.executable, str(Path(__file__).resolve()), *raw_argv, "--_benchmark-worker",
        ]
        return _run_cli_worker(worker_command, timeout_seconds=args.timeout_seconds)
    app = None
    try:
        inference_runner = None
        baseline_record = None
        if args.compare_with is not None:
            baseline_limit = _MAX_MATRIX_RECORD_BYTES if args.full_matrix else 10_000_000
            if args.compare_with.stat().st_size > baseline_limit:
                limit_mb = baseline_limit // 1_000_000
                raise ValueError(f"baseline record exceeds {limit_mb} MB limit")
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
        if args.full_matrix:
            if args.files is not None or args.rag_chunks is not None:
                raise ValueError("--full-matrix fixes documented sizes; omit --files and --rag-chunks")
            result = run_benchmark_matrix(
                state_dir=args.state_dir,
                scratch_dir=args.scratch_dir,
                input_seed=args.input_seed,
                light_repetitions=args.light_repetitions,
                comparison_repetitions=args.comparison_repetitions,
                concurrency=tuple(args.concurrency) if args.concurrency else None,
                inference_runner=inference_runner,
                include_inference=args.inference,
                include_t12_matrix=args.t12_matrix,
                include_quality_goldens=args.inference,
                speech_fixture=args.speech_fixture,
                speech_expected_text=args.speech_expected_text,
                baseline_record=baseline_record,
            )
        else:
            result = run_benchmark(
                state_dir=args.state_dir, scratch_dir=args.scratch_dir,
                input_seed=args.input_seed,
                file_count=100 if args.files is None else args.files,
                rag_chunks=1_000 if args.rag_chunks is None else args.rag_chunks,
                repetitions=args.repetitions,
                light_repetitions=args.light_repetitions, comparison_repetitions=args.comparison_repetitions,
                concurrency=tuple(args.concurrency) if args.concurrency else (1, 4), full=args.full,
                inference_runner=inference_runner, include_inference=args.inference,
                include_t12_matrix=args.t12_matrix,
                include_quality_goldens=args.inference,
                speech_fixture=args.speech_fixture,
                speech_expected_text=args.speech_expected_text,
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
    if args.full_matrix and result.get("metadata", {}).get("baseline_readiness") != "plan_grade":
        return 2
    return 2 if comparison_status == "inconclusive" else 0


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

if __name__ == "__main__":
    raise SystemExit(main())
