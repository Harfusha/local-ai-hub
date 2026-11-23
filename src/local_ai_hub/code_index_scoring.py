from __future__ import annotations

from typing import Any


def _root_archive_path_sql(path_expression: str = "path") -> str:
    # Apply the inventory policy to legacy rows before SQL LIMIT as well.
    # One predicate keeps scanning and persisted-index retrieval in agreement.
    return f"NOT hub_root_archive_path({path_expression})"


def _escape_like_literal(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def _code_index_candidate_score(
    name: Any,
    name_path: Any,
    container: Any,
    path: Any,
    terms: list[str],
    exact_identifier: str | None,
    *,
    docstring: Any = "",
    kind: Any = "",
    architecture: bool = False,
    public_entrypoints: bool = False,
) -> float:
    name_l = str(name or "").lower()
    if exact_identifier is not None and name_l == exact_identifier.lower():
        return 1000.0
    name_path_l = str(name_path or "").lower()
    container_l = str(container or "").lower()
    path_l = str(path or "").lower()
    doc_l = str(docstring or "").lower()
    score = 0.0
    for term in terms:
        if name_l == term:
            score += 8.0
        elif name_l.startswith(term):
            score += 5.0
        elif term in name_l:
            score += 3.0
        elif term in name_path_l or term in container_l:
            score += 2.0
        elif exact_identifier is None and term in path_l:
            score += 1.0
        if exact_identifier is None and term in doc_l:
            score += 2.0
    if score > 0 and architecture and kind == "class":
        score += 8.0
    if (
        score > 0
        and public_entrypoints
        and kind == "function"
        and not container_l
        and not name_l.startswith("_")
    ):
        score += 16.0
    return score


class _CallablePathPolicy:
    """Adapt a callable path checker to the ProjectPathPolicy protocol."""

    def __init__(self, checker: Any, root: Any, settings: Any) -> None:
        self._checker = checker
        self._root = root
        self._settings = settings

    def allows(
        self,
        path: Any,
        *,
        phase: str,
        soft_ignored: bool = False,
        hard_denied: bool = False,
        binary: bool = False,
        size_bytes: int | None = None,
    ) -> bool:
        return bool(
            self._checker(
                self._root,
                path,
                self._settings,
                phase=phase,
                soft_ignored=soft_ignored,
                hard_denied=hard_denied,
                binary=binary,
                size_bytes=size_bytes,
            )
        )


def _resolve_code_index_path_policy(api: Any | None, root: Any, settings: Any | None) -> Any | None:
    if api is None or settings is None:
        return None
    policy_cls = getattr(api, "ProjectPathPolicy", None)
    if policy_cls is not None:
        return policy_cls(root, settings)
    checker = getattr(api, "path_is_allowed", None)
    if callable(checker):
        return _CallablePathPolicy(checker, root, settings)
    return None
