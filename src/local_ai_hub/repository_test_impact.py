from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any


class RepositoryTestImpactService:
    """Run cached deterministic test-impact operations behind a small seam."""

    def __init__(
        self,
        engine: Any,
        operation_runner: Callable[..., dict[str, Any]],
    ) -> None:
        if engine is None:
            raise ValueError("engine cannot be None")
        if not callable(operation_runner):
            raise TypeError("operation_runner must be callable")
        self.engine = engine
        self.operation_runner = operation_runner

    @staticmethod
    def _validate_root(root: str | Path | None) -> str:
        if root is None or isinstance(root, bool) or not isinstance(root, (str, Path)):
            raise ValueError("root must be a valid path string or Path")
        root_str = str(root)
        if not root_str.strip():
            raise ValueError("root must be non-empty")
        if "\x00" in root_str:
            raise ValueError("root cannot contain null byte")
        return root_str

    def test_matrix(self, root: str | Path) -> dict[str, Any]:
        canonical_root = self._validate_root(root)
        return self.operation_runner(
            "test-matrix",
            canonical_root,
            {},
            lambda: self.engine.test_matrix(canonical_root),
        )

    def affected_tests(
        self,
        root: str | Path,
        changed_paths: list[str] | tuple[str, ...] | Iterable[str] | None = None,
        base: str = "HEAD",
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        canonical_root = self._validate_root(root)
        if changed_paths is not None:
            if isinstance(changed_paths, bool) or not isinstance(changed_paths, Iterable) or isinstance(changed_paths, (str, bytes)):
                raise TypeError("changed_paths must be iterable or None")
            normalized_paths = []
            for p in changed_paths:
                if p is None or isinstance(p, bool) or not isinstance(p, (str, Path)):
                    raise TypeError("changed_paths entries must be path strings or Path values")
                p_str = str(p)
                if not p_str or "\x00" in p_str:
                    raise ValueError("changed_paths entries must be nonempty and contain no NUL")
                normalized_paths.append(p_str)
        else:
            normalized_paths = None

        if base is None:
            clean_base = "HEAD"
        elif isinstance(base, bool) or not isinstance(base, (str, Path)):
            raise TypeError("base must be a revision string or Path")
        else:
            clean_base = str(base)
            if "\x00" in clean_base:
                raise ValueError("base must be nonempty and contain no NUL")
            if clean_base == "":
                clean_base = "HEAD"
            elif not clean_base.strip():
                raise ValueError("base must be nonempty and contain no NUL")

        if params is not None and not isinstance(params, dict):
            raise TypeError("params must be a mapping or None")
        clean_params = dict(params) if params is not None else {}
        return self.operation_runner(
            "affected-tests",
            canonical_root,
            clean_params,
            lambda: self.engine.affected_tests(canonical_root, normalized_paths, clean_base),
        )
