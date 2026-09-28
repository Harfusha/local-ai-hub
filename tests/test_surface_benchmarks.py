from __future__ import annotations

import gc
import json
import os
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import tools.benchmark_surfaces as benchmark_surfaces
from tools.benchmark_surfaces import _plan_grade_reasons, compare_records, main, run_benchmark, summarize_samples
from local_ai_hub.async_jobs import AsyncJobManager

_REQUIRED_GOLDEN_OPERATIONS = (
    "symbols", "graph", "affected_tests", "retrieval_relevance",
    "code_generation", "vision", "speech", "context_pack",
)
_REQUIRED_COMPARISON_STAGES = (
    "transport", "hub_health", "hub_validation", "hub_sqlite_index",
    "hub_sqlite_db_read", "hub_code_index", "hub_context_pack",
    "hub_queue_admission", "hub_rag_chunking",
)
_COMPARISON_METADATA_FIELDS = (
    "benchmark_scope", "config_fingerprint", "hardware_fingerprint",
)


def _async_jobs_lifecycle_snapshot(state_dir: Path) -> dict[str, object]:
    target_dir = state_dir.resolve()
    observed: list[dict[str, object]] = []
    for manager in gc.get_objects():
        if not isinstance(manager, AsyncJobManager):
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
        is_current_run = database_path.resolve().parent == target_dir
        if not is_current_run and not any(item["alive"] for item in handles):
            continue
        try:
            uri = f"{database_path.resolve().as_uri()}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=0.05) as connection:
                table_exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='async_jobs'"
                ).fetchone() is not None
            schema = {"async_jobs_table_exists": table_exists}
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
        "config_fingerprint": "cfg",
        "hardware_fingerprint": "hw",
        "baseline_readiness": "plan_grade",
        "stage_repetitions": {"light": 1_000, "paired": 30},
        "concurrency": [1, 4, 16, 32],
        "completed_matrix": _completed_matrix(),
        "inference": "skipped_not_requested",
    }


def _comparison_stages(value: float, *, cold: int = 30, warm: int = 30) -> dict[str, object]:
    return {
        name: {
            "status": "passed",
            "samples_by_regime": {"cold": [value] * cold, "warm": [value] * warm},
        }
        for name in _REQUIRED_COMPARISON_STAGES
    }


def test_summarize_samples_reports_percentiles_and_throughput() -> None:
    summary = summarize_samples([10.0, 20.0, 30.0, 40.0])

    assert summary["count"] == 4
    assert summary["p50_ms"] == 25.0
    assert summary["p95_ms"] == 38.5
    assert summary["p99_ms"] == 39.7
    assert summary["throughput_per_second"] == 40.0


def test_queue_probe_failure_categories_distinguish_submit_and_cancel_outcomes() -> None:
    classify = getattr(benchmark_surfaces, "_queue_probe_failure_category", None)
    assert callable(classify), "queue probe must expose bounded outcome categories"

    assert classify("submit", response={"success": False, "error": "redacted"}) == "submit_rejected"
    assert classify("submit", response={"success": True, "job_id": ""}) == "submit_missing_job_id"
    assert classify("cancel", response={"success": False, "error": "redacted"}) == "cancel_rejected"
    assert classify("cancel", response={"success": True, "state": "running"}) == "cancel_not_cancelled"
    assert classify("submit", exception=RuntimeError("redacted")) == "submit_exception"
    assert classify("cancel", exception=RuntimeError("redacted")) == "cancel_exception"
    assert classify("cancel", response={"success": True, "state": "cancelled"}) is None


