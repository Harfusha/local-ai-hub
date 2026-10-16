from __future__ import annotations

import gc
import json
import hashlib
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tools.benchmark_surfaces import _plan_grade_reasons, compare_records, main, run_benchmark, run_benchmark_matrix, summarize_samples
from tools.benchmark_surfaces import (
    _summarize_t12_metric,
    _t12_hardware_identity,
    _run_t12_matrix,
    _t12_scenario_report,
    _code_generation_matches_golden,
    _benchmark_inference_config,
    _benchmark_inference_server_url,
    _run_model_quality_goldens,
    _sample_dedicated_vram_bytes,
    _stage_speech_golden_fixture,
    _speech_golden_identity,
    _transcription_matches_golden,
    _vision_matches_golden,
)
import tools.benchmark_surfaces as surface_benchmarks


def test_implementation_fingerprint_includes_retrieval_dependency(monkeypatch, tmp_path: Path) -> None:
    package_dir = tmp_path / "src" / "local_ai_hub"
    package_dir.mkdir(parents=True)
    retrieval = package_dir / "retrieval.py"
    retrieval.write_text("weight = 0.0\n", encoding="utf-8")
    monkeypatch.setattr(surface_benchmarks, "_REPO_ROOT", tmp_path)
    before = surface_benchmarks._implementation_fingerprint()
    retrieval.write_text("weight = 0.75\n", encoding="utf-8")
    after = surface_benchmarks._implementation_fingerprint()
    assert after != before, "fingerprint must include imported runtime dependencies"
from local_ai_hub.async_jobs import AsyncJobManager
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.normalizer import tokenize_query_terms

_REQUIRED_GOLDEN_OPERATIONS = (
    "symbols", "graph", "affected_tests", "retrieval_relevance",
    "code_generation", "vision", "speech", "context_pack",
)
_REQUIRED_COMPARISON_STAGES = (
    "transport", "hub_health", "hub_validation", "hub_sqlite_index",
    "hub_sqlite_db_read", "hub_code_index", "hub_context_pack",
    "hub_call_graph_query", "hub_call_graph_callees",
    "hub_rag_batch_index", "hub_rag_search", "hub_rag_fixture_relevance",
    "hub_queue_admission", "hub_rag_chunking", "parent_worktree_seed",
)
_COMPARISON_METADATA_FIELDS = (
    "benchmark_scope", "config_fingerprint", "hardware_fingerprint",
)
_FIXTURE_SAMPLE_CASES = ("health", "sqlite", "code-index", "call-graph", "context", "rag")
_FIXTURE_SAMPLE_BLOCKS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet")
_FIXTURE_SAMPLE_BLOCK_IDS = tuple(
    f"{case}:{block}" for case in _FIXTURE_SAMPLE_CASES for block in _FIXTURE_SAMPLE_BLOCKS
)


def test_t12_hardware_identity_includes_detected_profile_and_devices():
    hardware, fingerprint = _t12_hardware_identity({
        "profile": "balanced",
        "gpus": [{"vendor": "nvidia", "gpu_name": "Example GPU", "vram_total_mb": 8192, "serial": "omit-me"}],
        "npus": [{"name": "Example NPU", "backend": "test"}],
    })

    assert hardware["profile"] == "balanced"
    assert hardware["gpus"] == [{"gpu_name": "Example GPU", "vendor": "nvidia", "vram_total_mb": 8192}]
    assert hardware["npus"] == [{"name": "Example NPU", "backend": "test"}]
    assert "serial" not in json.dumps(hardware)
    assert len(fingerprint) == 64


def test_synthetic_query_symbol_is_exact_single_term() -> None:
    index = 29
    query_symbol = surface_benchmarks._synthetic_query_symbol(index)

    assert query_symbol == "benchmarkcase000029"
    assert f"def {query_symbol}(" in surface_benchmarks._synthetic_source(index)
    assert tokenize_query_terms(query_symbol, min_len=2, max_terms=16) == [query_symbol]


def test_queue_admission_failure_reason_identifies_running_cancel_race() -> None:
    assert surface_benchmarks._queue_admission_error_reason(
        {"success": True, "job_id": "job-1"},
        {"success": False, "state": "running"},
    ) == "cancel_running"
    assert surface_benchmarks._queue_admission_error_reason(
        {"success": False}, None,
    ) == "submit_rejected"
    assert surface_benchmarks._queue_admission_error_reason(
        {"success": True, "job_id": "job-1"},
        {"success": True, "state": "cancelled"},
    ) is None


def test_queue_admission_probe_cancels_before_delayed_dispatch_registration_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor_started = threading.Event()
    release_executor = threading.Event()

    def execute(_action: str, _payload: dict[str, Any], _tenant: str) -> dict[str, Any]:
        executor_started.set()
        release_executor.wait(timeout=2)
        return {"success": False, "error": "cancelled by test"}

    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path)}},
        scheduler=None,
        artifacts=None,
        executor=execute,
    )
    original_event = manager._event
    injecting_tick = False
    injected_once = False
    tick_injected = threading.Event()

    def tick_between_insert_and_timer_registration(job_id: str) -> threading.Event:
        nonlocal injecting_tick, injected_once
        event = original_event(job_id)
        if not injecting_tick and not injected_once:
            injected_once = True
            injecting_tick = True
            try:
                committed = manager._row("benchmark", job_id)
                assert committed is not None
                assert committed["state"] == "queued"
                with manager._lock:
                    assert job_id not in manager._delayed_dispatch
                tick_injected.set()
                manager.tick()
                # Old code dispatches the committed row here, before the delayed
                # timer is registered. New code persists its not-before time.
                with manager._lock:
                    dispatched = bool(manager._workers)
                if dispatched:
                    assert executor_started.wait(timeout=1)
            finally:
                injecting_tick = False
        return event

    monkeypatch.setattr(manager, "_event", tick_between_insert_and_timer_registration)
    try:
        submitted = manager.submit(
            "benchmark", "reason", {"task": "T02 bounded queue probe"},
            dispatch_delay_seconds=30,
        )
        job_id = str(submitted.get("job_id", ""))
        with manager._lock:
            assert job_id in manager._delayed_dispatch
        cancelled = manager.cancel("benchmark", job_id)

        assert tick_injected.is_set()
        assert cancelled.get("state") == "cancelled"
        assert not executor_started.is_set()
        assert surface_benchmarks._queue_admission_error_reason(submitted, cancelled) is None
    finally:
        release_executor.set()
        manager.close()


def _async_jobs_lifecycle_snapshot(scratch_root: Path) -> dict[str, object]:
    target_dir = scratch_root.resolve()
    observed: list[dict[str, object]] = []
    for manager in gc.get_objects():
        if not issubclass(type(manager), AsyncJobManager):
            continue
        try:
            delayed = list(getattr(manager, "_delayed_dispatch", {}).values())
            dispatchers = list(getattr(manager, "_dispatchers", ()))
            workers = list(getattr(manager, "_workers", ()))
        except RuntimeError:
            continue
        handles = [
            {"role": role, "name": thread.name, "ident": thread.ident, "alive": thread.is_alive(), "daemon": thread.daemon}
            for role, threads in (("delayed_dispatch", delayed), ("dispatcher", dispatchers), ("worker", workers))
            for thread in threads
            if isinstance(thread, threading.Thread)
        ]
        database_path = Path(manager.path)
        is_current_run = database_path.resolve().is_relative_to(target_dir)
        if not is_current_run and not any(item["alive"] for item in handles):
            continue
        try:
            uri = f"{database_path.resolve().as_uri()}?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=0.05)) as connection:
                table_exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='async_jobs'"
                ).fetchone() is not None
                queue_rows: list[dict[str, object]] = []
                if table_exists:
                    available = {
                        str(row[1])
                        for row in connection.execute("PRAGMA table_info(async_jobs)").fetchall()
                    }
                    fields = (
                        "job_id", "tenant", "action", "task_id", "state", "cancel_requested",
                        "dispatch_not_before", "lease_until", "created_at", "updated_at",
                    )
                    selected = [field for field in fields if field in available]
                    if {"job_id", "tenant", "action"}.issubset(selected):
                        order_by = "created_at DESC" if "created_at" in selected else "job_id"
                        rows = connection.execute(
                            f"SELECT {', '.join(selected)} FROM async_jobs "
                            "WHERE tenant = ? AND action = ? "
                            f"ORDER BY {order_by} LIMIT 50",
                            ("benchmark", "reason"),
                        ).fetchall()
                        queue_rows = [dict(zip(selected, row)) for row in rows]
            schema = {
                "async_jobs_table_exists": table_exists,
                "benchmark_queue_rows": queue_rows,
            }
        except sqlite3.Error as exc:
            schema = {"read_only_probe_error": f"{type(exc).__name__}: {exc}"}
        observed.append({
            "manager_id": hex(id(manager)),
            "database_path": str(database_path),
            "database_exists": database_path.is_file(),
            "initialized": getattr(manager, "_initialized", None),
            "shutdown": getattr(manager, "_shutdown", None).is_set()
            if isinstance(getattr(manager, "_shutdown", None), threading.Event) else None,
            "sqlite_worker_alive": any(item["role"] == "worker" and item["alive"] for item in handles),
            "handles": handles,
            **schema,
        })
    observed.sort(key=lambda item: (str(item["database_path"]), str(item["manager_id"])))
    return {
        "sqlite_worker_alive": any(manager["sqlite_worker_alive"] for manager in observed),
        "managers": observed,
    }


def test_async_jobs_lifecycle_snapshot_includes_benchmark_queue_rows(tmp_path: Path) -> None:
    manager = AsyncJobManager(
        {"server": {"state_dir": str(tmp_path)}},
        scheduler=None,
        artifacts=None,
        executor=lambda _action, _payload, _tenant: {"success": True},
    )
    try:
        submitted = manager.submit(
            "benchmark", "reason", {"task": "T02 snapshot probe"},
            dispatch_delay_seconds=30,
        )
        assert submitted.get("success") is True
        job_id = str(submitted["job_id"])

        snapshot = _async_jobs_lifecycle_snapshot(tmp_path)

        observed = next(item for item in snapshot["managers"] if item["database_path"] == str(manager.path))
        queue_rows = observed["benchmark_queue_rows"]
        row = next(item for item in queue_rows if item["job_id"] == job_id)
        assert row["tenant"] == "benchmark"
        assert row["state"] == "queued"
        assert row["cancel_requested"] == 0
        assert "payload_json" not in row
    finally:
        manager.close()


def _comparison_diagnostic(
    baseline: dict[str, object], candidate: dict[str, object], comparison: dict[str, object],
) -> dict[str, object]:
    def record_summary(record: dict[str, object]) -> dict[str, object]:
        metadata = record.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        return {
            "success": record.get("success"),
            "metadata_gate_values": {field: metadata.get(field) for field in _COMPARISON_METADATA_FIELDS},
        }

    return {
        "comparison": comparison,
        "baseline": record_summary(baseline),
        "candidate": record_summary(candidate),
    }


def _completed_matrix() -> list[dict[str, object]]:
    return [
        {
            "file_count": file_count,
            "rag_chunk_count": rag_chunk_count,
            "status": "completed",
            "golden_operations": {name: True for name in _REQUIRED_GOLDEN_OPERATIONS},
        }
        for file_count in (100, 10_000, 100_000)
        for rag_chunk_count in (10_000, 100_000)
    ]


def _plan_grade_metadata() -> dict[str, object]:
    return {
        "benchmark_scope": "hub_app_synthetic_repo",
        "workload_fingerprint": "workload",
        "sample_identity_provenance": surface_benchmarks._sample_identity_provenance("workload"),
        "config_fingerprint": "cfg",
        "hardware_fingerprint": "hw",
        "baseline_readiness": "plan_grade",
        "stage_repetitions": {"light": 1_000, "comparison": 30},
        "concurrency": [1, 4, 16, 32],
        "completed_matrix": _completed_matrix(),
        "inference": "skipped_not_requested",
    }


def _comparison_stages(
    value: float, *, cold: int = 30, warm: int = 30, light_repetitions: int = 1_000,
) -> dict[str, object]:
    def sample_ids(name: str, regime: str, count: int) -> list[str]:
        ids = [f"{name}:{regime}:{block_id}" for block_id in _FIXTURE_SAMPLE_BLOCK_IDS[:count]]
        ids.extend(
            f"{name}:{regime}:extended-{index}"
            for index in range(len(ids), count)
        )
        return ids

    stages: dict[str, object] = {}
    fixture_run_id = uuid.uuid4().hex
    for name in _REQUIRED_COMPARISON_STAGES:
        counts = (cold, warm)
        if name in surface_benchmarks._REQUIRED_LIGHT_SAMPLE_STAGES:
            light_cold = min(cold, light_repetitions)
            light_warm = max(warm, light_repetitions - light_cold)
            counts = (light_cold, light_warm)
        cold_count, warm_count = counts
        stage = {
            "status": "passed",
            "samples_by_regime": {
                "cold": [value] * cold_count,
                "warm": [value] * warm_count,
            },
            "sample_ids_by_regime": {
                "cold": sample_ids(name, "cold", cold_count),
                "warm": sample_ids(name, "warm", warm_count),
            },
            "workload_fingerprint": f"workload:{name}",
            "sample_identity_provenance": surface_benchmarks._sample_identity_provenance(
                f"workload:{name}",
            ),
            "sample_independence_status": "established",
            "sample_independence_note": "test fixture provides distinct deterministic workload pairs",
        }
        state_fingerprints_by_regime = {
            regime: [
                surface_benchmarks._stable_fingerprint({"fixture": fixture_run_id, "sample_id": sample_id})
                for sample_id in ids
            ]
            for regime, ids in stage["sample_ids_by_regime"].items()
        }
        stage["sample_independence_proof"] = surface_benchmarks._build_sample_independence_proof(
            protocol=surface_benchmarks._SAMPLE_INDEPENDENCE_PROTOCOL,
            workload_fingerprint=f"workload:{name}",
            sample_ids_by_regime=stage["sample_ids_by_regime"],
            cache_epoch_ids_by_regime=state_fingerprints_by_regime,
            preparation_status_by_regime={
                "cold": ["cold_case_unseen"] * cold_count,
                "warm": ["warm_exact_case_primed"] * warm_count,
            },
            preparation_receipt_sample_ids_by_regime=stage["sample_ids_by_regime"],
            preparation_state_fingerprints_by_regime=state_fingerprints_by_regime,
        )
        stages[name] = stage
    stages["hub_context_pack"]["service_concurrency"] = {
        "status": "passed",
        "by_concurrency": {
            str(level): {
                "status": "passed",
                "error_count": 0,
                "response_measurement": "exact_http_response_body_bytes",
                "http_response_body_bytes": 64,
                "request_count": 30 * level,
                "sample_count": 30 * level,
                "samples_ms": [value] * (30 * level),
                "sample_ids": [
                    f"context-pack-concurrency:{level}:{repetition}:{slot}"
                    for repetition in range(30)
                    for slot in range(level)
                ],
                "batch_sample_ids": [
                    f"context-pack-concurrency:{level}:batch:{repetition}"
                    for repetition in range(30)
                ],
                "request_latency_samples_by_batch_ms": [[value] * level for _ in range(30)],
                "request_sample_ids_by_batch": [
                    [f"context-pack-concurrency:{level}:{repetition}:{slot}" for slot in range(level)]
                    for repetition in range(30)
                ],
                "batch_throughput_samples_per_second": [level * 1_000.0 / value] * 30,
                "workload_fingerprint": surface_benchmarks._stable_fingerprint({
                    "measurement": "concurrent valid POST /api/context/pack requests",
                    "concurrency": level,
                    "repetitions": 30,
                }),
                "sample_identity_provenance": surface_benchmarks._sample_identity_provenance(
                    surface_benchmarks._stable_fingerprint({
                        "measurement": "concurrent valid POST /api/context/pack requests",
                        "concurrency": level,
                        "repetitions": 30,
                    }),
                ),
            }
            for level in (1, 4, 16, 32)
        },
    }
    return stages


def test_graph_edge_found_requires_true_positive_edges() -> None:
    exact_edge = {"caller": "caller_case_1", "callee": "target_case_1"}
    assert surface_benchmarks._graph_edge_found(
        {"success": True, "callers": [exact_edge]},
        collection="callers", caller="caller_case_1", callee="target_case_1",
    ) is True
    assert surface_benchmarks._graph_edge_found(
        {"success": True, "callees": [exact_edge]},
        collection="callees", caller="caller_case_1", callee="target_case_1",
    ) is True
    for result, collection in (
        ({"success": True, "callers": [{"caller": "caller_case_10", "callee": "target_case_1"}]}, "callers"),
        ({"success": True, "callees": [{"caller": "caller_case_1", "callee": "target_case_10"}]}, "callees"),
        ({"success": False, "callers": [exact_edge]}, "callers"),
        ({"success": True, "callers": [exact_edge]}, "callees"),
    ):
        assert surface_benchmarks._graph_edge_found(
            result, collection=collection, caller="caller_case_1", callee="target_case_1",
        ) is False


def test_synthetic_repository_declares_pytest_for_affected_test_selection(tmp_path: Path) -> None:
    from local_ai_hub.deterministic import DeterministicEngine
    from local_ai_hub.repo_tools import RepositoryTools

    files, test_path, _corpus, _fingerprint = surface_benchmarks._build_synthetic_repo(
        tmp_path, file_count=1, rag_chunks=1,
    )
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    engine = DeterministicEngine(config, RepositoryTools(config))
    root = tmp_path / "repo"
    result = engine.affected_tests(
        str(root), changed_paths=[files[0].relative_to(root).as_posix()],
    )

    assert result["success"] is True
    assert result["framework"] == "pytest"
    assert result["test_files"] == [test_path.relative_to(root).as_posix()]
    assert result["confidence"] >= 0.95


