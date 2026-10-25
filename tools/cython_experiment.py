from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import platform
import random
import re
import sys
import tempfile
import time
from array import array
from pathlib import Path
from contextlib import nullcontext
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "experiments" / "cython_simhash_votes.pyx"


def _python_votes(hashes: array) -> int:
    votes = [0] * 64
    for value in hashes:
        for bit in range(64):
            votes[bit] += 1 if value & (1 << bit) else -1
    return sum(1 << bit for bit, vote in enumerate(votes) if vote > 0)


def _build_extension(work_dir: Path):
    work_dir = work_dir.resolve()
    if work_dir.is_relative_to(ROOT.resolve()):
        raise ValueError("Cython build directory must be outside the checkout")
    if "cython_simhash_votes" in sys.modules:
        raise RuntimeError("Cython experiment requires a fresh process")
    work_dir.mkdir(parents=True, exist_ok=True)
    from Cython.Build import cythonize
    from setuptools import Distribution, Extension

    extension = cythonize(
        [Extension("cython_simhash_votes", [str(SOURCE)])],
        build_dir=str(work_dir / "cython-build"),
        compiler_directives={"language_level": "3"},
    )
    distribution = Distribution({"name": "local-ai-hub-cython-experiment", "ext_modules": extension})
    command = distribution.get_command_obj("build_ext")
    command.build_lib = str(work_dir)
    command.build_temp = str(work_dir / "native-build")
    command.inplace = False
    distribution.run_command("build_ext")
    original_path = list(sys.path)
    try:
        sys.path.insert(0, str(work_dir))
        module = importlib.import_module("cython_simhash_votes")
        binary = Path(module.__file__).resolve(strict=True)
        if not binary.is_relative_to(work_dir) or binary.suffix.lower() not in {".pyd", ".so"}:
            raise RuntimeError("Cython import did not load the owned external extension")
        compiler = getattr(command, "compiler", None)
        module.__build_provenance__ = {
            "compiler_class": type(compiler).__name__ if compiler is not None else None,
            "compiler": getattr(compiler, "cc", None),
            "linker": getattr(compiler, "linker", None),
            "include_dirs": getattr(compiler, "include_dirs", None),
            "library_dirs": getattr(compiler, "library_dirs", None),
        }
        return module
    finally:
        sys.path[:] = original_path


def _native_simhash(text: str, module) -> int:
    """Experiment-only adapter; retain production normalization and shingle hashes."""
    from local_ai_hub.rag import _simhash_shingle_hash

    clean = re.sub(r"\s+", " ", text.lower().strip())
    shingles = ([clean] if clean else []) if len(clean) < 4 else (
        clean[index:index + 4] for index in range(len(clean) - 3)
    )
    return int(module.simhash_votes(array("Q", (_simhash_shingle_hash(item) for item in shingles))))


def _check_parity(module) -> dict[str, int]:
    import local_ai_hub.rag as production
    from local_ai_hub.rag import _simhash

    if Path(production.__file__).resolve() != (ROOT / "src/local_ai_hub/rag.py").resolve():
        raise RuntimeError("Cython comparison requires the current checkout production module")

    random_source = random.Random(20261025)
    vectors = [[], [0], [2**64 - 1], [0, 2**64 - 1], [1, 2], [2**63] * 5]
    vectors += [[random_source.getrandbits(64) for _ in range(size)] for size in (1, 2, 63, 64, 257)]
    for values in vectors:
        buffer = array("Q", values)
        if int(module.simhash_votes(buffer)) != _python_votes(buffer):
            raise RuntimeError("Cython uint64 parity failed")
    texts = ["", "a", "ABC", " Žluťoučký\tKŮŇ\n", "aaaa" * 1024, "🙂漢字" * 13]
    texts += ["".join(random_source.choices("abCD ž漢🙂\t\n", k=size)) for size in (1, 3, 4, 64, 1024)]
    for text in texts:
        if _native_simhash(text, module) != _simhash(text):
            raise RuntimeError("Cython current-production text parity failed")
    return {"uint64_cases": len(vectors), "production_text_cases": len(texts)}


