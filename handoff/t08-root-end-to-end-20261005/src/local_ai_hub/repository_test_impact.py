from __future__ import annotations

from collections.abc import Callable
from typing import Any


class RepositoryTestImpactService:
    """Run cached deterministic test-impact operations behind a small seam."""

    def __init__(
        self,
        engine: Any,
        operation_runner: Callable[..., dict[str, Any]],
    ) -> None:
        self.engine = engine
        self.operation_runner = operation_runner

    def test_matrix(self, root: str) -> dict[str, Any]:
        return self.operation_runner(
            "test-matrix",
            root,
            {},
            lambda: self.engine.test_matrix(root),
        )

    def affected_tests(
        self,
        root: str,
        changed_paths: list[str] | None,
        base: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        return self.operation_runner(
            "affected-tests",
            root,
            params,
            lambda: self.engine.affected_tests(root, changed_paths, base),
        )
