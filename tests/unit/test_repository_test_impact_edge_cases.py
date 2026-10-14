from __future__ import annotations

from pathlib import Path
from typing import Any
import pytest

from local_ai_hub.repository_test_impact import RepositoryTestImpactService


class _DummyEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def test_matrix(self, root: str) -> dict[str, Any]:
        self.calls.append(("test_matrix", root))
        return {"success": True, "test_files": ["tests/test_a.py"]}

    def affected_tests(
        self, root: str, changed_paths: list[str] | None, base: str
    ) -> dict[str, Any]:
        self.calls.append(("affected_tests", root, changed_paths, base))
        return {"success": True, "test_files": ["tests/test_b.py"]}


def _dummy_runner(calls: list[tuple[Any, ...]]):
    def run(operation: str, root: str, params: dict[str, Any], compute: Any):
        calls.append((operation, root, params))
        return compute()
    return run


def test_init_rejects_none_engine_or_non_callable_runner() -> None:
    engine = _DummyEngine()
    calls: list[tuple[Any, ...]] = []
    runner = _dummy_runner(calls)

    with pytest.raises(ValueError, match="engine cannot be None"):
        RepositoryTestImpactService(None, runner)

    with pytest.raises(TypeError, match="operation_runner must be callable"):
        RepositoryTestImpactService(engine, "not-a-callable")  # type: ignore[arg-type]


def test_root_validation_and_path_support(tmp_path: Path) -> None:
    engine = _DummyEngine()
    calls: list[tuple[Any, ...]] = []
    service = RepositoryTestImpactService(engine, _dummy_runner(calls))

    # Path object accepted
    res = service.test_matrix(tmp_path)
    assert res["success"] is True
    assert calls[0][1] == str(tmp_path)
    assert engine.calls[0] == ("test_matrix", str(tmp_path))

    # Empty and whitespace root rejected
    with pytest.raises(ValueError, match="root must be non-empty"):
        service.test_matrix("")

    with pytest.raises(ValueError, match="root must be non-empty"):
        service.test_matrix("   ")

    # Null byte in root rejected
    with pytest.raises(ValueError, match="null byte"):
        service.test_matrix("/tmp\x00/repo")


def test_affected_tests_defaults_and_normalization(tmp_path: Path) -> None:
    engine = _DummyEngine()
    calls: list[tuple[Any, ...]] = []
    service = RepositoryTestImpactService(engine, _dummy_runner(calls))

    # tuple or set changed_paths normalized to list, None params normalized to dict, empty base defaults to HEAD
    res = service.affected_tests(
        root=tmp_path,
        changed_paths=("src/foo.py", "src/bar.py"),  # type: ignore[arg-type]
        base="",
        params=None,  # type: ignore[arg-type]
    )
    assert res["success"] is True
    assert calls[0] == ("affected-tests", str(tmp_path), {})
    assert engine.calls[0] == ("affected_tests", str(tmp_path), ["src/foo.py", "src/bar.py"], "HEAD")

    # Invalid changed_paths (not None and not iterable) raises TypeError
    with pytest.raises(TypeError, match="changed_paths must be iterable or None"):
        service.affected_tests(root=tmp_path, changed_paths=123)  # type: ignore[arg-type]