def _generate_synthetic_chunks(count: int) -> list[str]:
    rnd = random.Random(20261025)
    templates = [
        "def process_record_{i}(data: dict[str, int]) -> bool:\n    # validate data payload\n    value = data.get('key_{k}', {val})\n    return value > 0 and len(data) < {limit}\n",
        "class ModelConfig_{i}:\n    # Configuration block {i} for indexing candidate\n    dimension: int = {dim}\n    context_window: int = {ctx}\n    batch_size: int = {batch}\n",
        "async def handle_request_{i}(session_id: str, payload: bytes) -> dict[str, str]:\n    # ensure security and bounds\n    token = hashlib.sha256(payload).hexdigest()\n    return {{'status': 'ok', 'token': token, 'session': session_id}}\n",
        "# Implementation detail for chunk {i}\n# This block verifies hash alignment across systems.\nCONST_{i} = 0x{hex_val}\n",
    ]
    chunks = []
    base_pool = []
    for i in range(count):
        if base_pool and rnd.random() < 0.05:
            base = rnd.choice(base_pool)
            chunks.append(base + f"\n    # near-duplicate revision {i}\n")
        else:
            tmpl = templates[i % len(templates)]
            chunk = tmpl.format(
                i=i, k=i % 16, val=i * 7, limit=100 + (i % 50),
                dim=256 + (i % 8) * 64, ctx=4096 * (1 + (i % 4)), batch=16 * (1 + (i % 8)),
                hex_val=f"{i * 31337:08x}",
            )
            chunk = chunk * (1 + (i % 3))
            chunks.append(chunk)
            if len(base_pool) < 200:
                base_pool.append(chunk)
    return chunks


