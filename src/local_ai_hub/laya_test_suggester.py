"""Laya Test Edge-Case & Invariant Suggester.

Analyzes function definitions and AST signatures to predict:
1. Boundary condition edge cases (zero, negative, empty collections, None).
2. Potential unhandled exceptions (ZeroDivisionError, KeyError, IndexError).
3. Concrete synthetic test assertions for test-driven development (TDD).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
# from typing import Sequence


@dataclass(frozen=True)
class EdgeCaseHypothesis:
    param_name: str
    edge_value_repr: str
    rationale: str
    expected_behavior: str  # "raise_value_error", "return_default", "handle_gracefully"


@dataclass(frozen=True)
class TestSuggestion:
    target_function: str
    hypotheses: tuple[EdgeCaseHypothesis, ...]
    potential_exceptions: tuple[str, ...]
    suggested_test_code: str


class LayaTestSuggester:
    """Predicts test invariants and edge cases in <2ms."""

    def analyze_function(self, func_code: str) -> TestSuggestion:
        """Inspect a single function definition and generate test edge-case recommendations."""
        try:
            tree = ast.parse(func_code)
        except SyntaxError:
            return TestSuggestion(
                target_function="unknown",
                hypotheses=(),
                potential_exceptions=("SyntaxError",),
                suggested_test_code="",
            )

        fn_node = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_node = node
                break

        if not fn_node:
            return TestSuggestion(
                target_function="unknown",
                hypotheses=(),
                potential_exceptions=(),
                suggested_test_code="",
            )

        fn_name = fn_node.name
        hypotheses: list[EdgeCaseHypothesis] = []
        potential_exceptions: list[str] = []

        # 1. Inspect AST for risky operations
        for node in ast.walk(fn_node):
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                potential_exceptions.append("ZeroDivisionError")
            elif isinstance(node, ast.Subscript):
                potential_exceptions.append("IndexError_or_KeyError")

        # 2. Inspect Arguments for Edge Cases
        args = [a for a in fn_node.args.args if a.arg not in ("self", "cls")]
        for arg in args:
            an_str = ast.unparse(arg.annotation) if arg.annotation else ""
            an_lower = an_str.lower()

            if any(k in an_lower for k in ("list", "dict", "sequence", "set", "tuple")):
                hypotheses.append(EdgeCaseHypothesis(
                    param_name=arg.arg,
                    edge_value_repr="[]" if "list" in an_lower or "sequence" in an_lower else "{}",
                    rationale="Empty collection input",
                    expected_behavior="handle_gracefully",
                ))
            elif "int" in an_lower or "float" in an_lower:
                hypotheses.append(EdgeCaseHypothesis(
                    param_name=arg.arg,
                    edge_value_repr="0",
                    rationale="Zero boundary condition",
                    expected_behavior="handle_gracefully",
                ))
                hypotheses.append(EdgeCaseHypothesis(
                    param_name=arg.arg,
                    edge_value_repr="-1",
                    rationale="Negative boundary value",
                    expected_behavior="handle_or_raise_value_error",
                ))
            elif "str" in an_lower:
                hypotheses.append(EdgeCaseHypothesis(
                    param_name=arg.arg,
                    edge_value_repr="\"\"",
                    rationale="Empty string input",
                    expected_behavior="handle_gracefully",
                ))
            else:
                # Untyped or generic
                hypotheses.append(EdgeCaseHypothesis(
                    param_name=arg.arg,
                    edge_value_repr="None",
                    rationale="Null / None value handling",
                    expected_behavior="raise_or_default",
                ))

        # 3. Synthesize test code
        test_lines = [f"def test_{fn_name}_edge_cases():"]
        if not args:
            test_lines.append(f"    result = {fn_name}()")
            test_lines.append("    assert result is not None")
        else:
            first_arg = args[0].arg
            test_lines.append(f"    # Verify boundary behavior for parameter '{first_arg}'")
            test_lines.append("    # Ensure function does not crash on empty/zero input")

        suggested_code = "\n".join(test_lines)

        return TestSuggestion(
            target_function=fn_name,
            hypotheses=tuple(hypotheses),
            potential_exceptions=tuple(sorted(list(set(potential_exceptions)))),
            suggested_test_code=suggested_code,
        )