def test_graph_unpaired_fallback_does_not_claim_paired_cases(tmp_path: Path) -> None:
    result = run_benchmark(
        state_dir=tmp_path / "results",
        scratch_dir=tmp_path / "scratch",
        file_count=1,
        rag_chunks=2,
        repetitions=1,
        light_repetitions=1,
        comparison_repetitions=2,
        concurrency=(1,),
    )

    assert result["success"] is True, result.get("stages", {}).get("hub_queue_admission", {}).get("error_reasons")
    concurrent_load = result["stages"]["hub_context_pack"]["service_concurrency"]
    assert concurrent_load["status"] == "passed"
    assert set(concurrent_load["by_concurrency"]) == {"1"}
    assert concurrent_load["by_concurrency"]["1"]["request_count"] == 2
    for stage_name in ("hub_call_graph_query", "hub_call_graph_callees"):
        stage = result["stages"][stage_name]
        assert stage["paired_case_edges_all_found"] is False
        assert stage["edge_checks_all_found"] is True
        assert stage["golden_edge_found"] is True


def test_benchmark_records_service_load_and_available_golden_outputs(tmp_path: Path) -> None:
    result = run_benchmark(
        state_dir=tmp_path / "results",
        scratch_dir=tmp_path / "scratch",
        file_count=2,
        rag_chunks=3,
        repetitions=1,
        light_repetitions=1,
        comparison_repetitions=2,
        concurrency=(1, 4),
    )

    context_stage = result["stages"]["hub_context_pack"]
    assert context_stage["sample_independence_status"] == "established"
    assert surface_benchmarks._sample_independence_proof_is_valid(context_stage) is True
    assert set(context_stage["sample_ids_by_regime"]["cold"]).isdisjoint(
        context_stage["sample_ids_by_regime"]["warm"],
    )
    assert context_stage["service_concurrency"]["by_concurrency"]["4"]["request_count"] == 8
    affected_golden = result["golden"]["affected_tests"]
    assert affected_golden["status"] == "passed"
    assert affected_golden["measurement"] == "Services.affected_tests over indexed synthetic import edge"
    assert affected_golden["expected_test"] in affected_golden["observed_tests"]
    assert result["golden"]["retrieval_relevance"]["status"] == "passed"


def test_queue_admission_failure_retains_phase_and_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_submit = AsyncJobManager.submit

    def reject_benchmark_submission(
        self: AsyncJobManager,
        tenant: str,
        action: str,
        payload: dict[str, object],
        *,
        dispatch_delay_seconds: float = 0.0,
    ) -> dict[str, object]:
        if tenant == "benchmark":
            return {
                "success": False,
                "state": "rejected",
                "error": "SENTINEL_PAYLOAD_SECRET",
                "admission": {"state": "rejected", "reason": "resource_pressure", "pressure_level": "critical"},
            }
        return original_submit(self, tenant, action, payload, dispatch_delay_seconds=dispatch_delay_seconds)

    monkeypatch.setattr(AsyncJobManager, "submit", reject_benchmark_submission)
    result = run_benchmark(
        state_dir=tmp_path / "state",
        scratch_dir=tmp_path / "scratch",
        file_count=4,
        rag_chunks=2,
        repetitions=1,
        light_repetitions=1,
        comparison_repetitions=1,
        concurrency=(1,),
    )

    stage = result["stages"]["hub_queue_admission"]
    assert stage["status"] == "failed"
    assert stage["error_count"] == 1
    assert stage["error_types"] == ["RuntimeError"]
    assert stage["error_reasons"] == {"submit_rejected": 1}
    assert len(stage["failed_samples"]) == 1
    diagnostic = stage["failed_samples"][0]
    assert diagnostic["error_type"] == "RuntimeError"
    assert diagnostic["error_reason"] == "submit_rejected"
    assert diagnostic["submit"]["success"] is False
    assert diagnostic["submit"]["state"] == "rejected"
    assert diagnostic["submit"]["admission_reason"] == "resource_pressure"
    assert "SENTINEL_PAYLOAD_SECRET" not in repr(result)


def test_benchmark_seed_accepts_null_code_index_cached_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_update = CodeIndex.update_files_batch
    processed_counts: list[int] = []

    def update_with_null_cached(self: CodeIndex, root: str, items: list[str] | list[tuple[str, str]]) -> dict[str, Any]:
        result = original_update(self, root, items)
        processed_counts.append(int(result.get("files_processed", 0)))
        result["cached"] = None
        return result

    monkeypatch.setattr(CodeIndex, "update_files_batch", update_with_null_cached)
    result = run_benchmark(
        state_dir=tmp_path / "state",
        scratch_dir=tmp_path / "scratch",
        file_count=4,
        rag_chunks=2,
        repetitions=1,
        light_repetitions=1,
        comparison_repetitions=1,
        concurrency=(1,),
    )

    seeded_files = result["stages"]["hub_sqlite_index"]["main_repo_seeded_files"]
    assert processed_counts
    assert isinstance(seeded_files, int)


def test_queue_admission_exception_redacts_exception_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_submit = AsyncJobManager.submit

    def raise_benchmark_submission(
        self: AsyncJobManager,
        tenant: str,
        action: str,
        payload: dict[str, object],
        *,
        dispatch_delay_seconds: float = 0.0,
    ) -> dict[str, object]:
        if tenant == "benchmark":
            raise RuntimeError("SENTINEL_EXCEPTION_SECRET")
        return original_submit(self, tenant, action, payload, dispatch_delay_seconds=dispatch_delay_seconds)

    monkeypatch.setattr(AsyncJobManager, "submit", raise_benchmark_submission)
    result = run_benchmark(
        state_dir=tmp_path / "state",
        scratch_dir=tmp_path / "scratch",
        file_count=4,
        rag_chunks=2,
        repetitions=1,
        light_repetitions=1,
        comparison_repetitions=1,
        concurrency=(1,),
    )

    stage = result["stages"]["hub_queue_admission"]
    assert stage["status"] == "failed"
    assert stage["error_count"] == 1
    assert stage["error_types"] == ["RuntimeError"]
    assert stage["error_reasons"] == {"exception_RuntimeError": 1}
    assert len(stage["failed_samples"]) == 1
    assert stage["failed_samples"][0]["error_type"] == "RuntimeError"
    assert stage["failed_samples"][0]["error_reason"] == "exception_RuntimeError"
    assert "SENTINEL_EXCEPTION_SECRET" not in repr(result)


def test_summarize_samples_reports_percentiles_and_throughput() -> None:
    summary = summarize_samples([10.0, 20.0, 30.0, 40.0])

    assert summary["count"] == 4
    assert summary["p50_ms"] == 25.0
    assert summary["p95_ms"] == 38.5
    assert summary["p99_ms"] == 39.7
    assert summary["throughput_per_second"] == 40.0


def test_t12_metric_summary_preserves_measurement_units() -> None:
    latency = _summarize_t12_metric("ttft_ms", [10.0, 20.0, 30.0, 40.0])
    memory = _summarize_t12_metric("peak_vram_bytes", [100.0, 200.0, 300.0, 400.0])
    throughput = _summarize_t12_metric("tokens_per_second", [10.0, 20.0, 30.0, 40.0])

    assert latency["unit"] == "ms"
    assert latency["p50"] == 25.0
    assert memory["unit"] == "bytes"
    assert memory["p50"] == 250.0
    assert "p50_ms" not in memory
    assert throughput["unit"] == "tokens/second"
    assert throughput["p50"] == 25.0

def test_code_generation_golden_checks_function_behavior_shape() -> None:
    passing = {
        "success": True,
        "text": "```python\ndef generated_answer(value: int) -> int:\n    return value + 1\n```",
    }
    wrong_behavior = {
        "success": True,
        "text": "def generated_answer(value: int) -> int:\n    return value - 1\n",
    }

    assert _code_generation_matches_golden(passing) is True
    assert _code_generation_matches_golden(wrong_behavior) is False
    assert _code_generation_matches_golden({"success": True, "text": "not python"}) is False


def test_vision_golden_requires_success_and_expected_observation() -> None:
    passing = {"success": True, "review": {"summary": "A green square on a white background."}}
    wrong_observation = {"success": True, "review": {"summary": "A blue square on a white background."}}

    assert _vision_matches_golden(passing) is True
    assert _vision_matches_golden(wrong_observation) is False
    assert _vision_matches_golden({"success": False, "review": {"summary": "green square"}}) is False


def test_speech_golden_requires_non_degraded_exact_normalized_transcript() -> None:
    passing = {"success": True, "engine": "whisper_cli", "text": "Turn left at the next street."}
    degraded = {"success": True, "engine": "local_stt_fallback", "text": "Turn left at the next street." , "degraded": True}

    assert _transcription_matches_golden(passing, "turn left at the next street") is True
    assert _transcription_matches_golden(passing, "turn right at the next street") is False
    assert _transcription_matches_golden(degraded, "turn left at the next street") is False


def test_model_quality_goldens_call_real_surface_contracts_and_keep_outputs_private(tmp_path: Path) -> None:
    audio_fixture = tmp_path / "speech.wav"
    audio_fixture.write_bytes(b"synthetic fixture bytes")

    class FakeServices:
        calls: list[tuple[str, dict[str, object], str]] = []

        def delegate(self, args: dict[str, object], tenant: str) -> dict[str, object]:
            self.calls.append(("delegate", args, tenant))
            return {
                "success": True,
                "text": "def generated_answer(value: int) -> int:\n    return value + 1\n",
            }

        def vision(self, args: dict[str, object], tenant: str) -> dict[str, object]:
            self.calls.append(("vision", args, tenant))
            return {
                "success": True,
                "response": "{\"summary\":\"A green square on white.\"}",
                "review": {"summary": "A green square on white."},
            }

        def transcribe(self, args: dict[str, object], tenant: str) -> dict[str, object]:
            self.calls.append(("transcribe", args, tenant))
            return {"success": True, "engine": "whisper_cli", "text": "Turn left at the next street."}

    services = FakeServices()
    goldens = _run_model_quality_goldens(
        services,
        speech_fixture=audio_fixture,
        speech_expected_text="turn left at the next street",
    )

    assert [item[0] for item in services.calls] == ["delegate", "vision", "transcribe"]
    assert all(item[2] == "benchmark" for item in services.calls)
    assert str(audio_fixture) == services.calls[2][1]["audio"]
    assert goldens["code_generation"]["passed"] is True
    assert goldens["vision"]["passed"] is True
    assert goldens["speech"]["passed"] is True
    assert "turn left at the next street" not in str(goldens["speech"])
    assert goldens["code_generation"]["response_bytes"] > 0


def test_inference_benchmark_runs_model_goldens_and_persists_metrics_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from local_ai_hub.services import LocalAIServices

    calls: list[tuple[str, object]] = []

    def delegate(_services, args: dict[str, object], tenant: str) -> dict[str, object]:
        calls.append(("delegate", tenant))
        return {
            "success": True,
            "model": "test-code",
            "text": "def generated_answer(value: int) -> int:\n    return value + 1\n",
        }

    def vision(_services, args: dict[str, object], tenant: str) -> dict[str, object]:
        calls.append(("vision", args["image"]))
        return {
            "success": True,
            "model": "test-vision",
            "response": "{\"summary\":\"A green square on white.\"}",
            "review": {"summary": "A green square on white."},
        }

    def transcribe(_services, args: dict[str, object], tenant: str) -> dict[str, object]:
        calls.append(("transcribe", Path(str(args["audio"]))))
        return {"success": True, "model": "whisper", "engine": "whisper_cli", "text": "Turn left at the next street."}

    monkeypatch.setattr(LocalAIServices, "delegate", delegate)
    monkeypatch.setattr(LocalAIServices, "vision", vision)
    monkeypatch.setattr(LocalAIServices, "transcribe", transcribe)
    sampled_vram = iter(range(1, 9))
    monkeypatch.setattr(
        surface_benchmarks,
        "_sample_dedicated_vram_bytes",
        lambda: next(sampled_vram) * 1024 * 1024,
    )

    class FakeRunner:
        config = {
            "models": {"fast_code": "test-code", "vision": "test-vision"},
            "server": {"ollama_url": "http://127.0.0.1:11434"},
        }

        def run(self, **_kwargs: object) -> dict[str, object]:
            return {
                "success": True,
                "model_digest": "sha256:" + ("a" * 64),
                "ttft_ms": 2.0,
                "tokens_per_second": 4.0,
                "generation_duration_ms": 10.0,
                "tokens_generated": 8,
                "load_duration_ms": 5.0,
                "initial_vram": {"vram_used_mb": 10},
                "final_vram": {"vram_used_mb": 12},
            }

    audio_fixture = tmp_path / "known.wav"
    audio_fixture.write_bytes(b"known audio fixture")
    result = run_benchmark(
        state_dir=tmp_path / "state",
        scratch_dir=tmp_path / "scratch",
        file_count=2,
        rag_chunks=2,
        repetitions=1,
        comparison_repetitions=1,
        concurrency=(1,),
        inference_runner=FakeRunner(),
        include_inference=True,
        speech_fixture=audio_fixture,
        speech_expected_text="turn left at the next street",
    )

    record_text = Path(result["record_path"]).read_text(encoding="utf-8")
    assert result["success"] is True
    assert [name for name, _ in calls] == ["delegate", "vision", "transcribe"]
    assert isinstance(calls[1][1], str) and calls[1][1].startswith("data:image/png;base64,")
    assert isinstance(calls[2][1], Path) and calls[2][1].parent != audio_fixture.parent
    assert result["metadata"]["golden_operations"]["code_generation"] is True
    assert result["metadata"]["golden_operations"]["vision"] is True
    assert result["metadata"]["golden_operations"]["speech"] is True
    assert result["golden"]["code_generation"]["sample_count"] == 1
    assert result["golden"]["vision"]["response_bytes"] > 0
    assert result["golden"]["speech"]["peak_vram_bytes"] == 6 * 1024 * 1024
    assert result["resource_usage"]["peak_vram_bytes"] == 12 * 1024 * 1024
    assert str(audio_fixture) not in record_text
    assert "turn left at the next street" not in record_text


def test_speech_golden_identity_hashes_fixture_without_recording_its_path_or_transcript(tmp_path: Path) -> None:
    audio_fixture = tmp_path / "private-speech.wav"
    audio_fixture.write_bytes(b"fixture audio")

    identity = _speech_golden_identity(audio_fixture, "turn left at the next street")

    assert identity is not None
    assert identity["fixture_size_bytes"] == len(b"fixture audio")
    assert str(audio_fixture) not in str(identity)
    assert "turn left at the next street" not in str(identity)


