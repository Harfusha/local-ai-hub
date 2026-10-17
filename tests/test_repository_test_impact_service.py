from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from local_ai_hub.repository_test_impact import RepositoryTestImpactService
from local_ai_hub.services import LocalAIServices


class _Engine:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def test_matrix(self, root: str) -> dict[str, Any]:
        self.calls.append(("test_matrix", root))
        return {"success": True, "test_files": ["tests/test_math.py"]}

    def affected_tests(
        self, root: str, changed_paths: list[str] | None, base: str
    ) -> dict[str, Any]:
        self.calls.append(("affected_tests", root, changed_paths, base))
        return {
            "success": True,
            "test_files": ["tests/test_math.py"],
            "suggested_command": "pytest tests/test_math.py",
        }


def _runner(calls: list[tuple[Any, ...]]):
    def run(operation: str, root: str, params: dict[str, Any], compute: Any):
        calls.append((operation, root, params))
        result = compute()
        return {**result, "preprocessed_hit": True, "workspace_cache": {"fingerprint": "rev-1"}}

    return run


class _RepositoryCache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def get_or_compute(self, key: str, compute: Any):
        if key in self.values:
            return self.values[key], True, False
        value = compute()
        self.values[key] = value
        return value, False, False


def test_test_matrix_adapter_preserves_cached_service_result() -> None:
    engine = _Engine()
    operation_calls: list[tuple[Any, ...]] = []
    service = RepositoryTestImpactService(engine, _runner(operation_calls))

    result = service.test_matrix("repo")

    assert result == {
        "success": True,
        "test_files": ["tests/test_math.py"],
        "preprocessed_hit": True,
        "workspace_cache": {"fingerprint": "rev-1"},
    }
    assert operation_calls == [("test-matrix", "repo", {})]
    assert engine.calls == [("test_matrix", "repo")]


def test_local_ai_services_test_matrix_facade_keeps_signature_and_result() -> None:
    engine = _Engine()
    operation_calls: list[tuple[Any, ...]] = []
    services = LocalAIServices.__new__(LocalAIServices)
    services.deterministic = engine
    services.deterministic_operation = _runner(operation_calls)

    result = services.test_matrix("repo")

    assert tuple(inspect.signature(LocalAIServices.test_matrix).parameters) == (
        "self",
        "root",
    )
    assert result == {
        "success": True,
        "test_files": ["tests/test_math.py"],
        "preprocessed_hit": True,
        "workspace_cache": {"fingerprint": "rev-1"},
    }
    assert operation_calls == [("test-matrix", "repo", {})]


def test_cold_warm_cache_preserves_both_engine_call_counts(tmp_path: Path) -> None:
    engine = _Engine()
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {}
    services.deterministic = engine
    services.repo_flight = _RepositoryCache()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {
        "fingerprint": "rev-1",
        "kind": "git",
    }

    root = tmp_path / "repo"
    root.mkdir()

    cold = services.test_matrix(str(root))
    warm = services.test_matrix(str(root))

    assert cold["cache_hit"] is False
    assert warm["cache_hit"] is True
    assert cold["test_files"] == warm["test_files"]

    affected_cold = services.affected_tests(str(root), ["src/math.py"], "HEAD")
    affected_warm = services.affected_tests(str(root), ["src/math.py"], "HEAD")

    assert affected_cold["cache_hit"] is False
    assert affected_warm["cache_hit"] is True
    assert affected_cold["test_files"] == affected_warm["test_files"]
    assert affected_cold["suggested_command"] == affected_warm["suggested_command"]
    assert engine.calls == [
        ("test_matrix", str(root)),
        ("affected_tests", str(root), ["src/math.py"], "HEAD"),
    ]


def test_affected_tests_adapter_preserves_params_and_cached_result() -> None:
    engine = _Engine()
    operation_calls: list[tuple[Any, ...]] = []
    service = RepositoryTestImpactService(engine, _runner(operation_calls))
    params = {
        "changed_paths": ["src/math.py"],
        "base": "origin/main",
        "project_config_digest": "cfg-1",
        "path_hints_digest": "hints-1",
    }

    result = service.affected_tests(
        "repo", ["src/math.py"], "origin/main", params
    )

    assert result == {
        "success": True,
        "test_files": ["tests/test_math.py"],
        "suggested_command": "pytest tests/test_math.py",
        "preprocessed_hit": True,
        "workspace_cache": {"fingerprint": "rev-1"},
    }
    assert operation_calls == [("affected-tests", "repo", params)]
    assert engine.calls == [("affected_tests", "repo", ["src/math.py"], "origin/main")]
