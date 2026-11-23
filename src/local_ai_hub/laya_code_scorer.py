"""Laya Real-Time Code Quality & Complexity Scorer.

Calculates sub-2ms code quality metrics and structural hygiene indicators:
1. Maintainability Index (MI) normalized to 0-100 scale.
2. Cyclomatic Complexity based on branching nodes (if/for/while/try/bool ops).
3. Type Annotation Coverage & Docstring Density.
4. Overall Quality Score [0.0, 1.0] used for reward signals and commit gating.
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
# from typing import Sequence


@dataclass(frozen=True)
class CodeQualityScore:
    overall_score: float  # [0.0, 1.0]
    maintainability_index: float  # [0, 100]
    cyclomatic_complexity: int
    lines_of_code: int
    has_docstrings: bool
    type_coverage_percent: float
    recommendations: tuple[str, ...]


class LayaCodeScorer:
    """Fast AST-based code health and maintainability scorer."""

    def score_code(self, source_code: str) -> CodeQualityScore:
        """Analyze Python source snippet and compute comprehensive quality score."""
        lines = [line.strip() for line in source_code.splitlines() if line.strip() and not line.strip().startswith("#")]
        loc = len(lines)
        if loc == 0:
            return CodeQualityScore(
                overall_score=1.0,
                maintainability_index=100.0,
                cyclomatic_complexity=1,
                lines_of_code=0,
                has_docstrings=True,
                type_coverage_percent=100.0,
                recommendations=(),
            )

        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return CodeQualityScore(
                overall_score=0.1,
                maintainability_index=10.0,
                cyclomatic_complexity=10,
                lines_of_code=loc,
                has_docstrings=False,
                type_coverage_percent=0.0,
                recommendations=("Fix syntax errors in Python code",),
            )

        # 1. Calculate Cyclomatic Complexity
        # V(G) = E - N + 2P ≈ 1 + number of branching points
        branch_points = 0
        total_functions = 0
        typed_arguments = 0
        total_arguments = 0
        typed_returns = 0
        has_docstring_count = 0

        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
                branch_points += 1
            elif isinstance(node, ast.BoolOp):
                branch_points += max(0, len(node.values) - 1)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total_functions += 1
                if ast.get_docstring(node):
                    has_docstring_count += 1
                if node.returns:
                    typed_returns += 1

                args = node.args.args
                # Exclude 'self' and 'cls'
                actual_args = [a for a in args if a.arg not in ("self", "cls")]
                total_arguments += len(actual_args)
                typed_arguments += sum(1 for a in actual_args if a.annotation is not None)

        cyclomatic = 1 + branch_points

        # 2. Type Coverage
        if total_arguments > 0:
            arg_type_ratio = typed_arguments / total_arguments
        else:
            arg_type_ratio = 1.0

        ret_type_ratio = typed_returns / max(1, total_functions) if total_functions > 0 else 1.0
        type_coverage = ((arg_type_ratio + ret_type_ratio) / 2.0) * 100.0

        # 3. Maintainability Index (Simplified Halstead/McCabe derivative)
        # MI = 171 - 5.2 * ln(Halstead Volume) - 0.23 * Cyclomatic - 16.2 * ln(LOC)
        # Bounded between 0 and 100
        vol_approx = max(1.0, loc * 4.5)
        raw_mi = 171.0 - (5.2 * math.log(vol_approx)) - (0.23 * cyclomatic) - (16.2 * math.log(max(1, loc)))
        # Normalize to 0-100
        mi = max(0.0, min(100.0, (raw_mi * 100.0) / 171.0))

        # 4. Recommendations
        recommendations: list[str] = []
        if cyclomatic > 10:
            recommendations.append("Reduce cyclomatic complexity by decomposing nested branches")
        if type_coverage < 60.0:
            recommendations.append("Add type annotations to function parameters and return values")
        if total_functions > 0 and has_docstring_count < total_functions:
            recommendations.append("Add docstrings to explain module/function behavior")
        if loc > 120 and total_functions <= 1:
            recommendations.append("Decompose long linear script into modular helper functions")

        # 5. Composite Overall Score [0.0, 1.0]
        score = (
            (mi / 100.0) * 0.40 +
            (type_coverage / 100.0) * 0.30 +
            (max(0.0, 1.0 - (cyclomatic / 20.0))) * 0.30
        )
        overall = max(0.1, min(1.0, score))

        return CodeQualityScore(
            overall_score=round(overall, 3),
            maintainability_index=round(mi, 2),
            cyclomatic_complexity=cyclomatic,
            lines_of_code=loc,
            has_docstrings=(has_docstring_count == total_functions and total_functions > 0),
            type_coverage_percent=round(type_coverage, 2),
            recommendations=tuple(recommendations),
        )
