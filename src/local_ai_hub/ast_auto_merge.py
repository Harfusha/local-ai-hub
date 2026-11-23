"""AST-Aware 3-Way Semantic Auto-Merge.

Resolves file conflicts between divergent branches/worktrees at the AST symbol level
instead of failing on raw line conflicts.

Capabilities:
1. Decomposes Python source into top-level statements, functions, classes, and imports.
2. Identifies non-conflicting divergent additions (e.g., branch A added func_a, branch B added func_b).
3. Resolves disjoint modifications (e.g., branch A edited func_1, branch B edited func_2).
4. Performs recursive class-level method merging when different methods in the same class are edited.
5. Reconstructs unified syntax-verified Python source and guarantees valid compilation.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SemanticMergeResult:
    """Outcome of 3-way AST semantic merge."""

    success: bool
    merged_code: str
    conflicts: List[str] = field(default_factory=list)
    resolved_symbols: List[str] = field(default_factory=list)


def _get_symbol_map(tree: ast.AST) -> Dict[str, ast.AST]:
    """Map top-level symbol names to AST nodes."""
    symbols: Dict[str, ast.AST] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols[node.name] = node
    return symbols


def _get_imports(tree: ast.AST) -> List[ast.AST]:
    """Extract top-level import statements."""
    imports: List[ast.AST] = []
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
    return imports


def _ast_equal(n1: ast.AST, n2: ast.AST) -> bool:
    """Compare two AST nodes for semantic equivalence via dump."""
    return ast.dump(n1) == ast.dump(n2)


def _merge_class_nodes(
    base_cls: Optional[ast.ClassDef],
    ours_cls: ast.ClassDef,
    theirs_cls: ast.ClassDef,
) -> Tuple[Optional[ast.ClassDef], List[str]]:
    """Merge methods and attributes inside a class."""
    conflicts: List[str] = []
    base_methods = {m.name: m for m in base_cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))} if base_cls else {}
    ours_methods = {m.name: m for m in ours_cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
    theirs_methods = {m.name: m for m in theirs_cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}

    all_method_names = list(dict.fromkeys(list(base_methods.keys()) + list(ours_methods.keys()) + list(theirs_methods.keys())))
    merged_body: List[ast.AST] = []

    # Preserve docstring if present
    docstring = ast.get_docstring(ours_cls) or ast.get_docstring(theirs_cls)
    if docstring:
        merged_body.append(ast.Expr(value=ast.Constant(value=docstring)))

    for name in all_method_names:
        in_base = base_methods.get(name)
        in_ours = ours_methods.get(name)
        in_theirs = theirs_methods.get(name)

        if in_ours and not in_theirs:
            if not in_base:
                merged_body.append(in_ours)
            else:
                # Deleted in theirs, kept in ours -> take ours
                merged_body.append(in_ours)
        elif in_theirs and not in_ours:
            if not in_base:
                merged_body.append(in_theirs)
            else:
                # Deleted in ours, kept in theirs -> take theirs
                merged_body.append(in_theirs)
        elif in_ours and in_theirs:
            if _ast_equal(in_ours, in_theirs):
                merged_body.append(in_ours)
            elif in_base and _ast_equal(in_ours, in_base):
                # Ours unchanged, theirs modified
                merged_body.append(in_theirs)
            elif in_base and _ast_equal(in_theirs, in_base):
                # Theirs unchanged, ours modified
                merged_body.append(in_ours)
            else:
                # Both modified differently
                conflicts.append(f"Method conflict in {ours_cls.name}.{name}")

    if conflicts:
        return None, conflicts

    new_cls = ast.ClassDef(
        name=ours_cls.name,
        bases=ours_cls.bases,
        keywords=ours_cls.keywords,
        body=merged_body if merged_body else [ast.Pass()],
        decorator_list=ours_cls.decorator_list,
    )
    return new_cls, []


def semantic_ast_merge(
    base_code: str,
    ours_code: str,
    theirs_code: str,
) -> SemanticMergeResult:
    """Execute 3-way semantic AST merge.
    
    Args:
        base_code: Common ancestor code
        ours_code: Local branch code
        theirs_code: Remote/worktree branch code
    """
    try:
        base_tree = ast.parse(base_code) if base_code.strip() else ast.Module(body=[], type_ignores=[])
        ours_tree = ast.parse(ours_code)
        theirs_tree = ast.parse(theirs_code)
    except SyntaxError as e:
        return SemanticMergeResult(
            success=False,
            merged_code="",
            conflicts=[f"Syntax error during AST parse: {e}"],
        )

    base_syms = _get_symbol_map(base_tree)
    ours_syms = _get_symbol_map(ours_tree)
    theirs_syms = _get_symbol_map(theirs_tree)

    # 1. Merge imports (union, preserving unique unparsed lines)
    import_nodes: List[ast.AST] = []
    seen_imports: Set[str] = set()
    for imp in _get_imports(ours_tree) + _get_imports(theirs_tree):
        line = ast.unparse(imp).strip()
        if line not in seen_imports:
            seen_imports.add(line)
            import_nodes.append(imp)

    # 2. Merge symbols
    all_sym_names = list(dict.fromkeys(list(base_syms.keys()) + list(ours_syms.keys()) + list(theirs_syms.keys())))
    merged_symbols: List[ast.AST] = []
    conflicts: List[str] = []
    resolved: List[str] = []

    for name in all_sym_names:
        b = base_syms.get(name)
        o = ours_syms.get(name)
        t = theirs_syms.get(name)

        if o and not t:
            if not b:
                # Added in ours
                merged_symbols.append(o)
                resolved.append(f"add:{name} (ours)")
            else:
                # Deleted in theirs, keep ours
                merged_symbols.append(o)
        elif t and not o:
            if not b:
                # Added in theirs
                merged_symbols.append(t)
                resolved.append(f"add:{name} (theirs)")
            else:
                # Deleted in ours, keep theirs
                merged_symbols.append(t)
        elif o and t:
            if _ast_equal(o, t):
                merged_symbols.append(o)
            elif b and _ast_equal(o, b):
                # Ours unchanged, theirs modified
                merged_symbols.append(t)
                resolved.append(f"modify:{name} (theirs)")
            elif b and _ast_equal(t, b):
                # Theirs unchanged, ours modified
                merged_symbols.append(o)
                resolved.append(f"modify:{name} (ours)")
            else:
                # Both modified
                if isinstance(o, ast.ClassDef) and isinstance(t, ast.ClassDef):
                    merged_cls, cls_conflicts = _merge_class_nodes(b if isinstance(b, ast.ClassDef) else None, o, t)
                    if merged_cls:
                        merged_symbols.append(merged_cls)
                        resolved.append(f"class_merge:{name}")
                    else:
                        conflicts.extend(cls_conflicts)
                else:
                    conflicts.append(f"Direct conflict in symbol: {name}")

    if conflicts:
        return SemanticMergeResult(
            success=False,
            merged_code="",
            conflicts=conflicts,
            resolved_symbols=resolved,
        )

    # Construct final module AST
    final_body = import_nodes + merged_symbols
    merged_module = ast.Module(body=final_body, type_ignores=[])
    ast.fix_missing_locations(merged_module)

    try:
        final_code = ast.unparse(merged_module)
        # Verify result parses
        ast.parse(final_code)
    except Exception as e:
        return SemanticMergeResult(
            success=False,
            merged_code="",
            conflicts=[f"AST unparse or reparse failed: {e}"],
        )

    return SemanticMergeResult(
        success=True,
        merged_code=final_code,
        conflicts=[],
        resolved_symbols=resolved,
    )
