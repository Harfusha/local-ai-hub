"""Context Dependency Tree Flattener & Import Path Optimizer.

Transforms relative imports (e.g., 'from ...storage.db import Connection') into absolute canonical
module paths based on repository file coordinates.
Eliminates context ambiguity when files from different subtrees are assembled into prompt envelopes.

Features:
1. AST-level relative ImportFrom resolution (level > 0 -> level = 0).
2. Deterministic package hierarchy reconstruction relative to project root or source root.
3. Guaranteed syntax validity via roundtrip AST compile verification.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportOptimizeResult:
    """Outcome of import path canonicalization."""

    optimized_code: str
    resolved_count: int
    resolved_mapping: Dict[str, str]


def resolve_relative_module(current_file_rel: str, import_module: Optional[str], level: int) -> str:
    """Resolve a relative import (level > 0) to a canonical absolute package path."""
    parts = Path(current_file_rel.replace("\\", "/")).parts
    # Package parts of current file (excluding the file itself)
    pkg_parts = list(parts[:-1])

    # Strip common leading source roots like 'src' or 'lib' if present for clean module naming
    if pkg_parts and pkg_parts[0] in ("src", "lib"):
        pkg_parts = pkg_parts[1:]

    # Level 1 = same package, Level 2 = parent, Level 3 = grandparent
    steps_up = level - 1
    if steps_up > len(pkg_parts):
        target_base = []
    else:
        target_base = pkg_parts[: len(pkg_parts) - steps_up]

    if import_module:
        target_base.append(import_module)

    return ".".join(target_base)


class _ImportCanonicalizer(ast.NodeTransformer):
    """Rewrites relative ImportFrom nodes to absolute."""

    def __init__(self, current_file_path: str) -> None:
        self.current_file_path = current_file_path
        self.resolved_count = 0
        self.mapping: Dict[str, str] = {}

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST:
        if node.level and node.level > 0:
            orig_module = ("." * node.level) + (node.module or "")
            abs_module = resolve_relative_module(self.current_file_path, node.module, node.level)
            if abs_module:
                new_node = ast.ImportFrom(
                    module=abs_module,
                    names=node.names,
                    level=0,
                )
                self.resolved_count += 1
                self.mapping[orig_module] = abs_module
                return ast.copy_location(new_node, node)
        return node


def canonicalize_imports(source: str, current_file_path: str) -> ImportOptimizeResult:
    """Canonicalize all relative imports in source code to absolute module imports."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ImportOptimizeResult(
            optimized_code=source,
            resolved_count=0,
            resolved_mapping={},
        )

    canonicalizer = _ImportCanonicalizer(current_file_path)
    tree = canonicalizer.visit(tree)
    ast.fix_missing_locations(tree)

    try:
        optimized = ast.unparse(tree)
        ast.parse(optimized)
    except Exception:
        optimized = source

    return ImportOptimizeResult(
        optimized_code=optimized,
        resolved_count=canonicalizer.resolved_count,
        resolved_mapping=canonicalizer.mapping,
    )