def test_benchmark_runner_imports_package_from_its_own_repository(tmp_path: Path) -> None:
    foreign_source = tmp_path / "foreign-source"
    foreign_package = foreign_source / "local_ai_hub"
    foreign_package.mkdir(parents=True)
    (foreign_package / "__init__.py").write_text("origin = 'foreign'\n", encoding="utf-8")
    repo_source = Path(benchmark_surfaces.__file__).resolve().parents[1] / "src"
    runner_path = Path(benchmark_surfaces.__file__).resolve()
    probe = (
        "import pathlib, runpy; "
        f"runpy.run_path({str(runner_path)!r}, run_name='benchmark_test'); "
        "import local_ai_hub; "
        f"assert pathlib.Path(local_ai_hub.__file__).resolve().is_relative_to(pathlib.Path({str(repo_source)!r}).resolve())"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(foreign_source)

    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=runner_path.parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr


def test_implementation_fingerprint_includes_retrieval_dependency(monkeypatch, tmp_path: Path) -> None:
    package_dir = tmp_path / "src" / "local_ai_hub"
    package_dir.mkdir(parents=True)
    retrieval = package_dir / "retrieval.py"
    retrieval.write_text("weight = 0.0\n", encoding="utf-8")
    monkeypatch.setattr(benchmark_surfaces, "_REPO_ROOT", tmp_path)

    before = benchmark_surfaces._implementation_fingerprint()
    retrieval.write_text("weight = 0.75\n", encoding="utf-8")
    after = benchmark_surfaces._implementation_fingerprint()

    assert after != before, "fingerprint must include imported runtime dependencies"


def test_plan_grade_gate_rejects_malformed_metadata_without_crashing() -> None:
    reasons = _plan_grade_reasons({
        "stage_repetitions": {"light": "1000", "paired": None},
        "concurrency": [1, 4, 16, []],
        "full": True,
        "synthetic_file_count": 10_000,
        "rag_chunk_count": 10_000,
    })

    assert "light_repetitions_below_1000" in reasons
    assert "paired_repetitions_below_30" in reasons
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

    diagnostic["async_jobs_before"] = _async_jobs_lifecycle_snapshot(state_dir)

    def emit_diagnostic() -> None:
        diagnostic["async_jobs_at_teardown"] = _async_jobs_lifecycle_snapshot(state_dir)
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
            paired_repetitions=2,
            concurrency=(1, 2),
        )
    finally:
        diagnostic["async_jobs_after_baseline_close"] = _async_jobs_lifecycle_snapshot(state_dir)

    assert result["metadata"].get("watchdog_enabled") is False
    assert result["metadata"].get("debug_traces_enabled") is False
    assert result["success"] is True
    assert collision_path.read_text(encoding="utf-8") == "user-owned sentinel"
    assert result["metadata"]["benchmark_scope"] == "hub_app_synthetic_repo"
    assert "preseeded warm keys" in result["metadata"]["cold_warm_policy"]
    assert result["metadata"]["prewarm_enabled"] is False
    assert result["metadata"]["observability_enabled"] is False
    assert "processor" in result["metadata"]["platform"]
    assert "total_memory_bytes" in result["metadata"]["platform"]
    assert result["metadata"]["synthetic_file_count"] == 12
    assert result["metadata"]["rag_chunk_count"] == 20
    assert result["metadata"]["stage_repetitions"] == {"light": 3, "paired": 2}
    assert result["metadata"]["inference"] == "skipped_not_requested"
    assert result["metadata"]["baseline_readiness"] == "per_case"
    assert result["metadata"]["matrix_aggregation"] == "not_performed_single_case_record"
    assert result["metadata"]["baseline_readiness_reasons"]
    assert result["metadata"]["implementation_fingerprint"]
    assert result["metadata"]["config_fingerprint"]
    assert result["metadata"]["hardware_fingerprint"]
    assert "not model tokenization" in result["metadata"]["whitespace_token_estimate"]
    assert result["golden"]["symbols"]["passed"] is True
    assert result["golden"]["context_pack"]["passed"] is True
    for task in ("graph", "affected_tests", "retrieval_relevance", "code_generation", "vision", "speech"):
        assert result["golden"][task]["status"] == "skipped_unavailable"
        assert result["golden"][task]["reason"]
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
    assert result["stages"]["hub_queue_admission"]["error_categories"] == {}
    assert result["stages"]["hub_rag_chunking"]["measurement"] == "RAGStore._chunks_chunker_only"
    assert result["resource_usage"]["peak_rss_bytes"] is None or result["resource_usage"]["peak_rss_bytes"] > 0
    assert "availability" in result["resource_usage"]
    assert result["resource_usage"]["availability"]["peak_vram_bytes"] == "not_measured_no_gpu_adapter"
    assert result["resource_usage"]["availability"]["peak_rss_scope"] == "process_lifetime_high_water_mark"
    assert result["resource_usage"]["availability"]["peak_rss_bytes"] == (
        "measured" if result["resource_usage"]["peak_rss_bytes"] is not None else "platform_unavailable"
    )
    assert result["stages"]["hub_validation"]["samples_ms"] and len(result["stages"]["hub_validation"]["samples_ms"]) == 2
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
            paired_repetitions=2,
            concurrency=(1, 2),
            baseline_record=result,
        )
    finally:
        diagnostic["async_jobs_after_candidate_close"] = _async_jobs_lifecycle_snapshot(state_dir)
    comparison = compared.get("comparison")
    diagnostic["comparison"] = _comparison_diagnostic(
        result,
        compared,
        comparison if isinstance(comparison, dict) else {},
    )
    assert compared["comparison"]["status"] == "inconclusive"
    assert compared["comparison"]["provisional"]["status"] in {"within_tolerance", "regression"}
    persisted_comparison = json.loads(Path(compared["record_path"]).read_text(encoding="utf-8"))
    assert persisted_comparison["comparison"]["status"] == compared["comparison"]["status"]


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


def test_benchmark_rejects_duplicate_concurrency_and_unbounded_samples(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="concurrency levels must be unique"):
        run_benchmark(
            state_dir=tmp_path / "state", file_count=2, rag_chunks=2,
            repetitions=1, concurrency=(1, 1),
        )
    with pytest.raises(ValueError, match="maximum is 1000"):
        run_benchmark(
            state_dir=tmp_path / "state", file_count=2, rag_chunks=2,
            repetitions=1, paired_repetitions=1001, concurrency=(1,),
        )
    assert not (tmp_path / "state").exists()


