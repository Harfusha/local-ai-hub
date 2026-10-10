"""Freeze T02's synthetic workload contract and emit bounded run commands."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


CANDIDATE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = CANDIDATE_ROOT
PINNED_ROOT_HEAD = "98a9a1a7611af574caf20a88620c4aa3eb2e918a"
PINNED_CANDIDATE_HEAD = "a7b0868ac964fd14e160001024e6e0ecaaf4e9db"
GENERATOR_NAMES = {"_synthetic_query_symbol", "_synthetic_source", "_build_synthetic_repo"}
IMPLEMENTATION_PATHS = (
    "src/local_ai_hub/app.py",
    "src/local_ai_hub/http_server.py",
    "src/local_ai_hub/services.py",
    "src/local_ai_hub/code_index.py",
    "src/local_ai_hub/rag.py",
    "src/local_ai_hub/async_jobs.py",
    "src/local_ai_hub/repo_tools.py",
    "src/local_ai_hub/benchmark.py",
    "tools/benchmark_surfaces.py",
)
FILE_COUNTS = (100, 10_000, 100_000)
RAG_COUNTS = (10_000, 100_000)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def _head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _source_identity(root: Path) -> dict[str, Any]:
    path = root / "tools" / "benchmark_surfaces.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    functions: dict[str, str] = {}
    max_repetitions: int | None = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in GENERATOR_NAMES:
            segment = ast.get_source_segment(source, node)
            if segment is not None:
                functions[node.name] = segment
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_MAX_REPETITIONS" for target in node.targets
        ):
            max_repetitions = ast.literal_eval(node.value)
    if set(functions) != GENERATOR_NAMES or max_repetitions is None:
        raise ValueError(f"synthetic corpus generator contract missing in {root}")
    generator = {"max_repetitions": max_repetitions, "functions": functions}
    canonical = json.dumps(generator, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    implementation_digest = hashlib.sha256()
    implementation_files: dict[str, str] = {}
    for relative in IMPLEMENTATION_PATHS:
        source_path = root / relative
        implementation_digest.update(Path(relative).name.encode("utf-8"))
        implementation_digest.update(b"\0")
        try:
            payload = source_path.read_bytes()
        except OSError:
            implementation_files[relative] = "unavailable"
            implementation_digest.update(b"unavailable")
        else:
            file_digest = hashlib.sha256(payload).digest()
            implementation_files[relative] = file_digest.hex().upper()
            implementation_digest.update(file_digest)
    return {
        "benchmark_path": str(path),
        "benchmark_sha256": _sha256(path.read_bytes()),
        "generator_sha256": _sha256(canonical.encode("utf-8")),
        "max_repetitions": max_repetitions,
        "implementation_fingerprint": implementation_digest.hexdigest(),
        "implementation_file_sha256": implementation_files,
    }


def _case_id(generator_sha256: str, file_count: int, rag_chunks: int) -> str:
    identity = {
        "schema": "t02-frozen-synthetic-corpus/v1",
        "generator_sha256": generator_sha256,
        "repository_file_count": file_count,
        "rag_chunk_count": rag_chunks,
        "embedding_identity": "not_applicable_model_free_keyword_fixture",
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return _sha256(canonical.encode("utf-8"))


def _commands() -> dict[str, list[str]]:
    common = [
        "C:\\Python313\\python.exe", "-B", "tools/benchmark_surfaces.py",
        "--state-dir", "<ARM_STATE_DIR>", "--scratch-dir", "<ARM_SCRATCH_DIR>",
        "--full-matrix", "--light-repetitions", "1000",
        "--comparison-repetitions", "30", "--concurrency", "1", "4", "16", "32",
        "--timeout-seconds", "3600",
    ]
    return {
        "root_baseline": common,
        "candidate_comparison": [*common, "--compare-with", "<ROOT_MATRIX_RECORD_PATH>"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--candidate", type=Path, default=CANDIDATE_ROOT)
    args = parser.parse_args()
    root, candidate = args.root.resolve(), args.candidate.resolve()
    root_head, candidate_head = _head(root), _head(candidate)
    if root_head != PINNED_ROOT_HEAD:
        raise ValueError(f"root HEAD drift: expected {PINNED_ROOT_HEAD}, got {root_head}")
    if candidate_head != PINNED_CANDIDATE_HEAD:
        raise ValueError(f"candidate HEAD drift: expected {PINNED_CANDIDATE_HEAD}, got {candidate_head}")
    root_source, candidate_source = _source_identity(root), _source_identity(candidate)
    if root_source["generator_sha256"] != candidate_source["generator_sha256"]:
        raise ValueError("root/candidate synthetic corpus generator differs; paired workload is not frozen")

    generator_sha256 = str(root_source["generator_sha256"])
    cases = [
        {
            "repository_files": file_count,
            "rag_chunks": rag_chunks,
            "corpus_id_sha256": _case_id(generator_sha256, file_count, rag_chunks),
        }
        for file_count in FILE_COUNTS
        for rag_chunks in RAG_COUNTS
    ]
    print(json.dumps({
        "schema_version": "t02-artifact-matrix-preflight/v1",
        "status": "ready_for_t20_slot",
        "root": {"path": str(root), "head": root_head, **root_source},
        "candidate": {"path": str(candidate), "head": candidate_head, **candidate_source},
        "frozen_workload": {
            "generator_sha256": generator_sha256,
            "embedding_identity": "not_applicable_model_free_keyword_fixture",
            "cases": cases,
        },
        "sampling": {
            "light_repetitions": 1000,
            "comparison_repetitions": 30,
            "concurrency": [1, 4, 16, 32],
            "inference": False,
            "case_execution": "full six-case matrix per arm; re-run two light cases at plan-grade sample counts",
        },
        "commands": _commands(),
        "comparison_contract": {
            "must_match": ["benchmark_scope", "workload_fingerprint", "config_fingerprint", "hardware_fingerprint"],
            "expected_to_differ": ["revision", "implementation_fingerprint"],
            "artifact_outputs": ["raw stdout JSON", "stderr log", "six per-case JSON files", "matrix JSON", "SHA-256 manifest"],
            "embedding_digest": "not_applicable; no model inference or embedded vectors in T02 synthetic fixture",
            "model_free_limit": "Both matrices will remain non-plan-grade; compare_matrix_records reports inconclusive until model-dependent goldens exist.",
        },
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise SystemExit(f"T02 preflight blocked: {exc}") from exc