def test_speech_golden_stages_audio_outside_original_fixture_directory(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    scratch_dir = tmp_path / "scratch"
    source_dir.mkdir()
    scratch_dir.mkdir()
    audio_fixture = source_dir / "spoken.wav"
    audio_fixture.write_bytes(b"audio fixture")

    staged = _stage_speech_golden_fixture(audio_fixture, scratch_dir)

    assert staged == scratch_dir / "speech-golden.wav"
    assert staged.read_bytes() == audio_fixture.read_bytes()
    assert not audio_fixture.with_suffix(".txt").exists()


def test_vram_sampler_requires_live_dedicated_gpu_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai_hub import gpu_monitor

    telemetry = {
        "available": True,
        "backend": "cuda",
        "vram_total_mb": 8192,
        "vram_used_mb": 1024,
    }
    monkeypatch.setattr(gpu_monitor, "get_gpu_telemetry", lambda: dict(telemetry))

    assert _sample_dedicated_vram_bytes() == 1024 * 1024 * 1024

    telemetry["integrated"] = True
    assert _sample_dedicated_vram_bytes() is None
    telemetry["integrated"] = False
    telemetry["available"] = False
    assert _sample_dedicated_vram_bytes() is None


def test_inference_config_copies_only_model_and_local_runtime_scalars() -> None:
    import tomllib

    class Runner:
        config = {
            "models": {"fast_code": "coder:7b", "vision": "vision:9b"},
            "ollama": {"base_url": "http://127.0.0.1:11434", "keep_alive": "5m", "api_key": "secret"},
            "server": {"state_dir": "private-state", "ollama_url": "http://127.0.0.1:11438"},
        }

    raw = _benchmark_inference_config(Runner())
    parsed = tomllib.loads(raw)

    assert parsed["models"] == {"fast_code": "coder:7b", "vision": "vision:9b"}
    assert parsed["ollama"] == {"base_url": "http://127.0.0.1:11434", "keep_alive": "5m"}
    assert _benchmark_inference_server_url(Runner()) == "http://127.0.0.1:11438"
    assert "secret" not in raw and "private-state" not in raw


def test_plan_grade_inference_matrix_requires_speech_golden_before_allocating_state(tmp_path: Path) -> None:
    state_dir = tmp_path / "benchmark-state"

    with pytest.raises(ValueError, match="known-audio speech fixture"):
        run_benchmark_matrix(
            state_dir=state_dir,
            inference_runner=object(),
            include_inference=True,
        )

    assert not state_dir.exists()


def test_plan_grade_gate_rejects_malformed_metadata_without_crashing() -> None:
    reasons = _plan_grade_reasons({
        "stage_repetitions": {"light": "1000", "comparison": None},
        "concurrency": [1, 4, 16, []],
        "full": True,
        "synthetic_file_count": 10_000,
        "rag_chunk_count": 10_000,
    })

    assert "light_repetitions_below_1000" in reasons
    assert "comparison_repetitions_below_30" in reasons
    assert "concurrency_must_include_1_4_16_32" in reasons


def test_plan_grade_requires_explicit_complete_matrix_and_golden_operations() -> None:
    metadata = _plan_grade_metadata()
    assert _plan_grade_reasons(metadata) == []

    metadata["completed_matrix"] = _completed_matrix()[:-1]
    reasons = _plan_grade_reasons(metadata)
    assert "completed_matrix_missing_or_incomplete" in reasons

    metadata["completed_matrix"] = _completed_matrix()
    first_case = metadata["completed_matrix"][0]
    first_case["golden_operations"]["vision"] = False
    reasons = _plan_grade_reasons(metadata)
    assert "required_golden_operations_incomplete" in reasons


def test_plan_grade_rejects_unestablished_sample_independence() -> None:
    metadata = _plan_grade_metadata()
    stages = _comparison_stages(1.0)
    stages["hub_code_index"]["sample_independence_status"] = "not_established"

    reasons = _plan_grade_reasons(metadata, stages)

    assert "sample_independence_not_established:hub_code_index" in reasons


def test_plan_grade_rejects_forged_sample_independence_without_epoch_proof() -> None:
    metadata = _plan_grade_metadata()
    stages = _comparison_stages(1.0)
    stages["hub_code_index"].pop("sample_independence_proof", None)

    reasons = _plan_grade_reasons(metadata, stages)

    assert "sample_independence_proof_invalid:hub_code_index" in reasons


def test_plan_grade_requires_concurrent_service_samples_at_all_load_levels() -> None:
    metadata = _plan_grade_metadata()
    stages = _comparison_stages(1.0)
    stages["hub_context_pack"]["service_concurrency"]["by_concurrency"].pop("32")

    reasons = _plan_grade_reasons(metadata, stages)

    assert "service_concurrency_incomplete:32" in reasons


def test_plan_grade_uses_1000_total_light_samples_and_30_paired_heavy_samples() -> None:
    metadata = _plan_grade_metadata()
    stages = _comparison_stages(1.0)
    light_stages = {"transport", "hub_health", "hub_validation", "hub_queue_admission"}
    for name in light_stages:
        stages[name]["samples_by_regime"] = {"cold": [1.0], "warm": [1.0] * 999}
        stages[name]["sample_ids_by_regime"] = {
            "cold": [f"{name}:cold:0"],
            "warm": [f"{name}:warm:{index}" for index in range(999)],
        }
        stages[name]["sample_independence_status"] = "not_established"

    assert _plan_grade_reasons(metadata, stages) == []

    stages["hub_health"]["samples_by_regime"]["warm"].pop()
    stages["hub_health"]["sample_ids_by_regime"]["warm"].pop()
    assert "light_samples_below_1000:hub_health" in _plan_grade_reasons(metadata, stages)


def test_plan_grade_accepts_exactly_30_paired_expensive_samples() -> None:
    metadata = _plan_grade_metadata()
    baseline = {
        "success": True,
        "metadata": metadata,
        "stages": _comparison_stages(1.0, cold=30, warm=30),
    }
    candidate = {
        "success": True,
        "metadata": json.loads(json.dumps(metadata)),
        "stages": _comparison_stages(0.5, cold=30, warm=30),
    }

    comparison = compare_records(baseline, candidate)
    metrics = comparison.get("provisional", comparison)

    assert comparison["status"] == "improved"
    assert metrics["compared_stage_count"] == len(surface_benchmarks._REQUIRED_COMPARISON_STAGES)
    assert metrics["stages"]["hub_code_index"]["cold"]["paired_count"] == 30
    assert metrics["stages"]["hub_code_index"]["cold"]["paired_mean_delta_pct"] == -50.0


def test_plan_grade_rejects_fewer_than_30_paired_expensive_samples() -> None:
    metadata = _plan_grade_metadata()
    baseline = {
        "success": True,
        "metadata": metadata,
        "stages": _comparison_stages(1.0, cold=29, warm=30),
    }
    candidate = {
        "success": True,
        "metadata": json.loads(json.dumps(metadata)),
        "stages": _comparison_stages(0.5, cold=29, warm=30),
    }

    comparison = compare_records(baseline, candidate)

    assert comparison["status"] == "inconclusive"
    assert "paired_tail_samples_below_30:hub_code_index:cold" in comparison["reason"]
    assert "paired_samples_below_30:hub_code_index:cold" in comparison["reason"]


def test_single_full_file_rag_pair_is_not_whole_plan_grade() -> None:
    metadata = _plan_grade_metadata()
    metadata.update({
        "completed_matrix": [_completed_matrix()[-1]],
        "full": True,
        "synthetic_file_count": 100_000,
        "rag_chunk_count": 100_000,
    })

    reasons = _plan_grade_reasons(metadata)

    assert "completed_matrix_missing_or_incomplete" in reasons


def test_plan_grade_inference_requires_valid_model_digest() -> None:
    metadata = _plan_grade_metadata()
    metadata["inference"] = "requested"
    metadata["inference_model_digest"] = "not-a-content-digest"

    assert "inference_model_digest_missing_or_invalid" in _plan_grade_reasons(metadata)

    metadata["inference_model_digest"] = "sha256:" + "a" * 64
    assert "inference_model_digest_missing_or_invalid" not in _plan_grade_reasons(metadata)


def test_run_benchmark_retains_busy_scratch_without_cleanup_watcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scratch_parent = tmp_path / "scratch"
    worker_start_gate = threading.Event()
    worker_start_attempted = threading.Event()
    worker_finished = threading.Event()
    observed: dict[str, Any] = {"capture_dispatch": False}
    cleanup_watchers: list[threading.Thread] = []
    sentinel_task_id = "t02-controlled-late-worker"
    original_submit = AsyncJobManager.submit
    original_execute = AsyncJobManager._execute
    original_dispatch_background = AsyncJobManager._dispatch_background
    original_thread_start = threading.Thread.start

    def capture_dispatch(self: AsyncJobManager, job_id: str) -> None:
        if observed["capture_dispatch"]:
            observed["capture_dispatch"] = False
            observed["manager"] = self
            observed["job_id"] = job_id
            observed["database_path"] = self.path
        original_dispatch_background(self, job_id)

    def inspect_worker_database(self: AsyncJobManager, job_id: str) -> dict[str, Any]:
        if job_id != observed.get("job_id"):
            return original_execute(self, job_id)
        observed["worker_thread"] = threading.current_thread()
        worker_start_attempted.set()
        worker_start_gate.wait()
        try:
            connection = sqlite3.connect(self.path, timeout=0.2)
            try:
                connection.execute("SELECT 1").fetchone()
            finally:
                connection.close()
            observed["worker_database_error"] = None
        except sqlite3.Error as exc:
            observed["worker_database_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            worker_finished.set()
        return {"success": True, "state": "done"}

    def inject_worker_after_admission(
        self: AsyncJobManager, tenant: str, action: str, payload: dict[str, Any], *,
        dispatch_delay_seconds: float = 0.0,
    ) -> dict[str, Any]:
        result = original_submit(
            self, tenant, action, payload, dispatch_delay_seconds=dispatch_delay_seconds,
        )
        if dispatch_delay_seconds and not observed.get("injected"):
            observed["injected"] = True
            observed["capture_dispatch"] = True
            injected = original_submit(
                self, tenant, action, {"task_id": sentinel_task_id}, dispatch_delay_seconds=0.0,
            )
            assert injected["success"] is True
            assert worker_start_attempted.wait(timeout=3)
        return result

    def intercept_thread_start(thread: threading.Thread) -> None:
        if thread.name == "benchmark-scratch-cleanup":
            cleanup_watchers.append(thread)
        original_thread_start(thread)

    monkeypatch.setattr(AsyncJobManager, "submit", inject_worker_after_admission)
    monkeypatch.setattr(AsyncJobManager, "_execute", inspect_worker_database)
    monkeypatch.setattr(AsyncJobManager, "_dispatch_background", capture_dispatch)
    monkeypatch.setattr(threading.Thread, "start", intercept_thread_start)

    manager: AsyncJobManager | None = None
    scratch_root: Path | None = None
    try:
        result = run_benchmark(
            state_dir=tmp_path / "results", scratch_dir=scratch_parent,
            file_count=12, rag_chunks=20, repetitions=2, light_repetitions=3,
            comparison_repetitions=2, concurrency=(1, 2),
        )
        manager = observed.get("manager")
        assert isinstance(manager, AsyncJobManager)
        scratch_root = Path(observed["database_path"]).parents[1]
        queue_stage = result.get("stages", {}).get("hub_queue_admission", {})
        assert result["success"] is True, queue_stage.get("failed_samples", [])
        assert worker_start_attempted.is_set()
        assert not worker_start_gate.is_set()
        assert scratch_root.is_dir()
        assert cleanup_watchers == []
        observed["worker_alive_before_second_run"] = bool(
            isinstance(observed.get("worker_thread"), threading.Thread)
            and observed["worker_thread"].is_alive()
        )
        observed["retained_scratch_count_before_second_run"] = len(
            surface_benchmarks._RETAINED_BENCHMARK_SCRATCH,
        )
        assert observed["worker_alive_before_second_run"] is True, observed
        assert observed["retained_scratch_count_before_second_run"] == 1, observed
        with pytest.raises(RuntimeError, match="scratch cleanup is still pending"):
            run_benchmark(
                state_dir=tmp_path / "second-results", scratch_dir=tmp_path / "second-scratch",
                file_count=4, rag_chunks=8, repetitions=1, light_repetitions=1,
                comparison_repetitions=1, concurrency=(1,),
            )
        assert not (tmp_path / "second-scratch").exists()
    finally:
        worker_start_gate.set()
        worker_thread = observed.get("worker_thread")
        manager = manager or observed.get("manager")
        deadline = time.monotonic() + 5
        while True:
            threads: list[threading.Thread] = list(cleanup_watchers)
            if isinstance(worker_thread, threading.Thread):
                threads.append(worker_thread)
            if isinstance(manager, AsyncJobManager):
                threads.extend(manager._delayed_dispatch.values())
                threads.extend(manager._dispatchers)
                threads.extend(manager._workers)
            for _, _, retained_groups, _, _ in surface_benchmarks._RETAINED_BENCHMARK_SCRATCH:
                threads.extend(thread for group in retained_groups for thread in group)
            threads.extend(
                thread for thread in threading.enumerate()
                if thread.name == "hub-surface-benchmark-http"
            )
            alive = tuple(dict.fromkeys(
                thread for thread in threads
                if thread is not threading.current_thread() and thread.is_alive()
            ))
            if not alive:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            joinable = False
            for thread in alive:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if thread.ident is not None:
                    joinable = True
                    thread.join(timeout=min(0.05, remaining))
            if not joinable:
                threading.Event().wait(min(0.01, remaining))
        assert not alive, f"benchmark-owned threads did not stop: {[thread.name for thread in alive]}"
        surface_benchmarks._reap_retained_benchmark_scratch()
    assert worker_finished.is_set()
    assert observed["worker_database_error"] is None
    assert scratch_root is not None and not scratch_root.exists()


def test_run_benchmark_rejects_concurrent_invocation_before_allocating_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered_run = threading.Event()
    release_run = threading.Event()
    original_resolve = surface_benchmarks._resolve_outside_repo
    first_result: dict[str, Any] = {}

    def pause_first_run(path: Path, name: str) -> Path:
        if name == "state_dir" and not entered_run.is_set():
            entered_run.set()
            assert release_run.wait(timeout=10)
        return original_resolve(path, name)

    def run_first_benchmark() -> None:
        try:
            first_result["result"] = run_benchmark(
                state_dir=tmp_path / "first-state", scratch_dir=tmp_path / "first-scratch",
                file_count=4, rag_chunks=8, repetitions=1, light_repetitions=1,
                comparison_repetitions=1, concurrency=(1,),
            )
        except Exception as exc:
            first_result["error"] = exc

    monkeypatch.setattr(surface_benchmarks, "_resolve_outside_repo", pause_first_run)
    first_thread = threading.Thread(
        target=run_first_benchmark, name="benchmark-concurrency-regression", daemon=True,
    )
    first_thread.start()
    try:
        assert entered_run.wait(timeout=5)
        with pytest.raises(RuntimeError, match="another benchmark run is already in progress"):
            run_benchmark(
                state_dir=tmp_path / "second-state", scratch_dir=tmp_path / "second-scratch",
                file_count=4, rag_chunks=8, repetitions=1, light_repetitions=1,
                comparison_repetitions=1, concurrency=(1,),
            )
        assert not (tmp_path / "second-state").exists()
        assert not (tmp_path / "second-scratch").exists()
    finally:
        release_run.set()
        first_thread.join(timeout=25)

    assert not first_thread.is_alive()
    assert "error" not in first_result, repr(first_result.get("error"))
    assert first_result["result"]["success"] is True


def test_retained_scratch_reaper_resamples_late_worker_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SimpleNamespace(
        _lock=threading.RLock(), _delayed_dispatch={}, _dispatchers=set(), _workers=set(),
    )
    app = SimpleNamespace(async_jobs=manager)
    dispatch_entered = threading.Event()
    release_dispatch = threading.Event()
    worker_entered = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()
    retained = surface_benchmarks.tempfile.TemporaryDirectory(
        prefix="late-worker-reaper-", dir=tmp_path,
    )
    scratch_root = Path(retained.name)

    def worker_run() -> None:
        worker_entered.set()
        try:
            assert release_worker.wait(timeout=5)
        finally:
            worker_finished.set()
            with manager._lock:
                manager._workers.discard(worker)

    worker = threading.Thread(target=worker_run, name="async-job-late-reaper", daemon=True)

    def dispatch_run() -> None:
        dispatch_entered.set()
        try:
            if release_dispatch.wait(timeout=5):
                with manager._lock:
                    manager._workers.add(worker)
                worker.start()
        finally:
            with manager._lock:
                manager._dispatchers.discard(dispatcher)

    dispatcher = threading.Thread(target=dispatch_run, name="async-dispatch-late-reaper", daemon=True)
    with manager._lock:
        manager._dispatchers.add(dispatcher)
    dispatcher.start()
    assert dispatch_entered.wait(timeout=2)

    before_close = surface_benchmarks._benchmark_owned_thread_groups(app)
    surface_benchmarks._cleanup_scratch_after_benchmark_threads(retained, app, before_close)
    assert scratch_root.is_dir()

    original_snapshot = surface_benchmarks._benchmark_owned_thread_groups
    reaper_snapshot_taken = False

    def release_after_reaper_snapshot(snapshot_app: Any) -> tuple[tuple[threading.Thread, ...], ...]:
        nonlocal reaper_snapshot_taken
        groups = original_snapshot(snapshot_app)
        if not reaper_snapshot_taken:
            reaper_snapshot_taken = True
            release_dispatch.set()
        return groups

    monkeypatch.setattr(surface_benchmarks, "_benchmark_owned_thread_groups", release_after_reaper_snapshot)
    try:
        with pytest.raises(RuntimeError, match="scratch cleanup is still pending"):
            surface_benchmarks._reap_retained_benchmark_scratch()
        assert worker_entered.wait(timeout=2)
        assert scratch_root.is_dir()
    finally:
        release_dispatch.set()
        release_worker.set()
        deadline = time.monotonic() + 2
        for thread in (dispatcher, worker):
            remaining = deadline - time.monotonic()
            if thread.ident is not None and remaining > 0:
                thread.join(timeout=remaining)
        monkeypatch.setattr(surface_benchmarks, "_benchmark_owned_thread_groups", original_snapshot)
        surface_benchmarks._reap_retained_benchmark_scratch()
    assert worker_finished.is_set()
    assert not scratch_root.exists()


def test_cleanup_retains_scratch_until_active_http_handler_finishes(tmp_path: Path) -> None:
    handler_active = False
    handler_lock = threading.Lock()
    handler_entered = threading.Event()
    release_handler = threading.Event()
    scratch = surface_benchmarks.tempfile.TemporaryDirectory(
        prefix="http-handler-reaper-", dir=tmp_path,
    )
    scratch_root = Path(scratch.name)

    def concurrency_stats() -> dict[str, int]:
        with handler_lock:
            return {"active": int(handler_active)}

    server = SimpleNamespace(concurrency_stats=concurrency_stats)

    def serve_request() -> None:
        nonlocal handler_active
        with handler_lock:
            handler_active = True
        handler_entered.set()
        try:
            assert release_handler.wait(timeout=5)
        finally:
            with handler_lock:
                handler_active = False

    request_thread = threading.Thread(target=serve_request, name="benchmark-http-handler", daemon=True)
    request_thread.start()
    assert handler_entered.wait(timeout=2)

    try:
        surface_benchmarks._cleanup_scratch_after_benchmark_threads(
            scratch, None, ((), (), ()), http_server=server,
        )
        assert scratch_root.is_dir()
        with pytest.raises(RuntimeError, match="scratch cleanup is still pending"):
            surface_benchmarks._reap_retained_benchmark_scratch()
        assert scratch_root.is_dir()
    finally:
        release_handler.set()
        request_thread.join(timeout=2)
        surface_benchmarks._reap_retained_benchmark_scratch()
    assert not request_thread.is_alive()
    assert not scratch_root.exists()


def test_python_allocation_peak_starts_and_stops_owned_tracing() -> None:
    trace = surface_benchmarks.tracemalloc
    if trace.is_tracing():
        pytest.skip("another caller already owns tracemalloc")
    held: list[bytearray] = []

    result = surface_benchmarks._measure_python_allocation_peak(
        lambda: held.append(bytearray(256 * 1024)),
    )

    assert result["status"] == "passed"
    assert result["peak_python_allocated_bytes"] > 0
    assert not trace.is_tracing()


def test_python_allocation_peak_preserves_caller_tracing_and_peak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = surface_benchmarks.tracemalloc
    tracing_before = trace.is_tracing()
    if not tracing_before:
        trace.start()
    try:
        trace.reset_peak()
        _, peak_before = trace.get_traced_memory()
        original_reset_peak = trace.reset_peak
        reset_calls = 0

        def record_reset_peak() -> None:
            nonlocal reset_calls
            reset_calls += 1
            original_reset_peak()

        monkeypatch.setattr(trace, "reset_peak", record_reset_peak)
        ran: list[bytearray] = []
        result = surface_benchmarks._measure_python_allocation_peak(
            lambda: ran.append(bytearray(512 * 1024)),
        )
        _, peak_after = trace.get_traced_memory()

        assert result["status"] == "skipped"
        assert result["reason"] == "caller_tracemalloc_already_active"
        assert result["peak_python_allocated_bytes"] is None
        assert ran
        assert reset_calls == 0
        assert peak_after >= peak_before
        assert trace.is_tracing()
    finally:
        if not tracing_before and trace.is_tracing():
            trace.stop()


def test_run_benchmark_is_isolated_and_preserves_existing_scratch_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest,
) -> None:
    state_dir = tmp_path / "state"
    scratch_dir = tmp_path / "synthetic"
    sqlite_operational_errors: list[dict[str, object]] = []
    diagnostic: dict[str, object] = {"nodeid": request.node.nodeid}

    for method_name in ("submit", "cancel"):
        original_method = getattr(AsyncJobManager, method_name)

        def observe_sqlite_errors(self, *args, _method=method_name, _original=original_method, **kwargs):
            try:
                return _original(self, *args, **kwargs)
            except sqlite3.OperationalError as exc:
                sqlite_operational_errors.append({
                    "operation": _method,
                    "database_path": str(self.path),
                    "thread": threading.current_thread().name,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                })
                raise

        monkeypatch.setattr(AsyncJobManager, method_name, observe_sqlite_errors)

    previous_thread_excepthook = threading.excepthook

    def observe_thread_sqlite_errors(args) -> None:
        if isinstance(args.exc_value, sqlite3.OperationalError):
            sqlite_operational_errors.append({
                "operation": "uncaught_thread_exception",
                "thread": args.thread.name,
                "exception_type": type(args.exc_value).__name__,
                "message": str(args.exc_value),
            })
        previous_thread_excepthook(args)

    monkeypatch.setattr(threading, "excepthook", observe_thread_sqlite_errors)

    diagnostic["async_jobs_before"] = _async_jobs_lifecycle_snapshot(scratch_dir)

    def emit_diagnostic() -> None:
        diagnostic["async_jobs_at_teardown"] = _async_jobs_lifecycle_snapshot(scratch_dir)
        diagnostic["sqlite_operational_errors"] = sqlite_operational_errors
        print("T02_DIAGNOSTIC=" + json.dumps(diagnostic, sort_keys=True, separators=(",", ":"), default=str))

    request.addfinalizer(emit_diagnostic)

    collision_path = scratch_dir / "repo" / "src" / "module_000000.py"
    collision_path.parent.mkdir(parents=True)
    collision_path.write_text("user-owned sentinel", encoding="utf-8")

    try:
        result = run_benchmark(
            state_dir=state_dir,
            scratch_dir=scratch_dir,
            file_count=12,
            rag_chunks=20,
            repetitions=2,
            light_repetitions=3,
            comparison_repetitions=2,
            concurrency=(1, 2),
        )
    finally:
        diagnostic["async_jobs_after_baseline_close"] = _async_jobs_lifecycle_snapshot(scratch_dir)

    diagnostic["baseline_result"] = {
        "success": result.get("success"),
        "failed_stages": result.get("failed_stages", []),
        "stage_failures": {
            name: {
                "error_count": stage.get("error_count"),
                "error_types": stage.get("error_types", []),
                "error_reasons": stage.get("error_reasons", {}),
            }
            for name, stage in result.get("stages", {}).items()
            if isinstance(stage, dict) and stage.get("status") == "failed"
        },
    }
    print("T02_BASELINE_RESULT=" + json.dumps(
        diagnostic["baseline_result"], sort_keys=True, separators=(",", ":"), default=str,
    ))
    assert result["success"] is True
    assert collision_path.read_text(encoding="utf-8") == "user-owned sentinel"
    assert result["metadata"]["benchmark_scope"] == "hub_app_synthetic_repo"
    assert result["metadata"]["runtime_source_root"] == str(Path(__file__).resolve().parents[1] / "src")
    assert "preseeded warm keys" in result["metadata"]["cold_warm_policy"]
    assert result["metadata"]["prewarm_enabled"] is False
    assert result["metadata"]["observability_enabled"] is False
    assert "processor" in result["metadata"]["platform"]
    assert "total_memory_bytes" in result["metadata"]["platform"]
    assert result["metadata"]["synthetic_file_count"] == 12
    assert result["metadata"]["rag_chunk_count"] == 20
    assert result["metadata"]["stage_repetitions"] == {"light": 3, "comparison": 2}
    sqlite_index_stage = result["stages"]["hub_sqlite_index"]
    expected_sqlite_index_ids = {
        "cold": [
            "sqlite-index:cold:src/module_000000.py",
            "sqlite-index:cold:src/module_000001.py",
        ],
        "warm": [
            "sqlite-index:warm:src/module_000002.py",
            "sqlite-index:warm:src/module_000003.py",
        ],
    }
    assert sqlite_index_stage["sample_ids_by_regime"] == {
        **expected_sqlite_index_ids,
    }
    assert sqlite_index_stage["sample_independence_status"] == "established"
    assert sqlite_index_stage["sample_identity_provenance"] == surface_benchmarks._sample_identity_provenance(
        sqlite_index_stage["workload_fingerprint"],
    )
    assert sqlite_index_stage["main_repo_seeded_files"] == 12
    sqlite_read_stage = result["stages"]["hub_sqlite_db_read"]
    expected_sqlite_read_ids = [
        "sqlite-db-read:src/module_000000.py:symbol_0",
        "sqlite-db-read:src/module_000001.py:symbol_1",
    ]
    assert sqlite_read_stage["sample_ids_by_regime"] == {
        "cold": expected_sqlite_read_ids,
        "warm": expected_sqlite_read_ids,
    }
    assert sqlite_read_stage["sample_identity_provenance"] == surface_benchmarks._sample_identity_provenance(
        sqlite_read_stage["workload_fingerprint"],
    )
    assert sqlite_read_stage["sample_independence_status"] == "established"
    code_index_stage = result["stages"]["hub_code_index"]
    expected_code_index_ids = [
        "code-index:src/module_000000.py:benchmarkcase000000:cold",
        "code-index:src/module_000001.py:benchmarkcase000001:cold",
    ]
    assert code_index_stage["sample_ids_by_regime"] == {
        "cold": expected_code_index_ids,
        "warm": [sample_id.replace(":cold", ":warm") for sample_id in expected_code_index_ids],
    }
    assert code_index_stage["sample_independence_status"] == "established"
    assert code_index_stage["sample_identity_provenance"] == surface_benchmarks._sample_identity_provenance(
        code_index_stage["workload_fingerprint"],
    )
    context_pack_stage = result["stages"]["hub_context_pack"]
    expected_context_pack_ids = [
        "context-pack:src/module_000000.py:benchmarkcase000000",
        "context-pack:src/module_000001.py:benchmarkcase000001",
    ]
    assert context_pack_stage["sample_ids_by_regime"] == {
        "cold": [f"{sample_id}:cold" for sample_id in expected_context_pack_ids],
        "warm": [f"{sample_id}:warm" for sample_id in expected_context_pack_ids],
    }
    assert context_pack_stage["sample_independence_status"] == "established"
    assert context_pack_stage["sample_identity_provenance"] == surface_benchmarks._sample_identity_provenance(
        context_pack_stage["workload_fingerprint"],
    )
    graph_caller_stage = result["stages"]["hub_call_graph_query"]
    expected_graph_caller_ids = [
        "callers:src/module_000000.py:graph_target_case_0",
        "callers:src/module_000001.py:graph_target_case_1",
    ]
    assert graph_caller_stage["sample_ids_by_regime"] == {
        "cold": expected_graph_caller_ids,
        "warm": expected_graph_caller_ids,
    }
    assert graph_caller_stage["sample_independence_status"] == "established"
    assert graph_caller_stage["sample_identity_provenance"] == surface_benchmarks._sample_identity_provenance(
        graph_caller_stage["workload_fingerprint"],
    )
    assert graph_caller_stage["paired_case_edges_all_found"] is True
    assert graph_caller_stage["golden_edge_found"] is True
    graph_callee_stage = result["stages"]["hub_call_graph_callees"]
    expected_graph_callee_ids = [
        "callees:src/module_000000.py:graph_caller_case_0",
        "callees:src/module_000001.py:graph_caller_case_1",
    ]
    assert graph_callee_stage["sample_ids_by_regime"] == {
        "cold": expected_graph_callee_ids,
        "warm": expected_graph_callee_ids,
    }
    assert graph_callee_stage["workload_fingerprint"] == graph_caller_stage["workload_fingerprint"]
    assert graph_callee_stage["sample_identity_provenance"] == surface_benchmarks._sample_identity_provenance(
        graph_callee_stage["workload_fingerprint"],
    )
    assert graph_callee_stage["paired_case_edges_all_found"] is True
    assert graph_callee_stage["golden_edge_found"] is True
    rag_chunking_stage = result["stages"]["hub_rag_chunking"]
    expected_rag_chunk_ids = [
        "rag-chunk:src/module_000000.py",
        "rag-chunk:src/module_000001.py",
    ]
    assert rag_chunking_stage["sample_ids_by_regime"] == {
        "cold": expected_rag_chunk_ids,
        "warm": expected_rag_chunk_ids,
    }
    assert rag_chunking_stage["sample_identity_provenance"] == surface_benchmarks._sample_identity_provenance(
        rag_chunking_stage["workload_fingerprint"],
    )
    assert result["metadata"]["inference"] == "skipped_not_requested"
    assert result["metadata"]["baseline_readiness"] == "per_case"
    assert result["metadata"]["matrix_aggregation"] == "not_performed_single_case_record"
    assert result["metadata"]["baseline_readiness_reasons"]
    assert result["metadata"]["implementation_fingerprint"]
    assert result["metadata"]["config_fingerprint"]
    assert result["metadata"]["hardware_fingerprint"]
    assert result["metadata"]["golden_operations"]["vision"] is False
    assert result["metadata"]["golden_operations"]["speech"] is False
    assert "not model tokenization" in result["metadata"]["whitespace_token_estimate"]
    assert result["golden"]["symbols"]["passed"] is True
    assert result["golden"]["context_pack"]["passed"] is True
    assert result["golden"]["graph"]["passed"] is True
    assert result["golden"]["graph"]["measurement"].startswith("CodeIndex.find_callers")
    assert result["golden"]["affected_tests"]["status"] == "passed"
    assert "tests/test_graph_target.py" in result["golden"]["affected_tests"]["observed_tests"]
    assert result["golden"]["retrieval_relevance"]["status"] == "passed"
    assert result["metadata"]["golden_operations"]["affected_tests"] is True
    assert result["metadata"]["golden_operations"]["retrieval_relevance"] is True
    for task in ("code_generation", "vision", "speech"):
        assert result["golden"][task]["status"] == "skipped_unavailable"
        assert result["golden"][task]["reason"]
    assert result["stages"]["hub_rag_fixture_relevance"]["quality_scope"] == "synthetic_fixture_only"
    assert result["synthetic_checks"]["graph"]["passed"] is True
    assert result["synthetic_checks"]["affected_tests"]["passed"] is True
    assert result["synthetic_checks"]["retrieval_relevance"]["passed"] is True
    assert result["synthetic_checks"]["code_generation"]["passed"] is True
    assert {"transport", "hub_health", "hub_validation", "hub_sqlite_index", "hub_code_index", "hub_context_pack", "hub_queue_admission", "hub_rag_chunking", "model_load", "inference"} <= set(result["stages"])
    assert not {"synthetic_validation", "synthetic_index", "synthetic_database", "synthetic_queue", "graph", "retrieval"} & set(result["stages"])
    assert all("p50_ms" in stage and "p95_ms" in stage and "p99_ms" in stage for stage in result["stages"].values())
    for stage in result["stages"].values():
        assert stage["cold_warm"]["cold"]["count"] <= 12
        assert stage["cold_warm"]["warm"]["count"] <= 12
    assert result["stages"]["transport"]["cold_warm"]["cold"]["count"] == 1
    assert result["stages"]["transport"]["cold_warm"]["warm"]["count"] == 2
    assert result["stages"]["hub_health"]["http_response_body_bytes"] > 0
    assert result["stages"]["hub_validation"]["http_response_body_bytes"] > 0
    assert "excludes HTTP headers" in result["metadata"]["http_response_body_bytes_scope"]
    assert all("response_bytes" not in stage for stage in result["stages"].values())
    assert result["stages"]["hub_queue_admission"]["measurement"] == "async_jobs_submit_cancel_admission_only"
    queue_stage = result["stages"]["hub_queue_admission"]
    expected_queue_ids = {
        "cold": [
            f"queue-admission:level-{level}:iteration-0:slot-{slot}"
            for level in (1, 2)
            for slot in range(level)
        ],
        "warm": [
            f"queue-admission:level-{level}:iteration-{iteration}:slot-{slot}"
            for level in (1, 2)
            for iteration in (1, 2)
            for slot in range(level)
        ],
    }
    assert queue_stage["sample_ids_by_regime"] == expected_queue_ids
    assert {
        regime: len(samples)
        for regime, samples in queue_stage["samples_by_regime"].items()
    } == {regime: len(sample_ids) for regime, sample_ids in expected_queue_ids.items()}
    assert queue_stage["sample_identity_provenance"] == surface_benchmarks._sample_identity_provenance(
        queue_stage["workload_fingerprint"],
    )
    assert queue_stage["sample_identity_unit"] == "concurrency_repetition_slot"
    assert result["stages"]["hub_rag_chunking"]["measurement"] == "RAGStore._chunks_chunker_only"
    assert result["resource_usage"]["peak_rss_bytes"] is None or result["resource_usage"]["peak_rss_bytes"] > 0
    assert "availability" in result["resource_usage"]
    assert result["resource_usage"]["availability"]["peak_vram_bytes"] == "not_measured_no_dedicated_gpu_telemetry"
    assert result["resource_usage"]["availability"]["peak_rss_scope"] == "process_lifetime_high_water_mark"
    assert result["resource_usage"]["availability"]["peak_rss_bytes"] == (
        "measured" if result["resource_usage"]["peak_rss_bytes"] is not None else "platform_unavailable"
    )
    assert result["stages"]["hub_validation"]["samples_ms"] and len(result["stages"]["hub_validation"]["samples_ms"]) == 3
    assert all("whitespace_token_estimate" in stage for stage in result["stages"].values())
    assert all("response_tokens_estimate" not in stage for stage in result["stages"].values())

    record_path = Path(result["record_path"])
    assert record_path.is_relative_to(state_dir)
    persisted = json.loads(record_path.read_text(encoding="utf-8"))
    serialized = json.dumps(persisted)
    assert str(tmp_path) not in serialized
    assert "def generated_symbol_" not in serialized

    try:
        compared = run_benchmark(
            state_dir=state_dir,
            scratch_dir=scratch_dir,
            file_count=12,
            rag_chunks=20,
            repetitions=2,
            light_repetitions=3,
            comparison_repetitions=2,
            concurrency=(1, 2),
            baseline_record=result,
        )
    finally:
        diagnostic["async_jobs_after_candidate_close"] = _async_jobs_lifecycle_snapshot(scratch_dir)
    diagnostic["candidate_result"] = {
        "success": compared.get("success"),
        "failed_stages": compared.get("failed_stages", []),
        "stage_failures": {
            name: {
                "error_count": stage.get("error_count"),
                "error_types": stage.get("error_types", []),
            }
            for name, stage in compared.get("stages", {}).items()
            if isinstance(stage, dict) and stage.get("status") == "failed"
        },
    }
    comparison = compared.get("comparison")
    diagnostic["comparison"] = _comparison_diagnostic(
        result,
        compared,
        comparison if isinstance(comparison, dict) else {},
    )
    assert compared["comparison"]["status"] == "inconclusive"
    assert compared["comparison"]["provisional"]["status"] in {
        "within_tolerance", "regression", "inconclusive",
    }
    persisted_comparison = json.loads(Path(compared["record_path"]).read_text(encoding="utf-8"))
    assert persisted_comparison["comparison"]["status"] == compared["comparison"]["status"]


def test_component_baselines_measure_graph_rag_batch_parent_seed_and_serena(tmp_path: Path) -> None:
    result = run_benchmark(
        state_dir=tmp_path / "state",
        file_count=4,
        rag_chunks=8,
        repetitions=1,
        light_repetitions=2,
        comparison_repetitions=2,
        concurrency=(1,),
    )

    stages = result["stages"]
    call_graph = stages["hub_call_graph_query"]
    assert call_graph["status"] == "passed"
    assert call_graph["measurement"] == "CodeIndex.find_callers"
    assert call_graph["expected_edge"] == ["graph_caller", "graph_target"]
    assert call_graph["golden_edge_found"] is True

    rag_batch = stages["hub_rag_batch_index"]
    assert rag_batch["status"] == "passed"
    assert rag_batch["measurement"] == "RAGStore.index_paths_step"
    assert rag_batch["chunks_per_second"] > 0
    assert rag_batch["workload_fingerprint"]
    cold_sample_ids = rag_batch["sample_ids_by_regime"]["cold"]
    warm_sample_ids = rag_batch["sample_ids_by_regime"]["warm"]
    assert len(cold_sample_ids) == len(warm_sample_ids) == 2
    assert len(set(cold_sample_ids)) == len(cold_sample_ids)
    assert len(set(warm_sample_ids)) == len(warm_sample_ids)
    assert cold_sample_ids == warm_sample_ids
    assert rag_batch["embedded_chunk_count_by_regime"]["cold"] > 0
    assert rag_batch["embedded_chunk_count_by_regime"]["warm"] == 0
    assert rag_batch["reused_chunk_count_by_regime"]["warm"] > 0
    assert rag_batch["workspace_count_by_regime"] == {"cold": 2, "warm": 2}
    assert rag_batch["sample_independence_status"] == "established"
    assert rag_batch["memory"]["scope"] == "python_allocation_peak"
    if rag_batch["memory"]["status"] == "passed":
        assert rag_batch["memory"]["peak_python_allocated_bytes"] > 0
    else:
        assert rag_batch["memory"]["status"] == "skipped"
        assert rag_batch["memory"]["reason"] == "caller_tracemalloc_already_active"
        assert rag_batch["memory"]["peak_python_allocated_bytes"] is None

    rag_search = stages["hub_rag_search"]
    assert rag_search["status"] == "passed"
    assert rag_search["quality_scope"] == "synthetic_fixture_only"
    assert rag_search["workload_fingerprint"]
    cold_search_ids = rag_search["sample_ids_by_regime"]["cold"]
    warm_search_ids = rag_search["sample_ids_by_regime"]["warm"]
    assert len(cold_search_ids) == len(warm_search_ids) == 2
    assert len(set(cold_search_ids)) == len(cold_search_ids)
    assert cold_search_ids == warm_search_ids
    assert rag_search["search_cache_scope"] == "isolated_by_workspace_and_revision"
    assert rag_search["embedding_cache_scope"] == "bypassed_by_deterministic_fixture"
    assert rag_search["search_cache_hits_by_regime"]["cold"] == 0
    assert rag_search["search_cache_hits_by_regime"]["warm"] == 2
    assert rag_search["query_embedding_calls_by_regime"] == {"cold": 2, "warm": 0}
    assert rag_search["sample_independence_status"] == "established"
    assert rag_search["ranking_metrics"]["recall_at_10"] == 1.0
    assert rag_search["ranking_metrics"]["ndcg_at_10"] == 1.0
    assert rag_search["ranking_metrics"]["file_evidence_accuracy_at_10"] == 1.0
    assert rag_search["ranking_metrics"]["line_evidence_status"] == "unsupported_no_line_offsets"

    backend_selection = stages["hub_backend_selection"]
    assert backend_selection["status"] == "skipped"
    assert backend_selection["reason"]

    rag_fixture = stages["hub_rag_fixture_relevance"]
    assert rag_fixture["status"] == "passed"
    assert rag_fixture["sample_ids_by_regime"]["cold"] == rag_fixture["sample_ids_by_regime"]["warm"]
    assert len(rag_fixture["sample_ids_by_regime"]["cold"]) == 2
    assert rag_fixture["sample_independence_status"] == "established"

    parent_seed = stages["parent_worktree_seed"]
    assert parent_seed["status"] == "passed"
    assert parent_seed["measurement"] == "ProjectPreprocessor._seed_from_parent"
    assert parent_seed["seeded_rows"]["code_index"] > 0
    assert parent_seed["sample_ids_by_regime"]["cold"] == parent_seed["sample_ids_by_regime"]["warm"]
    assert len(parent_seed["sample_ids_by_regime"]["cold"]) == 2
    assert parent_seed["sample_independence_status"] == "established"

    serena = stages["serena_pool_latency"]
    assert serena["status"] in {"passed", "skipped"}
    if serena["status"] == "skipped":
        assert serena["reason"]
        assert serena["samples_ms"] == []


@pytest.mark.parametrize(
    ("comparison_repetitions", "missing_concurrency", "compare_candidate", "improvement"),
    [
        (29, False, False, False),
        (30, False, False, False),
        (30, True, False, False),
        (30, False, True, False),
        (30, False, True, True),
    ],
)
def test_full_matrix_persists_cases_and_compares_each_size_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    comparison_repetitions: int,
    missing_concurrency: bool,
    compare_candidate: bool,
    improvement: bool,
) -> None:
    cases_seen: list[tuple[int, int]] = []
    expected_cases = sorted(surface_benchmarks._REQUIRED_MATRIX_CASES)
    baseline_samples = {key: float(index + 10) for index, key in enumerate(expected_cases)}
    candidate_samples = dict(baseline_samples)

    def fake_run_benchmark(**kwargs: Any) -> dict[str, object]:
        file_count = int(kwargs["file_count"])
        rag_chunk_count = int(kwargs["rag_chunks"])
        key = (file_count, rag_chunk_count)
        cases_seen.append((file_count, rag_chunk_count))
        metadata = {
            "benchmark_scope": "hub_app_synthetic_repo",
            "revision": "synthetic-revision",
            "implementation_fingerprint": "synthetic-implementation",
            "config_fingerprint": surface_benchmarks._config_fingerprint({
                "file_count": file_count,
                "rag_chunks": rag_chunk_count,
                "light_repetitions": int(kwargs["light_repetitions"]),
                "comparison_repetitions": int(kwargs["comparison_repetitions"]),
                "concurrency": list(kwargs["concurrency"]),
            }),
            "workload_fingerprint": surface_benchmarks._stable_fingerprint({
                "file_count": file_count,
                "rag_chunks": rag_chunk_count,
            }),
            "sample_identity_provenance": surface_benchmarks._sample_identity_provenance(
                surface_benchmarks._stable_fingerprint({
                    "file_count": file_count,
                    "rag_chunks": rag_chunk_count,
                }),
            ),
            "hardware_fingerprint": "synthetic-hardware",
            "platform": {"processor": "synthetic"},
            "full": True,
            "stage_repetitions": {
                "light": int(kwargs["light_repetitions"]),
                "comparison": int(kwargs["comparison_repetitions"]),
            },
            "concurrency": list(kwargs["concurrency"]),
            "synthetic_file_count": file_count,
            "rag_chunk_count": rag_chunk_count,
            "inference": "skipped_not_requested",
            "inference_model_digest": None,
            "golden_operations": {name: True for name in surface_benchmarks._REQUIRED_GOLDEN_OPERATIONS},
        }
        stages = _comparison_stages(
            candidate_samples[key],
            cold=int(kwargs["comparison_repetitions"]),
            warm=int(kwargs["comparison_repetitions"]),
        )
        if missing_concurrency and key == expected_cases[0]:
            stages["hub_context_pack"]["service_concurrency"]["by_concurrency"].pop("32")
        return {
            "success": True,
            "metadata": metadata,
            "stages": stages,
            "golden": {name: {"passed": True} for name in surface_benchmarks._REQUIRED_GOLDEN_OPERATIONS},
            "record_path": str(tmp_path / f"case-{file_count}-{rag_chunk_count}.json"),
        }

    monkeypatch.setattr(surface_benchmarks, "run_benchmark", fake_run_benchmark)
    matrix_args = {
        "state_dir": tmp_path / "matrix-state",
        "light_repetitions": 1_000,
        "comparison_repetitions": comparison_repetitions,
        "concurrency": (1, 4, 16, 32),
    }
    baseline = surface_benchmarks.run_benchmark_matrix(**matrix_args)

    assert cases_seen == expected_cases
    assert baseline["metadata"]["matrix_aggregation"] == "complete_six_case_cross_product"
    assert len({case["record"]["metadata"]["config_fingerprint"] for case in baseline["cases"]}) == 1
    assert len({case["record"]["metadata"]["workload_fingerprint"] for case in baseline["cases"]}) == 6
    assert len(json.loads(Path(baseline["record_path"]).read_text(encoding="utf-8"))["cases"]) == 6
    for case in baseline["cases"]:
        key = (case["file_count"], case["rag_chunk_count"])
        assert case["record"]["stages"]["hub_health"]["samples_by_regime"]["cold"][0] == baseline_samples[key]

    if missing_concurrency:
        assert baseline["metadata"]["baseline_readiness"] == "provisional"
        assert "matrix_case:100:10000:service_concurrency_incomplete:32" in baseline["metadata"]["baseline_readiness_reasons"]
        return

    if comparison_repetitions < 30:
        assert baseline["metadata"]["baseline_readiness"] == "provisional"
        assert baseline["metadata"]["baseline_readiness_reasons"]
        return

    assert baseline["metadata"]["baseline_readiness"] == "plan_grade"
    if not compare_candidate:
        assert baseline["metadata"]["baseline_readiness_reasons"] == []
        return

    cases_seen.clear()
    candidate_samples.update({
        key: value * (0.5 if improvement else 1.0 + (index + 1) / 100.0)
        for index, (key, value) in enumerate(baseline_samples.items())
    })
    candidate = surface_benchmarks.run_benchmark_matrix(**matrix_args, baseline_record=baseline)

    expected_status = "improved" if improvement else "within_tolerance"
    assert candidate["comparison"]["status"] == expected_status, {
        label: (comparison.get("status"), comparison.get("reason"))
        for label, comparison in candidate["comparison"].get("cases", {}).items()
    }
    assert candidate["comparison"]["compared_case_count"] == 6
    for index, key in enumerate(expected_cases):
        label = f"files={key[0]},rag_chunks={key[1]}"
        case_comparison = candidate["comparison"]["cases"][label]
        compared_stage = case_comparison["stages"]["hub_health"]["cold"]["latency"]["p50_ms"]
        assert compared_stage["baseline"] == baseline_samples[key]
        assert compared_stage["candidate"] == pytest.approx(candidate_samples[key])
        if index:
            previous_label = f"files={expected_cases[index - 1][0]},rag_chunks={expected_cases[index - 1][1]}"
            previous_comparison = candidate["comparison"]["cases"][previous_label]
            previous_stage = previous_comparison["stages"]["hub_health"]["cold"]["latency"]["p50_ms"]
            assert compared_stage["baseline"] != previous_stage["baseline"]

    duplicate = json.loads(json.dumps(candidate))
    duplicate["cases"][1]["file_count"] = duplicate["cases"][0]["file_count"]
    duplicate["cases"][1]["rag_chunk_count"] = duplicate["cases"][0]["rag_chunk_count"]
    duplicate_metadata = duplicate["cases"][1]["record"]["metadata"]
    duplicate_metadata["synthetic_file_count"] = duplicate["cases"][0]["file_count"]
    duplicate_metadata["rag_chunk_count"] = duplicate["cases"][0]["rag_chunk_count"]
    assert surface_benchmarks.compare_matrix_records(baseline, duplicate)["status"] == "incomparable"

    mislabeled = json.loads(json.dumps(candidate))
    mislabeled["cases"][0]["record"]["metadata"]["synthetic_file_count"] += 1
    assert surface_benchmarks.compare_matrix_records(baseline, mislabeled)["status"] == "incomparable"

    mismatched_goldens = json.loads(json.dumps(candidate))
    mismatched_goldens["cases"][0]["record"]["metadata"]["golden_operations"]["vision"] = False
    assert surface_benchmarks.compare_matrix_records(baseline, mismatched_goldens)["status"] == "incomparable"

    mismatched_row_goldens = json.loads(json.dumps(candidate))
    mismatched_row_goldens["metadata"]["completed_matrix"][0]["golden_operations"]["vision"] = False
    assert surface_benchmarks.compare_matrix_records(baseline, mismatched_row_goldens)["status"] == "incomparable"

    mismatched_matrix_goldens = json.loads(json.dumps(candidate))
    mismatched_matrix_goldens["metadata"]["golden_operations"]["vision"] = False
    assert surface_benchmarks.compare_matrix_records(baseline, mismatched_matrix_goldens)["status"] == "incomparable"


