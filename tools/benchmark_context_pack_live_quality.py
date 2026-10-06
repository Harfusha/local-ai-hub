from __future__ import annotations

import builtins
import argparse
import contextvars
import io
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_ai_hub.agent_consistency import ConsistencyRequest  # noqa: E402
from local_ai_hub.app import LocalAIApp  # noqa: E402


QUERY = "tenant policy identity context request"
RELEVANT = {"src/tenant_policy.py", "src/context_identity.py"}
_ACTIVE_ACCESS: contextvars.ContextVar["_FileAccess | None"] = contextvars.ContextVar("benchmark_file_access", default=None)


@dataclass
class _FileAccess:
    root: Path
    visited: set[str] = field(default_factory=set)
    read: set[str] = field(default_factory=set)

    def _relative(self, value: Any) -> str | None:
        if not isinstance(value, (str, bytes, os.PathLike)):
            return None
        try:
            path = Path(os.fsdecode(value)).resolve(strict=False)
            relative = path.relative_to(self.root)
        except (OSError, ValueError, TypeError):
            return None
        return relative.as_posix()

    def note_visit(self, value: Any) -> None:
        relative = self._relative(value)
        if relative:
            self.visited.add(relative)

    def note_read(self, value: Any) -> None:
        relative = self._relative(value)
        if relative:
            self.read.add(relative)
            self.visited.add(relative)


class _TrackedScandir:
    def __init__(self, entries: os.ScandirIterator[str], access: _FileAccess | None):
        self._entries = entries
        self._access = access

    def __iter__(self) -> _TrackedScandir:
        return self

    def __next__(self) -> os.DirEntry[str]:
        entry = next(self._entries)
        if self._access is not None:
            try:
                if entry.is_file(follow_symlinks=False):
                    self._access.note_visit(entry.path)
            except OSError:
                pass
        return entry

    def __enter__(self) -> _TrackedScandir:
        self._entries.__enter__()
        return self

    def __exit__(self, *exc: Any) -> Any:
        return self._entries.__exit__(*exc)

    def close(self) -> None:
        self._entries.close()


class _FileReadTrace:
    """Temporarily capture Python filesystem reads/scans limited to fixture root."""

    def __enter__(self) -> _FileReadTrace:
        self._builtin_open = builtins.open
        self._io_open = io.open
        self._scandir = os.scandir

        def tracked_open(opener: Any) -> Any:
            def open_file(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
                access = _ACTIVE_ACCESS.get()
                if access is not None and ("r" in mode or "+" in mode):
                    access.note_read(file)
                return opener(file, mode, *args, **kwargs)
            return open_file

        self._builtin_wrapper = tracked_open(self._builtin_open)
        self._io_wrapper = tracked_open(self._io_open)

        def tracked_scandir(path: Any = ".") -> _TrackedScandir:
            return _TrackedScandir(self._scandir(path), _ACTIVE_ACCESS.get())

        self._scandir_wrapper = tracked_scandir
        builtins.open = self._builtin_wrapper
        io.open = self._io_wrapper
        os.scandir = self._scandir_wrapper  # type: ignore[assignment]
        return self

    def __exit__(self, *_exc: Any) -> None:
        builtins.open = self._builtin_open
        io.open = self._io_open
        os.scandir = self._scandir  # type: ignore[assignment]


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
    if not samples:
        raise ValueError("percentile requires at least one sample")
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * percentile) - 1))
    return round(ordered[index], 3)


def _normalize_sample_count(value: int | None) -> int:
    count = 100 if value is None else int(value)
    if count < 100 or count > 10_000:
        raise ValueError("sample count must be in 100..10000")
    return count


