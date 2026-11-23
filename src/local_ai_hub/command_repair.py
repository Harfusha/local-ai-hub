from __future__ import annotations

import ntpath
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from .command_rollback import _close_rollback_root, _snapshot_rollback_scope
from .json_utils import dumps as json_dumps
from .process_utils import canonical_root, hidden_run_kwargs

class CommandRepairMixin:
    @staticmethod
    def _extract_failed_tests(result: dict[str, Any]) -> list[dict[str, Any]]:
        stdout = str(result.get("stdout") or "")
        stderr = str(result.get("stderr") or "")
        combined = f"{stdout}\n{stderr}"
        lines = [line.strip() for line in combined.splitlines()]

        failed_tests: list[dict[str, Any]] = []
        seen: set[Any] = set()

        # 1. Pytest
        pytest_trace_re = re.compile(r"^(?P<file>[^\s:]+):(?P<line>\d+):\s+in\s+(?P<name>\S+)")
        pytest_trace_map: dict[Any, int] = {}
        for line in lines:
            m = pytest_trace_re.match(line)
            if m:
                pytest_trace_map[(m.group("file"), m.group("name"))] = int(m.group("line"))
                pytest_trace_map[m.group("name")] = int(m.group("line"))

        pytest_failed_re = re.compile(r"^FAILED\s+(?P<file>[^\s:]+)::(?P<name>\S+?)(?:\s+-\s+(?P<msg>.*))?$")
        for line in lines:
            m = pytest_failed_re.match(line)
            if m:
                f = m.group("file")
                n = m.group("name")
                key = (f, n)
                if key not in seen:
                    seen.add(key)
                    item: dict[str, Any] = {
                        "name": n,
                        "file": f,
                        "error_message": (m.group("msg") or "").strip(),
                    }
                    line_no = pytest_trace_map.get((f, n)) or pytest_trace_map.get(n)
                    if line_no is not None:
                        item["line"] = line_no
                    failed_tests.append(item)

        # 2. Cargo
        cargo_panic_re = re.compile(
            r"^thread\s+'(?P<name>[^']+)'\s+panicked\s+at\s+(?:'(?P<msg>[^']*)'|(?P<msg2>[^,]+)),\s+(?P<file>[^:\s]+):(?P<line>\d+)"
        )
        cargo_panics: dict[str, dict[str, Any]] = {}
        for line in lines:
            m = cargo_panic_re.match(line)
            if m:
                cargo_panics[m.group("name")] = {
                    "name": m.group("name"),
                    "file": m.group("file"),
                    "line": int(m.group("line")),
                    "error_message": (m.group("msg") or m.group("msg2") or "").strip(),
                }

        cargo_failed_re = re.compile(r"^test\s+(?P<name>\S+)\s+\.\.\.\s+FAILED")
        for line in lines:
            m = cargo_failed_re.match(line)
            if m:
                n = m.group("name")
                if n not in seen:
                    seen.add(n)
                    if n in cargo_panics:
                        failed_tests.append(cargo_panics[n])
                    else:
                        failed_tests.append({
                            "name": n,
                            "file": "",
                            "error_message": "FAILED",
                        })

        for n, item in cargo_panics.items():
            if n not in seen:
                seen.add(n)
                failed_tests.append(item)

        # 3. Jest / Vitest
        jest_fail_re = re.compile(r"^[✕●]\s+(?P<name>.+?)(?:\s+\(\d+.*\))?$")
        jest_stack_re = re.compile(r"^\s*at\s+.*\(?(?P<file>[^:\s()]+\.[a-zA-Z0-9]+):(?P<line>\d+):\d+\)?")
        current_jest: dict[str, Any] | None = None
        for line in lines:
            m = jest_fail_re.match(line)
            if m:
                n = m.group("name").strip()
                if n not in seen and not n.startswith("FAIL "):
                    current_jest = {
                        "name": n,
                        "file": "",
                        "error_message": "",
                    }
            elif current_jest and not current_jest.get("file"):
                sm = jest_stack_re.match(line)
                if sm:
                    current_jest["file"] = sm.group("file")
                    current_jest["line"] = int(sm.group("line"))
                    seen.add(current_jest["name"])
                    failed_tests.append(current_jest)
                    current_jest = None

        return failed_tests
    def format(
        self,
        root: str,
        paths: list[str] | None = None,
        *,
        timeout: int | None = None,
        task_id: str = "",
        _work_attempt_fence: Any = None,
    ) -> dict[str, Any]:
        """Automatically detect local code formatters and format paths or repository."""
        resolved_root = Path(canonical_root(root))
        if not resolved_root.is_dir():
            return {"success": False, "error": f"Directory not found: {root}"}
        if not paths:
            return {
                "success": False,
                "error": "format requires explicit target paths",
                "mutation_write_set_required": True,
                "terminal": True,
                "retryable": False,
            }

        target_str = " ".join(f'"{p}"' for p in paths) if paths else "."
        cmd = None
        formatter_name = None

        if (resolved_root / "pyproject.toml").exists() or any((resolved_root / f).is_file() for f in ("setup.py", "requirements.txt")):
            if shutil.which("ruff"):
                cmd = f"ruff format {target_str}"
                formatter_name = "ruff"
            elif shutil.which("black"):
                cmd = f"black {target_str}"
                formatter_name = "black"
        elif (resolved_root / "package.json").exists():
            if shutil.which("prettier"):
                cmd = f"prettier --write {target_str}"
                formatter_name = "prettier"
        elif (resolved_root / "Cargo.toml").exists():
            if shutil.which("cargo"):
                cmd = "cargo fmt"
                formatter_name = "cargo fmt"
        elif (resolved_root / "go.mod").exists():
            if shutil.which("gofmt"):
                cmd = f"gofmt -w {target_str}"
                formatter_name = "gofmt"
        elif any((resolved_root / f).is_file() for f in os.listdir(str(resolved_root)) if f.endswith((".sln", ".csproj"))):
            if shutil.which("dotnet"):
                cmd = "dotnet format"
                formatter_name = "dotnet format"

        if not cmd:
            if shutil.which("ruff"):
                cmd = f"ruff format {target_str}"
                formatter_name = "ruff"
            elif shutil.which("black"):
                cmd = f"black {target_str}"
                formatter_name = "black"

        if not cmd:
            return {"success": False, "error": "No supported code formatter found in PATH (tried ruff, black, prettier, cargo, gofmt, dotnet)"}

        res = self.run(
            cmd,
            str(resolved_root),
            timeout=timeout or 60,
            force=True,
            task_id=task_id,
            paths=paths,
            rollback_on_failure=True,
            rollback_paths=paths,
            _work_attempt_fence=_work_attempt_fence,
        )
        res["formatter"] = formatter_name
        return res
    def lint_fix(
        self,
        root: str,
        command: str | None = None,
        paths: list[str] | None = None,
        *,
        timeout: int | None = None,
        task_id: str = "",
        _work_attempt_fence: Any = None,
    ) -> dict[str, Any]:
        """Automatically run project linters in auto-fix mode to resolve style/lint issues."""
        resolved_root = Path(root).expanduser().resolve(strict=False)
        if not resolved_root.is_dir():
            return {"success": False, "error": f"root directory does not exist: {root}"}
        if not paths:
            return {
                "success": False,
                "error": "lint_fix requires explicit target paths",
                "mutation_write_set_required": True,
                "terminal": True,
                "retryable": False,
            }

        target_str = " ".join(f'"{p}"' for p in paths) if paths else "."
        cmd = command
        linter_name = "custom"

        if not cmd:
            if (resolved_root / "pyproject.toml").exists() or any((resolved_root / f).is_file() for f in ("setup.py", "requirements.txt")):
                if shutil.which("ruff"):
                    cmd = f"ruff check --fix {target_str}"
                    linter_name = "ruff"
                elif shutil.which("autopep8"):
                    cmd = f"autopep8 --in-place --aggressive {target_str}"
                    linter_name = "autopep8"
            elif (resolved_root / "package.json").exists():
                if shutil.which("eslint"):
                    cmd = f"eslint --fix {target_str}"
                    linter_name = "eslint"
                elif shutil.which("npm"):
                    cmd = "npm run lint -- --fix"
                    linter_name = "npm lint"
            elif (resolved_root / "Cargo.toml").exists():
                if shutil.which("cargo"):
                    cmd = "cargo fix --allow-no-vcs"
                    linter_name = "cargo fix"
            elif (resolved_root / "go.mod").exists():
                if shutil.which("golangci-lint"):
                    cmd = f"golangci-lint run --fix {target_str}"
                    linter_name = "golangci-lint"
                elif shutil.which("gofmt"):
                    cmd = f"gofmt -w {target_str}"
                    linter_name = "gofmt"

        if not cmd:
            if shutil.which("ruff"):
                cmd = f"ruff check --fix {target_str}"
                linter_name = "ruff"

        if not cmd:
            return {"success": False, "error": "No supported linter with auto-fix found in PATH (tried ruff, eslint, cargo, golangci-lint)"}

        res = self.run(
            cmd,
            str(resolved_root),
            timeout=timeout or 120,
            force=True,
            task_id=task_id,
            paths=paths,
            rollback_on_failure=True,
            rollback_paths=paths,
            _work_attempt_fence=_work_attempt_fence,
        )
        res["linter"] = linter_name
        return res
    def preflight(
        self,
        cwd: str | Path,
        *,
        paths: list[str] | None = None,
        timeout: int = 10,
    ) -> dict[str, Any]:
        """Perform fast syntax and typecheck pre-flight on modified or specified files."""
        cwd_path = Path(canonical_root(cwd))
        if not cwd_path.is_dir():
            return {"success": False, "error": "Working directory does not exist"}

        target_files = [p.replace("\\", "/").strip() for p in (paths or []) if p]
        if not target_files:
            cp = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(cwd_path), capture_output=True, text=True, check=False,
                timeout=5, **hidden_run_kwargs()
            )
            if cp.returncode == 0:
                for line in cp.stdout.splitlines():
                    parts = line.strip().split(None, 1)
                    if len(parts) == 2:
                        target_files.append(parts[1].replace("\\", "/").strip())

        if not target_files:
            return {
                "success": True,
                "clean": True,
                "checker": "none",
                "message": "No modified files detected for pre-flight check",
                "errors": [],
            }

        py_files = [f for f in target_files if f.endswith(".py") and (cwd_path / f).is_file()]
        ts_files = [f for f in target_files if f.endswith((".ts", ".tsx", ".js", ".jsx")) and (cwd_path / f).is_file()]

        errors: list[dict[str, Any]] = []
        checker = "none"

        if py_files:
            checker = "py_compile"
            for pf in py_files:
                p_path = cwd_path / pf
                try:
                    compile(p_path.read_bytes(), str(p_path), "exec")
                except (SyntaxError, UnicodeError) as err:
                    syntax_message = str(getattr(err, "msg", err))
                    errors.append({
                        "file": pf,
                        "line": getattr(err, "lineno", 1) or 1,
                        "message": syntax_message,
                        "level": "syntax_error",
                    })

        if ts_files and not errors and (cwd_path / "tsconfig.json").is_file():
            checker = "tsc"
            try:
                cp_tsc = subprocess.run(
                    ["npx", "tsc", "--noEmit", "--pretty", "false"],
                    cwd=str(cwd_path), capture_output=True, text=True, check=False,
                    timeout=timeout, **hidden_run_kwargs()
                )
                if cp_tsc.returncode != 0:
                    for line in cp_tsc.stdout.splitlines():
                        if ": error TS" in line:
                            parts = line.split(":", 3)
                            if len(parts) >= 4:
                                errors.append({
                                    "file": parts[0].strip(),
                                    "line": int(parts[1].strip() or 1),
                                    "col": int(parts[2].strip() or 1),
                                    "message": parts[3].strip(),
                                    "level": "type_error",
                                })
            except Exception:
                pass

        return {
            "success": True,
            "clean": len(errors) == 0,
            "checker": checker,
            "target_files": target_files[:10],
            "errors_count": len(errors),
            "errors": errors[:5],
            "message": "Pre-flight clean" if not errors else f"Found {len(errors)} pre-flight issue(s)",
        }
    def repair_loop(
        self,
        command: str,
        cwd: str | Path,
        *,
        max_attempts: int = 3,
        task_id: str = "",
        criterion: str = "",
        timeout: int | None = None,
        fix_generator: Any | None = None,
        initial_result: dict[str, Any] | None = None,
        log_callback: Any | None = None,
        paths: list[str] | None = None,
        docker_image: str = "python:3.11-slim",
        _transaction_context: str = "",
        _work_attempt_fence: Any = None,
    ) -> dict[str, Any]:
        """Execute autonomous self-healing test loop on command failure.

        Synthesizes candidate diffs/patches, applies them with in-memory file backups,
        re-tests, and keeps successful fixes. Durable verification receipts are only
        forwarded from the command broker's execution result.
        If all attempts fail, cleanly rolls back all modified files to pristine state.
        """
        cwd_path = Path(cwd).resolve(strict=True) if _transaction_context else Path(canonical_root(cwd))
        if initial_result is not None:
            if initial_result.get("success"):
                return {
                    "success": True,
                    "repaired": False,
                    "attempts": 0,
                    "result": initial_result,
                    "message": "command passed without repair",
                }
            classification = self.classify(command)
            replay_safe = bool(classification.get("replay_safe", False))
            if classification.get("class") == "mutating":
                return {
                    "success": False,
                    "repaired": False,
                    "repair_skipped": True,
                    "outcome_unknown": True,
                    "retryable": False,
                    "terminal": True,
                    "attempts": 0,
                    "result": initial_result,
                    "error": "repair loop skipped after failed mutating command; private transaction will be discarded",
                }
            outcome_uncertain = bool(
                initial_result.get("outcome_unknown")
                or initial_result.get("timed_out")
                or initial_result.get("cancelled")
            )
            if outcome_uncertain or not replay_safe:
                uncertain = dict(initial_result)
                out_unk = bool(
                    outcome_uncertain
                    or initial_result.get("outcome_unknown")
                    or not replay_safe
                )
                uncertain["outcome_unknown"] = out_unk
                return {
                    "success": False,
                    "repaired": False,
                    "repair_skipped": True,
                    "outcome_unknown": out_unk,
                    "retryable": False,
                    "terminal": True,
                    "attempts": 0,
                    "result": uncertain,
                    "message": "repair skipped because command outcome or side effects are not safe to replay",
                }
        if _transaction_context:
            transaction_root = self._transaction_root_for_context(_transaction_context).resolve(strict=True)
            if cwd_path != transaction_root:
                return {"success": False, "error": "private transaction cwd does not match transaction context", "terminal": True, "retryable": False}
        else:
            worktree_error = self._require_task_worktree(task_id, cwd_path, command)
            if worktree_error:
                return {
                    "success": False,
                    "error": worktree_error,
                    "mutation_worktree_required": True,
                    "terminal": True,
                    "retryable": False,
                }
        scope_snapshot, scope_error = _snapshot_rollback_scope(str(cwd_path), paths)
        if scope_error:
            return {
                "success": False,
                "error": scope_error,
                "mutation_write_set_required": paths is None or not paths,
                "mutation_write_set_invalid": bool(paths),
                "terminal": True,
                "retryable": False,
            }
        assert scope_snapshot is not None
        declared_write_paths = set(scope_snapshot.files)
        _close_rollback_root(scope_snapshot.root_guard)
        if not _transaction_context:
            return self._run_private_transaction(
                command=command,
                source_root=cwd_path,
                task_id=task_id,
                paths=list(paths or []),
                timeout=int(timeout or self.timeout),
                docker_image=docker_image,
                work_attempt_fence=_work_attempt_fence,
                log_callback=log_callback,
                operation=lambda transaction_root, transaction_id: self.repair_loop(
                    command, transaction_root,
                    max_attempts=max_attempts, task_id=task_id, criterion=criterion,
                    timeout=timeout, fix_generator=fix_generator,
                    initial_result=initial_result, log_callback=log_callback,
                    paths=paths, docker_image=docker_image,
                    _transaction_context=transaction_id,
                    _work_attempt_fence=_work_attempt_fence,
                ),
            )
        initial = initial_result or self.run(
            command, str(cwd_path), timeout=timeout, force=True,
            task_id=task_id, criterion=criterion, auto_fix=False,
            paths=paths, log_callback=log_callback,
            docker_image=docker_image, _transaction_context=_transaction_context,
            _work_attempt_fence=_work_attempt_fence,
        )
        if initial.get("success"):
            return {
                "success": True,
                "repaired": False,
                "attempts": 0,
                "result": initial,
                "message": "command passed without repair",
            }
        classification = self.classify(command)
        replay_safe = bool(classification.get("replay_safe", False))
        if classification.get("class") == "mutating":
            # A failed mutating command can leave partial effects inside its
            # private transaction even when the command process exited cleanly.
            outcome_unknown = True
            return {
                "success": False,
                "repaired": False,
                "repair_skipped": True,
                "outcome_unknown": outcome_unknown,
                "retryable": False,
                "terminal": True,
                "attempts": 0,
                "result": initial,
                "error": "repair loop skipped after failed mutating command; private transaction will be discarded",
            }
        outcome_unknown = bool(
            initial.get("outcome_unknown")
            or initial.get("timed_out")
            or initial.get("cancelled")
            or not replay_safe
        )
        if outcome_unknown:
            uncertain = dict(initial)
            uncertain["outcome_unknown"] = True
            return {
                "success": False,
                "repaired": False,
                "repair_skipped": True,
                "outcome_unknown": True,
                "attempts": 0,
                "result": uncertain,
                "message": "repair skipped because command outcome or side effects are not safe to replay",
            }

        classification = self.classify(command)
        replay_safe = bool(
            classification.get("replay_safe", False)
        )
        uncertain = bool(initial.get("outcome_unknown") or initial.get("timed_out") or initial.get("in_progress"))
        unsafe_class = classification.get("class") in {"mutating", "dangerous"}
        if uncertain or unsafe_class or not replay_safe:
            return {
                "success": False,
                "repaired": False,
                "repair_skipped": True,
                "outcome_unknown": bool(uncertain or unsafe_class or not replay_safe),
                "attempts": 0,
                "result": initial,
                "message": "repair skipped because command outcome or side effects are unsafe to replay",
            }

        repair_classification = self.classify(command)
        command_class = repair_classification.get("class", "unknown")
        outcome_uncertain = bool(
            initial.get("outcome_unknown")
            or initial.get("timed_out")
            or initial.get("cancelled")
            or initial.get("aborted_interactive")
        )
        unsafe_command_class = command_class in {"mutating", "unknown"}
        if outcome_uncertain or unsafe_command_class or not repair_classification.get("replay_safe", False):
            return {
                "success": False,
                "repaired": False,
                "repair_skipped": True,
                "outcome_unknown": outcome_uncertain or unsafe_command_class,
                "attempts": 0,
                "result": initial,
                "message": (
                    "repair skipped because command outcome is uncertain"
                    if outcome_uncertain or unsafe_command_class
                    else "repair skipped because command is not replay-safe"
                ),
            }

        classification = self.classify(command)
        replay_safe = bool(
            classification.get(
                "replay_safe", classification.get("class") == "validation"
            )
        )
        uncertain = bool(initial.get("outcome_unknown") or initial.get("timed_out") or initial.get("in_progress"))
        unsafe_class = classification.get("class") in {"mutating", "dangerous"}
        if uncertain or unsafe_class or not replay_safe:
            return {
                "success": False,
                "repaired": False,
                "repair_skipped": True,
                "outcome_unknown": bool(uncertain or unsafe_class or not replay_safe),
                "attempts": 0,
                "result": initial,
                "message": "repair skipped because command outcome or side effects are unsafe to replay",
            }

        original_files: dict[Path, str | None] = {}
        attempt_history: list[dict[str, Any]] = []
        last_result = initial
        generated_patches: dict[str, str] | None = None
        generator_invoked = False

        try:
            for attempt in range(1, max(1, max_attempts) + 1):
                patches: dict[str, str] = {}
                if callable(fix_generator):
                    # A repair loop may retry applying the same bounded candidate,
                    # but it must never amplify one failed command into repeated
                    # local-model inference calls or send subsequent raw outputs.
                    if not generator_invoked:
                        generator_invoked = True
                        try:
                            gen_res = fix_generator(command, str(cwd_path), last_result)
                            if isinstance(gen_res, dict):
                                generated_patches = {str(k): str(v) for k, v in gen_res.items()}
                        except Exception as exc:
                            attempt_history.append({"attempt": attempt, "error": f"fix generator error: {exc}"})
                            continue
                    patches = dict(generated_patches or {})
                    if not patches and self.incident_store is not None:
                        rem = last_result.get("remediation") or {}
                        fix = rem.get("verified_fix")
                        if isinstance(fix, dict):
                            patches = {str(k): str(v) for k, v in fix.items()}
                elif self.incident_store is not None:
                    rem = last_result.get("remediation") or {}
                    fix = rem.get("verified_fix")
                    if isinstance(fix, dict):
                        patches = {str(k): str(v) for k, v in fix.items()}

                if not patches:
                    return {
                        "success": False,
                        "repaired": False,
                        "attempts": len(attempt_history),
                        "history": attempt_history,
                        "original_result": initial,
                        "reason": "no_candidate_synthesizer",
                        "error": "No repair candidate was synthesized.",
                    }

                patch_targets: list[tuple[str, Path, str]] = []
                invalid_patch_path = False
                for rel_path, new_content in patches.items():
                    if not isinstance(rel_path, str) or not rel_path or "\x00" in rel_path:
                        invalid_patch_path = True
                        break
                    portable = rel_path.replace("\\", "/")
                    drive, _tail = ntpath.splitdrive(rel_path)
                    parts = portable.split("/")
                    if (
                        drive or ntpath.isabs(rel_path) or portable.startswith("/")
                        or any(part in {"", ".", ".."} for part in parts)
                    ):
                        invalid_patch_path = True
                        break
                    relative = Path(*parts).as_posix()
                    if relative not in declared_write_paths:
                        invalid_patch_path = True
                        break
                    target = cwd_path.joinpath(*parts).resolve()
                    try:
                        target.relative_to(cwd_path)
                    except ValueError:
                        invalid_patch_path = True
                        break
                    patch_targets.append((relative, target, new_content))
                if invalid_patch_path:
                    return {
                        "success": False,
                        "error": "repair patch contains a path outside the declared write set",
                        "mutation_write_set_violation": True,
                        "terminal": True,
                        "retryable": False,
                        "attempts": len(attempt_history),
                    }

                applied_paths: list[Path] = []
                for rel_path, target, new_content in patch_targets:
                    if target not in original_files:
                        original_files[target] = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(new_content, encoding="utf-8")
                    applied_paths.append(target)

                re_result = self.run(
                    command, str(cwd_path), timeout=timeout, force=True,
                    task_id=task_id, criterion=criterion, auto_fix=False,
                    paths=paths, log_callback=log_callback,
                    docker_image=docker_image, _transaction_context=_transaction_context,
                    _work_attempt_fence=_work_attempt_fence,
                )
                last_result = re_result
                attempt_history.append({
                    "attempt": attempt,
                    "applied_files": [str(p.relative_to(cwd_path)) for p in applied_paths],
                    "success": bool(re_result.get("success")),
                    "re_stderr": re_result.get("stderr"),
                    "re_exit_code": re_result.get("exit_code"),
                })

                if re_result.get("success"):
                    rcpt_dict = re_result.get("verification_receipt")
                    receipt_warning = (
                        "command succeeded but broker did not provide a durable verification receipt"
                        if task_id and self.verification_store is not None and not rcpt_dict
                        else None
                    )

                    if self.incident_store is not None:
                        try:
                            rem = initial.get("remediation") or {}
                            inc_id = rem.get("incident_id")
                            if inc_id:
                                self.incident_store.record_decision(
                                    inc_id,
                                    action="apply_verified_fix",
                                    verified_fix=json_dumps([str(p.relative_to(cwd_path)) for p in applied_paths]),
                                    confidence=1.0,
                                )
                        except Exception:
                            pass

                    original_files.clear()
                    result = {
                        "success": True,
                        "repaired": True,
                        "attempts": attempt,
                        "patches_applied": [str(p.relative_to(cwd_path)) for p in applied_paths],
                        "verification_receipt": rcpt_dict,
                        "result": re_result,
                    }
                    if receipt_warning:
                        result["verification_receipt_warning"] = receipt_warning
                    return result
                else:
                    for target, orig_content in list(original_files.items()):
                        if orig_content is None:
                            target.unlink(missing_ok=True)
                        else:
                            target.write_text(orig_content, encoding="utf-8")
                    original_files.clear()

        finally:
            for target, orig_content in original_files.items():
                try:
                    if orig_content is None:
                        target.unlink(missing_ok=True)
                    else:
                        target.write_text(orig_content, encoding="utf-8")
                except Exception:
                    pass

        return {
            "success": False,
            "repaired": False,
            "attempts": len(attempt_history),
            "history": attempt_history,
            "original_result": initial,
            "error": "Self-healing repair loop exhausted without passing command.",
        }
