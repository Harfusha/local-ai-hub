"""Bounded, one-hop file admission for the partial code index."""

from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath
from typing import Any


def one_hop_python_imports(
    root: Path, seeds: list[str], eligible: set[str], repo_tools: Any, *, limit: int = 64
) -> list[str]:
    """Resolve direct local Python imports without executing code or recursing.

    The caller supplies the already policy-filtered inventory. Unresolved,
    ambiguous, non-Python and inaccessible dependencies remain unknown.
    """
    if type(limit) is not int or limit < 1 or limit > 256:
        raise ValueError("limit must be an integer between 1 and 256")
    base = Path(root).resolve(strict=True)
    seed_set = set(seeds)
    found: list[str] = []
    seen: set[str] = set()

    def add_module(prefix: PurePosixPath, parts: list[str]) -> None:
        module = prefix.joinpath(*parts)
        if ".." in module.parts:
            return
        choices = [module.as_posix() + ".py", (module / "__init__.py").as_posix()]
        matches = [path for path in choices if path in eligible]
        # A directory package and module with the same name is ambiguous.
        if len(matches) != 1:
            return
        path = matches[0]
        if path not in seed_set and path not in seen and len(found) < limit:
            seen.add(path)
            found.append(path)

    for seed in seeds[:128]:
        if len(found) >= limit or seed not in eligible or not seed.endswith(".py"):
            continue
        target = base / seed
        if not repo_tools._inventory_path_safe(base, target):
            continue
        try:
            _, lines = repo_tools._read_snapshot(target)
            tree = ast.parse("\n".join(lines))
        except (OSError, UnicodeError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in (PurePosixPath(), PurePosixPath("src")):
                        add_module(prefix, alias.name.split("."))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parent = PurePosixPath(seed).parent
                    for _ in range(node.level - 1):
                        if not parent.parts:
                            parent = PurePosixPath("..")
                            break
                        parent = parent.parent
                    prefixes = (parent,)
                else:
                    prefixes = (PurePosixPath(), PurePosixPath("src"))
                parts = node.module.split(".") if node.module else []
                for prefix in prefixes:
                    if parts:
                        add_module(prefix, parts)
                    for alias in node.names:
                        if alias.name != "*":
                            add_module(prefix, [*parts, alias.name])
    return found
