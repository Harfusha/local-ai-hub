"""Incident Intelligence and Proactive Negative Knowledge Advisory.

Extracts normalized canonical failure fingerprints from error traces and stack traces,
clustering recurring runtime incidents into categorized negative knowledge.
Proactively evaluates planned agent commands to issue early warnings before known pitfalls fire.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Volatile patterns to remove during stack trace normalization
_TEMP_PATH_PATTERN = re.compile(r"[A-Za-z]:\\[^:\n\r\t]+?\\tmp[a-zA-Z0-9_.]+|\/tmp\/[a-zA-Z0-9_.]+")
_LINE_NUM_PATTERN = re.compile(r"\bline\s+\d+\b", re.IGNORECASE)
_TIMESTAMP_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\b")
_HEX_ADDR_PATTERN = re.compile(r"\b0x[0-9a-fA-F]+\b")


@dataclass(frozen=True)
class FailureFingerprint:
    """Normalized signature of a runtime failure for incident clustering."""

    canonical_signature: str
    failure_class: str
    root_cause_summary: str
    exit_code: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FailureWarning:
    """Proactive advisory triggered before executing an action with known failure patterns."""

    warning_code: str
    reason: str
    recommended_alternative: str
    incident_reference_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FailureFingerprinter:
    """Normalizes and classifies error traces into reproducible signatures."""

    @staticmethod
    def extract_fingerprint(
        stderr_or_trace: str,
        exit_code: int | None = None,
    ) -> FailureFingerprint:
        """Strip volatile elements and classify failure type."""
        text = stderr_or_trace.strip()
        if not text:
            return FailureFingerprint(
                canonical_signature="empty_failure",
                failure_class="UNKNOWN_ERROR",
                root_cause_summary="Process failed with no stderr output",
                exit_code=exit_code,
            )

        # 1. Normalize
        cleaned = _TEMP_PATH_PATTERN.sub("<TMP_PATH>", text)
        cleaned = _LINE_NUM_PATTERN.sub("line <N>", cleaned)
        cleaned = _TIMESTAMP_PATTERN.sub("<TIMESTAMP>", cleaned)
        cleaned = _HEX_ADDR_PATTERN.sub("<HEX_ADDR>", cleaned)

        # 2. Classify
        cleaned_lower = cleaned.lower()
        if "permission denied" in cleaned_lower or "[errno 13]" in cleaned_lower:
            fclass = "FILE_LOCK_PERMISSION_DENIED"
            summary = "File is locked by an active process on Windows filesystem"
        elif "cuda out of memory" in cleaned_lower or "torch.cuda.outofmemoryerror" in cleaned_lower:
            fclass = "CUDA_OUT_OF_MEMORY"
            summary = "GPU VRAM capacity exceeded during tensor allocation"
        elif "modulenotfounderror" in cleaned_lower or "no module named" in cleaned_lower:
            fclass = "MISSING_PYTHON_DEPENDENCY"
            summary = "Import failed due to uninstalled or unpath-resolved dependency"
        elif "unexpected token '&&'" in cleaned_lower or "tokens are not allowed" in cleaned_lower:
            fclass = "SHELL_SYNTAX_INCOMPATIBILITY"
            summary = "Bash-style operators used in Windows PowerShell environment"
        elif "timeout" in cleaned_lower or "timed out" in cleaned_lower:
            fclass = "PROCESS_TIMEOUT"
            summary = "Command exceeded allocated synchronous wait deadline"
        else:
            fclass = "GENERAL_RUNTIME_EXCEPTION"
            summary = cleaned.splitlines()[-1][:150] if cleaned.splitlines() else "Runtime error"

        # Stable hash of first 3 and last 3 normalized lines
        norm_lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        core_sample = "\n".join(norm_lines[:3] + norm_lines[-3:])
        sig = hashlib.sha256(f"{fclass}:{core_sample}".encode("utf-8")).hexdigest()[:16]

        return FailureFingerprint(
            canonical_signature=sig,
            failure_class=fclass,
            root_cause_summary=summary,
            exit_code=exit_code,
        )


class ProactiveNegativeKnowledgeAdvisory:
    """Pre-execution safety auditor warning agents about known failure vectors."""

    _KNOWN_PITFALLS = [
        (
            re.compile(r"powershell.*&&"),
            FailureWarning(
                warning_code="POWERSHELL_DOUBLE_AMPERSAND",
                reason="PowerShell doesn't support '&&' in some command-line string contexts.",
                recommended_alternative="Use ';' or separate sequential commands.",
            ),
        ),
        (
            re.compile(r"pytest(?:\s+-q)?\s*$"),
            FailureWarning(
                warning_code="UNCONSTRAINED_BARE_PYTEST",
                reason="Running unconstrained pytest across all 17,500+ tests freezes development sessions.",
                recommended_alternative="Specify targeted test file (e.g. pytest tests/test_my_module.py) or category filter (-m critical).",
            ),
        ),
        (
            re.compile(r"git\s+(?:reset\s+--hard|checkout\s+--\s+\.)"),
            FailureWarning(
                warning_code="DESTRUCTIVE_GIT_RESET",
                reason="Hard git reset wipes user modifications in active dirty worktrees.",
                recommended_alternative="Inspect diff with git status and modify target files surgically.",
            ),
        ),
    ]

    @classmethod
    def audit_command(cls, command: str) -> FailureWarning | None:
        """Inspect command before execution and return warning if known to fail."""
        cmd_clean = command.strip()
        for pattern, warning in cls._KNOWN_PITFALLS:
            if pattern.search(cmd_clean):
                return warning
        return None