def test_large_benchmark_sizes_require_explicit_opt_in(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="full benchmark opt-in"):
        run_benchmark(
            state_dir=tmp_path / "state",
            scratch_dir=tmp_path / "synthetic",
            file_count=10_000,
            rag_chunks=10_000,
            repetitions=1,
            concurrency=(1,),
        )


def test_context_symbol_match_requires_exact_identifier() -> None:
    assert surface_benchmarks._contains_identifier("def symbol_10(value): return value", "symbol_1") is False
    assert surface_benchmarks._contains_identifier("def symbol_10(value): return value", "symbol_10") is True


def test_graph_edge_match_rejects_different_synthetic_case() -> None:
    result = {
        "success": True,
        "callers": [{"caller": "graph_caller_case_0", "callee": "graph_target_case_0"}],
    }

    assert surface_benchmarks._graph_edge_found(
        result, collection="callers", caller="graph_caller", callee="graph_target",
    ) is False
    assert surface_benchmarks._graph_edge_found(
        result, collection="callers", caller="graph_caller_case_0", callee="graph_target_case_0",
    ) is True


def test_benchmark_rejects_duplicate_concurrency_and_unbounded_samples(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="concurrency levels must be unique"):
        run_benchmark(
            state_dir=tmp_path / "state", file_count=2, rag_chunks=2,
            repetitions=1, concurrency=(1, 1),
        )
    with pytest.raises(ValueError, match="maximum is 1000"):
        run_benchmark(
            state_dir=tmp_path / "state", file_count=2, rag_chunks=2,
            repetitions=1, comparison_repetitions=1001, concurrency=(1,),
        )
    assert not (tmp_path / "state").exists()


