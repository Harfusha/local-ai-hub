"""Measure T02 async-job submit/cancel admission without running the full suite.

This is a queue-only diagnostic companion to benchmark_surfaces.py. It preserves
the benchmark's per-repetition concurrency barrier, 30-second delayed dispatch,
and immediate cancellation. It never invokes model inference.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import tempfile
import threading
import time
import uuid
from typing import Any

if __package__:
    from tools.benchmark_surfaces import (
        _implementation_fingerprint,
        _revision,
        _resolve_outside_repo,
        _total_memory_bytes,
        summarize_samples,
    )
    from tools.t02_queue_diagnostics import admission_failure_code, cancellation_failure_code, resource_decision_sample, NominalFixtureScheduler
else:  # Direct script execution puts tools/, not the repository root, on sys.path.
    from benchmark_surfaces import (
        _implementation_fingerprint,
        _revision,
        _resolve_outside_repo,
        _total_memory_bytes,
        summarize_samples,
    )
    from t02_queue_diagnostics import admission_failure_code, cancellation_failure_code, resource_decision_sample, NominalFixtureScheduler


_MAX_REPETITIONS = 1_000
_MAX_CONCURRENCY = 256
_DISPATCH_DELAY_SECONDS = 30.0
_QUEUE_TARGET_P95_MS = 150.0


class _BenchmarkCheckpoint:
    """Atomic queue-only progress, bound to the exact runner and runtime bytes."""

    def __init__(self, path, *, run_fingerprint, scratch_path, resume):
        self.path = path
        if resume:
            self.data = json.loads(path.read_text(encoding="utf-8"))
            if (self.data.get("schema_version") != 1
                    or self.data.get("run_fingerprint") != run_fingerprint
                    or Path(self.data.get("scratch_path", "")).resolve() != scratch_path.resolve()):
                raise ValueError("queue checkpoint fingerprint or scratch identity mismatch")
        else:
            if path.exists():
                raise ValueError("queue checkpoint exists; use compatible resume or a new path")
            self.data = {"schema_version": 1, "run_fingerprint": run_fingerprint,
                         "scratch_path": str(scratch_path), "progress": {}, "completed": {}}

    def completed_stage(self, name):
        return self.data["completed"].get(name)

    def stage_progress(self, name):
        return self.data["progress"].setdefault(name, {})

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            temporary.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def save_progress(self, name, progress):
        self.data["progress"][name] = progress
        self._save()

    def complete_stage(self, name, result):
        self.data["completed"][name] = result
        self._save()
_CHECKPOINT_BATCH_SIZE = 25


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _read_record(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 10_000_000:
        raise ValueError("comparison record exceeds 10 MB limit")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("comparison record must contain a JSON object")
    return value


def _compare_queue_records(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Compare queue-only p95 values without pretending the record has other stages."""
    baseline_meta = baseline.get("metadata", {})
    candidate_meta = candidate.get("metadata", {})
    if not isinstance(baseline_meta, dict) or not isinstance(candidate_meta, dict):
        return {"status": "incomparable", "reason": "benchmark metadata is missing or malformed"}
    if any(
        not baseline_meta.get(field) or baseline_meta.get(field) != candidate_meta.get(field)
        for field in ("benchmark_scope", "config_fingerprint", "hardware_fingerprint")
    ):
        return {"status": "incomparable", "reason": "benchmark scope, configuration, or hardware differs"}
    baseline_stage = baseline.get("stages", {}).get("hub_queue_admission")
    candidate_stage = candidate.get("stages", {}).get("hub_queue_admission")
    baseline_levels = baseline_stage.get("by_concurrency") if isinstance(baseline_stage, dict) else None
    candidate_levels = candidate_stage.get("by_concurrency") if isinstance(candidate_stage, dict) else None
    if not isinstance(baseline_levels, dict) or not isinstance(candidate_levels, dict):
        return {"status": "incomparable", "reason": "queue stage or per-concurrency samples are missing"}
    if set(baseline_levels) != set(candidate_levels):
        return {"status": "incomparable", "reason": "concurrency sets differ"}

    comparisons: dict[str, Any] = {}
    regressions: list[str] = []
    for level in sorted(baseline_levels, key=int):
        old = baseline_levels[level].get("p95_ms")
        new = candidate_levels[level].get("p95_ms")
        if not isinstance(old, (int, float)) or not isinstance(new, (int, float)) or old <= 0:
            return {"status": "incomparable", "reason": f"p95 sample is missing for concurrency {level}"}
        delta_pct = round((new - old) * 100.0 / old, 3)
        comparisons[level] = {
            "baseline_p95_ms": old,
            "candidate_p95_ms": new,
            "delta_pct": delta_pct,
            "baseline_target_met": old <= _QUEUE_TARGET_P95_MS,
            "candidate_target_met": new <= _QUEUE_TARGET_P95_MS,
            "regression": delta_pct > 10.0,
        }
        if delta_pct > 10.0:
            regressions.append(level)
    return {
        "status": "regression" if regressions else "within_tolerance",
        "regression_tolerance_pct": 10.0,
        "target_p95_ms": _QUEUE_TARGET_P95_MS,
        "stages": comparisons,
        "regressed_concurrency_levels": regressions,
    }