def _cache_observation(result: dict[str, Any]) -> dict[str, Any]:
    values: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if any(key in value for key in ("cache_hit", "coalesced", "workspace_cache")):
                values.append(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(result)
    cache_hits = [item["cache_hit"] for item in values if isinstance(item.get("cache_hit"), bool)]
    coalesced = [item["coalesced"] for item in values if isinstance(item.get("coalesced"), bool)]
    workspace_hits = [
        item["workspace_cache"].get("hit")
        for item in values
        if isinstance(item.get("workspace_cache"), dict)
        and isinstance(item["workspace_cache"].get("hit"), bool)
    ]
    signals = {"hit" if value else "miss" for value in cache_hits + workspace_hits}
    if any(coalesced):
        signals.add("coalesced")
    reported = bool(signals)
    if "miss" in signals and ("hit" in signals or "coalesced" in signals):
        state = "mixed"
    elif "coalesced" in signals:
        state = "coalesced"
    elif signals:
        state = next(iter(signals))
    else:
        state = "not_reported"
    layers = [str(item["cache_layer"]) for item in values if item.get("cache_layer") is not None]
    return {
        "state": state,
        "reported": reported,
        "cache_hit": cache_hits[-1] if cache_hits else (workspace_hits[-1] if workspace_hits else None),
        "coalesced": coalesced[-1] if coalesced else None,
        "signals": sorted(signals),
        "cache_layers": layers,
    }


def _cache_summary(cold: list[dict[str, Any]], warm: list[dict[str, Any]]) -> dict[str, Any]:
    first = cold[0] if cold else {"state": "not_reported", "reported": False}
    first_passed = first.get("state") == "miss" if first.get("reported") else None
    warm_reported = [item for item in warm if item.get("reported")]
    all_warm_hits = bool(warm) and len(warm_reported) == len(warm) and all(item.get("state") == "hit" for item in warm)
    warm_passed = all_warm_hits if len(warm_reported) == len(warm) and warm else None
    return {
        "cold_first_miss": {"expected": "miss", "observed": first.get("state"), "passed": first_passed},
        "warm_hits": {
            "expected": "hit",
            "observed": sum(item.get("state") == "hit" for item in warm_reported),
            "samples": len(warm),
            "reported_samples": len(warm_reported),
            "passed": warm_passed,
        },
        "cold_observations": cold,
        "warm_observations": warm,
    }


class ExternalAccessBlocked(OSError):
    """Raised when benchmark code attempts network or child-process access."""


@dataclass
class _OfflinePolicy:
    blocked_calls: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def blocker(self, name: str):
        def reject(*_args: Any, **_kwargs: Any) -> Any:
            with self._lock:
                self.blocked_calls.append(name)
            raise ExternalAccessBlocked(f"offline benchmark blocked {name}")
        return reject

    def report(self) -> dict[str, Any]:
        return {
            "enforced": True,
            "outbound_attempts": len(self.blocked_calls),
            "blocked_calls": list(self.blocked_calls),
            "offline_environment": True,
        }


@contextmanager
def _offline_network_guard() -> Iterator[_OfflinePolicy]:
    """Block all socket access and child-process launch for the benchmark lifetime."""
    policy = _OfflinePolicy()
    offline_env = {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    }
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, offline_env))
        for name in ("connect", "connect_ex", "send", "sendall", "sendto", "sendfile"):
            stack.enter_context(patch.object(socket.socket, name, policy.blocker(f"socket.{name}")))
        for name in ("create_connection", "getaddrinfo", "gethostbyname"):
            stack.enter_context(patch.object(socket, name, policy.blocker(f"socket.{name}")))
        stack.enter_context(patch.object(subprocess, "Popen", policy.blocker("subprocess.Popen")))
        stack.enter_context(patch.object(subprocess, "run", policy.blocker("subprocess.run")))
        stack.enter_context(patch.object(os, "system", policy.blocker("os.system")))
        yield policy


def _write_config(path: Path, state_dir: Path) -> None:
    escaped_state = str(state_dir).replace("\\", "\\\\").replace('"', '\\"')
    path.write_text(
        "\n".join((
            "[server]", f'state_dir = "{escaped_state}"',
            "[hardware]", 'profile = "cpu"', "auto_tune = false",
            "[features]", "rag = false", "code_intelligence = false", "preprocessing = false",
            "[code_intelligence]", "enabled = false", "serena_enabled = false",
            "[prewarm]", "enabled = false",
            "[background_gpu]", "enabled = false", "cpu_fallback_enabled = false",
            "[resilience]", "watchdog_enabled = false",
            "[search]", "use_ripgrep_if_available = false", "use_git_grep_fallback = false",
            "",
        )),
        encoding="utf-8",
    )