def test_measure_stage_regimes_emits_stable_ids_for_equivalent_workloads() -> None:
    sample_ids = {
        "cold": ["health-query:case-alpha", "health-query:case-bravo", "health-query:case-charlie"],
        "warm": ["health-cache:block-alpha", "health-cache:block-bravo", "health-cache:block-charlie"],
    }
    measure = lambda: surface_benchmarks._measure_stage_regimes(
        "health workload",
        lambda _index: {"success": True},
        lambda _index: {"success": True},
        3,
        definition="same logical workload",
        workload_fingerprint="health-workload-v1",
        sample_ids_by_regime=sample_ids,
    )

    baseline = measure()
    candidate = measure()

    assert baseline["sample_ids_by_regime"] == candidate["sample_ids_by_regime"]
    assert baseline["workload_fingerprint"] == candidate["workload_fingerprint"]
    assert baseline["sample_identity_provenance"] == surface_benchmarks._sample_identity_provenance(
        "health-workload-v1",
    )
    assert baseline["sample_identity_unit"] == "declared_workload_label"
    assert baseline["sample_independence_status"] == "not_established"
    assert baseline["sample_independence_note"] == (
        "unique labels do not prove independent workloads or cache epochs"
    )
    for regime in ("cold", "warm"):
        ids = baseline["sample_ids_by_regime"][regime]
        assert len(ids) == 3
        assert len(set(ids)) == 3


def test_measure_stage_regimes_reports_errors_by_cold_and_warm_regime() -> None:
    def failed_warm_operation(_index: int) -> dict[str, bool]:
        raise RuntimeError("sensitive exception text must not be serialized")

    measured = surface_benchmarks._measure_stage_regimes(
        "synthetic stage",
        lambda _index: {"success": True},
        failed_warm_operation,
        3,
        definition="cold succeeds; warm fails",
    )

    assert measured["error_count_by_regime"] == {"cold": 0, "warm": 3}
    assert measured["error_rate_pct_by_regime"] == {"cold": 0.0, "warm": 100.0}
    assert measured["error_types_by_regime"] == {"cold": [], "warm": ["RuntimeError"]}
    assert measured["error_count_by_phase_by_regime"] == {
        "cold": {"before_each": 0, "operation": 0},
        "warm": {"before_each": 0, "operation": 3},
    }
    assert measured["error_count"] == 3
    assert "sensitive exception text" not in str(measured)


def test_measure_stage_regimes_attributes_preparation_errors_separately() -> None:
    def failed_warm_preparation(_index: int) -> None:
        raise RuntimeError("sensitive preparation error")

    measured = surface_benchmarks._measure_stage_regimes(
        "synthetic stage",
        lambda _index: {"success": True},
        lambda _index: {"success": True},
        2,
        warm_prepare=failed_warm_preparation,
        definition="warm preparation fails before operation",
    )

    assert measured["error_count_by_phase_by_regime"] == {
        "cold": {"before_each": 0, "operation": 0},
        "warm": {"before_each": 2, "operation": 0},
    }
    assert measured["error_count_by_regime"] == {"cold": 0, "warm": 2}
    assert "sensitive preparation error" not in str(measured)


def test_rag_workspace_count_verifier_uses_normalized_scope_key(tmp_path: Path) -> None:
    database = tmp_path / "rag.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE files (tenant TEXT, workspace TEXT)")
        connection.execute("CREATE TABLE chunks (tenant TEXT, workspace TEXT)")
        connection.execute("INSERT INTO files VALUES ('*', 'warm')")
        connection.executemany("INSERT INTO chunks VALUES (?, ?)", [("*", "warm")] * 3)
        connection.commit()
    finally:
        connection.close()

    class SharedScopeRagStore:
        def _scope_key(self, tenant: str) -> str:
            assert tenant == "t02-benchmark"
            return "*"

        def _connect(self) -> sqlite3.Connection:
            return sqlite3.connect(database)

    counts = surface_benchmarks._rag_workspace_document_counts(
        SharedScopeRagStore(), "t02-benchmark", "warm",
    )

    assert counts == {"files": 1, "chunks": 3}


