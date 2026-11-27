"""Bounded static Python import impact graph; never imports or executes project code."""
from __future__ import annotations

import ast
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
import time
import stat

MAX_SOURCE_BYTES = 512_000
MAX_TOTAL_BYTES = 32_000_000
MAX_EDGES = 250_000


def _module_names(path: str) -> set[str]:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    variants = [parts]
    if parts and parts[0] == "src":
        variants.append(parts[1:])
    return {".".join(p) for p in variants if p and all(name.isidentifier() for name in p)}


def _imports(tree: ast.AST, path: str) -> set[str]:
    result: set[str] = set()
    packages = {name if path.endswith("/__init__.py") else name.rpartition(".")[0]
                for name in _module_names(path)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            bases = {node.module or ""} if not node.level else set()
            if node.level:
                for package in packages:
                    parts = package.split(".") if package else []
                    if len(parts) >= node.level:
                        prefix = parts[:len(parts) - node.level + 1]
                        bases.add(".".join([*prefix, *([node.module] if node.module else [])]))
            for base in bases:
                if base:
                    result.add(base)
                    result.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
    # Importing pkg.mod also executes package initializers.
    return {".".join(parts[:length]) for name in result
            for parts in [name.split(".")] for length in range(1, len(parts) + 1)}


def python_import_dependents(root: str, resources: Iterable[str], changed: Iterable[str],
                             *, deadline: float) -> dict[str, set[str]]:
    """Reverse edges for statically resolvable root/src-layout Python imports.

    Include deleted modules as possible targets; never read deleted files.
    Ambiguous module names conservatively match all candidates.
    """
    from .repo_tools import RepositoryTools

    base = Path(root).resolve(strict=True)
    tools = RepositoryTools({})
    sources = sorted(path for path in set(resources) if path.endswith(".py"))
    modules: dict[str, set[str]] = defaultdict(set)
    for path in sorted(set(sources) | {path for path in changed if path.endswith(".py")}):
        for name in _module_names(path):
            modules[name].add(path)
    reverse: dict[str, set[str]] = defaultdict(set)
    total_bytes = 0
    edges = 0
    for rel in sources:
        if time.monotonic() >= deadline:
            raise ValueError("Python import impact exceeded deadline")
        candidate = base / rel
        before = tools._resolve_inventory_path_safe_with_stat(base, candidate, resolved_base=base)
        if before is None or not stat.S_ISREG(before[2].st_mode):
            raise ValueError("Python import impact source became unavailable")
        info = before[2]
        total_bytes += info.st_size
        if info.st_size > MAX_SOURCE_BYTES or total_bytes > MAX_TOTAL_BYTES:
            raise ValueError("Python import impact exceeded source byte limit")
        try:
            _, lines = tools._read_snapshot(candidate, force=True, max_bytes=MAX_SOURCE_BYTES)
            after = tools._resolve_inventory_path_safe_with_stat(base, candidate, resolved_base=base)
            if after is None or any(getattr(after[2], field) != getattr(info, field)
                                    for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")):
                raise ValueError("Python import impact source changed during analysis")
            source = "\n".join(lines)
            if "\ufffd" in source:
                raise ValueError("Python import impact source could not be decoded losslessly")
            tree = ast.parse(source, filename=rel)
        except (OSError, SyntaxError, UnicodeError, RecursionError) as exc:
            raise ValueError("Python import impact source could not be parsed") from exc
        for name in _imports(tree, rel):
            if time.monotonic() >= deadline:
                raise ValueError("Python import impact exceeded deadline")
            for target in modules.get(name, set()):
                if target != rel and rel not in reverse[target]:
                    reverse[target].add(rel)
                    edges += 1
                    if edges > MAX_EDGES:
                        raise ValueError("Python import impact exceeded edge limit")
    if time.monotonic() >= deadline:
        raise ValueError("Python import impact exceeded deadline")
    return dict(reverse)


def expand_import_dependents(paths: Iterable[str], reverse: Mapping[str, set[str]]) -> set[str]:
    result = set(paths)
    pending = deque(sorted(result))
    while pending:
        path = pending.popleft()
        for dependent in sorted(reverse.get(path, set()) - result):
            result.add(dependent)
            pending.append(dependent)
    return result