def _measure_indexing_workflow(module, chunk_counts: tuple[int, ...]) -> list[dict[str, Any]]:
    from local_ai_hub.rag import _simhash, _simhash_shingle_hash, _fragment_hash

    results = []
    for count in chunk_counts:
        chunks = _generate_synthetic_chunks(count)
        for regime in ("cold", "warm"):
            if regime == "cold":
                _simhash_shingle_hash.cache_clear()

            seen_py: list[int] = []
            records_py: list[tuple[str, int]] = []
            near_dup_py = 0
            sh_wall_py = 0.0
            sh_cpu_py = 0.0
            wf_wall_start, wf_cpu_start = time.perf_counter(), time.process_time()
            for chunk in chunks:
                t0, c0 = time.perf_counter(), time.process_time()
                fp = _simhash(chunk)
                sh_wall_py += (time.perf_counter() - t0)
                sh_cpu_py += (time.process_time() - c0)
                if fp != 0 and any((fp ^ s_fp).bit_count() <= 4 for s_fp in seen_py):
                    near_dup_py += 1
                    continue
                if fp != 0:
                    seen_py.append(fp)
                records_py.append((_fragment_hash(chunk), len(chunk)))
            wf_wall_py = (time.perf_counter() - wf_wall_start) * 1000.0
            wf_cpu_py = (time.process_time() - wf_cpu_start) * 1000.0
            sh_wall_py *= 1000.0
            sh_cpu_py *= 1000.0

            if regime == "cold":
                _simhash_shingle_hash.cache_clear()

            seen_native: list[int] = []
            records_native: list[tuple[str, int]] = []
            near_dup_native = 0
            sh_wall_native = 0.0
            sh_cpu_native = 0.0
            wf_wall_start, wf_cpu_start = time.perf_counter(), time.process_time()
            for chunk in chunks:
                t0, c0 = time.perf_counter(), time.process_time()
                fp = _native_simhash(chunk, module)
                sh_wall_native += (time.perf_counter() - t0)
                sh_cpu_native += (time.process_time() - c0)
                if fp != 0 and any((fp ^ s_fp).bit_count() <= 4 for s_fp in seen_native):
                    near_dup_native += 1
                    continue
                if fp != 0:
                    seen_native.append(fp)
                records_native.append((_fragment_hash(chunk), len(chunk)))
            wf_wall_native = (time.perf_counter() - wf_wall_start) * 1000.0
            wf_cpu_native = (time.process_time() - wf_cpu_start) * 1000.0
            sh_wall_native *= 1000.0
            sh_cpu_native *= 1000.0

            if seen_py != seen_native:
                raise RuntimeError(f"SimHash fingerprints mismatch at chunk count {count} ({regime})")
            if near_dup_py != near_dup_native or records_py != records_native:
                raise RuntimeError(f"Deduplicated records mismatch at chunk count {count} ({regime})")

            sh_speedup = round(sh_wall_py / max(sh_wall_native, 0.001), 3)
            wall_reduction = round((wf_wall_py - wf_wall_native) / max(wf_wall_py, 0.001) * 100.0, 2)
            cpu_reduction = round((wf_cpu_py - wf_cpu_native) / max(wf_cpu_py, 0.001) * 100.0, 2)
            sh_fraction = round(sh_wall_py / max(wf_wall_py, 0.001) * 100.0, 2)

            results.append({
                "chunk_count": count,
                "regime": regime,
                "chunks_processed": len(chunks),
                "near_duplicates_skipped": near_dup_py,
                "records_indexed": len(records_py),
                "python_simhash_wall_ms": round(sh_wall_py, 2),
                "native_simhash_wall_ms": round(sh_wall_native, 2),
                "simhash_speedup": sh_speedup,
                "python_workflow_wall_ms": round(wf_wall_py, 2),
                "native_workflow_wall_ms": round(wf_wall_native, 2),
                "workflow_wall_reduction_pct": wall_reduction,
                "workflow_cpu_reduction_pct": cpu_reduction,
                "simhash_share_of_workflow_pct": sh_fraction,
                "kernel_gate_met": sh_speedup >= 3.0,
                "workflow_gate_met": wall_reduction >= 15.0 or cpu_reduction >= 20.0,
            })
    return results