def _new_app(config_path: Path) -> LocalAIApp:
    # Avoid hardware discovery/probing and eager model loads. The service path
    # under test is deterministic; optional embeddings/reranking are disabled.
    import local_ai_hub.hardware as hardware
    import local_ai_hub.app as app_module

    original_detect = hardware.detect_hardware
    original_embedding_init = app_module.EmbeddingModel.__init__
    original_reranker_init = app_module.Reranker.__init__
    hardware.detect_hardware = lambda _profile="auto": {"profile": "cpu", "gpu": False, "benchmark": "disabled"}
    app_module.EmbeddingModel.__init__ = lambda _self, _config: None
    app_module.Reranker.__init__ = lambda _self, _config: None
    try:
        return LocalAIApp(config_path=str(config_path))
    finally:
        hardware.detect_hardware = original_detect
        app_module.EmbeddingModel.__init__ = original_embedding_init
        app_module.Reranker.__init__ = original_reranker_init


def _request(root: Path, request_id: str = "bench") -> ConsistencyRequest:
    return ConsistencyRequest(
        root=str(root), query=QUERY, phase="plan", focus=("tenant policy", "context identity"),
        token_budget=512, tenant="benchmark-fixture", session_id=request_id,
    )


def _service_request(app: LocalAIApp, root: Path, request_id: str) -> tuple[float, dict[str, Any], _FileAccess]:
    access = _FileAccess(root.resolve())
    token = _ACTIVE_ACCESS.set(access)
    started = time.perf_counter()
    try:
        result = app.services.adaptive_context_pack(_request(root, request_id), mode="adaptive")
    finally:
        elapsed = (time.perf_counter() - started) * 1000
        _ACTIVE_ACCESS.reset(token)
    if not isinstance(result, dict) or not result.get("success"):
        raise RuntimeError(f"adaptive context-pack request failed: {result!r}")
    return elapsed, result, access


def _response_measurement(result: dict[str, Any]) -> dict[str, int]:
    envelope = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return {
        "bytes": len(envelope),
        "context_bytes": len(str(result.get("context", "")).encode("utf-8")),
        "tokens_est": int(result.get("estimated_tokens", 0) or 0),
    }


