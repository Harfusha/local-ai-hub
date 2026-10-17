from __future__ import annotations

from pathlib import Path
from typing import Any
import pytest

from local_ai_hub.repository_test_impact import RepositoryTestImpactService


def _runner(operation, root, params, compute):
    return {"operation": operation, "root": root, "params": params, "value": compute()}


def test_repository_test_impact_rejects_missing_engine_and_invalid_runner() -> None:
    with pytest.raises(ValueError, match="engine cannot be None"):
        RepositoryTestImpactService(None, _runner)
    with pytest.raises(TypeError, match="operation_runner must be callable"):
        RepositoryTestImpactService(object(), None)  # type: ignore[arg-type]


@pytest.mark.parametrize("root", [None, "", "  ", "bad\x00root"])
def test_repository_test_impact_rejects_invalid_roots(root: object) -> None:
    engine = type("Engine", (), {"test_matrix": lambda _self, value: value})()
    service = RepositoryTestImpactService(engine, _runner)
    with pytest.raises(ValueError):
        service.test_matrix(root)  # type: ignore[arg-type]


def test_affected_tests_rejects_blank_base_before_execution(tmp_path: Path) -> None:
    observed = {}

    class Engine:
        def affected_tests(self, root, paths, base):
            observed.update(root=root, paths=paths, base=base)
            return {"ok": True}

    service = RepositoryTestImpactService(Engine(), _runner)
    with pytest.raises(ValueError, match="base must be nonempty"):
        service.affected_tests(str(tmp_path), (path for path in ("tests/a.py",)), "  ", {"limit": 7})
    assert observed == {}


def test_affected_tests_materializes_iterable_and_copies_params(tmp_path: Path) -> None:
    observed = {}

    class Engine:
        def affected_tests(self, root, paths, base):
            observed.update(root=root, paths=paths, base=base)
            return {"ok": True}

    service = RepositoryTestImpactService(Engine(), _runner)
    original_params = {"limit": 7}
    result = service.affected_tests(
        str(tmp_path),
        (path for path in ("tests/a.py", "tests/b.py")),
        "",
        original_params,
    )

    assert observed == {"root": str(tmp_path), "paths": ["tests/a.py", "tests/b.py"], "base": "HEAD"}
    assert result["params"] == original_params
    assert result["params"] is not original_params


def test_affected_tests_rejects_scalar_changed_paths(tmp_path: Path) -> None:
    service = RepositoryTestImpactService(object(), _runner)
    with pytest.raises(TypeError, match="changed_paths must be iterable or None"):
        service.affected_tests(str(tmp_path), 123)  # type: ignore[arg-type]
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

    # tuple or set changed_paths normalized to list, None params normalized to dict
    res = service.affected_tests(
        root=tmp_path,
        changed_paths=("src/foo.py", "src/bar.py"),  # type: ignore[arg-type]
        base="HEAD",
        params=None,  # type: ignore[arg-type]
    )
    assert res["success"] is True
    assert calls[0] == ("affected-tests", str(tmp_path), {})
    assert engine.calls[0] == ("affected_tests", str(tmp_path), ["src/foo.py", "src/bar.py"], "HEAD")

    # Invalid changed_paths (not None and not iterable) raises TypeError
    with pytest.raises(TypeError, match="changed_paths must be iterable or None"):
        service.affected_tests(root=tmp_path, changed_paths=123)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("base", "error_type"),
    [
        ("   ", ValueError),
        ("\x00", ValueError),
        (True, TypeError),
    ],
)
def test_affected_tests_rejects_invalid_base_before_execution(
    tmp_path: Path, base: Any, error_type: type[Exception]
) -> None:
    engine = _DummyEngine()
    calls: list[tuple[Any, ...]] = []
    service = RepositoryTestImpactService(engine, _dummy_runner(calls))

    with pytest.raises(error_type, match="base"):
        service.affected_tests(root=tmp_path, base=base)  # type: ignore[arg-type]

    assert calls == []
    assert engine.calls == []
