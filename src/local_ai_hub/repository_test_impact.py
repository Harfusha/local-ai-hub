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
    def _validate_root(root: str | Path) -> str:
        if root is None:
            raise ValueError("root must be non-empty")
        root_str = str(root).strip()
        if not root_str:
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
        norm_changed_paths: list[str] | None
        if changed_paths is not None:
            if not hasattr(changed_paths, "__iter__") or isinstance(changed_paths, (str, bytes)):
                raise TypeError("changed_paths must be iterable or None")
            norm_changed_paths = [str(p) for p in changed_paths]
        else:
            norm_changed_paths = None

        clean_base = str(base).strip() if base is not None else ""
        if not clean_base:
            clean_base = "HEAD"

        clean_params = dict(params) if params is not None else {}

        return self.operation_runner(
            "affected-tests",
            canonical_root,
            clean_params,
            lambda: self.engine.affected_tests(canonical_root, norm_changed_paths, clean_base),
        )
