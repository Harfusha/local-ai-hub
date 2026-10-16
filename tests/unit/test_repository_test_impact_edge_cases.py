from pathlib import Path

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
        "  ",
        original_params,
    )

    assert observed == {
        "root": str(tmp_path),
        "paths": ["tests/a.py", "tests/b.py"],
        "base": "HEAD",
    }
    assert result["params"] == original_params
    assert result["params"] is not original_params


def test_affected_tests_rejects_scalar_changed_paths(tmp_path: Path) -> None:
    service = RepositoryTestImpactService(object(), _runner)
    with pytest.raises(TypeError, match="changed_paths must be iterable or None"):
        service.affected_tests(str(tmp_path), 123)  # type: ignore[arg-type]