def test_measure_concurrent_service_records_http_samples_by_concurrency() -> None:
    def request(_level: int, _repetition: int, _slot: int) -> surface_benchmarks._HTTPObservation:
        return surface_benchmarks._HTTPObservation(200, b'{"success":true}', {"success": True})

    measured = surface_benchmarks._measure_concurrent_service(
        "valid context pack",
        request,
        concurrency=(1, 4),
        repetitions=3,
    )

    assert measured["status"] == "passed"
    assert measured["by_concurrency"]["1"]["sample_count"] == 3
    assert measured["by_concurrency"]["4"]["sample_count"] == 12
    assert measured["by_concurrency"]["4"]["error_count"] == 0
    assert measured["by_concurrency"]["4"]["http_response_body_bytes"] == len(b'{"success":true}')
    assert measured["by_concurrency"]["4"]["batch_sample_ids"] == [
        f"context-pack-concurrency:4:batch:{index}" for index in range(3)
    ]
    assert len(measured["by_concurrency"]["4"]["batch_throughput_samples_per_second"]) == 3


def test_compare_service_concurrency_pairs_batches_and_measures_achieved_throughput() -> None:
    baseline = _comparison_stages(10.0)
    candidate = _comparison_stages(10.0)
    baseline_level = baseline["hub_context_pack"]["service_concurrency"]["by_concurrency"]["4"]
    candidate_level = candidate["hub_context_pack"]["service_concurrency"]["by_concurrency"]["4"]
    candidate_level["samples_ms"] = list(reversed(candidate_level["samples_ms"]))
    candidate_level["sample_ids"] = list(reversed(candidate_level["sample_ids"]))
    candidate_level["batch_sample_ids"] = list(reversed(candidate_level["batch_sample_ids"]))
    candidate_level["request_latency_samples_by_batch_ms"] = list(
        reversed(candidate_level["request_latency_samples_by_batch_ms"]),
    )
    candidate_level["request_sample_ids_by_batch"] = list(
        reversed(candidate_level["request_sample_ids_by_batch"]),
    )
    candidate_level["batch_throughput_samples_per_second"] = list(
        reversed(candidate_level["batch_throughput_samples_per_second"]),
    )

    result = surface_benchmarks._compare_service_concurrency(
        {"hub_context_pack": baseline["hub_context_pack"]},
        {"hub_context_pack": candidate["hub_context_pack"]},
        regression_tolerance=0.10,
        minimum_repetitions=30,
    )

    assert result["status"] == "within_tolerance"
    assert result["by_concurrency"]["4"]["paired_count"] == 30
    assert result["by_concurrency"]["4"]["paired_request_count"] == 120

    candidate_level["samples_ms"] = [20.0] * len(candidate_level["samples_ms"])
    candidate_level["request_latency_samples_by_batch_ms"] = [[20.0] * 4 for _ in range(30)]
    candidate_level["batch_throughput_samples_per_second"] = [
        value / 2.0 for value in candidate_level["batch_throughput_samples_per_second"]
    ]
    regression = surface_benchmarks._compare_service_concurrency(
        {"hub_context_pack": baseline["hub_context_pack"]},
        {"hub_context_pack": candidate["hub_context_pack"]},
        regression_tolerance=0.10,
        minimum_repetitions=30,
    )
    assert regression["status"] == "regression"
    assert regression["by_concurrency"]["4"]["paired_quantile_delta_pct"][
        "batch_p50_throughput"
    ]["estimate_pct"] == -50.0


def test_measure_stage_emits_stable_request_ids_for_cold_and_warm_samples() -> None:
    measure = lambda: surface_benchmarks._measure_stage(
        "health request",
        lambda: {"success": True},
        3,
    )

    baseline = measure()
    candidate = measure()

    assert baseline["sample_ids_by_regime"] == candidate["sample_ids_by_regime"]
    assert baseline["workload_fingerprint"] == candidate["workload_fingerprint"]
    assert baseline["sample_identity_provenance"] == surface_benchmarks._sample_identity_provenance(
        baseline["workload_fingerprint"],
    )
    assert len(baseline["sample_ids_by_regime"]["cold"]) == 1
    assert len(baseline["sample_ids_by_regime"]["warm"]) == 2
    assert baseline["sample_identity_unit"] == "request_event"
    assert baseline["sample_independence_note"] == "sequential events may share one cache epoch"
    assert baseline["sample_independence_status"] == "not_established"
    with pytest.raises(ValueError, match="repetitions must be positive"):
        surface_benchmarks._measure_stage("health request", lambda: {"success": True}, 0)


def test_measure_stage_regimes_requires_independent_state_observations() -> None:
    sample_ids = {"cold": ["case-a", "case-b"], "warm": ["case-a", "case-b"]}

    def measure(
        prepare_result: bool | None = None,
        receipt_sample_id: str | None = None,
        verifier_success: bool = True,
    ) -> dict[str, Any]:
        def prepare(regime: str, index: int) -> dict[str, Any] | bool:
            if prepare_result is not None:
                return prepare_result
            receipt = surface_benchmarks._preparation_receipt(
                receipt_sample_id or sample_ids[regime][index],
                "cold_case_unseen" if regime == "cold" else "warm_exact_case_primed",
            )
            receipt["cache_epoch_id"] = f"fabricated:{regime}:{index}"
            return receipt

        def verify(regime: str, index: int) -> dict[str, Any]:
            if not verifier_success:
                return {"success": False}
            expected_status = (
                "cold_case_unseen" if regime == "cold" else "warm_exact_case_primed"
            )
            return surface_benchmarks._preparation_observation(
                sample_ids[regime][index],
                expected_status,
                {"sample_id": sample_ids[regime][index], "state": "observed"},
            )

        return surface_benchmarks._measure_stage_regimes(
            "paired workload",
            lambda _index: {"success": True},
            lambda _index: {"success": True},
            2,
            cold_prepare=lambda index: prepare("cold", index),
            warm_prepare=lambda index: prepare("warm", index),
            cold_verify=lambda index: verify("cold", index),
            warm_verify=lambda index: verify("warm", index),
            definition="same synthetic cases; each warm case is primed before timing",
            workload_fingerprint="paired-workload-v1",
            sample_ids_by_regime=sample_ids,
            sample_independence_protocol=surface_benchmarks._SAMPLE_INDEPENDENCE_PROTOCOL,
        )

    measured = measure()
    assert measured["sample_independence_status"] == "established"
    assert surface_benchmarks._sample_independence_reasons(
        {"paired": measured}, stage_names={"paired"},
    ) == []
    proof = measured["sample_independence_proof"]
    expected_cold_epoch = surface_benchmarks._preparation_observation(
        sample_ids["cold"][0],
        "cold_case_unseen",
        {"sample_id": sample_ids["cold"][0], "state": "observed"},
    )["cache_epoch_id"]
    assert proof["cache_epoch_ids_by_regime"]["cold"][0] == expected_cold_epoch
    proof["cache_epoch_ids_by_regime"]["warm"][0] = proof["cache_epoch_ids_by_regime"]["cold"][0]
    assert surface_benchmarks._sample_independence_reasons(
        {"paired": measured}, stage_names={"paired"},
    ) == ["sample_independence_proof_invalid:paired"]

    for unverified_result in (True, False):
        unverified = measure(prepare_result=unverified_result)
        assert unverified["sample_independence_status"] == "not_established"
        assert "sample_independence_proof" not in unverified
        assert unverified["error_count"] == 4

    mismatched_receipt = measure(receipt_sample_id="different-case")
    assert mismatched_receipt["sample_independence_status"] == "not_established"
    assert "sample_independence_proof" not in mismatched_receipt
    assert mismatched_receipt["error_count"] == 4

    unverified_state = measure(verifier_success=False)
    assert unverified_state["sample_independence_status"] == "not_established"
    assert "sample_independence_proof" not in unverified_state
    assert unverified_state["error_count"] == 4


def test_measure_stage_regimes_does_not_trust_receipt_without_independent_verifier() -> None:
    sample_ids = {"cold": ["case-a", "case-b"], "warm": ["case-a", "case-b"]}

    def no_op_with_shaped_receipt(regime: str, index: int) -> dict[str, Any]:
        return {
            "success": True,
            "sample_id": sample_ids[regime][index],
            "cache_epoch_id": f"claimed:{regime}:{index}",
            "preparation_status": (
                "cold_case_unseen" if regime == "cold" else "warm_exact_case_primed"
            ),
        }

    measured = surface_benchmarks._measure_stage_regimes(
        "paired workload",
        lambda _index: {"success": True},
        lambda _index: {"success": True},
        2,
        cold_prepare=lambda index: no_op_with_shaped_receipt("cold", index),
        warm_prepare=lambda index: no_op_with_shaped_receipt("warm", index),
        cold_verify=lambda _index: {"success": False},
        warm_verify=lambda _index: {"success": False},
        definition="same synthetic cases; each warm case is primed before timing",
        workload_fingerprint="paired-workload-v1",
        sample_ids_by_regime=sample_ids,
        sample_independence_protocol=surface_benchmarks._SAMPLE_INDEPENDENCE_PROTOCOL,
    )

    assert measured["sample_independence_status"] == "not_established"
    assert "sample_independence_proof" not in measured
    assert measured["status"] == "failed"


def test_compare_records_pairs_shuffled_observations_by_explicit_id() -> None:
    metadata = _plan_grade_metadata()
    baseline_stages = _comparison_stages(10.0)
    candidate_stages = _comparison_stages(10.0)
    baseline_epochs = {
        epoch
        for regime_ids in baseline_stages["hub_code_index"]["sample_independence_proof"]["cache_epoch_ids_by_regime"].values()
        for epoch in regime_ids
    }
    candidate_epochs = {
        epoch
        for regime_ids in candidate_stages["hub_code_index"]["sample_independence_proof"]["cache_epoch_ids_by_regime"].values()
        for epoch in regime_ids
    }
    assert baseline_epochs.isdisjoint(candidate_epochs)
    baseline_stage = baseline_stages["hub_health"]
    candidate_stage = candidate_stages["hub_health"]
    baseline_stage["samples_by_regime"]["cold"] = [10.0, 20.0, 40.0]
    baseline_stage["sample_ids_by_regime"]["cold"] = ["sample-a", "sample-b", "sample-c"]
    candidate_stage["samples_by_regime"]["cold"] = [35.0, 30.0, 15.0]
    candidate_stage["sample_ids_by_regime"]["cold"] = ["sample-c", "sample-a", "sample-b"]
    baseline_by_id, _, baseline_ids_valid = surface_benchmarks._sample_values_by_id(
        baseline_stage["samples_by_regime"]["cold"],
        baseline_stage["sample_ids_by_regime"]["cold"],
    )
    candidate_by_id, _, candidate_ids_valid = surface_benchmarks._sample_values_by_id(
        candidate_stage["samples_by_regime"]["cold"],
        candidate_stage["sample_ids_by_regime"]["cold"],
    )
    assert baseline_ids_valid and candidate_ids_valid
    assert surface_benchmarks._paired_delta_pct_by_id(baseline_by_id, candidate_by_id) == {
        "sample-a": 200.0,
        "sample-b": -25.0,
        "sample-c": -12.5,
    }
    baseline = {"success": True, "metadata": metadata, "stages": baseline_stages}
    candidate = {
        "success": True, "metadata": json.loads(json.dumps(metadata)), "stages": candidate_stages,
    }

    comparison = compare_records(baseline, candidate)
    regime = comparison["provisional"]["stages"]["hub_health"]["cold"]

    assert regime["sample_comparison"] == "paired"
    assert regime["paired_count"] == 3
    assert regime["unmatched_baseline_count"] == 0
    assert regime["unmatched_candidate_count"] == 0
    assert regime["paired_mean_delta_pct"] == 54.167
    assert regime["paired_mean_delta_pct_interval_95"]["method"] == "paired_sample_t_interval"


def test_compare_records_reports_confident_paired_regression_over_tolerance() -> None:
    metadata = _plan_grade_metadata()
    baseline_stages = _comparison_stages(100.0)
    candidate_stages = _comparison_stages(100.0)
    case_blocks = [
        f"{case}:{block}" for case in _FIXTURE_SAMPLE_CASES for block in _FIXTURE_SAMPLE_BLOCKS
    ][:30]
    baseline_values = [100.0 + (index % 5) for index in range(30)]
    candidate_values = [
        value * (1.25 + ((index % 3) - 1) * 0.002)
        for index, value in enumerate(baseline_values)
    ]
    for stages, values in (
        (baseline_stages, baseline_values),
        (candidate_stages, candidate_values),
    ):
        stages["hub_health"]["samples_by_regime"]["cold"] = values
        stages["hub_health"]["sample_ids_by_regime"]["cold"] = [
            f"health:cold:{case_block}" for case_block in case_blocks
        ]
    baseline = {"success": True, "metadata": metadata, "stages": baseline_stages}
    candidate = {
        "success": True, "metadata": json.loads(json.dumps(metadata)), "stages": candidate_stages,
    }

    comparison = compare_records(baseline, candidate, regression_tolerance=0.05)
    regime = comparison["stages"]["hub_health"]["cold"]

    assert comparison["status"] == "regression"
    assert regime["paired_count"] == 30
    assert regime["paired_mean_delta_pct"] == pytest.approx(25.0, abs=0.1)
    assert regime["paired_mean_delta_pct_interval_95"]["low"] > 5.0


def test_compare_records_blocks_p95_and_p99_regression_even_when_mean_is_within_tolerance() -> None:
    metadata = _plan_grade_metadata()
    baseline_stages = _comparison_stages(100.0)
    candidate_stages = _comparison_stages(100.0)
    sample_ids = [f"health:cold:case-{index}" for index in range(100)]
    baseline_values = [100.0] * 100
    candidate_values = [100.0] * 80 + [120.0] * 20
    for stages, values in (
        (baseline_stages, baseline_values),
        (candidate_stages, candidate_values),
    ):
        stages["hub_health"]["samples_by_regime"]["cold"] = values
        stages["hub_health"]["sample_ids_by_regime"]["cold"] = sample_ids.copy()
    baseline = {"success": True, "metadata": metadata, "stages": baseline_stages}
    candidate = {
        "success": True, "metadata": json.loads(json.dumps(metadata)), "stages": candidate_stages,
    }

    comparison = compare_records(baseline, candidate, regression_tolerance=0.10)
    regime = comparison["stages"]["hub_health"]["cold"]

    assert regime["paired_mean_delta_pct"] == 4.0
    assert regime["tolerance_assessment"] == "regression"
    assert regime["paired_quantile_delta_pct"]["p95"]["estimate_pct"] == 20.0
    assert regime["paired_quantile_delta_pct"]["p99"]["estimate_pct"] == 20.0
    assert (
        regime["paired_quantile_delta_pct"]["p95"]["interval_95_pct"]["method"]
        == "paired_percentile_bootstrap_95"
    )
    assert regime["paired_quantile_delta_pct"]["p95"]["interval_95_pct"]["low"] > 10.0
    assert regime["paired_quantile_delta_pct"]["p99"]["interval_95_pct"]["low"] > 10.0
    assert comparison["status"] == "regression"


def test_compare_records_accepts_master_plan_30_pairs_without_t20_tail_minimum() -> None:
    metadata = _plan_grade_metadata()
    baseline_stages = _comparison_stages(100.0)
    candidate_stages = _comparison_stages(100.0)
    baseline = {"success": True, "metadata": metadata, "stages": baseline_stages}
    candidate = {
        "success": True, "metadata": json.loads(json.dumps(metadata)), "stages": candidate_stages,
    }

    comparison = compare_records(baseline, candidate)
    regime = comparison["stages"]["hub_health"]["cold"]

    assert regime["paired_count"] == 30
    assert comparison["status"] == "within_tolerance"


def test_compare_records_rejects_incomplete_pairing_even_at_1000_samples() -> None:
    metadata = _plan_grade_metadata()
    baseline_stages = _comparison_stages(100.0, cold=1_000, warm=1_000)
    candidate_stages = _comparison_stages(100.0, cold=1_000, warm=1_000)
    baseline_stage = baseline_stages["hub_health"]
    candidate_stage = candidate_stages["hub_health"]
    candidate_stage["samples_by_regime"]["cold"].extend([2_000.0] * 11)
    candidate_stage["sample_ids_by_regime"]["cold"].extend(
        f"hub_health:cold:unmatched-{index}" for index in range(11)
    )
    baseline = {"success": True, "metadata": metadata, "stages": baseline_stages}
    candidate = {
        "success": True, "metadata": json.loads(json.dumps(metadata)), "stages": candidate_stages,
    }

    comparison = compare_records(baseline, candidate)
    regime = comparison["provisional"]["stages"]["hub_health"]["cold"]

    assert comparison["status"] == "inconclusive"
    assert "paired_sample_identity_incomplete:hub_health:cold" in comparison["reason"]
    assert "paired_tail_samples_below_1000" not in comparison["reason"]
    assert regime["paired_count"] == 1_000
    assert regime["sample_identity_complete"] is False
    assert regime["tolerance_assessment"] == "inconclusive"
    assert regime["latency"]["p99_ms"]["candidate"] > regime["latency"]["p99_ms"]["baseline"]


def test_plan_grade_readiness_requires_tail_sample_identity() -> None:
    metadata = _plan_grade_metadata()
    stages = _comparison_stages(100.0, cold=1_000, warm=1_000)
    del stages["hub_health"]["sample_ids_by_regime"]

    reasons = surface_benchmarks._plan_grade_reasons(metadata, stages)

    assert "paired_tail_sample_ids_incomplete:hub_health:cold" in reasons
    assert "paired_tail_sample_ids_incomplete:hub_health:warm" in reasons


