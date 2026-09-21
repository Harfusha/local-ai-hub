from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
import tempfile
import time
from array import array
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "experiments" / "cython_simhash_votes.pyx"


def _python_votes(hashes: array) -> int:
    votes = [0] * 64
    for value in hashes:
        for bit in range(64):
            votes[bit] += 1 if value & (1 << bit) else -1
    return sum(1 << bit for bit, vote in enumerate(votes) if vote > 0)


def _build_extension(work_dir: Path):
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
    command.inplace = True
    distribution.run_command("build_ext")
    sys.path.insert(0, str(work_dir))
    return importlib.import_module("cython_simhash_votes")


def run(iterations: int = 20, hash_count: int = 20000) -> dict[str, object]:
    hashes = array(
        "Q",
        (
            int(hashlib.md5(f"shingle-{index % 4096}".encode(), usedforsecurity=False).hexdigest()[:16], 16)
            for index in range(hash_count)
        ),
    )
    expected = _python_votes(hashes)
    with tempfile.TemporaryDirectory(prefix="local-ai-cython-") as temp:
        module = _build_extension(Path(temp))
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

    return {
        "success": True,
        "kernel": "simhash_votes",
        "hash_count": hash_count,
        "iterations": iterations,
        "python_ms": round(python_ms, 3),
        "cython_ms": round(cython_ms, 3),
        "speedup": round(python_ms / max(cython_ms, 0.001), 3),
        "production_enabled": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and benchmark the optional Cython SimHash kernel")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--hash-count", type=int, default=20000)
    args = parser.parse_args(argv)
    print(json.dumps(run(max(1, min(args.iterations, 200)), max(64, min(args.hash_count, 200000))), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
