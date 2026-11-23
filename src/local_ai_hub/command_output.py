from __future__ import annotations

from pathlib import Path
import re
import time
from typing import Any

from .features import rollout_feature_enabled
from .trace_utils import deduplicate_stack_traces

class CommandOutputMixin:
    def _compact(self, result: dict[str, Any], command: str) -> dict[str, Any]:
        # A context artifact must be created by this compaction, never inherited
        # from a prior result or replayed as if it belonged to this execution.
        result.pop("diagnostic_context_artifact_id", None)
        stdout = str(result.get("stdout", "")); stderr = str(result.get("stderr", ""))
        argv = self._tokens(command)
        executable = Path(argv[0]).name.lower() if argv else ""
        is_pytest = executable in {"pytest", "pytest.exe", "py.test", "py.test.exe"} or (
            bool(re.fullmatch(r"(?:python(?:\d+(?:\.\d+)?)?|py)(?:\.exe)?", executable))
            and argv[1:3] == ["-m", "pytest"]
        )
        if is_pytest:
            from .command_summary import pytest_output_summary
            reported_summary = pytest_output_summary(stdout, stderr)
            if reported_summary is not None:
                result["test_summary"] = reported_summary
        stdout_compact, stdout_meta = deduplicate_stack_traces(stdout)
        stderr_compact, stderr_meta = deduplicate_stack_traces(stderr)
        clusters = list(stdout_meta.get("clusters", [])) + list(stderr_meta.get("clusters", []))
        if clusters:
            result["stack_trace_clusters"] = clusters
        if stdout_meta.get("total_collapsed", 0) > 0:
            stdout = stdout_compact
            result["stdout"] = stdout
        if stderr_meta.get("total_collapsed", 0) > 0:
            stderr = stderr_compact
            result["stderr"] = stderr
        combined_chars = len(stdout) + len(stderr)
        try:
            previously_discarded = max(0, int(result.get("discarded_output_chars", 0) or 0))
        except (TypeError, ValueError):
            previously_discarded = 0
        capture_incomplete = previously_discarded > 0 or any(
            bool(result.get(flag))
            for flag in ("output_capture_unconfirmed", "cleanup_unconfirmed")
        )
        if capture_incomplete:
            # Lost or unconfirmed capture cannot produce a complete output artifact.
            result.pop("output_artifact_id", None)
        diagnostic_artifacts_enabled = rollout_feature_enabled(self.config, "diagnostic_artifacts")
        local_diagnostic_dispatch_enabled = rollout_feature_enabled(self.config, "local_diagnostic_dispatch")
        diagnostic_artifacts_unavailable = {
            "available": False,
            "unsupported": True,
            "feature": "diagnostic_artifacts",
            "error": "diagnostic artifacts are disabled (features.diagnostic_artifacts=false)",
        }
        result["summary"] = self._deterministic_summary(result)
        classification = result.get("classification") if isinstance(result.get("classification"), dict) else {}
        if classification:
            # Keep the policy decision visible even in compact responses.
            result["allowed"] = bool(classification.get("allowed", False))
            result["class"] = str(classification.get("class", "unknown"))
            result["reason"] = str(classification.get("reason", ""))[:240]
        diagnostics = list(result.get("diagnostics") or self._extract_diagnostics(result))
        failure_summary = self._first_failure_summary({**result, "diagnostics": diagnostics})
        if result.get("remediation"):
            rem = result["remediation"]
            fix_msg = rem.get("verified_fix") or rem.get("root_cause")
            if fix_msg:
                diagnostics.insert(0, {
                    "path": "",
                    "line": 0,
                    "column": 0,
                    "message": f"Remediation guidance: {fix_msg}",
                })
        result["diagnostics"] = diagnostics
        if not result.get("success") and not result.get("cancelled"):
            if "failed_tests" not in result:
                result["failed_tests"] = self._extract_failed_tests(result)
            result["failure_summary"] = failure_summary
            result["preview"] = self._failure_preview(failure_summary)
            # Low-confidence short failures do not get the full-log artifact below.
            # Retain only the already-bounded diagnostic so the repair gate receives
            # a safe reference without persisting the raw command output.
            if combined_chars <= self.inline_chars and not result.get("artifact_id") and not failure_summary.get("path"):
                if local_diagnostic_dispatch_enabled and self.artifacts is not None:
                    diagnostic = str(result["preview"])[:800]
                    if self._local_diagnostic_preview_allowed(diagnostic):
                        result["artifact_id"] = self.artifacts.put(diagnostic, kind="local_diagnostic_context")
                        if result["artifact_id"]:
                            result["diagnostic_context_artifact_id"] = result["artifact_id"]
                    else:
                        result["local_diagnostic_status"] = "skipped_sensitive" if diagnostic else "skipped_no_preview"
                        if diagnostic_artifacts_enabled and diagnostic:
                            result["artifact_id"] = self.artifacts.put(diagnostic, kind="command_diagnostic")
                elif not diagnostic_artifacts_enabled:
                    result["diagnostic_artifacts"] = diagnostic_artifacts_unavailable
                elif self.artifacts is not None:
                    diagnostic = str(result["preview"])[:800]
                    result["artifact_id"] = self.artifacts.put(diagnostic, kind="command_diagnostic")
        if combined_chars > self.inline_chars:
            full = f"$ {command}\n\nSTDOUT:\n{stdout}\n\nSTDERR:\n{stderr}"
            if (local_diagnostic_dispatch_enabled and not diagnostic_artifacts_enabled
                    and self.artifacts is not None and not result.get("success")
                    and not result.get("cancelled") and result.get("preview")):
                diagnostic = str(result.get("preview", ""))[:800]
                if self._local_diagnostic_preview_allowed(diagnostic):
                    result["artifact_id"] = self.artifacts.put(diagnostic, kind="local_diagnostic_context")
                    if result["artifact_id"]:
                        result["diagnostic_context_artifact_id"] = result["artifact_id"]
                else:
                    result["local_diagnostic_status"] = "skipped_sensitive" if diagnostic else "skipped_no_preview"
            elif not diagnostic_artifacts_enabled:
                result["diagnostic_artifacts"] = diagnostic_artifacts_unavailable
            elif self.artifacts is not None:
                artifact_id = self.artifacts.put(full, kind="command")
                result["artifact_id"] = artifact_id
                if artifact_id and not capture_incomplete:
                    result["output_artifact_id"] = artifact_id
                if (local_diagnostic_dispatch_enabled and not result.get("success")
                        and not result.get("cancelled") and not failure_summary.get("path")):
                    diagnostic = str(result.get("preview", ""))[:800]
                    if self._local_diagnostic_preview_allowed(diagnostic):
                        context_id = self.artifacts.put(diagnostic, kind="local_diagnostic_context")
                        if context_id:
                            result["diagnostic_context_artifact_id"] = context_id
                    else:
                        result["local_diagnostic_status"] = "skipped_sensitive" if diagnostic else "skipped_no_preview"
            retained_stdout = stdout[: self.inline_chars // 2]
            retained_stderr = stderr[-self.inline_chars // 2:]
            result["discarded_output_chars"] = previously_discarded + combined_chars - len(retained_stdout) - len(retained_stderr)
            result["stdout"] = retained_stdout
            result["stderr"] = retained_stderr
            result["output_truncated"] = True
        else:
            result["output_truncated"] = bool(result.get("output_truncated")) or bool(previously_discarded)
        if result["output_truncated"]:
            if result.get("output_artifact_id"):
                result["output_recovery"] = {"available": True, "artifact_id": result["output_artifact_id"]}
            else:
                reason = "capture_incomplete" if capture_incomplete else "diagnostic_artifacts_disabled" if not diagnostic_artifacts_enabled else "artifact_unavailable"
                result["output_recovery"] = {"available": False, "reason": reason}
        return result
    def stats(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            active = [
                self._public_active(dict(v, age_ms=max(0, int((now - float(v.get("started_at", now))) * 1000))))
                for v in self._active_commands.values()
            ]
            blocked_by_reason = dict(sorted(self._blocked_by_reason.items(), key=lambda kv: (-kv[1], kv[0]))[:12])
        return {
            "enabled": self.enabled, "hits": self.hits, "misses": self.misses, "cancelled": self.cancelled,
            "coalesced_waiters": self.coalesced, "coalesced_wait_timeouts": self.coalesced_timeouts, "executed": self.executed,
            "blocked": self.blocked, "blocked_by_reason": blocked_by_reason,
            "suppressed": self.suppressed, "suppression_cache": self.suppression_cache.stats(),
            "active_count": len(active), "active": active[:24],
            "success_cache": self.success_cache.stats(), "failure_cache": self.failure_cache.stats(),
        }
