"""Reproducible paired benchmark primitives for an isolated T15 overlay."""

from __future__ import annotations

import hashlib
import argparse
import contextlib
import json
import math
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence
import re


_BROKER_WORKER = r'''
import json, os, sys, time
from pathlib import Path
from local_ai_hub.commands import CommandBroker
class Artifacts:
    def put(self, *_args, **_kwargs): return "t15-paired-benchmark"
class NullRepoState:
    def fingerprint(self, _cwd): return {"fingerprint":"t15-paired-fixture","stale":False,"degraded":False}
source_root, fixture_root, state_root = sys.argv[1:]
sys.path.insert(0, str(Path(source_root) / "src"))
config = {"server":{"state_dir":state_root},"commands":{"enabled":True,"allow_unknown":True,"success_ttl_seconds":300,"l1_ttl_seconds":30,"max_output_chars":65536,"inline_output_chars":65536}}
broker = CommandBroker(config, Artifacts(), NullRepoState())
for line in sys.stdin:
    try:
        request = json.loads(line)
        started = time.perf_counter_ns()
        callback_chunks = [0]
        def on_log(_stream, _text): callback_chunks[0] += 1
        active_broker = broker
        if request.get("fresh_broker"):
            fresh_state = Path(state_root) / ("fresh-" + str(time.perf_counter_ns()))
            fresh_state.mkdir(parents=True, exist_ok=True)
            fresh_config = {**config, "server":{"state_dir":str(fresh_state)}}
            active_broker = CommandBroker(fresh_config, Artifacts(), NullRepoState())
        result = active_broker.run_project_command(request["alias"], fixture_root, tenant="t15-paired", force=request.get("force", False), log_callback=on_log if request.get("capture_logs") else None)
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        print(json.dumps({"success":result.get("success"),"cache_hit":result.get("cache_hit"),"stdout":result.get("stdout"),"elapsed_ms":elapsed_ms,"callback_chunks":callback_chunks[0]}), flush=True)
    except Exception as error:
        print(json.dumps({"worker_error":type(error).__name__,"message":str(error)[:300]}), flush=True)
'''


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHARED_HASH_FIELDS = ("config_sha256", "harness_sha256", "runtime_sha256")
_SCHEMA = "t15-paired-overlay-benchmark-v1"


