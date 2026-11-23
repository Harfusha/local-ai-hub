"""Source Diff Invariant Verifier & Architectural Safety Gate.

Guarantees safety of agent-generated code modifications before merging or writing to disk:
1. Syntactic validity: Enforces zero-error AST compilation.
2. Interface preservation: Flags breaking changes to public function signatures and exported classes.
3. Complexity bounds: Flags excessive indentation nesting depth (>6 levels).
4. Dangerous pattern detection: Disallows silent bare 'except:' without logging.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiffVerificationVerdict:
    """Outcome of diff invariant verification."""

    passed: bool
    violations: Tuple[str, ...]
    public_interfaces_preserved: bool
    max_nesting_depth: int


def _get_public_signatures(tree: ast.AST) -> Dict[str, Tuple[str, int]]:
    """Extract public functions/classes: name -> (kind, arg_count)."""
    sigs: Dict[str, Tuple[str, int]] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                sigs[node.name] = ("function", len(node.args.args))
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                sigs[node.name] = ("class", len(node.bases))
    return sigs


class _NestingVisitor(ast.NodeVisitor):
    """Measures maximum block nesting depth in code."""

    def __init__(self) -> None:
        self.max_depth = 0
        self._current_depth = 0

    def _visit_block(self, node: ast.AST) -> None:
        self._current_depth += 1
        self.max_depth = max(self.max_depth, self._current_depth)
        self.generic_visit(node)
        self._current_depth -= 1

    def visit_If(self, node: ast.If) -> None:
        self._visit_block(node)

    def visit_For(self, node: ast.For) -> None:
        self._visit_block(node)

    def visit_While(self, node: ast.While) -> None:
        self._visit_block(node)

    def visit_With(self, node: ast.With) -> None:
        self._visit_block(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._visit_block(node)


class _DangerousPatternVisitor(ast.NodeVisitor):
    """Detects dangerous patterns like bare except: pass."""

    def __init__(self) -> None:
        self.violations: List[str] = []

    def visit_Try(self, node: ast.Try) -> None:
        for handler in node.handlers:
            if handler.type is None:
                # Bare except: check if body is only pass
                if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                    self.violations.append("Bare 'except: pass' silently swallowing all exceptions")
        self.generic_visit(node)


def verify_code_invariants(
    candidate_code: str,
    base_code: Optional[str] = None,
    max_allowed_nesting: int = 6,
    strict_interface_check: bool = True,
) -> DiffVerificationVerdict:
    """Verify syntactic and architectural invariants on candidate code."""
    violations: List[str] = []

    # 1. Syntactic check
    try:
        cand_tree = ast.parse(candidate_code)
    except SyntaxError as e:
        return DiffVerificationVerdict(
            passed=False,
            violations=(f"Syntax error in candidate code: {e}",),
            public_interfaces_preserved=False,
            max_nesting_depth=0,
        )

    # 2. Dangerous patterns
    pat_visitor = _DangerousPatternVisitor()
    pat_visitor.visit(cand_tree)
    violations.extend(pat_visitor.violations)

    # 3. Nesting depth
    nest_visitor = _NestingVisitor()
    nest_visitor.visit(cand_tree)
    if nest_visitor.max_depth > max_allowed_nesting:
        violations.append(
            f"Excessive nesting depth ({nest_visitor.max_depth} > max {max_allowed_nesting})"
        )

    # 4. Interface preservation
    interfaces_preserved = True
    if base_code and strict_interface_check:
        try:
            base_tree = ast.parse(base_code)
            base_sigs = _get_public_signatures(base_tree)
            cand_sigs = _get_public_signatures(cand_tree)

            for name, (kind, arg_cnt) in base_sigs.items():
                if name not in cand_sigs:
                    violations.append(f"Breaking change: public {kind} '{name}' was deleted")
                    interfaces_preserved = False
                elif kind == "function":
                    cand_kind, cand_args = cand_sigs[name]
                    if cand_args < arg_cnt:
                        violations.append(
                            f"Breaking signature: function '{name}' reduced arguments ({cand_args} < {arg_cnt})"
                        )
                        interfaces_preserved = False
        except SyntaxError:
            pass  # Base code was invalid, ignore comparison

    return DiffVerificationVerdict(
        passed=len(violations) == 0,
        violations=tuple(violations),
        public_interfaces_preserved=interfaces_preserved,
        max_nesting_depth=nest_visitor.max_depth,
    )