def _run_concurrency(app: LocalAIApp, root: Path, workers: int, requests: int) -> dict[str, Any]:
    def one(index: int) -> tuple[float, dict[str, Any], _FileAccess]:
        return _service_request(app, root, f"concurrency-{workers}-{index}")

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="context-pack-bench") as pool:
        samples = list(pool.map(one, range(requests)))
    wall_ms = (time.perf_counter() - started) * 1000
    latencies = [sample[0] for sample in samples]
    visited = set().union(*(sample[2].visited for sample in samples))
    read = set().union(*(sample[2].read for sample in samples))
    cache_observations = [_cache_observation(sample[1]) for sample in samples]
    return {
        "workers": workers,
        "requests": requests,
        "measurement_kind": "full_service_request",
        "latency_ms": {"p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95)},
        "wall_ms": round(wall_ms, 3),
        "throughput_requests_per_second": round(requests / max(wall_ms / 1000, 0.001), 3),
        "files": {"visited": len(visited), "read": len(read)},
        "cache": {
            "reported_samples": sum(item["reported"] for item in cache_observations),
            "states": {state: sum(item["state"] == state for item in cache_observations)
                       for state in ("hit", "miss", "coalesced", "not_reported")},
        },
    }


def _run_benchmark(*, repetitions: int, concurrency_requests: int, progress: dict[str, Any]) -> dict[str, Any]:
    """Run actual service requests; caller supplies fail-closed policy and progress journal."""
    fixture_root: Path | None = None
    progress["stage"] = "fixture"
    with tempfile.TemporaryDirectory(prefix="lah-context-pack-live-") as temp:
        temp_root = Path(temp)
        fixture_root = temp_root / "fixture-repo"
        fixture_root.mkdir()
        _fixture(fixture_root)
        config_path = temp_root / "benchmark-config.toml"
        cold_latencies: list[float] = []
        cold_results: list[tuple[dict[str, Any], _FileAccess]] = []
        cold_cache: list[dict[str, Any]] = []
        progress["stage"] = "cold"
        with _FileReadTrace():
            for index in range(repetitions):
                cold_state = temp_root / f"cold-state-{index}"
                cold_state.mkdir()
                cold_config = temp_root / f"cold-{index}.toml"
                _write_config(cold_config, cold_state)
                app = _new_app(cold_config)
                try:
                    elapsed, result, access = _service_request(app, fixture_root, f"cold-{index}")
                    cold_latencies.append(elapsed)
                    cold_results.append((result, access))
                    cold_cache.append(_cache_observation(result))
                    progress["cold_samples"].append({"latency_ms": round(elapsed, 3), "cache": cold_cache[-1]})
                finally:
                    app.close()

            warm_state = temp_root / "warm-state"
            warm_state.mkdir()
            _write_config(config_path, warm_state)
            app = _new_app(config_path)
            try:
                # Same request identity makes cache behavior observable, not assumed from timing.
                _service_request(app, fixture_root, "warm-stable-request")
                progress["stage"] = "warm"
                warm_samples = [_service_request(app, fixture_root, "warm-stable-request") for _ in range(repetitions)]
                warm_latencies = [sample[0] for sample in warm_samples]
                warm_cache = [_cache_observation(sample[1]) for sample in warm_samples]
                progress["warm_samples"].extend(
                    {"latency_ms": round(sample[0], 3), "cache": cache}
                    for sample, cache in zip(warm_samples, warm_cache)
                )
                progress["stage"] = "concurrency"
                scenarios = {
                    str(workers): _run_concurrency(app, fixture_root, workers, concurrency_requests)
                    for workers in (1, 4, 16)
                }
                progress["concurrency"] = scenarios
                sample_result = warm_samples[-1][1]
                sample_access = warm_samples[-1][2]
            finally:
                app.close()

        evidence_paths = [str(item.get("path", "")) for item in sample_result.get("evidence", []) if isinstance(item, dict)]
        retrieved = set(evidence_paths[:3])
        true_positives = len(retrieved & RELEVANT)
        response = _response_measurement(sample_result)
        retrieval = sample_result.get("retrieval") if isinstance(sample_result.get("retrieval"), dict) else {}
        backend_states = retrieval.get("backend_states") if isinstance(retrieval.get("backend_states"), dict) else {}
        phase_timings = sample_result.get("phase_timings_ms") or sample_result.get("timings_ms") or {}
        visited = set().union(*(access.visited for _result, access in cold_results), sample_access.visited)
        read = set().union(*(access.read for _result, access in cold_results), sample_access.read)
        report = {
            "success": True,
            "status": "complete",
            "service_path": "LocalAIApp.services.adaptive_context_pack",
            "measurement_kind": "full_service_request",
            "fixture_semantics": "five temporary fixture files; no external project data",
            "query": QUERY,
            "precision_at_3": round(true_positives / max(1, len(retrieved)), 3),
            "recall_at_3": round(true_positives / len(RELEVANT), 3),
            "latency_ms": {
                "cold": {"p50": _percentile(cold_latencies, 0.50), "p95": _percentile(cold_latencies, 0.95)},
                "warm": {"p50": _percentile(warm_latencies, 0.50), "p95": _percentile(warm_latencies, 0.95)},
            },
            "cache": _cache_summary(cold_cache, warm_cache),
            "files": {
                "visited": len(visited), "read": len(read),
                "visited_paths": sorted(visited), "read_paths": sorted(read),
                "service_reported_scanned_files": int(sample_result.get("scanned_files", 0) or 0),
            },
            "phase_timings_ms": phase_timings if isinstance(phase_timings, dict) else {},
            "phase_timings_available": bool(phase_timings),
            "response": response,
            "backends": {
                "serena": {"exercised": False, "status": "disabled_by_benchmark_config"},
                "rag": {"exercised": False, "status": "disabled_by_benchmark_config"},
                "embedding_model": {"exercised": False, "status": "constructor_stubbed"},
                "reranker": {"exercised": False, "status": "constructor_stubbed"},
                "gpu": {"exercised": False, "status": "hardware_probe_and_worker_disabled"},
                "deterministic": {"status": str(backend_states.get("deterministic", "not_reported"))},
                "code_index": {"status": str(backend_states.get("code_index", "not_reported"))},
                "lexical": {"status": str(backend_states.get("lexical", "not_reported"))},
            },
            "concurrency": scenarios,
            "repetitions": repetitions,
            "concurrency_requests_per_scenario": concurrency_requests,
            "p95_method": "nearest_rank; at least 100 samples per reported series",
            "fixture_root_exists_after_run": fixture_root.exists(),
            "instrumentation": "Python open/io.open reads and os.scandir visits, restricted to fixture root",
        }
    report["fixture_root_exists_after_run"] = bool(fixture_root and fixture_root.exists())
    progress["stage"] = "complete"
    return report


def run_benchmark(*, repetitions: int | None = None, concurrency_requests: int | None = None) -> dict[str, Any]:
    """Run a fail-closed offline benchmark and always return a structured report."""
    progress: dict[str, Any] = {"stage": "starting", "cold_samples": [], "warm_samples": [], "concurrency": {}}
    try:
        repetitions = _normalize_sample_count(repetitions)
        concurrency_requests = _normalize_sample_count(concurrency_requests if concurrency_requests is not None else repetitions)
    except (TypeError, ValueError) as exc:
        return {
            "success": False, "status": "invalid_configuration",
            "errors": [{"type": type(exc).__name__, "message": str(exc)}],
            "partial_report": progress,
            "network_policy": {"enforced": False, "outbound_attempts": 0, "blocked_calls": [], "offline_environment": False},
        }
    progress["requested_samples"] = {"cold": repetitions, "warm": repetitions, "concurrency_each": concurrency_requests}

    errors: list[dict[str, str]] = []
    result: dict[str, Any] = {}
    policy: _OfflinePolicy | None = None
    try:
        with _offline_network_guard() as policy:
            result = _run_benchmark(
                repetitions=repetitions,
                concurrency_requests=concurrency_requests,
                progress=progress,
            )
    except Exception as exc:
        errors.append({"type": type(exc).__name__, "message": str(exc)})
        result = {
            "success": False,
            "status": "partial" if progress["stage"] != "starting" else "error",
            "partial_report": progress,
        }

    network_report = policy.report() if policy is not None else {
        "enforced": False, "outbound_attempts": 0, "blocked_calls": [], "offline_environment": False,
    }
    if network_report["outbound_attempts"]:
        result["success"] = False
        result["status"] = "policy_violation"
        errors.append({
            "type": "ExternalAccessBlocked",
            "message": f"blocked {network_report['outbound_attempts']} external access attempt(s)",
        })
    result.setdefault("success", not errors)
    result.setdefault("status", "complete" if result["success"] else "error")
    result["errors"] = errors
    result["network_policy"] = network_report
    if errors or not result["success"]:
        result.setdefault("partial_report", progress)
    return result


def _main() -> int:
    parser = argparse.ArgumentParser(description="Offline adaptive-context-pack quality/latency benchmark")
    parser.add_argument("--repetitions", type=int, default=100, help="cold and warm samples (100..10000)")
    parser.add_argument("--concurrency-requests", type=int, default=None, help="requests per concurrency scenario (100..10000; defaults to repetitions)")
    args = parser.parse_args()
    report = run_benchmark(repetitions=args.repetitions, concurrency_requests=args.concurrency_requests)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(_main())