def test_plan_grade_does_not_promote_t20_paired_sample_proposal_to_t02_requirement() -> None:
    metadata = _plan_grade_metadata()
    stages = _comparison_stages(100.0, cold=30, warm=30)

    plan_reasons = surface_benchmarks._plan_grade_reasons(metadata, stages)
    proposed_quality_reasons = surface_benchmarks._paired_tail_sample_reasons(stages)

    assert not any(reason.startswith("paired_tail_samples_below_") for reason in plan_reasons)
    assert "paired_tail_samples_below_1000:hub_health:cold" in proposed_quality_reasons
    assert "paired_tail_samples_below_1000:hub_health:warm" in proposed_quality_reasons

    stages["hub_health"]["samples_by_regime"]["cold"] = []
    stages["hub_health"]["sample_ids_by_regime"]["cold"] = []
    missing_data_reasons = surface_benchmarks._plan_grade_reasons(metadata, stages)

    assert "paired_tail_samples_missing:hub_health:cold" in missing_data_reasons


def test_compare_records_detects_p99_regression_when_p95_is_unchanged() -> None:
    metadata = _plan_grade_metadata()
    baseline_stages = _comparison_stages(100.0, cold=1_000, warm=1_000)
    candidate_stages = _comparison_stages(100.0, cold=1_000, warm=1_000)
    candidate_stages["hub_health"]["samples_by_regime"]["cold"] = [100.0] * 975 + [120.0] * 25
    baseline = {"success": True, "metadata": metadata, "stages": baseline_stages}
    candidate = {
        "success": True, "metadata": json.loads(json.dumps(metadata)), "stages": candidate_stages,
    }

    comparison = compare_records(baseline, candidate, regression_tolerance=0.10)
    regime = comparison["stages"]["hub_health"]["cold"]

    assert regime["paired_quantile_delta_pct"]["p95"]["estimate_pct"] == 0.0
    assert regime["paired_quantile_delta_pct"]["p95"]["tolerance_assessment"] == "within_tolerance"
    assert regime["paired_quantile_delta_pct"]["p99"]["estimate_pct"] == 20.0
    assert regime["paired_quantile_delta_pct"]["p99"]["interval_95_pct"]["low"] > 10.0
    assert regime["tolerance_assessment"] == "regression"
    assert comparison["status"] == "regression"


def test_compare_records_classifies_tolerance_using_unrounded_interval() -> None:
    metadata = _plan_grade_metadata()
    baseline_stages = _comparison_stages(10.0)
    candidate_stages = _comparison_stages(10.0)
    block_ids = [
        f"health:cold:{case}:{block}"
        for case in _FIXTURE_SAMPLE_CASES for block in _FIXTURE_SAMPLE_BLOCKS
    ][:30]
    baseline_stages["hub_health"]["samples_by_regime"]["cold"] = [10.0] * 30
    candidate_stages["hub_health"]["samples_by_regime"]["cold"] = [10.50004] * 30
    baseline_stages["hub_health"]["sample_ids_by_regime"]["cold"] = block_ids
    candidate_stages["hub_health"]["sample_ids_by_regime"]["cold"] = block_ids.copy()
    baseline = {"success": True, "metadata": metadata, "stages": baseline_stages}
    candidate = {
        "success": True, "metadata": json.loads(json.dumps(metadata)), "stages": candidate_stages,
    }

    comparison = compare_records(baseline, candidate, regression_tolerance=0.05)
    regime = comparison["stages"]["hub_health"]["cold"]

    assert regime["paired_mean_delta_pct_interval_95"]["low"] == 5.0
    assert regime["tolerance_assessment"] == "regression"
    assert comparison["status"] == "regression"


def test_compare_records_returns_inconclusive_when_paired_interval_overlaps_tolerance() -> None:
    metadata = _plan_grade_metadata()
    baseline_stages = _comparison_stages(100.0)
    candidate_stages = _comparison_stages(100.0)
    block_ids = [
        f"health:cold:{case}:{block}"
        for case in _FIXTURE_SAMPLE_CASES for block in _FIXTURE_SAMPLE_BLOCKS
    ][:30]
    baseline_stages["hub_health"]["samples_by_regime"]["cold"] = [100.0] * 30
    candidate_stages["hub_health"]["samples_by_regime"]["cold"] = [80.0] + [100.0] * 26 + [130.0] * 3
    baseline_stages["hub_health"]["sample_ids_by_regime"]["cold"] = block_ids
    candidate_stages["hub_health"]["sample_ids_by_regime"]["cold"] = block_ids.copy()
    baseline = {"success": True, "metadata": metadata, "stages": baseline_stages}
    candidate = {
        "success": True, "metadata": json.loads(json.dumps(metadata)), "stages": candidate_stages,
    }

    comparison = compare_records(baseline, candidate, regression_tolerance=0.05)
    metrics = comparison.get("provisional", comparison)
    regime = metrics["stages"]["hub_health"]["cold"]

    assert regime["paired_count"] == 30
    assert regime["paired_mean_delta_pct_interval_95"]["low"] < 5.0
    assert regime["paired_mean_delta_pct_interval_95"]["high"] > 5.0
    assert regime["paired_quantile_delta_pct"]["p95"]["interval_95_pct"]["low"] < 5.0
    assert regime["paired_quantile_delta_pct"]["p95"]["interval_95_pct"]["high"] > 5.0
    assert regime["paired_quantile_delta_pct"]["p99"]["interval_95_pct"]["low"] < 5.0
    assert regime["paired_quantile_delta_pct"]["p99"]["interval_95_pct"]["high"] > 5.0
    assert comparison["status"] == "inconclusive"


def test_compare_records_retains_paired_mean_interval_as_diagnostic() -> None:
    metadata = _plan_grade_metadata()
    baseline_stages = _comparison_stages(10.0)
    candidate_stages = _comparison_stages(10.0)
    baseline_stages["hub_health"]["samples_by_regime"]["cold"] = [100.0, 100.0, 100.0]
    candidate_stages["hub_health"]["samples_by_regime"]["cold"] = [100.0, 110.0, 120.0]
    ids = ["sample-a", "sample-b", "sample-c"]
    baseline_stages["hub_health"]["sample_ids_by_regime"]["cold"] = ids
    candidate_stages["hub_health"]["sample_ids_by_regime"]["cold"] = ids.copy()
    baseline = {"success": True, "metadata": metadata, "stages": baseline_stages}
    candidate = {"success": True, "metadata": json.loads(json.dumps(metadata)), "stages": candidate_stages}

    comparison = compare_records(baseline, candidate)
    metrics = comparison.get("provisional", comparison)
    regime = metrics["stages"]["hub_health"]["cold"]
    interval = regime["paired_mean_delta_pct_interval_95"]

    assert interval["method"] == "paired_sample_t_interval"
    assert regime["paired_mean_delta_pct"] == 10.0
    assert interval["low"] == pytest.approx(-14.845, abs=0.01)
    assert interval["high"] == pytest.approx(34.845, abs=0.01)
    assert regime["regression"] is False
    assert comparison["status"] == "inconclusive"
    assert "light_samples_below_1000:hub_health" in comparison["reason"]


def test_compare_records_reports_unmatched_ids_and_unequal_counts() -> None:
    metadata = _plan_grade_metadata()
    baseline_stages = _comparison_stages(10.0)
    candidate_stages = _comparison_stages(10.2)
    baseline_stage = baseline_stages["hub_health"]
    candidate_stage = candidate_stages["hub_health"]
    baseline_stage["samples_by_regime"]["cold"] = [10.0, 20.0, 30.0, 40.0]
    candidate_stage["samples_by_regime"]["cold"] = [33.0, 11.0, 50.0]
    baseline_stage["sample_ids_by_regime"]["cold"] = ["sample-a", "sample-b", "sample-c", "baseline-only"]
    candidate_stage["sample_ids_by_regime"]["cold"] = ["sample-c", "sample-a", "candidate-only"]
    baseline = {"success": True, "metadata": metadata, "stages": baseline_stages}
    candidate = {"success": True, "metadata": json.loads(json.dumps(metadata)), "stages": candidate_stages}

    comparison = compare_records(baseline, candidate)
    metrics = comparison.get("provisional", comparison)
    regime = metrics["stages"]["hub_health"]["cold"]

    assert regime["sample_comparison"] == "paired"
    assert regime["baseline_count"] == 4
    assert regime["candidate_count"] == 3
    assert regime["paired_count"] == 2
    assert regime["unmatched_baseline_count"] == 2
    assert regime["unmatched_candidate_count"] == 1
    assert regime["unmatched_baseline_ids"] == ["baseline-only", "sample-b"]
    assert regime["unmatched_candidate_ids"] == ["candidate-only"]


@pytest.mark.parametrize("field", ["workload_fingerprint", "config_fingerprint", "hardware_fingerprint"])
def test_compare_records_marks_fingerprint_mismatch_inconclusive(field: str) -> None:
    metadata = _plan_grade_metadata()
    baseline = {"success": True, "metadata": metadata, "stages": _comparison_stages(10.0)}
    candidate_metadata = json.loads(json.dumps(metadata))
    candidate_metadata[field] = "different"
    candidate = {"success": True, "metadata": candidate_metadata, "stages": _comparison_stages(11.0)}

    comparison = compare_records(baseline, candidate)

    assert comparison["status"] == "inconclusive"
    assert field in comparison["fingerprint_mismatches"]


def test_compare_records_marks_stage_workload_mismatch_inconclusive() -> None:
    metadata = _plan_grade_metadata()
    baseline = {"success": True, "metadata": metadata, "stages": _comparison_stages(10.0)}
    candidate_stages = _comparison_stages(11.0)
    candidate_stages["hub_health"]["workload_fingerprint"] = "different-stage-workload"
    candidate = {
        "success": True, "metadata": json.loads(json.dumps(metadata)), "stages": candidate_stages,
    }

    comparison = compare_records(baseline, candidate)

    assert comparison["status"] == "inconclusive"
    assert "hub_health:workload_fingerprint" in comparison["fingerprint_mismatches"]


def test_compare_records_marks_singleton_or_missing_ids_inconclusive() -> None:
    metadata = _plan_grade_metadata()
    baseline_stages = _comparison_stages(10.0)
    candidate_stages = _comparison_stages(11.0)
    for stages in (baseline_stages, candidate_stages):
        stages["hub_health"]["samples_by_regime"]["cold"] = [10.0]
        stages["hub_health"]["sample_ids_by_regime"]["cold"] = ["one-pair"]
    baseline = {"success": True, "metadata": metadata, "stages": baseline_stages}
    candidate = {
        "success": True, "metadata": json.loads(json.dumps(metadata)), "stages": candidate_stages,
    }

    singleton = compare_records(baseline, candidate)
    singleton_metrics = singleton.get("provisional", singleton)
    singleton_regime = singleton_metrics["stages"]["hub_health"]["cold"]
    assert singleton["status"] == "inconclusive"
    assert singleton_regime["paired_count"] == 1
    assert singleton_regime["sample_comparison"] == "inconclusive"

    del candidate_stages["hub_health"]["sample_ids_by_regime"]["cold"]
    missing_ids = compare_records(baseline, candidate)
    missing_metrics = missing_ids.get("provisional", missing_ids)
    missing_regime = missing_metrics["stages"]["hub_health"]["cold"]
    assert missing_ids["status"] == "inconclusive"
    assert missing_regime["paired_count"] == 0
    assert missing_regime["unmatched_baseline_count"] == 1
    assert missing_regime["unmatched_candidate_count"] == 0


def test_compare_records_rejects_ids_without_workload_runner_provenance() -> None:
    metadata = _plan_grade_metadata()
    baseline_stages = _comparison_stages(10.0)
    candidate_stages = _comparison_stages(11.0)
    del candidate_stages["hub_health"]["sample_identity_provenance"]
    baseline = {"success": True, "metadata": metadata, "stages": baseline_stages}
    candidate = {
        "success": True, "metadata": json.loads(json.dumps(metadata)), "stages": candidate_stages,
    }

    comparison = compare_records(baseline, candidate)
    metrics = comparison.get("provisional", comparison)
    regime = metrics["stages"]["hub_health"]["cold"]

    assert comparison["status"] == "inconclusive"
    assert regime["sample_comparison"] == "inconclusive"
    assert regime["sample_identity_valid"] is False
    assert regime["paired_count"] == 0
    assert regime["unmatched_baseline_count"] == 30
    assert regime["unmatched_candidate_count"] == 30


def test_compare_records_rejects_missing_required_stage() -> None:
    metadata = _plan_grade_metadata()
    baseline = {"success": True, "metadata": metadata, "stages": _comparison_stages(10.0)}
    candidate = {
        "success": True,
        "metadata": json.loads(json.dumps(metadata)),
        "stages": _comparison_stages(10.0),
    }
    del candidate["stages"]["hub_sqlite_db_read"]

    comparison = compare_records(baseline, candidate)

    assert comparison["status"] == "incomparable"
    assert "hub_sqlite_db_read" in comparison["missing_required_stages"]["candidate"]


def test_compare_records_requires_plan_grade_light_sample_total() -> None:
    metadata = _plan_grade_metadata()
    baseline = {"success": True, "metadata": metadata, "stages": _comparison_stages(10.0)}
    candidate = {
        "success": True,
        "metadata": json.loads(json.dumps(metadata)),
        "stages": _comparison_stages(10.0),
    }
    for record in (baseline, candidate):
        health = record["stages"]["hub_health"]
        health["samples_by_regime"]["cold"] = [10.0] * 29
        health["sample_ids_by_regime"]["cold"] = [
            f"hub_health:cold:{block_id}" for block_id in _FIXTURE_SAMPLE_BLOCK_IDS[:29]
        ]

    comparison = compare_records(baseline, candidate)

    assert comparison["status"] == "inconclusive"
    assert "light_samples_below_1000:hub_health" in comparison["reason"]
    assert comparison["provisional"]["stages"]["hub_health"]["cold"]["paired_count"] == 29


def test_smoke_comparison_is_inconclusive_and_retains_provisional_metrics() -> None:
    metadata = {
        "benchmark_scope": "hub_app_synthetic_repo",
        "workload_fingerprint": "workload",
        "sample_identity_provenance": surface_benchmarks._sample_identity_provenance("workload"),
        "config_fingerprint": "cfg",
        "hardware_fingerprint": "hw",
        "baseline_readiness": "smoke_only",
    }
    baseline_stages = _comparison_stages(10.0, cold=1, warm=2, light_repetitions=3)
    candidate_stages = _comparison_stages(10.0, cold=1, warm=2, light_repetitions=3)
    candidate_stages["hub_health"]["samples_by_regime"]["warm"] = [12.0, 12.0]
    baseline = {"success": True, "metadata": metadata, "stages": baseline_stages}
    candidate = {"success": True, "metadata": dict(metadata), "stages": candidate_stages}

    comparison = compare_records(baseline, candidate)

    assert comparison["status"] == "inconclusive"
    assert comparison["provisional"]["status"] == "regression"
    assert comparison["provisional"]["stages"]["hub_health"]["warm"]["latency"]["p95_ms"]["delta_pct"] == 20.0


def test_compare_records_marks_different_hardware_or_configuration_inconclusive() -> None:
    baseline = {"success": True, "metadata": {"benchmark_scope": "synthetic_microbench_only", "workload_fingerprint": "workload", "config_fingerprint": "cfg", "hardware_fingerprint": "hw"}, "stages": {}}
    candidate = {"success": True, "metadata": {"benchmark_scope": "synthetic_microbench_only", "workload_fingerprint": "workload", "config_fingerprint": "other", "hardware_fingerprint": "hw"}, "stages": {}}

    comparison = compare_records(baseline, candidate)
    assert comparison["status"] == "inconclusive"
    assert "config_fingerprint" in comparison["fingerprint_mismatches"]


def test_compare_records_refuses_inference_without_model_digest() -> None:
    baseline = {
        "success": True,
        "metadata": {
            "benchmark_scope": "synthetic_microbench_only",
            "workload_fingerprint": "workload",
            "sample_identity_provenance": surface_benchmarks._sample_identity_provenance("workload"),
            "config_fingerprint": "cfg",
            "hardware_fingerprint": "hw",
            "inference": "requested",
        },
        "stages": {"inference": {"status": "passed", "samples_by_regime": {"cold": [100.0], "warm": []}}},
    }
    candidate = json.loads(json.dumps(baseline))

    comparison = compare_records(baseline, candidate)
    assert comparison["status"] == "incomparable"
    assert "model digest" in comparison["reason"]


