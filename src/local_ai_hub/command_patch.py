from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
from typing import Any

from .command_rollback import (
    _MAX_ROLLBACK_FILE_BYTES,
    _MAX_ROLLBACK_PATCH_BYTES,
    _MAX_ROLLBACK_TOTAL_BYTES,
    _assert_patch_root,
    _patch_write_paths,
    _restore_patch_targets,
    _snapshot_patch_targets,
    _stable_rollback_status,
    simulate_patch,
)
from .process_utils import canonical_root, hidden_run_kwargs
from .work_fencing import WorkAttemptFence

class CommandPatchMixin:
    @_stable_rollback_status
    def patch_and_verify(
        self,
        patch: str,
        cwd: str | Path,
        *,
        command: str = "",
        criterion: str = "",
        task_id: str = "",
        record_verification: bool = True,
        timeout: int | None = None,
        auto_rollback: bool = True,
        log_callback: Any | None = None,
        docker_image: str = "python:3.11-slim",
        dry_run: bool = False,
        _transaction_context: str = "",
        _work_attempt_fence: WorkAttemptFence | None = None,
    ) -> dict[str, Any]:
        """Apply a unified diff, run verification tests, and auto-rollback on failure."""
        cwd_path = Path(cwd).resolve(strict=True) if _transaction_context else Path(canonical_root(cwd))
        if not patch or not patch.strip():
            return {"success": False, "error": "patch text is empty", "terminal": True, "retryable": False}
        if dry_run:
            sim = self.simulate_patch(cwd_path, patch, timeout=float(timeout or self.git_snapshot_timeout))
            return {
                "success": sim["valid"],
                "dry_run": True,
                "valid": sim["valid"],
                "files": sim["files"],
                "additions": sim["additions"],
                "deletions": sim["deletions"],
                "file_stats": sim.get("file_stats", []),
                "error": sim.get("error", "") or "",
                "whitespace_fallback_used": sim.get("whitespace_fallback_used", False),
            }
        if _transaction_context:
            transaction_root = self._transaction_root_for_context(_transaction_context).resolve(strict=True)
            if cwd_path != transaction_root:
                return {"success": False, "error": "private transaction cwd does not match transaction context", "terminal": True, "retryable": False}
        else:
            worktree_error = self._require_task_worktree(task_id, cwd_path)
            if worktree_error:
                return {
                    "success": False,
                    "error": worktree_error,
                    "mutation_worktree_required": True,
                    "terminal": True,
                    "retryable": False,
                }
        patch_bytes = patch.encode("utf-8")
        if len(patch_bytes) > _MAX_ROLLBACK_PATCH_BYTES:
            return {"success": False, "applied": False, "rolled_back": False,
                    "error": "Patch text exceeds the 64 MiB rollback safety limit",
                    "terminal": True, "retryable": False}
        try:
            write_paths = _patch_write_paths(cwd_path, patch_bytes, self.git_snapshot_timeout)
        except subprocess.TimeoutExpired as exc:
            return {
                "success": False,
                "applied": False,
                "rolled_back": False,
                "timed_out": True,
                "error": f"Patch write set metadata timed out: {str(exc)[:512]}",
                "terminal": True,
                "retryable": False,
            }
        except (OSError, ValueError) as exc:
            return {
                "success": False,
                "applied": False,
                "rolled_back": False,
                "error": f"Patch write set rejected: {str(exc)[:512]}",
                "terminal": True,
                "retryable": False,
            }
        if not _transaction_context:
            return self._run_private_transaction(
                command=command or criterion or "patch verification",
                source_root=cwd_path,
                task_id=task_id,
                paths=write_paths,
                timeout=int(timeout or self.timeout),
                docker_image=docker_image,
                work_attempt_fence=_work_attempt_fence,
                log_callback=log_callback,
                operation=lambda transaction_root, transaction_id: self.patch_and_verify(
                    patch, transaction_root,
                    command=command, criterion=criterion, task_id=task_id,
                    record_verification=record_verification, timeout=timeout,
                    auto_rollback=auto_rollback, log_callback=log_callback,
                    docker_image=docker_image, _transaction_context=transaction_id,
                    _work_attempt_fence=_work_attempt_fence,
                ),
            )

        def _mark_patch_rollback_unknown(
            failure: dict[str, Any],
            rollback_error: str,
            *,
            incident_command: str,
            repository_revision: str = "",
        ) -> None:
            failure.update({
                "rollback_error": rollback_error[:512],
                "rollback_paths": list(write_paths),
                "outcome_unknown": True,
                "fail_closed": True,
                "incident_required": True,
                "cache_hit": False,
                "coalesced": False,
                "retryable": False,
                "terminal": True,
            })
            cache_invalidation_errors: list[str] = []
            try:
                classification = self.classify(incident_command)
                identity_timeout = max(1, int(timeout or self.timeout))
                command_key, _state = self._key(
                    incident_command, str(cwd_path), classification,
                    timeout=identity_timeout,
                )
                attempt_key = self._attempt_key(
                    incident_command, str(cwd_path), timeout=identity_timeout,
                )
                for cache, key in (
                    (self.success_cache, command_key),
                    (self.failure_cache, command_key),
                    (self.suppression_cache, attempt_key),
                ):
                    try:
                        if cache.delete(key) is False:
                            cache_invalidation_errors.append("cache delete reported failure")
                    except Exception as cache_exc:
                        cache_invalidation_errors.append(str(cache_exc)[:160])
                with self._lock:
                    self._last.pop(command_key, None)
            except Exception as cache_exc:
                cache_invalidation_errors.append(str(cache_exc)[:160])
            if cache_invalidation_errors:
                failure["cache_invalidation_failed"] = True
                failure["cache_invalidation_errors"] = cache_invalidation_errors
            self._capture_rollback_unknown_incident(
                failure,
                command=incident_command,
                repository_revision=repository_revision,
            )

        patch_paths = list(write_paths)
        try:
            patch_snapshot = _snapshot_patch_targets(cwd_path, patch_paths)
            _assert_patch_root(cwd_path, patch_snapshot)
        except (OSError, ValueError, TypeError) as exc:
            return {"success": False, "applied": False, "rolled_back": False,
                    "error": f"Unsafe patch scope: {str(exc)[:512]}",
                    "terminal": True, "retryable": False}

        # 2. Check if patch applies cleanly
        apply_flags = ["--whitespace=nowarn"]
        try:
            check_proc = subprocess.run(
                ["git", "apply", "--check"] + apply_flags,
                input=patch_bytes,
                cwd=str(cwd_path), capture_output=True, check=False,
                timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "success": False,
                "applied": False,
                "rolled_back": False,
                "timed_out": True,
                "error": f"Patch check timed out: {str(exc)[:512]}",
                "terminal": True,
                "retryable": False,
            }
        if check_proc.returncode != 0:
            fallback_flags = ["--ignore-whitespace", "--ignore-space-change"]
            try:
                check_fallback = subprocess.run(
                    ["git", "apply", "--check"] + fallback_flags,
                    input=patch_bytes,
                    cwd=str(cwd_path), capture_output=True, check=False,
                    timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
                )
                if check_fallback.returncode == 0:
                    check_proc = check_fallback
                    apply_flags = fallback_flags
            except subprocess.TimeoutExpired:
                pass

        if check_proc.returncode != 0:
            err_msg = check_proc.stderr.decode("utf-8", errors="replace")
            return {
                "success": False,
                "applied": False,
                "rolled_back": False,
                "error": f"Patch check failed: {err_msg.strip()}",
                "terminal": True,
                "retryable": False,
            }

        # 3. Apply patch
        try:
            apply_proc = subprocess.run(
                ["git", "apply"] + apply_flags,
                input=patch_bytes,
                cwd=str(cwd_path), capture_output=True, check=False,
                timeout=self.git_snapshot_timeout, **hidden_run_kwargs()
            )
        except subprocess.TimeoutExpired as exc:
            failure = {
                "success": False,
                "applied": None,
                "timed_out": True,
                "apply_state_unknown": True,
                "rolled_back": False,
                "error": "Patch application timed out; filesystem outcome is unknown",
            }
            _mark_patch_rollback_unknown(
                failure,
                str(exc),
                incident_command=command or criterion or "patch apply",
            )
            return failure
        if apply_proc.returncode != 0:
            err_msg = apply_proc.stderr.decode("utf-8", errors="replace")
            return {
                "success": False, "applied": False, "rolled_back": False,
                "error": f"Patch apply failed: {err_msg.strip()}",
                "terminal": True, "retryable": False,
            }


        try:
            _assert_patch_root(cwd_path, patch_snapshot)
            applied_snapshot = _snapshot_patch_targets(
                cwd_path,
                patch_paths,
                retain_contents=False,
                max_file_bytes=_MAX_ROLLBACK_FILE_BYTES + len(patch_bytes),
                max_total_bytes=_MAX_ROLLBACK_TOTAL_BYTES + len(patch_bytes),
            )
            _assert_patch_root(cwd_path, patch_snapshot)
        except (OSError, ValueError, TypeError) as exc:
            return {
                "success": False,
                "applied": True,
                "rolled_back": False,
                "error": "Cannot establish patch ownership state after apply",
                "rollback_error": str(exc)[:512],
                "terminal": True,
                "retryable": False,
            }

        # 4. Helper rollback closure
        def _do_rollback() -> tuple[bool, str | None]:
            try:
                _restore_patch_targets(cwd_path, patch_snapshot, applied_snapshot)
                return True, None
            except Exception as exc:
                return False, f"{type(exc).__name__}: {exc}"

        # 5. Syntax pre-flight check on modified Python files
        modified_py_files = [cwd_path / rel for rel in patch_paths if rel.endswith(".py")]
        for py_file in modified_py_files:
            if py_file.is_file():
                try:
                    compile(py_file.read_bytes(), str(py_file), "exec")
                except (SyntaxError, UnicodeError) as syn_err:
                    syntax_message = str(getattr(syn_err, "msg", syn_err))
                    rolled_back = False
                    rollback_error = None
                    if auto_rollback:
                        rolled_back, rollback_error = _do_rollback()
                    failure = {
                        "success": False,
                        "applied": False,
                        "rolled_back": rolled_back,
                        "error": f"Syntax error in modified file {py_file.name}: {syntax_message}",
                        "diagnostics": [{"path": str(py_file.relative_to(cwd_path)), "message": syntax_message}],
                    }
                    if rollback_error:
                        _mark_patch_rollback_unknown(
                            failure,
                            rollback_error,
                            incident_command=command or criterion or "patch validation",
                        )
                    return failure

        # 6. Determine test command
        test_cmd = command.strip() or criterion.strip()
        auto_detected_tests: list[str] = []
        incompatible_detected_tests: list[str] = []
        affected_test_selection_widened = False
        selection_error = ""
        requires_multiple_runners = False
        invalid_affected_selection = False
        if test_cmd.lower() == "auto":
            all_modified = list(patch_paths)
            det = None
            try:
                from .repo_tools import RepositoryTools
                from .deterministic import DeterministicEngine
                rt = RepositoryTools(self.config)
                det = DeterministicEngine(self.config, rt)
            except Exception:
                affected_test_selection_widened = True
                selection_error = "automatic test selection engine unavailable"

            aff = None
            if det is not None:
                try:
                    aff = det.affected_tests(str(cwd_path), changed_paths=all_modified)
                except Exception:
                    affected_test_selection_widened = True
                    selection_error = "automatic affected-test selection failed"

            if isinstance(aff, dict):
                excluded = aff.get("excluded_incompatible_tests", [])
                if not isinstance(excluded, list) or any(not isinstance(path, str) for path in excluded):
                    selection_error = "automatic test selection returned invalid incompatible test paths"
                    invalid_affected_selection = True
                    affected_test_selection_widened = True
                else:
                    incompatible_detected_tests = list(dict.fromkeys(excluded))
                requires_multiple_runners = aff.get("requires_multiple_runners") is True
                try:
                    confidence = float(aff.get("confidence", 0.0))
                except (TypeError, ValueError):
                    confidence = 0.0
                auto_detected_tests = [str(path) for path in aff.get("test_files", []) if isinstance(path, str)]
                if (
                    isinstance(aff, dict)
                    and aff.get("success")
                    and aff.get("selection_complete") is True
                    and not incompatible_detected_tests
                    and not requires_multiple_runners
                    and not selection_error
                    and confidence >= 0.95
                    and auto_detected_tests
                ):
                    from .test_selection import automatic_runner, compatible_tests, runner_path_argument
                    runner = automatic_runner(auto_detected_tests)
                    auto_detected_tests, incompatible_detected_tests = compatible_tests(auto_detected_tests, runner)
                    quote_path = (lambda value: subprocess.list2cmdline([value])) if os.name == "nt" else shlex.quote
                    quoted = " ".join(quote_path(runner_path_argument(path)) for path in auto_detected_tests)
                    if runner == "pytest":
                        test_cmd = f"python -m pytest {quoted} -q"
                    elif runner == "npm":
                        test_cmd = f"npm test -- {quoted}"
                    elif runner == "dotnet":
                        test_cmd = "dotnet test"
                    else:
                        # Use the existing full-suite detection for unsupported automatic runners.
                        affected_test_selection_widened = True
                else:
                    affected_test_selection_widened = True
            elif det is not None:
                affected_test_selection_widened = True

            if affected_test_selection_widened:
                try:
                    matrix = det.test_matrix(str(cwd_path)) if det is not None else {}
                    auto_detected_tests = [
                        str(item.get("path"))
                        for item in matrix.get("test_files", [])
                        if isinstance(item, dict) and item.get("path")
                    ]
                    from .test_selection import compatible_tests
                    auto_detected_tests, matrix_incompatible_tests = compatible_tests(
                        auto_detected_tests, str(matrix.get("framework", "unknown")),
                    )
                    incompatible_detected_tests = list(dict.fromkeys(
                        [*incompatible_detected_tests, *matrix_incompatible_tests]
                    ))
                    test_cmd = str(matrix.get("run_all_command") or "").strip()
                    if test_cmd and not invalid_affected_selection:
                        selection_error = ""
                except Exception:
                    test_cmd = ""
                    selection_error = selection_error or "automatic test selection and full-suite runner detection failed"

            if incompatible_detected_tests or requires_multiple_runners:
                selection_error = "automatic verification requires multiple test runners; provide an explicit validation command"
            if affected_test_selection_widened and not test_cmd:
                selection_error = selection_error or "automatic test selection was uncertain and no full-suite runner was detected"
            if selection_error:
                rollback_error = ""
                if auto_rollback:
                    try:
                        _do_rollback()
                    except Exception as rb_exc:
                        rollback_error = str(rb_exc)[:512]
                return {
                    "success": False,
                    "applied": False,
                    "rolled_back": auto_rollback and not rollback_error,
                    "error": selection_error,
                    "affected_test_selection_widened": True,
                    "affected_tests_run": auto_detected_tests,
                    "excluded_incompatible_tests": incompatible_detected_tests,
                    **({"rollback_error": rollback_error} if rollback_error else {}),
                }

        if not test_cmd:
            return {
                "success": True,
                "applied": True,
                "tests_passed": True,
                "affected_tests_run": [],
                "affected_test_selection_widened": affected_test_selection_widened,
                "message": "Patch applied cleanly and passed syntax verification (no tests required or specified)",
            }

        # 7. Run validation command
        run_res = self.run(
            test_cmd, str(cwd_path),
            timeout=timeout, force=True, task_id=task_id, criterion=criterion,
            paths=write_paths,
            record_verification=record_verification,
            # patch_and_verify owns restoration from its validated snapshot; a
            # second rollback inside run() would change the file before this
            # layer verifies ownership and cause a false unknown outcome.
            rollback_on_failure=False,
            log_callback=log_callback,
            docker_image=docker_image,
            _transaction_context=_transaction_context,
            _work_attempt_fence=_work_attempt_fence,
        )

        run_outcome_unknown = bool(
            run_res.get("outcome_unknown") or run_res.get("cleanup_unconfirmed")
        )
        if run_res.get("success") and not run_outcome_unknown:
            rcpt_data = run_res.get("verification_receipt")
            result = {
                "success": True,
                "applied": True,
                "tests_passed": True,
                "command": test_cmd,
                "affected_tests_run": auto_detected_tests,
                "excluded_incompatible_tests": incompatible_detected_tests,
                "affected_test_selection_widened": affected_test_selection_widened,
                "duration_ms": run_res.get("duration_ms"),
                "verification_receipt": rcpt_data,
                "message": "Patch applied and verified successfully",
            }
            if record_verification and task_id and self.verification_store is not None and not rcpt_data:
                result["verification_receipt_warning"] = (
                    "command succeeded but broker did not provide a durable verification receipt"
                )
            return result
        else:
            rolled_back = False
            rollback_error = None
            if auto_rollback and not run_res.get("cleanup_unconfirmed"):
                rolled_back, rollback_error = _do_rollback()
            failure = {
                "success": False,
                "applied": False,
                "rolled_back": rolled_back,
                "error": (
                    "Validation outcome is unknown after applying patch"
                    if run_outcome_unknown
                    else "Validation command failed after applying patch"
                ),
                "command": test_cmd,
                "affected_tests_run": auto_detected_tests,
                "excluded_incompatible_tests": incompatible_detected_tests,
                "affected_test_selection_widened": affected_test_selection_widened,
                "exit_code": run_res.get("exit_code"),
                "stdout": run_res.get("stdout"),
                "stderr": run_res.get("stderr"),
                "diagnostics": run_res.get("diagnostics", []),
                "remediation": run_res.get("remediation"),
                **({"rollback_error": rollback_error} if rollback_error else {}),
            }
            if rollback_error or run_outcome_unknown:
                _mark_patch_rollback_unknown(
                    failure,
                    rollback_error
                    or str(run_res.get("rollback_error") or "validation outcome is unknown"),
                    incident_command=test_cmd,
                    repository_revision=str(run_res.get("repository_revision") or ""),
                )
            return failure

    def patch_dry_run(
        self,
        cwd: str | Path,
        patch: str,
        *,
        timeout: float | None = None,
        allow_whitespace_fallback: bool = True,
    ) -> dict[str, Any]:
        """Alias for simulate_patch."""
        return self.simulate_patch(
            cwd,
            patch,
            timeout=timeout,
            allow_whitespace_fallback=allow_whitespace_fallback,
        )

    def simulate_patch(
        self,
        cwd: str | Path,
        patch: str,
        *,
        timeout: float | None = None,
        allow_whitespace_fallback: bool = True,
    ) -> dict[str, Any]:
        """In-memory dry-run patch simulation without modifying files on disk."""
        return simulate_patch(
            cwd,
            patch,
            timeout=float(timeout or self.git_snapshot_timeout),
            allow_whitespace_fallback=allow_whitespace_fallback,
        )