def run_queue_benchmark(
    *,
    state_dir: Path | str,
    scratch_dir: Path | str,
    checkpoint_path: Path | str,
    run_id: str,
    light_repetitions: int = 1_000,
    concurrency: tuple[int, ...] = (1, 4, 16, 32),
    checkpoint_batch_size: int = _CHECKPOINT_BATCH_SIZE,
    resume: bool = False,
    baseline_record: dict[str, Any] | None = None,
    resource_mode: str = "live",
) -> dict[str, Any]:
    """Run the isolated queue stage and durably save samples every batch."""
    if not run_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in run_id):
        raise ValueError("run_id must contain only letters, numbers, hyphens, and underscores")
    if not 1 <= light_repetitions <= _MAX_REPETITIONS:
        raise ValueError(f"light_repetitions must be between 1 and {_MAX_REPETITIONS}")
    if not concurrency or any(level < 1 or level > _MAX_CONCURRENCY for level in concurrency):
        raise ValueError(f"concurrency levels must be between 1 and {_MAX_CONCURRENCY}")
    if len(set(concurrency)) != len(concurrency):
        raise ValueError("concurrency levels must be unique")
    if checkpoint_batch_size < 1:
        raise ValueError("checkpoint_batch_size must be positive")
    if resource_mode not in {"live", "nominal-fixture"}:
        raise ValueError("resource_mode must be live or nominal-fixture")

    state_root = _resolve_outside_repo(Path(state_dir), "state_dir")
    scratch_root = _resolve_outside_repo(Path(scratch_dir), "scratch_dir")
    checkpoint_file = _resolve_outside_repo(Path(checkpoint_path), "checkpoint_path")
    state_root.mkdir(parents=True, exist_ok=True)
    scratch_root.mkdir(parents=True, exist_ok=True)

    config = {
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "resource_mode": resource_mode,
        "fixture_identity": "nominal-resource-v1" if resource_mode == "nominal-fixture" else None,
        "light_repetitions": light_repetitions,
        "concurrency": list(concurrency),
        "dispatch_delay_seconds": _DISPATCH_DELAY_SECONDS,
        "checkpoint_batch_size": checkpoint_batch_size,
        "inference": False,
        "operation": "AsyncJobManager.submit_then_cancel_before_dispatch",
    }
    implementation = _implementation_fingerprint()
    fingerprint = _fingerprint({"config": config, "implementation": implementation, "run_id": run_id})

    owned_scratch: tempfile.TemporaryDirectory[str] | None = None
    if resume:
        try:
            existing = json.loads(checkpoint_file.read_text(encoding="utf-8"))
            scratch = Path(existing["scratch_path"]).resolve()
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("queue checkpoint cannot be read") from exc
        try:
            scratch.relative_to(scratch_root)
        except ValueError as exc:
            raise ValueError("checkpoint scratch directory must stay under --scratch-dir") from exc
    else:
        scratch = Path(tempfile.mkdtemp(prefix=f"t02-queue-{run_id}-", dir=scratch_root))

    checkpoint = _BenchmarkCheckpoint(
        checkpoint_file,
        run_fingerprint=fingerprint,
        scratch_path=scratch,
        resume=resume,
    )
    prior_run = checkpoint.completed_stage("__run__") if resume else None
    if prior_run is not None:
        prior_path = Path(str(prior_run.get("record_path", "")))
        if prior_path.is_file():
            return {**_read_record(prior_path), "record_path": str(prior_path)}

    app: Any = None
    try:
        config_path = scratch / "hub-config.toml"
        app_state_dir = scratch / "hub-state"
        config_path.write_text(
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
        from local_ai_hub.app import LocalAIApp

        app = LocalAIApp(str(config_path))
        if resource_mode == "nominal-fixture":
            app.async_jobs.scheduler = NominalFixtureScheduler(app.async_jobs.scheduler)

        active_lock = threading.Lock()
        active = 0
        peak_active = 0

        def attempt(level: int, repetition: int, slot: int, barrier: threading.Barrier):
            nonlocal active, peak_active
            started = time.perf_counter()
            error_type: str | None = None
            error_code: str | None = None
            job_id: str | None = None
            cancelled = False
            sample = {"burst_id": f"{run_id}:{level}:{repetition}", "slot": slot,
                      "resource_mode": resource_mode, "resource_sample": None,
                      "enqueue_ms": None, "rejection_ms": None, "cancel_ms": None}
            try:
                barrier.wait(timeout=10.0)
                started = time.perf_counter()
                sample["started_at"] = time.time()
                with active_lock:
                    active += 1
                    peak_active = max(peak_active, active)
                sample["entered"] = True
                task_id = str(uuid.uuid5(
                    uuid.NAMESPACE_URL, f"t02-queue:{run_id}:{level}:{repetition}:{slot}",
                ))
                submitted = app.async_jobs.submit(
                    "reason", {"task_id": task_id, "task": "T02 queue admission probe"},
                    dispatch_delay_seconds=_DISPATCH_DELAY_SECONDS,
                )
                submit_ms = (time.perf_counter() - started) * 1000.0
                sample["resource_sample"] = resource_decision_sample(submitted)
                sample["admission_state"] = submitted.get("admission_state")
                if submitted.get("success") is not True or not submitted.get("job_id"):
                    sample["rejection_ms"] = submit_ms
                    error_code = admission_failure_code(submitted)
                    raise RuntimeError("Hub async job admission failed")
                sample["enqueue_ms"] = submit_ms
                job_id = str(submitted["job_id"])
                cancel_started = time.perf_counter()
                cancelled_result = app.async_jobs.cancel(job_id)
                sample["cancel_ms"] = (time.perf_counter() - cancel_started) * 1000.0
                cancelled = cancelled_result.get("success") is True and cancelled_result.get("state") == "cancelled"
                if not cancelled:
                    error_code = cancellation_failure_code(cancelled_result)
                    raise RuntimeError("Hub async job was not cancelled before worker service")
            except Exception as exc:  # capture type only; payloads and exception text are not evidence
                error_type = type(exc).__name__
            finally:
                if job_id is not None and not cancelled:
                    try:
                        cleanup = app.async_jobs.cancel(job_id)
                        cancelled = cleanup.get("success") is True and cleanup.get("state") == "cancelled"
                    except Exception:
                        pass
                sample["cancelled"] = cancelled
                sample["finished_at"] = time.time()
                if sample.pop("entered", False):
                    with active_lock:
                        active -= 1
            return (time.perf_counter() - started) * 1000.0, error_type, error_code, sample

        progress = checkpoint.stage_progress("queue_admission")
        levels = progress.setdefault("by_concurrency", {})
        all_samples: list[float] = []
        cold_samples: list[float] = []
        warm_samples: list[float] = []
        error_count = 0
        error_types: set[str] = set()
        error_codes: set[str] = set()
        batch_seconds_total = 0.0
        by_concurrency: dict[str, Any] = {}

        for level in concurrency:
            item = levels.setdefault(str(level), {
                "next_repetition": 0,
                "samples_ms": [],
                "cold_samples_ms": [],
                "warm_samples_ms": [],
                "error_count": 0,
                "error_types": [],
                "error_codes": [],
                "batch_seconds": 0.0,
                "decision_samples": [],
                "bursts": [],
            })
            level_samples = [float(value) for value in item["samples_ms"]]
            level_cold = [float(value) for value in item["cold_samples_ms"]]
            level_warm = [float(value) for value in item["warm_samples_ms"]]
            level_errors = int(item["error_count"])
            level_error_types = set(item["error_types"])
            level_error_codes = set(item.get("error_codes", []))
            level_seconds = float(item["batch_seconds"])
            next_repetition = int(item["next_repetition"])

            while next_repetition < light_repetitions:
                count = min(checkpoint_batch_size, light_repetitions - next_repetition)
                for repetition in range(next_repetition, next_repetition + count):
                    batch_started = time.perf_counter()
                    barrier = threading.Barrier(level)
                    peak_active = 0
                    with ThreadPoolExecutor(max_workers=level) as pool:
                        outcomes = list(pool.map(
                            lambda slot: attempt(level, repetition, slot, barrier), range(level),
                        ))
                    stats = app.async_jobs.stats()
                    counts = stats.get("counts")
                    complete_counts = isinstance(counts, dict) and stats.get("counts_truncated") is False
                    queued = counts.get("queued", 0) if complete_counts else None
                    running = counts.get("running", 0) if complete_counts else None
                    item["bursts"].append({"repetition": repetition, "offered_concurrency": level,
                                           "observed_active_concurrency": peak_active,
                                           "queued_after": queued,
                                           "running_after": running,
                                           "drained": queued == 0 and running == 0})
                    level_seconds += time.perf_counter() - batch_started
                    target = level_cold if repetition == 0 else level_warm
                    for elapsed_ms, error_type, error_code, sample in outcomes:
                        item["decision_samples"].append(sample)
                        level_samples.append(elapsed_ms)
                        target.append(elapsed_ms)
                        if error_type:
                            level_errors += 1
                            level_error_types.add(error_type)
                        if error_code:
                            level_error_codes.add(error_code)

                next_repetition += count
                item.update({
                    "next_repetition": next_repetition,
                    "samples_ms": level_samples,
                    "cold_samples_ms": level_cold,
                    "warm_samples_ms": level_warm,
                    "error_count": level_errors,
                    "error_types": sorted(level_error_types),
                    "error_codes": sorted(level_error_codes),
                    "batch_seconds": level_seconds,
                })
                checkpoint.save_progress("queue_admission", progress)

            all_samples.extend(level_samples)
            cold_samples.extend(level_cold)
            warm_samples.extend(level_warm)
            error_count += level_errors
            error_types.update(level_error_types)
            error_codes.update(level_error_codes)
            batch_seconds_total += level_seconds
            by_concurrency[str(level)] = {
                "decision_samples": item["decision_samples"],
                "bursts": item["bursts"],
                "attempted": len(item["decision_samples"]),
                "admitted": sum(sample["enqueue_ms"] is not None for sample in item["decision_samples"]),
                "rejected": sum(sample["rejection_ms"] is not None for sample in item["decision_samples"]),
                "degraded": sum(sample.get("admission_state") == "degraded" for sample in item["decision_samples"]),
                "accepted_enqueue": summarize_samples([sample["enqueue_ms"] for sample in item["decision_samples"] if sample["enqueue_ms"] is not None]),
                "rejection_latency": summarize_samples([sample["rejection_ms"] for sample in item["decision_samples"] if sample["rejection_ms"] is not None]),
                "independent_bursts": len(item["bursts"]),
                "tail_acceptance_sample_count_met": len(item["bursts"]) >= 1000,
                **summarize_samples(level_samples),
                "error_count": level_errors,
                "error_codes": sorted(level_error_codes),
                "error_rate_pct": round(level_errors * 100.0 / max(1, len(level_samples)), 3),
                "concurrent_admissions_per_second": round(
                    level * light_repetitions / level_seconds, 3,
                ) if level_seconds else None,
                "cold_warm": {
                    "cold": summarize_samples(level_cold),
                    "warm": summarize_samples(level_warm),
                },
            }

        all_bursts_drained = all(burst["drained"] for item in by_concurrency.values() for burst in item["bursts"])
        stage = {
            "status": "passed" if error_count == 0 and all_bursts_drained else "failed",
            **summarize_samples(all_samples),
            "samples_ms": all_samples,
            "samples_by_regime": {"cold": cold_samples, "warm": warm_samples},
            "cold_warm": {
                "cold": summarize_samples(cold_samples),
                "warm": summarize_samples(warm_samples),
                "definition": "first admission per concurrency level is cold; remaining samples are warm",
            },
            "error_count": error_count,
            "error_rate_pct": round(error_count * 100.0 / max(1, len(all_samples)), 3),
            "error_types": sorted(error_types),
            "error_codes": sorted(error_codes),
            "http_response_body_bytes": 0,
            "whitespace_token_estimate": 0,
            "response_measurement": "not_applicable_no_http_response",
            "measurement": "async_jobs_submit_cancel_admission_only",
            "dispatch_delay_seconds": _DISPATCH_DELAY_SECONDS,
            "concurrent_admissions_per_second": round(
                len(all_samples) / batch_seconds_total, 3,
            ) if batch_seconds_total else None,
            "by_concurrency": by_concurrency,
        }
        machine = {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor() or None,
            "cpu_count": os.cpu_count(),
            "total_memory_bytes": _total_memory_bytes(),
        }
        metadata = {
            "resource_mode": resource_mode,
            "live_capacity_proof": False,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "benchmark_scope": "t02_async_queue_only",
            "revision": _revision(),
            "implementation_fingerprint": implementation,
            "config_fingerprint": _fingerprint(config),
            "hardware_fingerprint": _fingerprint(machine),
            "run_id": run_id,
            "config": config,
            "platform": machine,
            "queue_admission_p95_target_ms": _QUEUE_TARGET_P95_MS,
            "inference": "skipped_not_requested",
        }
        p95_values = [value["p95_ms"] for value in by_concurrency.values()]
        acceptance = {
            "all_bursts_drained": all_bursts_drained,
            "sample_count_matches_config": len(all_samples) == light_repetitions * sum(concurrency),
            "all_cancellations_succeeded": error_count == 0,
            "every_concurrency_p95_within_target": all(
                isinstance(value, (int, float)) and value <= _QUEUE_TARGET_P95_MS for value in p95_values
            ),
        }
        record: dict[str, Any] = {
            "success": all(acceptance.values()),
            "metadata": metadata,
            "stages": {"hub_queue_admission": stage},
            "acceptance": acceptance,
            "failed_acceptance": [name for name, passed in acceptance.items() if not passed],
            "failed_stages": ["hub_queue_admission"] if not all(acceptance.values()) else [],
        }
        if baseline_record is not None:
            record["queue_comparison"] = _compare_queue_records(baseline_record, record)

        record_path = state_root / f"t02-queue-{run_id}.json"
        temporary_path = state_root / f".{record_path.name}.tmp"
        try:
            temporary_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(temporary_path, record_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        checkpoint.complete_stage("__run__", {"record_path": str(record_path)})
        return {**record, "record_path": str(record_path)}
    finally:
        if app is not None:
            app.close()
        if owned_scratch is not None:
            owned_scratch.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True, help="external output directory")
    parser.add_argument("--scratch-dir", type=Path, required=True, help="external parent for persistent scratch")
    parser.add_argument("--checkpoint", type=Path, required=True, help="atomic run checkpoint")
    parser.add_argument("--run-id", required=True, help="stable identifier pinned across paired runs")
    parser.add_argument("--light-repetitions", type=int, default=1_000)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 4, 16, 32])
    parser.add_argument("--checkpoint-batch-size", type=int, default=_CHECKPOINT_BATCH_SIZE)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--resource-mode", choices=("live", "nominal-fixture"), default="live")
    parser.add_argument("--compare-with", type=Path)
    args = parser.parse_args(argv)
    try:
        baseline = _read_record(args.compare_with) if args.compare_with is not None else None
        result = run_queue_benchmark(
            state_dir=args.state_dir,
            scratch_dir=args.scratch_dir,
            checkpoint_path=args.checkpoint,
            run_id=args.run_id,
            light_repetitions=args.light_repetitions,
            concurrency=tuple(args.concurrency),
            checkpoint_batch_size=args.checkpoint_batch_size,
            resume=args.resume,
            baseline_record=baseline,
            resource_mode=args.resource_mode,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
