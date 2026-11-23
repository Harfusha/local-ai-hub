from __future__ import annotations

from collections.abc import Mapping, Sequence
import ntpath
import os
from pathlib import Path
import shutil
import threading
from typing import Any
import re

from .command_policy import is_interactive_command_prompt, is_interactive_output_prompt
from .features import rollout_feature_enabled

_DIAGNOSTIC_PATTERNS = [
    re.compile(r"^(?P<path>[^:\n]+):(?P<line>\d+)(?::(?P<col>\d+))?[:\s]+(?P<msg>.+)$"),
    re.compile(r"^FAILED\s+(?P<path>[^:\s]+)(?:::(?P<msg>.+))?$"),
]


def _is_interactive_prompt(text: str) -> bool:
    return is_interactive_command_prompt(text) or is_interactive_output_prompt(text)

class CommandDiagnosticsMixin:
    def _capture_rollback_unknown_incident(
        self,
        result: dict[str, Any],
        *,
        command: str,
        repository_revision: str = "",
        affected_paths: Sequence[str] | None = None,
    ) -> None:
        if self.incident_store is None:
            return
        try:
            from .agent_incidents import ToolOutcome

            incident = self.incident_store.capture(ToolOutcome(
                tool_name="command",
                command=command,
                error=f"rollback failed; command filesystem outcome is unknown: {result.get('rollback_error', '')}",
                exit_code=int(result.get("exit_code", 1) or 1),
                state_revision=repository_revision,
                timed_out=bool(result.get("timed_out")),
                cancelled=bool(result.get("cancelled")),
                metadata={"outcome_unknown": True, "rollback_error": result.get("rollback_error", "")},
                affected_paths=tuple(
                    affected_paths
                    if affected_paths is not None
                    else result.get("rollback_paths", ())
                ),
            ))
            if incident:
                result["incident_id"] = incident.incident_id
                result["incident_recorded"] = True
        except Exception as exc:
            result["incident_recording_failed"] = True
            result["incident_recording_error_type"] = type(exc).__name__
    @staticmethod
    def _deterministic_summary(result: dict[str, Any], limit: int = 60) -> str:
        text = (str(result.get("stdout", "")) + "\n" + str(result.get("stderr", ""))).strip()
        lines = text.splitlines()
        if len(lines) <= limit:
            return text
        needles = ("error", "fail", "fatal", "warning", "assert", "exception", "traceback", "passed", "failed", "success", "tests", "errors")
        selected = [line for line in lines if any(n in line.lower() for n in needles)]
        # Keep final framework summary because pytest/phpunit/cargo/go normally report counts there.
        tail = lines[-min(12, len(lines)):]
        for line in tail:
            if line not in selected:
                selected.append(line)
        if len(selected) < limit // 2:
            selected = lines[: max(8, limit // 5)] + selected
        # Reserve space for the final framework lines instead of appending them
        # after a full limit of earlier skip/error diagnostics.
        tail = tail[-max(1, limit):]
        selected = [line for line in selected if line not in tail]
        return "\n".join(selected[:max(0, limit - len(tail))] + tail)
    @staticmethod
    def _distill_error(result: dict[str, Any]) -> str:
        """Extract a high-density, concise 1-3 line failure cause from command output."""
        if result.get("success"):
            return ""
        diagnostics = result.get("diagnostics", [])
        if diagnostics:
            parts = []
            for d in diagnostics[:2]:
                path = d.get("path")
                line = d.get("line")
                msg = str(d.get("message") or "").strip()
                if path and line:
                    parts.append(f"{path}:{line}: {msg}")
                elif msg:
                    parts.append(msg)
            if parts:
                return "\n".join(parts)[:300]
        text = (str(result.get("stderr", "")) + "\n" + str(result.get("stdout", ""))).strip()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines:
            for ln in reversed(lines):
                if any(k in ln.lower() for k in ("error", "failed", "exception", "fatal", "traceback")):
                    return ln[:240]
            return lines[-1][:240]
        return f"Command failed with exit code {result.get('exit_code', 1)}"
    def _distill_error_with_model(
        self, result: dict[str, Any], *, cancel_event: threading.Event | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        if not callable(self.error_distiller) or (cancel_event is not None and cancel_event.is_set()):
            return ""
        payload = {
            "exit_code": int(result.get("exit_code", 1) or 1),
            "summary": str(result.get("summary", ""))[:4000],
            "diagnostics": list(result.get("diagnostics", []))[:2],
        }
        try:
            options = {}
            if cancel_event is not None:
                options["cancel_event"] = cancel_event
            if timeout_seconds is not None:
                options["timeout_seconds"] = timeout_seconds
            distilled = self.error_distiller(payload, **options)
        except Exception:
            return ""
        if cancel_event is not None and cancel_event.is_set():
            return ""
        if isinstance(distilled, dict):
            if distilled.get("success") is not True:
                return ""
            distilled = distilled.get("text")
        return distilled.strip()[:300] if isinstance(distilled, str) else ""
    def _expected_search_no_match(
        self,
        command: str,
        classification: Mapping[str, Any],
        result: Mapping[str, Any],
        argv_override: Sequence[str] | None = None,
    ) -> bool:
        """Recognize empty direct-search results without turning them into passes."""
        if classification.get("class") != "read" or result.get("success") is not False:
            return False
        if type(result.get("exit_code")) is not int or result["exit_code"] != 1:
            return False
        if result.get("stdout") != "" or result.get("stderr") != "" or result.get("error"):
            return False
        if any(result.get(flag) for flag in (
            "timed_out", "cancelled", "outcome_unknown", "cleanup_unconfirmed",
            "output_capture_unconfirmed", "output_truncated", "discarded_output_chars",
            "log_chunks_dropped", "log_callback_delivery_unconfirmed",
            "log_callback_dropped_chars", "incident_required",
        )):
            return False
        try:
            if argv_override is None:
                if self._needs_shell(command):
                    return False
                argv = self._tokens(command)
            else:
                if isinstance(argv_override, (str, bytes)):
                    return False
                argv = list(argv_override)
        except (TypeError, ValueError):
            return False
        if not argv or any(type(part) is not str or "\x00" in part for part in argv):
            return False
        executable = ntpath.basename(argv[0].strip('"')).lower()
        if executable in {"rg", "rg.exe", "ripgrep", "ripgrep.exe"}:
            return len(argv) > 1 and not any(part == "--pre" or part.startswith("--pre=") for part in argv[1:])
        if executable not in {"git", "git.exe"}:
            return False
        index = 1
        while index < len(argv):
            if argv[index] == "--no-pager":
                index += 1
            elif argv[index] == "-C" and index + 1 < len(argv):
                index += 2
            else:
                break
        return index + 1 < len(argv) and argv[index] == "grep"
    @staticmethod
    def _extract_diagnostics(result: dict[str, Any], limit: int = 30) -> list[dict[str, Any]]:
        # stdout/stderr are captured independently, so their true interleaving is
        # unavailable. Preserve each stream's order while preferring explicit
        # failures over informational diagnostics and warnings from a failed run.
        # This keeps an early stdout warning from masking the useful stderr error.
        streams = (str(result.get("stdout", "")), str(result.get("stderr", "")))
        failures: list[dict[str, Any]] = []
        others: list[dict[str, Any]] = []
        patterns = _DIAGNOSTIC_PATTERNS
        failure_terms = ("error", "fatal", "exception", "traceback", "assertionerror", "panic", "failed", "failure")
        for text in streams:
            for raw in text.splitlines():
                line = raw.strip()
                if not line or line.startswith(("===", "___")):
                    continue
                matched = None
                matched_failure = False
                for pattern_index, pattern in enumerate(patterns):
                    m = pattern.match(line)
                    if m:
                        matched = m
                        # The dedicated pytest `FAILED path::test` pattern keeps
                        # the path but strips the word FAILED from its message.
                        # Preserve its failure semantics from the original line.
                        matched_failure = pattern_index == 1
                        break
                message = ""
                diagnostic: dict[str, Any] | None = None
                if matched:
                    data = matched.groupdict()
                    message = str(data.get("msg") or line)[:500]
                    diagnostic = {
                        "path": data.get("path", ""),
                        "line": int(data.get("line") or 0),
                        "column": int(data.get("col") or 0),
                        "message": message,
                    }
                elif any(term in line.lower() for term in failure_terms):
                    message = line[:500]
                    diagnostic = {"path": "", "line": 0, "column": 0, "message": message}
                if diagnostic is None:
                    continue
                target = failures if (
                    matched_failure
                    or any(term in line.lower() for term in failure_terms)
                ) else others
                if len(target) < limit:
                    target.append(diagnostic)
        return (failures + others)[:limit]
    @staticmethod
    def _failure_preview(summary: dict[str, Any]) -> str:
        """Expose only the narrow first-failure slice in command results."""
        path = str(summary.get("path") or "")
        line = int(summary.get("line") or 0)
        message = str(summary.get("message") or "").strip()
        if path and line:
            return f"{path}:{line}: {message}"[:800]
        if path:
            return f"{path}: {message}"[:800]
        return message[:800]
    @classmethod
    def _first_failure_summary(cls, result: dict[str, Any]) -> dict[str, Any]:
        """Return first deterministic failure location without replaying verbose logs."""
        diagnostics = list(result.get("diagnostics") or cls._extract_diagnostics(result, limit=1))
        if diagnostics:
            first = diagnostics[0]
            return {
                "path": str(first.get("path") or ""),
                "line": int(first.get("line") or 0),
                "message": str(first.get("message") or "").strip()[:500],
            }
        return {
            "path": "",
            "line": 0,
            "message": cls._distill_error(result)[:500],
        }
    @classmethod
    def _is_interactive_prompt(cls, text: str) -> bool:
        return _is_interactive_prompt(text)
    def _local_diagnostic_context(self, result: dict[str, Any], root: str) -> dict[str, str] | None:
        """Validate a newly compacted, bounded diagnostic before local inference."""
        if not rollout_feature_enabled(self.config, "local_diagnostic_dispatch") or self.artifacts is None:
            return None
        if (result.get("success") is not False or type(result.get("exit_code")) is not int
                or result["exit_code"] == 0 or result.get("cache_hit") is not False
                or result.get("coalesced") is not False):
            return None
        if any(result.get(flag, False) is not False for flag in (
            "timed_out", "cancelled", "outcome_unknown", "cleanup_unconfirmed", "output_capture_unconfirmed",
            "in_progress", "aborted_interactive", "log_callback_delivery_unconfirmed", "budget_accounting_unavailable",
        )):
            return None
        failure = result.get("failure_summary")
        if not isinstance(failure, dict) or failure.get("path"):
            return None
        state = result.get("repo_state")
        artifact_id, preview = result.get("diagnostic_context_artifact_id"), result.get("preview")
        if (not isinstance(state, dict) or not isinstance(state.get("root"), str)
                or not isinstance(root, str) or not root or not isinstance(artifact_id, str) or not artifact_id
                or not isinstance(preview, str) or not preview):
            return None
        try:
            if Path(state["root"]).resolve(strict=True) != Path(root).resolve(strict=True):
                return None
            artifact = self.artifacts.get(artifact_id, max_chars=801)
        except Exception:
            return None
        text = preview[:800]
        if not self._local_diagnostic_preview_allowed(text):
            return None
        if (not isinstance(artifact, dict) or artifact.get("success") is not True
                or artifact.get("kind") != "local_diagnostic_context" or artifact.get("text") != text
                or artifact.get("next_offset") is not None):
            return None
        return {"artifact_id": artifact_id, "summary": text}
    @staticmethod
    def _local_diagnostic_preview_allowed(text: str) -> bool:
        if not isinstance(text, str) or not text:
            return False
        try:
            from .agent_consistency import _redact_memory_text
            return _redact_memory_text(text, limit=800) == text
        except Exception:
            return False
    def _mark_rollback_outcome_unknown(
        self,
        result: dict[str, Any],
        *,
        command_key: str,
        attempt_key: str,
        error: BaseException,
        rollback_paths: Sequence[str] | None = None,
    ) -> None:
        result.update({
            "failure_kind": "rollback_incomplete",
            "rolled_back": False,
            "rollback_paths": list(rollback_paths or ()),
            "rollback_error": str(error)[:512],
            "outcome_unknown": True,
            "fail_closed": True,
            "incident_required": True,
            "terminal": True,
            "cache_hit": False,
            "coalesced": False,
            "retryable": False,
        })
        invalidation_errors: list[str] = []
        for cache, key in (
            (self.success_cache, command_key),
            (self.failure_cache, command_key),
            (self.suppression_cache, attempt_key),
        ):
            try:
                if cache.delete(key) is False:
                    invalidation_errors.append("cache delete reported failure")
            except Exception as cache_exc:
                invalidation_errors.append(str(cache_exc)[:160])
            try:
                cache.clear()
            except Exception as cache_exc:
                invalidation_errors.append(f"cache clear failed: {str(cache_exc)[:160]}")
        with self._lock:
            self._last.pop(command_key, None)
        if invalidation_errors:
            result["cache_invalidation_failed"] = True
            result["cache_invalidation_errors"] = invalidation_errors
    @staticmethod
    def _needs_model_error_distillation(result: dict[str, Any]) -> bool:
        if result.get("diagnostics"):
            return False
        text = (str(result.get("stderr", "")) + "\n" + str(result.get("stdout", ""))).strip()
        return bool(text)
    @staticmethod
    def _non_retryable_failure(result: dict[str, Any]) -> bool:
        if result.get("success") or result.get("timed_out"):
            return False
        text = (str(result.get("error", "")) + "\n" + str(result.get("stderr", ""))).lower()
        return int(result.get("exit_code", 0) or 0) == 127 or any(marker in text for marker in (
            "failed to spawn process", "command not found", "is not recognized as an internal", "no such file or directory",
        ))
    def _unavailable_executable(
        self,
        command: str,
        cwd: str,
        *,
        argv_override: Sequence[str] | None = None,
    ) -> str | None:
        if argv_override is None and self._needs_shell(command):
            if os.name == "nt":
                return None if (shutil.which("pwsh") or shutil.which("powershell")) else "powershell"
            return None if (shutil.which("sh") or Path("/bin/sh").exists()) else "sh"
        tokens = list(argv_override) if argv_override is not None else self._tokens(command)
        if not tokens:
            return None
        raw = tokens[0].strip('"')
        if argv_override is not None and os.name == "nt" and raw.lower() in {"ver", "set"}:
            return raw
        if os.name == "nt" and raw.lower() in {"ver", "set"}:
            return None if shutil.which("cmd") else "cmd"
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = Path(cwd) / candidate
        has_path = any(marker in raw for marker in ("/", "\\"))
        if has_path:
            return None if candidate.exists() else raw
        return None if shutil.which(raw) else raw
    def set_error_distiller(self, error_distiller: Any) -> None:
        """Set the optional local-model fallback for unstructured command failures."""
        self.error_distiller = error_distiller
