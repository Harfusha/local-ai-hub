"""Bounded, one-hop file admission for the partial code index."""

from __future__ import annotations

import ast
import posixpath
import re
from pathlib import Path, PurePosixPath
from typing import Any


_JS_IMPORT = re.compile(
    r"\b(?:import|export)\s+(?:(?:type\s+)?[^;\n]*?\s+from\s*)?['\"](\.{1,2}/[^'\"]+)['\"]"
)
_JS_DYNAMIC_IMPORT = re.compile(
    r"\b(?:import|require)\s*\(\s*['\"](\.{1,2}/[^'\"]+)['\"]\s*\)"
)
_PHP_INCLUDE = re.compile(
    r"\b(?:require|include)(?:_once)?\s*(?:\(\s*)?(?:(?P<dir>__DIR__)\s*\.\s*)?['\"](?P<path>(?:\.{1,2}/|/)[^'\"]+)['\"]\s*\)?"
)
_JS_EXTENSIONS = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".json")


def _safe_inventory_file(base: Path, path: str, repo_tools: Any) -> bool:
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        return False
    try:
        return bool(repo_tools._inventory_path_safe(base, base / Path(path)))
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _resolve_relative_module(
    base: Path,
    seed: str,
    specifier: str,
    eligible: set[str],
    repo_tools: Any,
    *,
    extensions: tuple[str, ...],
) -> str | None:
    normalized = specifier.replace("\\", "/")
    if not normalized.startswith(("./", "../")) or normalized.startswith("/"):
        return None
    parent = PurePosixPath(seed).parent.as_posix()
    target = posixpath.normpath(posixpath.join(parent, normalized))
    pure_target = PurePosixPath(target)
    if pure_target.is_absolute() or ".." in pure_target.parts or target in ("", "."):
        return None
    candidates = [target]
    if not pure_target.suffix:
        candidates.extend(target + extension for extension in extensions)
        candidates.extend(
            (PurePosixPath(target) / ("index" + extension)).as_posix()
            for extension in extensions
        )
    matches = list(dict.fromkeys(path for path in candidates if path in eligible))
    if len(matches) != 1:
        return None
    return matches[0] if _safe_inventory_file(base, matches[0], repo_tools) else None


def _python_import_candidates(seed: str, tree: ast.AST, eligible: set[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add_module(prefix: PurePosixPath, parts: list[str]) -> None:
        module = prefix.joinpath(*parts)
        if ".." in module.parts:
            return
        choices = [module.as_posix() + ".py", (module / "__init__.py").as_posix()]
        matches = [path for path in choices if path in eligible]
        if len(matches) != 1:
            return
        path = matches[0]
        if path != seed and path not in seen:
            seen.add(path)
            found.append(path)

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


def one_hop_related_files(
    root: Path, seeds: list[str], eligible: set[str], repo_tools: Any, *, limit: int = 64
) -> list[str]:
    """Resolve bounded direct local imports without executing or recursing.

    Python imports, relative JavaScript/TypeScript modules, and literal relative
    PHP includes are supported. Unresolved, ambiguous, external, non-literal,
    unsupported, and inaccessible dependencies remain unknown. The caller
    supplies the already policy-filtered inventory.
    """
    if type(limit) is not int or limit < 1 or limit > 256:
        raise ValueError("limit must be an integer between 1 and 256")
    base = Path(root).resolve(strict=True)
    found: list[str] = []
    seen = set(seeds)

    for seed in seeds[:128]:
        if len(found) >= limit or seed not in eligible or not _safe_inventory_file(base, seed, repo_tools):
            continue
        suffix = PurePosixPath(seed).suffix.lower()
        if suffix not in {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".php"}:
            continue
        target = base / Path(seed)
        try:
            _, lines = repo_tools._read_snapshot(target)
            source = "\n".join(lines)
            if suffix == ".py":
                candidates = _python_import_candidates(seed, ast.parse(source), eligible)
            elif suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
                specifiers = [match.group(1) for match in _JS_IMPORT.finditer(source)]
                specifiers.extend(match.group(1) for match in _JS_DYNAMIC_IMPORT.finditer(source))
                candidates = [
                    path for specifier in specifiers
                    if (path := _resolve_relative_module(
                        base, seed, specifier, eligible, repo_tools, extensions=_JS_EXTENSIONS,
                    )) is not None
                ]
            else:
                candidates = []
                for match in _PHP_INCLUDE.finditer(source):
                    specifier = match.group("path")
                    if specifier.startswith("/"):
                        if not match.group("dir"):
                            continue
                        specifier = "." + specifier
                    path = _resolve_relative_module(
                        base, seed, specifier, eligible, repo_tools, extensions=(".php",),
                    )
                    if path is not None:
                        candidates.append(path)
        except (OSError, RuntimeError, UnicodeError, SyntaxError, TypeError, ValueError, RecursionError):
            continue

        for path in candidates:
            if path not in seen and len(found) < limit:
                seen.add(path)
                found.append(path)
    return found
