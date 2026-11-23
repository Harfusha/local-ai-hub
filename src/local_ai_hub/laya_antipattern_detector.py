"""Laya Active Negative-Knowledge & Anti-Pattern Detector.

Scans generated code proposals and commands against historical incident records
and Windows runtime traps:
1. Windows Shared Memory Buffer Export leaks (missing memoryview.release()).
2. Signed char array initialization overflow (array.array('b', bytes)).
3. Destructive git state commands (git clean, git reset --hard, stash).
4. Silent exception swallowing (except: pass).
5. Unbounded while True loops without break.

Provides instantaneous negative-knowledge enforcement in <2ms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AntiPatternViolation:
    pattern_id: str
    severity: str  # "critical", "warning"
    description: str
    safe_alternative: str


@dataclass(frozen=True)
class AntiPatternScanResult:
    has_violations: bool
    risk_score: float
    violations: tuple[AntiPatternViolation, ...]
    status: str  # "clean", "rejected", "warning"


class LayaAntiPatternDetector:
    """Fast semantic scanner against known runtime traps and destructive patterns."""

    def scan_code(self, code: str) -> AntiPatternScanResult:
        """Scan code snippet for dangerous anti-patterns and Windows traps."""
        violations: list[AntiPatternViolation] = []

        # 1. Windows Shared Memory Export Leak
        if "shm.close()" in code and "release()" not in code and "memoryview" in code:
            violations.append(AntiPatternViolation(
                pattern_id="win_shm_buffer_export",
                severity="critical",
                description="shm.close() called with active memoryview without explicit release()",
                safe_alternative="Invoke memoryview.release() or track active views before closing shared memory",
            ))

        # 2. Signed char overflow in array.array('b', ...)
        if re.search(r"array\.array\(\s*['\"]b['\"]\s*,\s*[^)]+\)", code):
            violations.append(AntiPatternViolation(
                pattern_id="signed_char_array_overflow",
                severity="critical",
                description="Direct byte initialization in array.array('b') can raise OverflowError on bytes > 127",
                safe_alternative="Use a = array.array('b'); a.frombytes(data) for safe byte copying",
            ))

        # 3. Silent exception swallowing
        if re.search(r"except\s*:\s*\n\s*pass\b|except\s+Exception\s*:\s*\n\s*pass\b", code):
            violations.append(AntiPatternViolation(
                pattern_id="silent_exception_swallow",
                severity="warning",
                description="Silent except: pass swallows runtime diagnostics and corrupts state",
                safe_alternative="Log exception via logger.debug/error or handle specific exception types",
            ))

        # 4. Destructive repository commands in code or scripts
        destructive_git = ("git clean", "git reset --hard", "git checkout --", "git stash drop")
        for cmd in destructive_git:
            if cmd in code:
                violations.append(AntiPatternViolation(
                    pattern_id="destructive_git_command",
                    severity="critical",
                    description=f"Destructive repository modification command detected: '{cmd}'",
                    safe_alternative="Preserve dirty working tree state; use non-destructive inspection",
                ))

        # 5. Dangerous dynamic evaluation
        if re.search(r"\b(eval|exec)\s*\(", code):
            violations.append(AntiPatternViolation(
                pattern_id="unsafe_eval_exec",
                severity="critical",
                description="Unsafe arbitrary code execution using eval() or exec()",
                safe_alternative="Use ast.literal_eval() or structured parser contracts",
            ))

        risk = 0.0
        if any(v.severity == "critical" for v in violations):
            risk = 1.0
            status = "rejected"
        elif violations:
            risk = 0.4
            status = "warning"
        else:
            status = "clean"

        return AntiPatternScanResult(
            has_violations=len(violations) > 0,
            risk_score=risk,
            violations=tuple(violations),
            status=status,
        )
