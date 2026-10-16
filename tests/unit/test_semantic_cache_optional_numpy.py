from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_without_numpy(project_root: Path, state_dir: Path, operation: str) -> subprocess.CompletedProcess[str]:
    script = f"""
import sys

sys.modules["numpy"] = None
import local_ai_hub.services
from local_ai_hub import semantic_cache
assert semantic_cache._NUMPY_CHECKED is False
assert semantic_cache._load_numpy() is None

cache = semantic_cache.SemanticGenerationCache(
    {{"server": {{"state_dir": sys.argv[1]}}}}, embeddings=None,
)
if {operation!r} == "write":
    cache.set("scope", "reusable exact query", {{"answer": "cached"}})
else:
    assert cache.get("scope", "reusable exact query") == ({{"answer": "cached"}}, 1.0)
"""
    env = os.environ.copy()
    src_path = str(project_root / "src")
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (src_path, env.get("PYTHONPATH", "")) if value
    )
    return subprocess.run(
        [sys.executable, "-c", script, str(state_dir)],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_exact_cache_persists_across_processes_without_optional_numpy(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    write_result = _run_without_numpy(project_root, tmp_path, "write")
    assert write_result.returncode == 0, write_result.stderr or write_result.stdout

    read_result = _run_without_numpy(project_root, tmp_path, "read")
    assert read_result.returncode == 0, read_result.stderr or read_result.stdout


def test_vector_similarity_uses_lazily_loaded_numpy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    numpy = pytest.importorskip("numpy")
    from local_ai_hub import semantic_cache

    class Embeddings:
        def encode(self, texts: list[str], *, query: bool) -> dict[str, object]:
            return {"success": True, "embeddings": [[1.0, 0.0] for _ in texts]}

    monkeypatch.setattr(semantic_cache, "_load_numpy", lambda: numpy)
    cache = semantic_cache.SemanticGenerationCache(
        {"server": {"state_dir": str(tmp_path)}}, embeddings=Embeddings(),
    )
    cache.set("scope", "stored base query", {"answer": "similar"})

    value, score = cache.get("scope", "different retrieval query")

    assert value == {"answer": "similar"}
    assert score >= cache.threshold


@pytest.mark.parametrize("failure", [RuntimeError("encoder unavailable"), {"success": True, "embeddings": [[object()]]}])
def test_embedding_failures_disable_optional_cache_operation(tmp_path: Path, failure: object) -> None:
    from local_ai_hub.semantic_cache import SemanticGenerationCache

    class Embeddings:
        def encode(self, texts: list[str], *, query: bool) -> object:
            if isinstance(failure, Exception):
                raise failure
            return failure

    cache = SemanticGenerationCache(
        {"server": {"state_dir": str(tmp_path)}}, embeddings=Embeddings(),
    )

    assert cache._vector("embedding failure query") is None
