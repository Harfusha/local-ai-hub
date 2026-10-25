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


def run(iterations: int = 20, hash_count: int = 20000, *, work_dir: Path | None = None) -> dict[str, object]:
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
        "whole_workflow_measured": False,
        "provenance": provenance,
        "production_enabled": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and benchmark the optional Cython SimHash kernel")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--hash-count", type=int, default=20000)
    parser.add_argument("--work-dir", type=Path, help="owned external directory; retain native binary evidence")
    parser.add_argument("--output", type=Path, help="persist actual success or failure outside the checkout")
    args = parser.parse_args(argv)
    if args.output is not None and args.output.resolve().is_relative_to(ROOT.resolve()):
        parser.error("experiment output must be outside the checkout")
    try:
        result = run(args.iterations, args.hash_count, work_dir=args.work_dir)
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