def stream_command_argv() -> list[str]:
    return [
        sys.executable,
        "-B",
        "-c",
        "import sys; print('t15-paired-ok'); sys.stderr.write('t15-stream-event\\n')",
    ]


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _source_map_digest(files: dict[str, str]) -> str:
    payload = json.dumps(dict(sorted(files.items())), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def config_sha256(config: Any) -> str:
    payload = json.dumps(config, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def project_benchmark_config(
    command_argv: Sequence[str], *, case: str = "warm_success_cache"
) -> tuple[str, str]:
    argv = list(command_argv)
    if not argv or any(not isinstance(value, str) or "\x00" in value for value in argv):
        raise ValueError("command argv must contain null-free strings")
    project_config = "[commands.bench]\nargv = " + json.dumps(argv) + "\n"
    broker_config = {
        "server": {"state_dir": "<temporary benchmark state>"},
        "commands": {
            "enabled": True,
            "allow_unknown": True,
            "success_ttl_seconds": 300,
            "l1_ttl_seconds": 30,
            "max_output_chars": 65536,
            "inline_output_chars": 65536,
        },
    }
    fingerprint = config_sha256(
        {
            "project_config": project_config,
            "broker_config": broker_config,
            "benchmark_case": case,
            "command_argv": argv,
        }
    )
    return project_config, fingerprint


@contextlib.contextmanager
def _exclusive_benchmark_lock() -> Any:
    lock_path = Path(tempfile.gettempdir()) / "local-ai-hub-t15-paired-benchmark.lock"
    try:
        with lock_path.open("x", encoding="ascii") as stream:
            stream.write(f"pid={os.getpid()}\n")
    except FileExistsError as exc:
        raise RuntimeError(f"another T15 paired benchmark may be active: {lock_path}") from exc
    try:
        yield str(lock_path)
    finally:
        try:
            lock_path.unlink()
        except OSError:
            pass


def runtime_fingerprint() -> dict[str, str]:
    identity = {
        "python": sys.version,
        "executable": str(Path(sys.executable).resolve()),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpus": str(os.cpu_count()),
        "path_sha256": hashlib.sha256(os.environ.get("PATH", "").encode()).hexdigest(),
        "pythonpath_sha256": hashlib.sha256(os.environ.get("PYTHONPATH", "").encode()).hexdigest(),
    }
    payload = json.dumps(identity, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return {"sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()}


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_active_hashes(hashes: dict[str, str]) -> str:
    harness_path = Path(__file__).resolve()
    if _file_sha256(harness_path) != hashes["harness_sha256"]:
        raise ValueError("harness_sha256 does not match active harness")
    if runtime_fingerprint()["sha256"] != hashes["runtime_sha256"]:
        raise ValueError("runtime_sha256 does not match active runtime")
    return str(harness_path)


def _source_files(root: Path) -> dict[str, str]:
    package = root / "src" / "local_ai_hub"
    if not package.is_dir():
        raise ValueError(f"source root lacks src/local_ai_hub: {root}")
    files: dict[str, str] = {}
    for path in sorted(package.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(root).as_posix()
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not files:
        raise ValueError(f"source root has no package files: {root}")
    return files


def source_snapshot(root: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    files = _source_files(root)
    return {
        "source_root": str(root),
        "source_files_sha256": files,
        "source_sha256": _source_map_digest(files),
    }


def _comparison_hashes(
    config_sha256: str, harness_sha256: str, runtime_sha256: str
) -> dict[str, str]:
    values = {
        "config_sha256": config_sha256,
        "harness_sha256": harness_sha256,
        "runtime_sha256": runtime_sha256,
    }
    for name, value in values.items():
        if not _valid_sha256(value):
            raise ValueError(f"{name} must be lowercase SHA-256")
    return values


def baseline_input(
    source_root: Path,
    *,
    config_sha256: str,
    harness_sha256: str,
    runtime_sha256: str,
) -> dict[str, Any]:
    snapshot = source_snapshot(source_root)
    hashes = _comparison_hashes(config_sha256, harness_sha256, runtime_sha256)
    harness_path = _validate_active_hashes(hashes)
    return {
        **snapshot,
        **hashes,
        "harness_path": harness_path,
        "base_source_sha256": snapshot["source_sha256"],
        "overlay_patch_sha256": None,
        "overlay_paths": [],
        "allowed_paths": [],
    }


def checkout_input(
    source_root: Path,
    *,
    config_sha256: str,
    harness_sha256: str,
    runtime_sha256: str,
) -> dict[str, Any]:
    snapshot = source_snapshot(source_root)
    hashes = _comparison_hashes(config_sha256, harness_sha256, runtime_sha256)
    harness_path = _validate_active_hashes(hashes)
    return {**snapshot, **hashes, "harness_path": harness_path}


def build_overlay(
    source_root: Path,
    patch_path: Path,
    overlay_root: Path,
    *,
    expected_patch_sha256: str,
    allowed_paths: list[str],
    config_sha256: str,
    harness_sha256: str,
    runtime_sha256: str,
) -> dict[str, Any]:
    source_root = source_root.resolve(strict=True)
    patch_path = patch_path.resolve(strict=True)
    overlay_root = overlay_root.resolve(strict=False)
    if overlay_root == source_root or overlay_root.is_relative_to(source_root) or source_root.is_relative_to(overlay_root):
        raise ValueError("overlay root must be separate from source root")
    if overlay_root.exists():
        raise FileExistsError(f"refusing to overwrite overlay: {overlay_root}")
    if not _valid_sha256(expected_patch_sha256):
        raise ValueError("expected patch digest must be lowercase SHA-256")
    patch_bytes = patch_path.read_bytes()
    patch_sha256 = hashlib.sha256(patch_bytes).hexdigest()
    if patch_sha256 != expected_patch_sha256:
        raise ValueError("overlay patch digest mismatch")
    touched_paths = sorted(
        line[6:]
        for line in patch_bytes.decode("utf-8").splitlines()
        if line.startswith("+++ b/")
    )
    if not touched_paths or len(touched_paths) != len(set(touched_paths)):
        raise ValueError("overlay patch has no unique source paths")
    allowed = sorted(set(allowed_paths))
    if not allowed or any(
        path.startswith("/") or ".." in Path(path).parts or not path.startswith("src/local_ai_hub/")
        for path in allowed
    ):
        raise ValueError("declared T15 paths must stay under src/local_ai_hub")
    if not set(touched_paths).issubset(allowed):
        raise ValueError("overlay patch touches paths outside declared T15 paths")
    hashes = _comparison_hashes(config_sha256, harness_sha256, runtime_sha256)
    harness_path = _validate_active_hashes(hashes)

    before = source_snapshot(source_root)
    overlay_root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=overlay_root, check=True, capture_output=True)
    (overlay_root / "src").mkdir()
    shutil.copytree(
        source_root / "src" / "local_ai_hub",
        overlay_root / "src" / "local_ai_hub",
    )
    subprocess.run(
        ["git", "apply", "--check", str(patch_path)],
        cwd=overlay_root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "apply", str(patch_path)],
        cwd=overlay_root,
        check=True,
        capture_output=True,
    )
    after = source_snapshot(source_root)
    if after["source_sha256"] != before["source_sha256"] or after["source_files_sha256"] != before["source_files_sha256"]:
        raise RuntimeError("baseline source changed while constructing overlay")
    overlay = source_snapshot(overlay_root)
    actual_changes = sorted(
        path
        for path in set(before["source_files_sha256"]) | set(overlay["source_files_sha256"])
        if before["source_files_sha256"].get(path) != overlay["source_files_sha256"].get(path)
    )
    if actual_changes != touched_paths:
        raise ValueError("overlay source changes do not match patch paths exactly")
    if not actual_changes:
        raise ValueError("overlay patch produced no source changes")
    return {
        **overlay,
        **hashes,
        "harness_path": harness_path,
        "base_source_sha256": before["source_sha256"],
        "overlay_patch_sha256": patch_sha256,
        "overlay_paths": actual_changes,
        "allowed_paths": allowed,
    }


def validate_comparable_inputs(
    baseline: dict[str, Any], overlay: dict[str, Any]
) -> None:
    for name, value in (("baseline", baseline), ("overlay", overlay)):
        for field in ("source_sha256", "base_source_sha256", *_SHARED_HASH_FIELDS):
            if not _valid_sha256(value.get(field)):
                raise ValueError(f"{name} {field} must be lowercase SHA-256")
        files = value.get("source_files_sha256")
        if not isinstance(files, dict) or not files or any(
            not isinstance(path, str) or not _valid_sha256(digest)
            for path, digest in files.items()
        ):
            raise ValueError(f"{name} source file hashes are invalid")
        if _source_map_digest(files) != value["source_sha256"]:
            raise ValueError(f"{name} source snapshot digest mismatch")

    for field in _SHARED_HASH_FIELDS:
        if baseline[field] != overlay[field]:
            raise ValueError(f"incomparable inputs: {field} differs")
    if baseline.get("harness_path") != overlay.get("harness_path"):
        raise ValueError("incomparable inputs: harness path differs")
    if baseline["base_source_sha256"] != baseline["source_sha256"]:
        raise ValueError("baseline source must equal pinned base source")
    if overlay["base_source_sha256"] != baseline["base_source_sha256"]:
        raise ValueError("incomparable inputs: base source differs")
    if baseline.get("overlay_patch_sha256") is not None or baseline.get("overlay_paths"):
        raise ValueError("baseline input must not contain an overlay")
    if not _valid_sha256(overlay.get("overlay_patch_sha256")):
        raise ValueError("overlay patch digest is missing or invalid")
    base_files = baseline["source_files_sha256"]
    overlay_files = overlay["source_files_sha256"]
    if set(base_files) != set(overlay_files):
        raise ValueError("incomparable inputs: source file sets differ")
    actual_changes = sorted(
        path for path in base_files if base_files[path] != overlay_files[path]
    )
    if not actual_changes or actual_changes != overlay.get("overlay_paths"):
        raise ValueError("overlay changed paths do not match pinned source hashes")
    allowed = overlay.get("allowed_paths")
    if not isinstance(allowed, list) or not set(actual_changes).issubset(allowed):
        raise ValueError("overlay changes exceed declared T15 paths")


def validate_paired_environment(baseline: dict[str, Any], current: dict[str, Any]) -> None:
    for label, value in (("baseline", baseline), ("current", current)):
        for field in ("source_sha256", *_SHARED_HASH_FIELDS):
            if not _valid_sha256(value.get(field)):
                raise ValueError(f"{label} {field} must be lowercase SHA-256")
        files = value.get("source_files_sha256")
        if not isinstance(files, dict) or not files or any(
            not isinstance(path, str) or not _valid_sha256(digest)
            for path, digest in files.items()
        ):
            raise ValueError(f"{label} source file hashes are invalid")
        if _source_map_digest(files) != value["source_sha256"]:
            raise ValueError(f"{label} source snapshot digest mismatch")
        if value.get("harness_path") != str(Path(__file__).resolve()):
            raise ValueError(f"{label} harness path is not active harness")

    for field in _SHARED_HASH_FIELDS:
        if baseline[field] != current[field]:
            raise ValueError(f"incomparable inputs: {field} differs")
    if baseline["source_root"] == current["source_root"]:
        if baseline["source_files_sha256"] != current["source_files_sha256"]:
            raise ValueError("source changed between baseline and current snapshots")


def _paired_orders(pairs: int, seed: int) -> list[tuple[str, str]]:
    if pairs < 1:
        raise ValueError("pairs must be positive")
    orders = [("baseline", "overlay") for _ in range((pairs + 1) // 2)]
    orders.extend(("overlay", "baseline") for _ in range(pairs // 2))
    random.Random(seed).shuffle(orders)
    return orders


def _nearest_rank(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, (percentile * len(ordered) + 99) // 100 - 1))
    return round(ordered[index], 3)


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        raise ValueError("cannot summarize empty samples")
    variance = statistics.variance(values) if len(values) > 1 else None
    return {
        "n": len(values),
        "median": round(statistics.median(values), 3),
        "p95": _nearest_rank(values, 95),
        "sample_variance": round(variance, 3) if variance is not None else None,
        "raw": [round(value, 3) for value in values],
    }


def _verify_inputs_unchanged(value: dict[str, Any]) -> None:
    current = source_snapshot(Path(value["source_root"]))
    if (
        current["source_sha256"] != value["source_sha256"]
        or current["source_files_sha256"] != value["source_files_sha256"]
    ):
        raise RuntimeError("source changed during paired benchmark")
    if _file_sha256(Path(value["harness_path"])) != value["harness_sha256"]:
        raise RuntimeError("harness changed during paired benchmark")
    if runtime_fingerprint()["sha256"] != value["runtime_sha256"]:
        raise RuntimeError("runtime changed during paired benchmark")


def _start_broker_worker(source_root: Path, fixture: Path, state: Path) -> subprocess.Popen[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(source_root / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.Popen(
        [sys.executable, "-B", "-u", "-c", _BROKER_WORKER, str(source_root), str(fixture), str(state)],
        cwd=source_root,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )


def _broker_measurement(
    worker: subprocess.Popen[str],
    alias: str,
    *,
    force: bool = False,
    capture_logs: bool = False,
    fresh_broker: bool = False,
) -> dict[str, Any]:
    if worker.poll() is not None or worker.stdin is None or worker.stdout is None:
        raise RuntimeError("broker benchmark worker is not available")
    worker.stdin.write(
        json.dumps(
            {
                "alias": alias,
                "force": force,
                "capture_logs": capture_logs,
                "fresh_broker": fresh_broker,
            }
        )
        + "\n"
    )
    worker.stdin.flush()
    line = worker.stdout.readline()
    if not line:
        raise RuntimeError("broker benchmark worker returned no result")
    result = json.loads(line)
    if result.get("worker_error"):
        raise RuntimeError(f"broker benchmark worker failed: {result['worker_error']}: {result.get('message', '')}")
    if result.get("success") is not True or result.get("stdout") != "t15-paired-ok\n":
        raise RuntimeError("broker benchmark worker returned invalid command outcome")
    return result


def run_project_cache_benchmark(
    baseline: dict[str, Any],
    overlay: dict[str, Any],
    *,
    fixture_root: Path,
    state_root: Path,
    pairs: int,
    seed: int,
    warmup_pairs: int,
    command_argv: Sequence[str] | None = None,
    case: str = "warm_success_cache",
) -> dict[str, Any]:
    """Compare pinned project-command warm-cache or callback-stream calls."""
    validate_comparable_inputs(baseline, overlay)
    if case not in {"warm_success_cache", "stream_callback"}:
        raise ValueError("case must be warm_success_cache or stream_callback")
    if command_argv is None:
        argv = (
            [sys.executable, "-B", "-c", "print('t15-paired-ok')"]
            if case == "warm_success_cache"
            else stream_command_argv()
        )
    else:
        argv = list(command_argv)
    if not argv or any(not isinstance(value, str) or "\x00" in value for value in argv):
        raise ValueError("command argv must contain null-free strings")
    command_config, actual_config_sha256 = project_benchmark_config(argv, case=case)
    if actual_config_sha256 != baseline["config_sha256"]:
        raise ValueError("config_sha256 differs from active project benchmark config")
    if pairs < 2:
        raise ValueError("real paired benchmark requires at least 2 pairs")
    fixture_root = fixture_root.resolve()
    state_root = state_root.resolve()
    fixture_root.mkdir(parents=True, exist_ok=True)
    state_root.mkdir(parents=True, exist_ok=True)
    config_path = fixture_root / ".local-ai.toml"
    if config_path.exists():
        raise FileExistsError(f"refusing to overwrite project benchmark config: {config_path}")
    config_path.write_text(command_config, encoding="utf-8")
    workers: dict[str, subprocess.Popen[str]] = {}
    try:
        workers = {
            "baseline": _start_broker_worker(Path(baseline["source_root"]), fixture_root, state_root / "baseline"),
            "overlay": _start_broker_worker(Path(overlay["source_root"]), fixture_root, state_root / "overlay"),
        }
        seeds: dict[str, Any] = {}
        if case == "warm_success_cache":
            seeds = {
                arm: _broker_measurement(worker, "bench")
                for arm, worker in workers.items()
            }
            if any(result.get("cache_hit") is True for result in seeds.values()):
                raise RuntimeError("initial benchmark cache seed unexpectedly hit cache")

        def measure(arm: str) -> float:
            result = _broker_measurement(
                workers[arm],
                "bench",
                force=case == "stream_callback",
                capture_logs=case == "stream_callback",
            )
            if case == "warm_success_cache" and result.get("cache_hit") is not True:
                raise RuntimeError(f"{arm} warm-cache sample was not a cache hit")
            if case == "stream_callback" and result.get("callback_chunks", 0) < 1:
                raise RuntimeError(f"{arm} callback stream produced no chunks")
            return float(result["elapsed_ms"])

        receipt = measure_paired(
            baseline,
            overlay,
            lambda: measure("baseline"),
            lambda: measure("overlay"),
            pairs=pairs,
            warmups=warmup_pairs,
            seed=seed,
        )
        project_config_sha256 = _file_sha256(config_path)
        if project_config_sha256 != hashlib.sha256(command_config.encode("utf-8")).hexdigest():
            raise RuntimeError("project benchmark config changed during paired benchmark")
        receipt["benchmark_case"] = f"real CommandBroker.run_project_command {case}"
        receipt["environment"] = {
            "python_executable": str(Path(sys.executable).resolve()),
            "python_version": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "logical_cpus": os.cpu_count(),
        }
        receipt["fixture"] = {
            "project_config_sha256": project_config_sha256,
            "argv": argv,
            "expected_stdout": "t15-paired-ok\\n",
            "state_root": str(state_root),
        }
        receipt["cache_seed_results"] = seeds
        receipt["competing_t15_benchmark_gate"] = "exclusive host-local lock held for complete run"
        return receipt
    finally:
        for worker in workers.values():
            if worker.stdin:
                worker.stdin.close()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.terminate()
                worker.wait(timeout=5)


def _run_independent_checkout_case(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    fixture_root: Path,
    state_root: Path,
    pairs: int,
    seed: int,
    warmup_pairs: int,
    case: str,
    command_argv: Sequence[str],
) -> dict[str, Any]:
    if case not in {"cold_first_call", "warm_success_cache"}:
        raise ValueError("case must be cold_first_call or warm_success_cache")
    validate_paired_environment(baseline, current)
    command_config, actual_config_hash = project_benchmark_config(command_argv, case=case)
    if actual_config_hash != baseline["config_sha256"]:
        raise ValueError("config_sha256 differs from active project benchmark config")
    fixture_root = fixture_root.resolve()
    state_root = state_root.resolve()
    fixture_root.mkdir(parents=True, exist_ok=True)
    state_root.mkdir(parents=True, exist_ok=True)
    config_path = fixture_root / ".local-ai.toml"
    if config_path.exists():
        raise FileExistsError(f"refusing to overwrite project benchmark config: {config_path}")
    config_path.write_text(command_config, encoding="utf-8")
    workers: dict[str, subprocess.Popen[str]] = {}
    try:
        workers = {
            "baseline": _start_broker_worker(
                Path(baseline["source_root"]), fixture_root, state_root / "baseline"
            ),
            "current": _start_broker_worker(
                Path(current["source_root"]), fixture_root, state_root / "current"
            ),
        }
        seeds: dict[str, Any] = {}
        if case == "warm_success_cache":
            seeds = {
                arm: _broker_measurement(worker, "bench")
                for arm, worker in workers.items()
            }
            if any(result.get("cache_hit") is True for result in seeds.values()):
                raise RuntimeError("initial warm-cache seed unexpectedly hit cache")

        def measure(arm: str) -> float:
            fresh = case == "cold_first_call"
            result = _broker_measurement(
                workers[arm], "bench", fresh_broker=fresh
            )
            expected_hit = case == "warm_success_cache"
            if result.get("cache_hit") is not expected_hit:
                raise RuntimeError(f"{arm} {case} sample returned wrong cache outcome")
            return float(result["elapsed_ms"])

        receipt = measure_paired_diagnostic(
            baseline,
            current,
            lambda: measure("baseline"),
            lambda: measure("current"),
            pairs=pairs,
            warmups=warmup_pairs,
            seed=seed,
        )
        expected_config_sha256 = hashlib.sha256(command_config.encode("utf-8")).hexdigest()
        project_config_sha256 = _file_sha256(config_path)
        if project_config_sha256 != expected_config_sha256:
            raise RuntimeError("project benchmark config changed during paired benchmark")
        receipt["benchmark_case"] = case
        receipt["correctness"] = {
            "expected_stdout": "t15-paired-ok\\n",
            "cache_seed_results": seeds,
            "sample_cache_state": "fresh broker cache miss" if case == "cold_first_call" else "warm success cache hit",
            "verified_success_samples": (pairs + warmup_pairs) * 2 + len(seeds),
            "all_samples_successful": True,
        }
        receipt["fixture"] = {
            "project_config_sha256": project_config_sha256,
            "command_argv": list(command_argv),
        }
        receipt["environment"] = {
            "python_executable": str(Path(sys.executable).resolve()),
            "python_version": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "logical_cpus": os.cpu_count(),
        }
        return receipt
    finally:
        for worker in workers.values():
            if worker.stdin:
                worker.stdin.close()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.terminate()
                worker.wait(timeout=5)


def run_root_pair_benchmark(
    baseline_root: Path,
    current_root: Path,
    *,
    pairs: int,
    warmup_pairs: int,
    seed: int,
) -> dict[str, Any]:
    """Run source-pinned cold/warm diagnostics across two current checkouts."""
    command_argv = [sys.executable, "-B", "-c", "print('t15-paired-ok')"]
    harness_hash = _file_sha256(Path(__file__).resolve())
    runtime_hash = runtime_fingerprint()["sha256"]
    cases: dict[str, Any] = {}
    with _exclusive_benchmark_lock() as lock_path:
        with tempfile.TemporaryDirectory(prefix="t15-root-pair-") as temp:
            base = Path(temp)
            for offset, case in enumerate(("cold_first_call", "warm_success_cache")):
                _project_config, config_hash = project_benchmark_config(command_argv, case=case)
                shared = {
                    "config_sha256": config_hash,
                    "harness_sha256": harness_hash,
                    "runtime_sha256": runtime_hash,
                }
                baseline = checkout_input(baseline_root, **shared)
                current = checkout_input(current_root, **shared)
                cases[case] = _run_independent_checkout_case(
                    baseline,
                    current,
                    fixture_root=base / case / "project",
                    state_root=base / case / "state",
                    pairs=pairs,
                    seed=seed + offset,
                    warmup_pairs=warmup_pairs,
                    case=case,
                    command_argv=command_argv,
                )
    trusted = all(value["comparison_trusted"] for value in cases.values())
    return {
        "schema": "t15-root-pair-diagnostic-v1",
        "performance_claim": False,
        "comparison_trusted": trusted,
        "comparison_reasons": sorted(
            {reason for value in cases.values() for reason in value["comparison_reasons"]}
        ),
        "source_sha256": {
            "baseline": cases["cold_first_call"]["input_hashes"]["baseline_source_sha256"],
            "current": cases["cold_first_call"]["input_hashes"]["current_source_sha256"],
        },
        "harness_sha256": harness_hash,
        "runtime_sha256": runtime_hash,
        "command_argv": command_argv,
        "pairs_per_case": pairs,
        "warmup_pairs_per_case": warmup_pairs,
        "competing_t15_benchmark_lock": lock_path,
        "cases": cases,
    }


def run_root_overlay_benchmark(
    source_root: Path,
    patch_path: Path,
    *,
    allowed_paths: list[str],
    pairs: int,
    warmup_pairs: int,
    seed: int,
    case: str = "warm_success_cache",
) -> dict[str, Any]:
    if case not in {"warm_success_cache", "stream_callback"}:
        raise ValueError("case must be warm_success_cache or stream_callback")
    command_argv = (
        [sys.executable, "-B", "-c", "print('t15-paired-ok')"]
        if case == "warm_success_cache"
        else stream_command_argv()
    )
    _project_config, config_hash = project_benchmark_config(command_argv, case=case)
    harness_hash = _file_sha256(Path(__file__).resolve())
    runtime_hash = runtime_fingerprint()["sha256"]
    with tempfile.TemporaryDirectory(prefix="t15-paired-overlay-") as temp:
        base = Path(temp)
        baseline = baseline_input(
            source_root,
            config_sha256=config_hash,
            harness_sha256=harness_hash,
            runtime_sha256=runtime_hash,
        )
        overlay = build_overlay(
            source_root,
            patch_path,
            base / "overlay",
            expected_patch_sha256=_file_sha256(patch_path.resolve(strict=True)),
            allowed_paths=allowed_paths,
            config_sha256=config_hash,
            harness_sha256=harness_hash,
            runtime_sha256=runtime_hash,
        )
        with _exclusive_benchmark_lock() as lock_path:
            receipt = run_project_cache_benchmark(
                baseline,
                overlay,
                fixture_root=base / "project",
                state_root=base / "state",
                pairs=pairs,
                seed=seed,
                warmup_pairs=warmup_pairs,
                command_argv=command_argv,
                case=case,
            )
            receipt["competing_t15_benchmark_lock"] = lock_path
            receipt["performance_claim"] = False
            return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source-root", type=Path)
    mode.add_argument("--baseline-root", type=Path)
    parser.add_argument("--current-root", type=Path)
    parser.add_argument("--overlay-patch", type=Path)
    parser.add_argument("--allowed-path", action="append")
    parser.add_argument("--pairs", type=int, default=7)
    parser.add_argument("--warmup-pairs", type=int, default=3)
    parser.add_argument("--seed", type=int, default=1501)
    parser.add_argument(
        "--case", choices=("warm_success_cache", "stream_callback"),
        default="warm_success_cache",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.pairs < 2 or args.warmup_pairs < 0:
        parser.error("--pairs must be at least 2; --warmup-pairs cannot be negative")
    output = args.output.resolve()
    if output.exists():
        parser.error("--output exists; receipts are immutable")
    if args.source_root is not None:
        if args.overlay_patch is None or not args.allowed_path:
            parser.error("overlay mode requires --overlay-patch and at least one --allowed-path")
        source_root = args.source_root.resolve(strict=True)
        if output.is_relative_to(source_root):
            parser.error("--output must be outside source root")
        receipt = run_root_overlay_benchmark(
            source_root,
            args.overlay_patch,
            allowed_paths=args.allowed_path,
            pairs=args.pairs,
            warmup_pairs=args.warmup_pairs,
            seed=args.seed,
            case=args.case,
        )
    else:
        if args.current_root is None or args.overlay_patch is not None or args.allowed_path:
            parser.error("checkout-pair mode requires --current-root and forbids overlay options")
        baseline_root = args.baseline_root.resolve(strict=True)
        current_root = args.current_root.resolve(strict=True)
        if output.is_relative_to(baseline_root) or output.is_relative_to(current_root):
            parser.error("--output must be outside baseline and current roots")
        receipt = run_root_pair_benchmark(
            baseline_root,
            current_root,
            pairs=args.pairs,
            warmup_pairs=args.warmup_pairs,
            seed=args.seed,
        )
    write_receipt(receipt, output)
    receipt_sha256 = _file_sha256(output)
    print(json.dumps({"success": True, "output": str(output), "receipt_sha256": receipt_sha256, "schema": receipt["schema"]}))
    return 0


def measure_paired(
    baseline: dict[str, Any],
    overlay: dict[str, Any],
    measure_baseline: Any,
    measure_overlay: Any,
    *,
    pairs: int,
    seed: int,
    warmups: int = 1,
) -> dict[str, Any]:
    """Measure callbacks returning milliseconds; receipt never claims performance acceptance."""
    validate_comparable_inputs(baseline, overlay)
    _verify_inputs_unchanged(baseline)
    _verify_inputs_unchanged(overlay)
    if not callable(measure_baseline) or not callable(measure_overlay):
        raise ValueError("paired measurements must be callable")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    if pairs < 1 or warmups < 0:
        raise ValueError("pairs must be positive and warmups must be non-negative")

    warmup_orders = _paired_orders(warmups, seed ^ 0x15A5) if warmups else []
    for order in warmup_orders:
        for arm in order:
            value = float(measure_baseline() if arm == "baseline" else measure_overlay())
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid {arm} warmup measurement")

    orders = _paired_orders(pairs, seed)
    rows: list[dict[str, Any]] = []
    baseline_samples: list[float] = []
    overlay_samples: list[float] = []
    for index, order in enumerate(orders, 1):
        row: dict[str, Any] = {"index": index, "order": "_then_".join(order)}
        for arm in order:
            value = float(measure_baseline() if arm == "baseline" else measure_overlay())
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid {arm} measurement")
            row[f"{arm}_ms"] = value
            if arm == "baseline":
                baseline_samples.append(value)
            else:
                overlay_samples.append(value)
        rows.append(row)

    _verify_inputs_unchanged(baseline)
    _verify_inputs_unchanged(overlay)

    base_median = statistics.median(baseline_samples)
    overlay_median = statistics.median(overlay_samples)
    delta = ((overlay_median / base_median) - 1) * 100 if base_median else None
    return {
        "schema": _SCHEMA,
        "performance_claim": False,
        "input_hashes": {
            "base_source_sha256": baseline["source_sha256"],
            "overlay_source_sha256": overlay["source_sha256"],
            "overlay_patch_sha256": overlay["overlay_patch_sha256"],
            **{field: baseline[field] for field in _SHARED_HASH_FIELDS},
        },
        "source_roots": {
            "baseline": baseline["source_root"],
            "overlay": overlay["source_root"],
        },
        "order_seed": seed,
        "warmup_pairs": warmups,
        "warmup_orders": ["_then_".join(order) for order in warmup_orders],
        "paired_runs": pairs,
        "order_counts": {
            "baseline_then_overlay": sum(row["order"] == "baseline_then_overlay" for row in rows),
            "overlay_then_baseline": sum(row["order"] == "overlay_then_baseline" for row in rows),
        },
        "raw_pairs": rows,
        "baseline_ms": _summary(baseline_samples),
        "overlay_ms": _summary(overlay_samples),
        "overlay_delta_percent": round(delta, 3) if delta is not None else None,
    }


def measure_paired_diagnostic(
    baseline: dict[str, Any],
    current: dict[str, Any],
    measure_baseline: Any,
    measure_current: Any,
    *,
    pairs: int,
    seed: int,
    warmups: int = 1,
) -> dict[str, Any]:
    """Measure current checkouts; source mismatch always keeps claim disabled."""
    validate_paired_environment(baseline, current)
    _verify_inputs_unchanged(baseline)
    _verify_inputs_unchanged(current)
    if not callable(measure_baseline) or not callable(measure_current):
        raise ValueError("paired measurements must be callable")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    if pairs < 1 or warmups < 0:
        raise ValueError("pairs must be positive and warmups must be non-negative")

    reasons = []
    if baseline["source_sha256"] != current["source_sha256"]:
        reasons.append("source hashes differ")
    trusted = not reasons
    warmup_orders = _paired_orders(warmups, seed ^ 0x15A5) if warmups else []
    for order in warmup_orders:
        for arm in order:
            value = float(measure_baseline() if arm == "baseline" else measure_current())
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid {arm} warmup measurement")

    orders = _paired_orders(pairs, seed)
    rows: list[dict[str, Any]] = []
    baseline_samples: list[float] = []
    current_samples: list[float] = []
    for index, order in enumerate(orders, 1):
        row: dict[str, Any] = {"index": index, "order": "_then_".join(order)}
        for arm in order:
            value = float(measure_baseline() if arm == "baseline" else measure_current())
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid {arm} measurement")
            row[f"{arm}_ms"] = value
            (baseline_samples if arm == "baseline" else current_samples).append(value)
        rows.append(row)

    _verify_inputs_unchanged(baseline)
    _verify_inputs_unchanged(current)
    base_median = statistics.median(baseline_samples)
    current_median = statistics.median(current_samples)
    return {
        "schema": _SCHEMA,
        "performance_claim": False,
        "comparison_trusted": trusted,
        "comparison_reasons": reasons,
        "input_hashes": {
            "baseline_source_sha256": baseline["source_sha256"],
            "current_source_sha256": current["source_sha256"],
            **{field: baseline[field] for field in _SHARED_HASH_FIELDS},
        },
        "source_roots": {
            "baseline": baseline["source_root"],
            "current": current["source_root"],
        },
        "order_seed": seed,
        "warmup_pairs": warmups,
        "warmup_orders": ["_then_".join(order) for order in warmup_orders],
        "paired_runs": pairs,
        "order_counts": {
            "baseline_then_current": sum(row["order"] == "baseline_then_current" for row in rows),
            "current_then_baseline": sum(row["order"] == "current_then_baseline" for row in rows),
        },
        "raw_pairs": rows,
        "baseline_ms": _summary(baseline_samples),
        "current_ms": _summary(current_samples),
        "current_delta_percent": round((current_median / base_median - 1) * 100, 3)
        if base_median
        else None,
    }


def write_receipt(receipt: dict[str, Any], output: Path) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    except FileExistsError as exc:
        raise FileExistsError(f"refusing to overwrite receipt: {output}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
