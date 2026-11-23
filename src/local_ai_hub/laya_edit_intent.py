"""Laya Edit Intent & Blast-Radius Classifier.

Classifies incoming task instructions before code generation to determine:
1. Primary Intent (BUGFIX, FEATURE_ADD, REFACTOR, PERFORMANCE, TYPING_DOCS).
2. Blast Radius (LOCAL_FUNCTION, MODULE_INTERNAL, CROSS_FILE_ARCHITECTURE).
3. Targeted Validation Strategy (SYNTAX_ONLY, LOCAL_UNIT_TEST, FULL_INVARIANT_GATE).

Prevents hallucinated multi-file mutations and selects minimal necessary verification pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence


class EditIntent(StrEnum):
    BUGFIX = "bugfix"
    FEATURE_ADD = "feature_add"
    REFACTOR = "refactor"
    PERFORMANCE = "performance"
    TYPING_DOCS = "typing_docs"


class BlastRadius(StrEnum):
    LOCAL_FUNCTION = "local_function"
    MODULE_INTERNAL = "module_internal"
    CROSS_FILE_ARCHITECTURE = "cross_file_architecture"


class ValidationLevel(StrEnum):
    SYNTAX_ONLY = "syntax_only"
    LOCAL_UNIT_TEST = "local_unit_test"
    FULL_INVARIANT_GATE = "full_invariant_gate"


@dataclass(frozen=True)
class IntentAnalysisResult:
    intent: EditIntent
    blast_radius: BlastRadius
    validation_level: ValidationLevel
    confidence: float
    reasons: tuple[str, ...]
    target_files_hint: tuple[str, ...]


class LayaEditIntentClassifier:
    """Classifies task instruction intent and blast radius in <2ms."""

    def classify(self, instruction: str, affected_paths: Sequence[str] = ()) -> IntentAnalysisResult:
        inst_lower = instruction.lower()
        reasons: list[str] = []

        # 1. Determine Intent
        if any(w in inst_lower for w in ("type annotation", "typing", "docstring", "comment", "synthesize return")):
            intent = EditIntent.TYPING_DOCS
            reasons.append("Instruction specifies type annotations or documentation")
        elif any(w in inst_lower for w in ("optimize", "speedup", "perf", "cache", "simd", "mmap", "pool", "zero-copy")):
            intent = EditIntent.PERFORMANCE
            reasons.append("Instruction targets performance optimization and resource pooling")
        elif any(w in inst_lower for w in ("fix", "bug", "error", "exception", "crash", "failure", "repair", "oprav")):
            intent = EditIntent.BUGFIX
            reasons.append("Instruction targets error resolution or defect correction")
        elif any(w in inst_lower for w in ("refactor", "rename", "clean up", "split", "reorganize", "decouple")):
            intent = EditIntent.REFACTOR
            reasons.append("Instruction targets code restructuring without external interface change")
        else:
            intent = EditIntent.FEATURE_ADD
            reasons.append("Instruction targets new capability or architecture creation")

        # 2. Determine Blast Radius
        num_files = len(affected_paths)
        if num_files > 2 or any(w in inst_lower for w in ("cross-repo", "multi-repo", "system-wide", "across files", "architecture")):
            blast_radius = BlastRadius.CROSS_FILE_ARCHITECTURE
            reasons.append("Changes span multiple files or architectural boundaries")
        elif num_files == 1 or any(w in inst_lower for w in ("function", "method", "helper", "single", "locally")):
            blast_radius = BlastRadius.LOCAL_FUNCTION
            reasons.append("Changes localized to a single function or helper")
        else:
            blast_radius = BlastRadius.MODULE_INTERNAL
            reasons.append("Changes contained within a single module")

        # 3. Determine Required Validation Level
        if intent == EditIntent.TYPING_DOCS and blast_radius == BlastRadius.LOCAL_FUNCTION:
            val_level = ValidationLevel.SYNTAX_ONLY
        elif blast_radius == BlastRadius.CROSS_FILE_ARCHITECTURE or intent == EditIntent.FEATURE_ADD:
            val_level = ValidationLevel.FULL_INVARIANT_GATE
        else:
            val_level = ValidationLevel.LOCAL_UNIT_TEST

        # Extract file hints from instruction
        extracted_paths = re.findall(r"[\w./\\-]+\.(?:py|md|toml|json)", instruction)
        unique_hints = tuple(sorted(list(set(affected_paths) | set(extracted_paths))))

        return IntentAnalysisResult(
            intent=intent,
            blast_radius=blast_radius,
            validation_level=val_level,
            confidence=0.92,
            reasons=tuple(reasons),
            target_files_hint=unique_hints,
        )
