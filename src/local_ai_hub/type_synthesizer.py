"""AST Type Annotation Synthesizer for Dynamic & Untyped Code.

Analyzes untyped Python functions and synthesizes PEP 484 type hints by inspecting:
1. Return expressions (constants, f-strings, bools, collections, None).
2. Default argument types (int, float, str, bool, dict, list).
3. Standard method signatures (__init__ -> None).

Enriches prompt context skeletons with clear interface typing contracts without modifying source on disk.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SynthesizeTypeResult:
    """Outcome of AST type synthesis."""

    enriched_code: str
    synthesized_count: int
    synthesized_annotations: Dict[str, str]


def _infer_type_from_constant(val: Any) -> Optional[str]:
    if isinstance(val, bool):
        return "bool"
    if isinstance(val, int):
        return "int"
    if isinstance(val, float):
        return "float"
    if isinstance(val, str):
        return "str"
    if isinstance(val, bytes):
        return "bytes"
    if val is None:
        return "None"
    return None


def _infer_return_type(fn_node: ast.FunctionDef | ast.AsyncFunctionDef) -> Optional[str]:
    """Inspect return statements in function body to infer return type."""
    if fn_node.name == "__init__":
        return "None"

    return_types: set[str] = set()
    has_explicit_return = False

    for child in ast.walk(fn_node):
        # Don't look inside nested functions
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child is not fn_node:
            continue
        if isinstance(child, ast.Return):
            has_explicit_return = True
            if child.value is None:
                return_types.add("None")
            elif isinstance(child.value, ast.Constant):
                t = _infer_type_from_constant(child.value.value)
                if t:
                    return_types.add(t)
            elif isinstance(child.value, ast.JoinedStr):
                return_types.add("str")
            elif isinstance(child.value, ast.List):
                return_types.add("list")
            elif isinstance(child.value, ast.Dict):
                return_types.add("dict")
            elif isinstance(child.value, ast.Set):
                return_types.add("set")
            elif isinstance(child.value, ast.Tuple):
                return_types.add("tuple")

    if not has_explicit_return:
        return "None"
    if len(return_types) == 1:
        return next(iter(return_types))
    return None


class _TypeAnnotator(ast.NodeTransformer):
    """Adds type annotations to untyped functions."""

    def __init__(self) -> None:
        self.count = 0
        self.annotations: Dict[str, str] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        self.generic_visit(node)
        self._annotate(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        self.generic_visit(node)
        self._annotate(node)
        return node

    def _annotate(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # 1. Return annotation
        if node.returns is None:
            ret_type = _infer_return_type(node)
            if ret_type:
                node.returns = ast.Name(id=ret_type, ctx=ast.Load())
                self.count += 1
                self.annotations[f"{node.name}->return"] = ret_type

        # 2. Argument annotations from defaults
        args = node.args.args
        defaults = node.args.defaults
        if defaults:
            # Align defaults to the rightmost positional arguments
            offset = len(args) - len(defaults)
            for i, default_node in enumerate(defaults):
                arg = args[offset + i]
                if arg.annotation is None and isinstance(default_node, ast.Constant):
                    param_type = _infer_type_from_constant(default_node.value)
                    if param_type and param_type != "None":
                        arg.annotation = ast.Name(id=param_type, ctx=ast.Load())
                        self.count += 1
                        self.annotations[f"{node.name}->{arg.arg}"] = param_type


def synthesize_types(source: str) -> SynthesizeTypeResult:
    """Analyze and inject inferred type annotations into untyped Python code."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return SynthesizeTypeResult(
            enriched_code=source,
            synthesized_count=0,
            synthesized_annotations={},
        )

    annotator = _TypeAnnotator()
    tree = annotator.visit(tree)
    ast.fix_missing_locations(tree)

    try:
        enriched = ast.unparse(tree)
        ast.parse(enriched)
    except Exception:
        enriched = source

    return SynthesizeTypeResult(
        enriched_code=enriched,
        synthesized_count=annotator.count,
        synthesized_annotations=annotator.annotations,
    )