def test_cli_persists_and_reports_baseline_comparison(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    state_dir = tmp_path / "state"
    baseline = run_benchmark(
        state_dir=state_dir, file_count=4, rag_chunks=4, repetitions=1,
        light_repetitions=2, comparison_repetitions=1, concurrency=(1,),
    )

    exit_code = main([
        "--state-dir", str(state_dir), "--files", "4", "--rag-chunks", "4",
        "--repetitions", "1", "--light-repetitions", "2", "--comparison-repetitions", "1",
        "--concurrency", "1", "--compare-with", baseline["record_path"],
    ])

    output = json.loads(capsys.readouterr().out)
    assert output["comparison"]["status"] == "inconclusive"
    assert exit_code == 2
    assert output["metadata"]["stage_repetitions"] == {"light": 2, "comparison": 1}
    assert Path(output["record_path"]).is_relative_to(state_dir)


def test_optional_inference_uses_runtime_load_metric_without_real_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunner:
        config = {"models": {"fast_code": "test-model"}}

        def run(self, **_kwargs):
            return {
                "success": True, "ttft_ms": 4.0, "tokens_per_second": 8.0,
                "generation_duration_ms": 20.0, "tokens_generated": 8,
                "load_duration_ms": 12.5,
                "initial_vram": {"vram_used_mb": 100}, "final_vram": {"vram_used_mb": 250},
            }

    monkeypatch.setattr(surface_benchmarks, "_sample_dedicated_vram_bytes", lambda: None)

    result = run_benchmark(
        state_dir=tmp_path / "state", file_count=2, rag_chunks=2, repetitions=1,
        comparison_repetitions=2, concurrency=(1,), inference_runner=FakeRunner(), include_inference=True,
        include_quality_goldens=False,
    )

    assert result["success"] is True
    assert result["metadata"]["benchmark_scope"] == "hub_app_synthetic_repo_plus_hardware_inference"
    assert result["metadata"]["inference_model"] == "test-model"
    assert result["metadata"]["inference_model_digest"] is None
    assert result["stages"]["inference"]["samples_ms"] and len(result["stages"]["inference"]["samples_ms"]) == 2
    assert result["stages"]["model_load"]["measurement"] == "runtime_reported_model_load_duration_ms"
    assert result["stages"]["model_load"]["samples_ms"] == [12.5, 12.5]
    assert result["stages"]["inference"]["reported_metrics"]["ttft_ms"]["p50_ms"] == 4.0
    assert result["stages"]["inference"]["reported_metrics"]["tokens_per_second"]["p50_ms"] == 8.0
    assert result["stages"]["inference_queue_wait"]["status"] == "skipped"
    assert result["resource_usage"]["peak_vram_bytes"] == 250 * 1024 * 1024
    assert result["resource_usage"]["availability"]["peak_vram_bytes"] == "measured_at_inference_boundaries"


def test_t12_matrix_reports_profile_corpus_metrics_and_scenario_receipts() -> None:
    class FakeRunner:
        config = {
            "models": {
                "reason": "reason-model",
                "review": "review-model",
                "compress": "compress-model",
                "complete": "complete-model",
                "scaffold": "scaffold-model",
                "reasoning": "reason-model",
                "fast_code": "compress-model",
                "heavy_code": "review-model",
            },
            "profile_configs": {profile: {"temperature": 0.0} for profile in (
                "reason", "review", "compress", "complete", "scaffold",
            )},
        }

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run(self, *, model: str, prompt: str, num_tokens: int) -> dict[str, object]:
            profile = next(name for name, model_name in self.config["models"].items() if model_name == model)
            repetition = sum(1 for call in self.calls if call["profile"] == profile)
            self.calls.append({"profile": profile, "prompt": prompt, "num_tokens": num_tokens})
            return {
                "success": True,
                "model": model,
                "routed_profile": profile,
                "model_digest": ("a" if profile == "reason" else "b") * 64,
                "quality_score_pct": 90.0,
                "quality_evaluator_id": "t12-rubric-v1",
                "ttft_ms": 4.0,
                "tokens_per_second": 20.0,
                "load_duration_ms": 12.0 if repetition == 0 else 0.0,
                "model_load_event": repetition == 0,
                "model_reuse_event": repetition > 0,
                "queue_age_ms": 10.0 + repetition,
                "queue_wait_ms": 8.0 + repetition,
                "fairness_wait_ms": 3.0 + repetition,
                "batch_size": 2,
                "batch_bucket": "short-prefill",
                "prefill_tokens": 64,
                "vram_admitted": True,
                "vram_budget_bytes": 512 * 1024 * 1024,
                "vram_required_bytes": 256 * 1024 * 1024,
                "deadline_ms": 500.0,
                "deadline_stage": "generation",
                "deadline_exceeded": False,
                "deadline_queue_ms": 4.0,
                "deadline_model_load_ms": 12.0,
                "deadline_generation_ms": 20.0,
                "deadline_stages_ms": {"queue": 4.0, "model_load": 12.0, "generation": 20.0},
                "peak_vram_bytes": 256 * 1024 * 1024,
                "switch_event_id": 7 if repetition == 0 else None,
                "model_switch_ms": 8.0 if repetition == 0 else None,
                "model_switch_success": True if repetition == 0 else None,
                "evicted_models": ["old-model"] if repetition == 0 else None,
                "eviction_count": 1 if repetition == 0 else None,
                "vram_before_bytes": 256 * 1024 * 1024 if repetition == 0 else None,
                "vram_after_bytes": 192 * 1024 * 1024 if repetition == 0 else None,
            }

        def run_benchmark_scenario(self, *, name: str, contract: dict[str, object]) -> dict[str, object]:
            inputs = contract["scenario_inputs"]
            scenarios: dict[str, dict[str, object]] = {
                "scheduler": {
                    "queue_age_ms": 25.0, "fairness_wait_ms": 10.0, "batch_size": 4,
                    "batch_item_count": 4, "bucket_id": "short-prefill",
                    "prefill_tokens": 128, "vram_admission": "admitted",
                    "vram_budget_bytes": 512 * 1024 * 1024,
                    "vram_available_bytes": 256 * 1024 * 1024,
                    "vram_required_bytes": 256 * 1024 * 1024,
                    "vram_admission_budget_bytes": 256 * 1024 * 1024,
                    "vram_incremental_required_bytes": 192 * 1024 * 1024,
                    "vram_estimate_source": "measured",
                },
                "batch": {
                    "input_item_ids": ["a", "b", "c"], "result_item_ids": ["a", "b", "c"],
                    "item_statuses": ["success", "failed", "success"], "partial_failure_count": 1,
                    "max_concurrency": 2, "concurrency_limit": 2,
                    "failure_probe_item_id": "c", "failure_probe_observed": True,
                },
                "deadline": {
                    "deadline_ms": 100.0, "stages": ["queue", "model_load", "generation"],
                    "stage_timings_ms": {"queue": 5.0, "model_load": 20.0, "generation": 40.0},
                    "deadline_stage": "generation", "completed_within_deadline": True,
                    "request_succeeded": True,
                },
                "overload": {
                    "overloaded": True, "queue_depth": 4, "queue_admission": "rejected",
                    "queued_count": 1, "rejected_count": 1, "resource_rejected_count": 0,
                },
                "cancel": {
                    "cancel_requested": True, "cancelled": True, "cleanup_complete": True,
                    "cancel_to_stop_ms": 15.0,
                },
                "fallback": {
                    "fallback_used": True, "fallback_visible": True, "source_profile": "reason",
                    "fallback_profile": inputs["fallback_profile"], "quality_floor_pct": 80.0,
                    "source_model": inputs["model"], "fallback_model": inputs["fallback_model"],
                    "source_backend": "ollama", "fallback_backend": "ollama",
                    "source_quality_pct": 0.0, "source_quality_status": "scored",
                    "fallback_quality_pct": 85.0,
                    "source_max_tokens": inputs["source_max_tokens"],
                    "fallback_max_tokens": inputs["fallback_max_tokens"],
                    "quality_floor_met": True,
                },
            }
            measurements = dict(scenarios[name])
            if name == "batch":
                item_ids = [item["id"] for item in inputs["items"]]
                probe_id = inputs["failure_probe_item_id"]
                statuses = ["success"] * len(item_ids)
                statuses[item_ids.index(probe_id)] = "failed"
                measurements.update({
                    "input_item_ids": item_ids,
                    "result_item_ids": list(item_ids),
                    "item_statuses": statuses,
                    "partial_failure_count": 1,
                    "max_concurrency": 2,
                    "concurrency_limit": inputs["max_concurrency"],
                    "failure_probe_item_id": probe_id,
                    "failure_probe_observed": True,
                })
            return {**measurements, "receipt_id": f"receipt-{name}"}

    runner = FakeRunner()
    report = _run_t12_matrix(runner, repetitions=2, concurrency_limit=4, quality_floor_pct=80.0)

    assert report["accepted"] is False
    assert report["contract_passed"] is True, {
        "task_roles": {
            name: role.get("missing_acceptance")
            for name, role in report["task_roles"].items()
            if role.get("contract_passed") is not True
        },
        "scenarios": {
            name: (scenario.get("contract_passed"), scenario.get("missing_fields"))
            for name, scenario in report["scenarios"].items()
            if scenario.get("contract_passed") is not True
        },
    }
    assert report["live_hardware"] is False
    assert report["run_id"].startswith("t12-")
    assert "receipt_id" not in report
    assert len(runner.calls) == 10
    assert report["corpus"]["corpus_id"] == "t12-live-quality-v1"
    assert len(report["corpus"]["fingerprint"]) == 64
    assert set(report["task_roles"]) == {"reason", "review", "compress", "complete", "scaffold"}
    assert report["hardware_profile"] is None
    reason = report["task_roles"]["reason"]
    assert reason["status"] == "measured"
    assert reason["identity"]["model"] == "reason-model"
    assert reason["identity"]["task_role"] == "reason"
    assert len(reason["identity"]["config_fingerprint"]) == 64
    assert len(reason["identity"]["hardware_fingerprint"]) == 64
    assert reason["quality"]["score_pct"] == 90.0
    assert reason["quality"]["evaluator_id"] == "t12-rubric-v1"
    assert all(sample["model"] == "reason-model" for sample in reason["samples"])
    assert reason["metrics"]["ttft_ms"]["p50"] == 4.0
    assert reason["metrics"]["end_to_end_latency_ms"]["count"] == 2
    assert reason["metrics"]["peak_vram_bytes"]["unit"] == "bytes"
    assert reason["metrics"]["peak_vram_bytes"]["p50"] == 256 * 1024 * 1024
    assert reason["events"]["model_load_count"] == 1
    assert reason["events"]["model_reuse_count"] == 1
    assert reason["events"]["model_switch_count"] == 1
    assert reason["events"]["model_switch_success_count"] == 1
    assert reason["events"]["eviction_count_total"] == 1
    assert reason["lifecycle_metrics"]["model_switch_ms"]["p50"] == 8.0
    assert reason["lifecycle_metrics"]["switch_vram_delta_bytes"]["p50"] == -64 * 1024 * 1024
    assert reason["samples"][0]["evicted_models"] == ["old-model"]
    assert reason["samples"][0]["vram_before_bytes"] == 256 * 1024 * 1024
    assert reason["samples"][0]["vram_after_bytes"] == 192 * 1024 * 1024
    assert reason["deadline_stage_counts"] == {"generation": 2}
    assert all(scenario["contract_passed"] is True for scenario in report["scenarios"].values())
    assert report["scenarios"]["fallback"]["runner_receipt_id"] == "receipt-fallback"
    serialized = json.dumps(report)
    assert "Given queue" not in serialized
    assert '"prompt"' not in serialized
    assert '"output"' not in serialized

    runner.config["_hardware"] = {"profile": "balanced"}
    live_spoof_attempt = _run_t12_matrix(
        runner, repetitions=1, concurrency_limit=4, quality_floor_pct=80.0, live_hardware=True,
    )
    assert live_spoof_attempt["accepted"] is False
    assert live_spoof_attempt["task_roles"]["reason"]["quality"]["sample_count"] == 0
    assert "trusted_structured_evaluator_required" in live_spoof_attempt["task_roles"]["reason"]["missing_acceptance"]


def test_t12_matrix_preserves_sanitized_vram_admission_on_failed_samples() -> None:
    class AdmissionFailureRunner:
        config = {
            "models": {
                "reasoning": "reason-model", "review": "review-model",
                "compress": "compress-model", "complete": "complete-model",
                "scaffold": "scaffold-model",
            },
        }

        def run_t12_case(self, **_kwargs: object) -> dict[str, object]:
            return {
                "success": False,
                "failure_code": "resource_exhausted",
                "vram_admitted": "rejected",
                "vram_budget_bytes": 8_000_000_000,
                "vram_available_bytes": 1_000_000_000,
                "vram_admission_budget_bytes": 6_500_000_000,
                "vram_incremental_required_bytes": 6_800_000_000,
                "vram_estimate_source": "measured",
                "prompt": "PRIVATE PROMPT",
                "response": "PRIVATE OUTPUT",
            }

    report = _run_t12_matrix(AdmissionFailureRunner(), repetitions=1, concurrency_limit=1)
    sample = report["task_roles"]["reason"]["samples"][0]

    assert sample["error_type"] == "resource_exhausted"
    assert report["task_roles"]["reason"]["events"]["vram_admission_counts"] == {
        "admitted": 0, "rejected": 1, "unknown": 0,
    }
    assert sample["diagnostics"] == {
        "vram_admitted": "rejected",
        "vram_budget_bytes": 8_000_000_000,
        "vram_available_bytes": 1_000_000_000,
        "vram_admission_budget_bytes": 6_500_000_000,
        "vram_incremental_required_bytes": 6_800_000_000,
        "vram_estimate_source": "measured",
    }
    serialized = json.dumps(report)
    assert "PRIVATE PROMPT" not in serialized
    assert "PRIVATE OUTPUT" not in serialized


def test_t12_scenario_does_not_accept_resource_rejections_as_queue_overload() -> None:
    class ResourceRejectedRunner:
        config = {"models": {"reasoning": "reason-model"}}

        def run_benchmark_scenario(self, *, name: str, contract: dict[str, object]) -> dict[str, object]:
            del name, contract
            return {
                "overloaded": False, "queue_depth": 0,
                "queue_admission": "resource_rejected", "queued_count": 0,
                "rejected_count": 0, "resource_rejected_count": 8,
                "receipt_id": "receipt-resource-rejection",
            }

    report = _t12_scenario_report(
        ResourceRejectedRunner(), "overload", concurrency_limit=4,
        quality_floor_pct=80.0, live_hardware=True,
    )

    assert report["status"] == "measured"
    assert report["contract_passed"] is False
    assert report["accepted"] is False
    assert report["measurements"]["resource_rejected_count"] == 8


def test_t12_matrix_keeps_missing_live_quality_and_scenarios_incomplete() -> None:
    class UnscoredRunner:
        config = {"models": {"reason": "reason-model"}}

        def run(self, **_kwargs: object) -> dict[str, object]:
            return {"success": True, "ttft_ms": 4.0}

    report = _run_t12_matrix(UnscoredRunner(), repetitions=1, concurrency_limit=1, quality_floor_pct=80.0)

    assert report["accepted"] is False
    assert report["task_roles"]["reason"]["quality"]["status"] == "not_measured"
    assert report["task_roles"]["review"]["status"] == "not_configured"
    assert report["scenarios"]["fallback"]["status"] == "not_measured"

def test_cli_wall_timeout_returns_incomplete_receipt_without_state_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    state_dir = tmp_path / "state"
    calls: dict[str, float] = {}

    def expire(command: list[str], **kwargs: Any) -> Any:
        calls["timeout"] = kwargs["timeout"]
        assert str(Path(command[1]).resolve()) == str(Path(surface_benchmarks.__file__).resolve())
        assert "--_benchmark-worker" in command
        raise surface_benchmarks.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(surface_benchmarks.subprocess, "run", expire)
    exit_code = main(["--state-dir", str(state_dir), "--timeout-seconds", "1"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 124
    assert payload == {
        "success": False, "status": "incomplete",
        "error": "benchmark_timeout", "timeout_seconds": 1.0,
        "record_complete": False, "return_code": 124,
        "stdout": {"byte_count": 0, "sha256": hashlib.sha256(b"").hexdigest()},
        "stderr": {"byte_count": 0, "sha256": hashlib.sha256(b"").hexdigest()},
    }
    assert calls["timeout"] == 1.0
    assert not state_dir.exists()


def test_cli_worker_enforces_wall_timeout_against_real_hung_child(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    worker = tmp_path / "slow_benchmark_worker.py"
    started = tmp_path / "worker_started.txt"
    worker.write_text(
        "from pathlib import Path\n"
        "import sys, time\n"
        "Path(sys.argv[1]).write_text('started', encoding='utf-8')\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )

    started_at = time.monotonic()
    exit_code = surface_benchmarks._run_cli_worker(
        [surface_benchmarks.sys.executable, str(worker), str(started)],
        timeout_seconds=1.5,
    )
    elapsed = time.monotonic() - started_at
    payload = json.loads(capsys.readouterr().out)

    assert started.read_text(encoding="utf-8") == "started"
    assert exit_code == 124
    assert payload == {
        "success": False, "status": "incomplete",
        "error": "benchmark_timeout", "timeout_seconds": 1.5,
        "record_complete": False, "return_code": 124,
        "stdout": {"byte_count": 0, "sha256": hashlib.sha256(b"").hexdigest()},
        "stderr": {"byte_count": 0, "sha256": hashlib.sha256(b"").hexdigest()},
    }
    assert elapsed >= 1.0
    assert elapsed < 4.5


def test_cli_worker_cancellation_never_reports_successful_record(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    record = {"success": True, "record_path": "benchmark.json", "comparison": {"status": "passed"}}

    def cancelled(command: list[str], **kwargs: Any) -> Any:
        return surface_benchmarks.subprocess.CompletedProcess(
            command, 130, stdout=json.dumps(record), stderr="cancelled",
        )

    monkeypatch.setattr(surface_benchmarks.subprocess, "run", cancelled)
    exit_code = surface_benchmarks._run_cli_worker(["benchmark-worker"], timeout_seconds=1.0)

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 130
    assert payload["success"] is False
    assert payload["status"] == "cancelled"
    assert payload["record_path"] == "benchmark.json"
    assert payload["worker_return_code"] == 130


def test_concurrent_benchmark_future_wait_has_a_deadline() -> None:
    from concurrent.futures import Future

    pending = Future()
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="concurrent requests exceeded"):
        surface_benchmarks._collect_concurrent_results([pending], timeout_seconds=0.01)

    assert pending.cancelled() is True
    assert time.monotonic() - started < 1.0