def test_compare_records_pairs_cold_and_warm_samples_and_flags_regressions() -> None:
    metadata = _plan_grade_metadata()
    baseline = {
        "success": True,
        "metadata": metadata,
        "stages": _comparison_stages(10.0),
    }
    candidate = {
        "success": True,
        "metadata": json.loads(json.dumps(metadata)),
        "stages": _comparison_stages(10.5),
    }

    comparison = compare_records(baseline, candidate)
    assert comparison["status"] == "within_tolerance"
    assert comparison["stages"]["hub_health"]["cold"]["paired_count"] == 30
    assert comparison["stages"]["hub_health"]["warm"]["paired_count"] == 30
    assert "paired_delta_pct_percentile_range_95" in comparison["stages"]["hub_health"]["warm"]

    candidate["stages"]["hub_health"]["samples_by_regime"]["warm"] = [12.0] * 30
    comparison = compare_records(baseline, candidate)
    assert comparison["status"] == "regression"
    assert comparison["stages"]["hub_health"]["warm"]["regression"] is True


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


def test_compare_records_requires_minimum_samples_per_regime_and_record() -> None:
    metadata = _plan_grade_metadata()
    baseline = {"success": True, "metadata": metadata, "stages": _comparison_stages(10.0)}
    candidate = {
        "success": True,
        "metadata": json.loads(json.dumps(metadata)),
        "stages": _comparison_stages(10.0),
    }
    for record in (baseline, candidate):
        record["stages"]["hub_health"]["samples_by_regime"] = {
            "cold": [10.0] * 60,
            "warm": [],
        }

    comparison = compare_records(baseline, candidate)

    assert comparison["status"] == "inconclusive"
    assert "hub_health:warm" in comparison["reason"]


def test_smoke_comparison_is_inconclusive_and_retains_provisional_metrics() -> None:
    metadata = {"benchmark_scope": "hub_app_synthetic_repo", "config_fingerprint": "cfg", "hardware_fingerprint": "hw", "baseline_readiness": "smoke_only"}
    baseline_stages = _comparison_stages(10.0, cold=1, warm=2)
    candidate_stages = _comparison_stages(10.0, cold=1, warm=2)
    candidate_stages["hub_health"]["samples_by_regime"]["warm"] = [12.0, 12.0]
    baseline = {"success": True, "metadata": metadata, "stages": baseline_stages}
    candidate = {"success": True, "metadata": dict(metadata), "stages": candidate_stages}

    comparison = compare_records(baseline, candidate)

    assert comparison["status"] == "inconclusive"
    assert comparison["reason"]
    assert comparison["provisional"]["status"] == "regression"
    assert comparison["provisional"]["stages"]["hub_health"]["warm"]["latency"]["p95_ms"]["delta_pct"] == 20.0


def test_compare_records_rejects_different_hardware_or_configuration() -> None:
    baseline = {"success": True, "metadata": {"benchmark_scope": "synthetic_microbench_only", "config_fingerprint": "cfg", "hardware_fingerprint": "hw"}, "stages": {}}
    candidate = {"success": True, "metadata": {"benchmark_scope": "synthetic_microbench_only", "config_fingerprint": "other", "hardware_fingerprint": "hw"}, "stages": {}}

    assert compare_records(baseline, candidate)["status"] == "incomparable"


def test_compare_records_refuses_inference_without_model_digest() -> None:
    baseline = {
        "success": True,
        "metadata": {"benchmark_scope": "synthetic_microbench_only", "config_fingerprint": "cfg", "hardware_fingerprint": "hw", "inference": "requested"},
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
        light_repetitions=2, paired_repetitions=1, concurrency=(1,),
    )

    exit_code = main([
        "--state-dir", str(state_dir), "--files", "4", "--rag-chunks", "4",
        "--repetitions", "1", "--light-repetitions", "2", "--paired-repetitions", "1",
        "--concurrency", "1", "--compare-with", baseline["record_path"],
    ])

    output = json.loads(capsys.readouterr().out)
    assert output["comparison"]["status"] == "inconclusive"
    assert exit_code == 2
    assert output["metadata"]["stage_repetitions"] == {"light": 2, "paired": 1}
    assert Path(output["record_path"]).is_relative_to(state_dir)


def test_optional_inference_uses_runtime_load_metric_without_real_model(tmp_path: Path) -> None:
    class FakeRunner:
        config = {"models": {"fast_code": "test-model"}}

        def run(self, **_kwargs):
            return {
                "success": True, "ttft_ms": 4.0, "tokens_per_second": 8.0,
                "generation_duration_ms": 20.0, "tokens_generated": 8,
                "load_duration_ms": 12.5,
                "initial_vram": {"vram_used_mb": 100}, "final_vram": {"vram_used_mb": 250},
            }

    result = run_benchmark(
        state_dir=tmp_path / "state", file_count=2, rag_chunks=2, repetitions=1,
        paired_repetitions=2, concurrency=(1,), inference_runner=FakeRunner(), include_inference=True,
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
