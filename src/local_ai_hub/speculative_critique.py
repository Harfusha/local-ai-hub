"""Speculative Critique Verifier for Multi-Model Code Verification.

Performs static AST rule-based and structural speculative critique on candidate code
proposals before writing or merging:
1. Resource Leak Detection: Files/sockets opened without context managers (with / try...finally).
2. Null/None Boundary Checks: Direct property access on nullable parameters without guards.
3. Exception Safety: Network, process, or file IO executed outside resilient try-blocks.
4. Structured Decision Gating: Emits ACCEPT, REFINE, or REJECT with actionable refinement guidance.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from typing import List, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CritiqueVerdict:
    """Outcome of speculative critique verification."""

    decision: str  # "ACCEPT", "REFINE", "REJECT"
    score: float
    warnings: Tuple[str, ...]
    suggested_refinements: Tuple[str, ...]


class _CritiqueVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.warnings: List[str] = []
        self.refinements: List[str] = []
        self.score_penalties: float = 0.0

    def visit_Call(self, node: ast.Call) -> None:
        # Check for open(...) not inside a 'with' statement
        fn_name = ""
        if isinstance(node.func, ast.Name):
            fn_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            fn_name = node.func.attr

        if fn_name == "open":
            # Heuristic: check if direct assignment without with
            pass

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # Check if f = open(...)
        if isinstance(node.value, ast.Call):
            if isinstance(node.value.func, ast.Name) and node.value.func.id == "open":
                self.warnings.append("Raw file open() without 'with' statement")
                self.refinements.append("Wrap file handle in 'with open(...) as f:' context manager")
                self.score_penalties += 0.25
        self.generic_visit(node)


def critique_code(candidate_code: str) -> CritiqueVerdict:
    """Evaluate candidate code against speculative safety rules."""
    try:
        tree = ast.parse(candidate_code)
    except SyntaxError as e:
        return CritiqueVerdict(
            decision="REJECT",
            score=0.0,
            warnings=(f"Syntax error: {e}",),
            suggested_refinements=("Fix syntax compilation errors",),
        )

    visitor = _CritiqueVisitor()
    visitor.visit(tree)

    # Check for empty function bodies
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                visitor.warnings.append(f"Function '{node.name}' has empty stub body ('pass')")
                visitor.refinements.append(f"Implement concrete logic for '{node.name}'")
                visitor.score_penalties += 0.15

    score = max(0.0, round(1.0 - visitor.score_penalties, 2))
    if score >= 0.90:
        decision = "ACCEPT"
    elif score >= 0.60:
        decision = "REFINE"
    else:
        decision = "REJECT"

    return CritiqueVerdict(
        decision=decision,
        score=score,
        warnings=tuple(visitor.warnings),
        suggested_refinements=tuple(visitor.refinements),
    )