def run(iterations: int = 20, hash_count: int = 20000, *, chunk_counts: tuple[int, ...] = (1000, 10000), work_dir: Path | None = None) -> dict[str, object]:
    if type(iterations) is not int or not 1 <= iterations <= 200:
        raise ValueError("iterations must be between 1 and 200")
    if type(hash_count) is not int or not 64 <= hash_count <= 200000:
        raise ValueError("hash_count must be between 64 and 200000")
    hashes = array(
        "Q",
        (
            int(hashlib.md5(f"shingle-{index % 4096}".encode(), usedforsecurity=False).hexdigest()[:16], 16)
            for index in range(hash_count)
        ),
    )
    expected = _python_votes(hashes)
    context = tempfile.TemporaryDirectory(prefix="local-ai-cython-") if work_dir is None else nullcontext(str(work_dir))
    with context as temp:
        module = _build_extension(Path(temp))
        parity = _check_parity(module)
        invalid_buffers = [array("I", [1, 2]), memoryview(array("Q", [1, 2, 3, 4]))[::2],
                           memoryview(array("Q", [1, 2, 3, 4])).cast("B").cast("Q", shape=[2, 2])]
        for invalid in invalid_buffers:
            try:
                module.simhash_votes(invalid)
            except (TypeError, ValueError, BufferError):
                continue
            raise RuntimeError("Cython accepted an invalid buffer format, stride or shape")
        parity["invalid_buffers_rejected"] = len(invalid_buffers)
        actual = int(module.simhash_votes(hashes))
        if actual != expected:
            raise RuntimeError(f"Cython result mismatch: {actual} != {expected}")

        started = time.perf_counter()
        for _ in range(iterations):
            _python_votes(hashes)
        python_ms = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        for _ in range(iterations):
            module.simhash_votes(hashes)
        cython_ms = (time.perf_counter() - started) * 1000.0

        from local_ai_hub.rag import _simhash, _simhash_shingle_hash
        text = "class Example: value = 'Žluťoučký kůň'\n" * 110
        samples = []
        for index in range(iterations):
            pair = {}
            order = (("production", _simhash), ("native_adapter", lambda item: _native_simhash(item, module)))
            for name, function in order if index % 2 == 0 else reversed(order):
                _simhash_shingle_hash.cache_clear()
                wall_start, cpu_start = time.perf_counter(), time.process_time()
                value = function(text)
                pair[name] = {"wall_ms": (time.perf_counter() - wall_start) * 1000.0,
                              "cpu_ms": (time.process_time() - cpu_start) * 1000.0, "value": value}
            if pair["production"]["value"] != pair["native_adapter"]["value"]:
                raise RuntimeError("Cython measured production parity failed")
            samples.append(pair)
        indexing_workflow = _measure_indexing_workflow(module, chunk_counts)
        kernel_gate_met = all(s["kernel_gate_met"] for s in indexing_workflow) if indexing_workflow else False
        workflow_gate_met = any(s["workflow_gate_met"] for s in indexing_workflow) if indexing_workflow else False
        overall_adoption_recommended = bool(kernel_gate_met and workflow_gate_met)
        recommendation_reason = (
            "Both kernel and whole-workflow threshold met"
            if overall_adoption_recommended
            else "Kernel speedup or whole-workflow gain below threshold; retain Python reference"
        )
        binary = Path(module.__file__).resolve(strict=True)
        provenance = {"binary_path": str(binary), "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                      "cython_source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                      "production_source_sha256": hashlib.sha256((ROOT / "src/local_ai_hub/rag.py").read_bytes()).hexdigest(),
                      "build": module.__build_provenance__,
                      "python": sys.executable, "python_version": sys.version, "machine": platform.machine()}

    return {
        "success": True,
        "kernel": "simhash_votes",
        "hash_count": hash_count,
        "iterations": iterations,
        "python_ms": round(python_ms, 3),
        "cython_ms": round(cython_ms, 3),
        "reference_votes_speedup": round(python_ms / max(cython_ms, 0.001), 3),
        "reference_is_current_production": False,
        "parity": parity,
        "current_production_adapter_samples": samples,
        "cache_regime": "shingle_hash_cache_cleared_before_each_arm",
        "os_cache_cleared": False,
        "whole_workflow_measured": True,
        "indexing_workflow": indexing_workflow,
        "kernel_gate_met": kernel_gate_met,
        "workflow_gate_met": workflow_gate_met,
        "overall_adoption_recommended": overall_adoption_recommended,
        "recommendation_reason": recommendation_reason,
        "provenance": provenance,
        "production_enabled": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and benchmark the optional Cython SimHash kernel")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--hash-count", type=int, default=20000)
    parser.add_argument("--chunk-counts", nargs="*", type=int, default=[1000, 10000], help="synthetic chunk counts to measure in the indexing workflow")
    parser.add_argument("--work-dir", type=Path, help="owned external directory; retain native binary evidence")
    parser.add_argument("--output", type=Path, help="persist actual success or failure outside the checkout")
    args = parser.parse_args(argv)
    if args.output is not None and args.output.resolve().is_relative_to(ROOT.resolve()):
        parser.error("experiment output must be outside the checkout")
    try:
        result = run(args.iterations, args.hash_count, chunk_counts=tuple(args.chunk_counts or ()), work_dir=args.work_dir)
    except Exception as exc:
        result = {"success": False, "status": "failed", "error_type": type(exc).__name__,
                  "error": str(exc)[:2000], "production_enabled": False,
                  "parity": None, "whole_workflow_measured": False}
    serialized = json.dumps(result, separators=(",", ":"))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if result["success"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
