from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import shlex
import time
from typing import Any

class CommandVerificationMixin:
    def _command_execution_record_path(self, command_id: str, *, create: bool = False) -> Path:
        if not isinstance(command_id, str) or len(command_id) != 32 or any(
            character not in "0123456789abcdef" for character in command_id
        ):
            raise ValueError("invalid broker command id")
        transaction_dir = self._transaction_state_dir.resolve(strict=False)
        record_dir = self._transaction_state_dir / "execution-records"
        if record_dir.exists() and record_dir.is_symlink():
            raise ValueError("execution record directory cannot be a symlink")
        if create:
            record_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        elif not record_dir.is_dir():
            raise FileNotFoundError("execution record directory is unavailable")
        resolved_dir = record_dir.resolve(strict=True)
        if os.path.normcase(str(resolved_dir.parent)) != os.path.normcase(str(transaction_dir)):
            raise ValueError("execution record directory escaped transaction state")
        return resolved_dir / f"{hashlib.sha256(command_id.encode('ascii')).hexdigest()}.json"
    def _get_server_command_execution_record(self, command_id: str) -> dict[str, Any] | None:
        """Read a checksum-verified record through the T09 internal consumer seam."""
        try:
            path = self._command_execution_record_path(command_id)
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(payload, dict)
                or payload.get("schema") != "command_execution_record.v2"
                or "tenant_identity" in payload
            ):
                return None
            record_digest = payload.pop("record_sha256", None)
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if not isinstance(record_digest, str) or record_digest != hashlib.sha256(canonical).hexdigest():
                return None
            if (
                payload.get("command_id") != command_id
                or type(payload.get("exit_code")) is not int
                or payload.get("exit_code") != 0
                or payload.get("cached") is not False
            ):
                return None
            payload["record_sha256"] = record_digest
            return dict(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None
    def _persist_command_execution_record(self, command_id: str, payload: dict[str, Any]) -> None:
        path = self._command_execution_record_path(command_id, create=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        try:
            self._persist_transaction_journal(path, payload)
        except Exception:
            try:
                path.unlink()
            except OSError:
                pass
            raise
    def _record_command_verification(
        self,
        result: dict[str, Any],
        *,
        task_id: str,
        criterion: str,
        command: str,
        command_id: str,
        command_digest: str,
        repository_revision: str,
        duration_ms: float,
        cached: bool = False,
        project_alias: str = "",
        project_config_digest: str = "",
        project_environment_sha256: str = "",
        configured_command_sha256: str = "",
        caller_arguments_sha256: str = "",
        project_alias_required: bool = False,
        repository_root: str = "",
    ) -> None:
        if (
            result.get("success") is not True or not task_id or self.verification_store is None
            or cached or result.get("cache_hit") or result.get("coalesced")
            or any(result.get(flag, False) is not False for flag in (
                "timed_out", "cancelled", "aborted_interactive", "outcome_unknown",
                "in_progress", "cleanup_unconfirmed", "output_capture_unconfirmed",
                "log_callback_delivery_unconfirmed",
            ))
            or len(command_id) != 32 or any(character not in "0123456789abcdef" for character in command_id)
        ):
            return
        try:
            if not callable(getattr(self.artifacts, "put_json", None)):
                raise RuntimeError("canonical JSON artifact persistence is unavailable")
            from .agent_verification import (
                VerificationReceipt,
                classify_verification_command,
                criterion_evidence_type,
            )

            evidence_type = classify_verification_command(command)
            if evidence_type not in {"test", "benchmark", "source_review"}:
                return
            project_bound = any((
                project_alias,
                configured_command_sha256, caller_arguments_sha256,
            ))
            if project_bound and (
                not project_alias
                or project_alias != criterion
                or not project_config_digest
                or not project_environment_sha256
                or not configured_command_sha256
                or not caller_arguments_sha256
            ):
                return
            if not project_bound and (project_alias_required or evidence_type == "source_review"):
                return
            raw_tokens = shlex.split(command, posix=(os.name != "nt"))
            tokens = [token.lower() for token in raw_tokens]
            no_execution_options = {
                "-h", "--help", "--version", "-version", "-V",
                "--collect-only", "--co", "--fixtures", "--fixtures-per-test",
                "--list-tests", "--dry-run",
            }
            effective_raw_tokens = list(raw_tokens)
            for index, token in enumerate(raw_tokens):
                lower_token = token.lower()
                override = ""
                if lower_token in {"-o", "--override-ini"} and index + 1 < len(raw_tokens):
                    override = raw_tokens[index + 1]
                elif lower_token.startswith("--override-ini="):
                    override = token.split("=", 1)[1]
                if override.lower().startswith("addopts="):
                    effective_raw_tokens.extend(
                        shlex.split(override.split("=", 1)[1], posix=(os.name != "nt"))
                    )
            if any(token in no_execution_options for token in effective_raw_tokens) or any(
                token.lower().startswith(("--help=", "--version="))
                for token in effective_raw_tokens
            ) or any(token in {";", "&&", "||", "|", ">", "<"} for token in tokens):
                return
            executable = Path(tokens[0].strip("\"'")).stem.lower() if tokens else ""
            invoked_tools = {executable}
            if (executable.startswith("python") or executable in {"pythonw", "py"}) and "-m" in tokens:
                module_index = tokens.index("-m") + 1
                if module_index < len(tokens):
                    invoked_tools.add(tokens[module_index].split(".", 1)[0])
            if executable in {"npm", "pnpm", "yarn", "dotnet", "cargo", "go"} and len(tokens) > 1:
                invoked_tools.add(tokens[1])
                invoked_tools.update(tokens[2:4])
            test_subcommand = executable in {"npm", "pnpm", "yarn", "dotnet", "cargo", "go"} and "test" in tokens[1:5]
            test_runners = {
                "pytest", "py.test", "unittest", "jest", "vitest", "mocha",
                "phpunit", "pester", "tox", "nox", "ctest", "hyperfine",
            }
            if evidence_type in {"test", "benchmark"} and not (invoked_tools.intersection(test_runners) or test_subcommand):
                return
            if evidence_type == "source_review":
                validator_tools = {
                    "ruff", "pyflakes", "flake8", "mypy", "pylint", "eslint",
                    "tsc", "bandit", "shellcheck", "yamllint", "markdownlint",
                    "biome", "phpstan", "phpcs", "clippy",
                }
                if not invoked_tools.intersection(validator_tools):
                    return
            task_store = self.task_store or getattr(self.verification_store, "task_store", None)
            task = task_store.get(task_id) if task_store is not None else None
            from .verified_execution import contract_evidence_types

            expected_kind = criterion_evidence_type(criterion)
            if not project_bound and task is not None:
                expected_kind = contract_evidence_types(getattr(task, "contract", None)).get(criterion, expected_kind)
            if expected_kind != evidence_type:
                return
            verified_owner = str(getattr(task, "owner", "") or "").strip()
            state_data = getattr(getattr(task, "checkpoint", None), "state_data", {}) or {}
            mutation_generation = int(state_data.get("mutation_generation", 0) or 0)
            exit_code = result.get("exit_code")
            if type(exit_code) is not int or exit_code != 0 or not verified_owner:
                return
            from .agent_tasks import _task_scope_root
            from .repository_scope import canonical_repository_root

            scope_root = _task_scope_root(task)
            canonical_root = str(canonical_repository_root(repository_root))
            if not scope_root or Path(canonical_root) != Path(scope_root):
                raise ValueError("verification root differs from the server-managed task scope")
            proof = {
                "kind": "work_command_verification",
                "task_id": task_id,
                "owner": verified_owner,
                "criterion": criterion,
                "command_id": command_id,
                "command_classification": evidence_type,
                "command_sha256": command_digest,
                "exit_code": exit_code,
                "repository_revision": repository_revision,
                "mutation_generation": mutation_generation,
                "passed": True,
                "result": {"success": result.get("success") is True, "exit_code": exit_code},
                "duration_ms": max(0.0, float(duration_ms or 0)),
                "cached": cached,
            }
            if project_bound:
                binding = {
                    "project_alias": project_alias,
                    "project_config_digest": project_config_digest,
                    "configured_command_sha256": configured_command_sha256,
                    "caller_arguments_sha256": caller_arguments_sha256,
                    "command_sha256": command_digest,
                    "project_environment_sha256": project_environment_sha256,
                }
                proof.update(binding)
                proof["project_execution_binding_sha256"] = hashlib.sha256(
                    json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
            evidence_id = self.artifacts.put_json(proof, kind="command_verification")
            if not evidence_id:
                raise RuntimeError("verification evidence was not persisted")
            receipt = VerificationReceipt.create(
                task_id=task_id,
                criterion=criterion,
                passed=True,
                command_id=command_id,
                evidence_id=str(evidence_id),
                repository_revision=repository_revision,
                owner=verified_owner,
                mutation_generation=mutation_generation,
                evidence_type=evidence_type,
                details={
                    "exit_code": proof["exit_code"],
                    "duration_ms": proof["duration_ms"],
                    "cached": cached,
                },
            )
            receipt_data = receipt.to_dict()
            record = {
                "schema": "command_execution_record.v2",
                "command_id": command_id,
                "task_id": task_id,
                "owner": verified_owner,
                "criterion": criterion,
                "command_sha256": command_digest,
                "evidence_type": evidence_type,
                "repository_root": canonical_root,
                "repository_root_sha256": hashlib.sha256(canonical_root.encode("utf-8")).hexdigest(),
                "repository_revision": repository_revision,
                "mutation_generation": mutation_generation,
                "evidence_id": str(evidence_id),
                "receipt_sha256": hashlib.sha256(
                    json.dumps(receipt_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                "exit_code": exit_code,
                "cached": False,
                "project_alias": project_alias if project_bound else "",
                "project_config_digest": project_config_digest if project_bound else "",
                "project_environment_sha256": project_environment_sha256 if project_bound else "",
                "configured_command_sha256": configured_command_sha256 if project_bound else "",
                "caller_arguments_sha256": caller_arguments_sha256 if project_bound else "",
                "project_execution_binding_sha256": proof.get("project_execution_binding_sha256", ""),
                "created_at_unix": time.time(),
            }
            encoded_record = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
            record["record_sha256"] = hashlib.sha256(encoded_record).hexdigest()
            # Persist the broker-owned execution record first. VerificationStore
            # requires this record when execution provenance is enabled, so a
            # caller-supplied receipt can never race ahead and mint completion.
            self._persist_command_execution_record(command_id, record)
            if "_pending_fenced_work" in state_data:
                # The primary agent must review the handoff before task acceptance.
                self.verification_store.record(receipt, update_task=False)
            else:
                self.verification_store.record(receipt)
            result["verification_receipt"] = receipt_data
            result["verification_evidence_id"] = str(evidence_id)
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            logging.getLogger(__name__).warning(
                "Command verification evidence unavailable (%s)", type(exc).__name__,
            )
            result["verification_receipt_warning"] = (
                "command succeeded but durable verification evidence was unavailable"
            )
        except Exception as exc:
            logging.getLogger(__name__).error(
                "Unexpected command verification evidence failure (%s)", type(exc).__name__,
            )
            result["verification_receipt_warning"] = (
                "command succeeded but durable verification evidence was unavailable"
            )
    def get_command_execution_record(
        self,
        command_id: str,
        *,
        task_id: str,
        repository_root: str,
    ) -> dict[str, Any] | None:
        """Return durable broker provenance only for matching trusted scope."""
        if not isinstance(task_id, str) or not task_id:
            return None
        if not isinstance(repository_root, str) or not repository_root:
            return None
        record = self._get_server_command_execution_record(command_id)
        if record is None:
            return None
        if record.get("schema") != "command_execution_record.v2" or "tenant_identity" in record:
            return None
        try:
            canonical_root = str(Path(repository_root).expanduser().resolve(strict=False))
        except (OSError, RuntimeError, ValueError):
            return None
        if (
            record.get("task_id") != task_id
            or record.get("repository_root") != canonical_root
            or record.get("repository_root_sha256") != hashlib.sha256(canonical_root.encode("utf-8")).hexdigest()
        ):
            return None
        return dict(record)
    def set_verification_store(self, verification_store: Any) -> None:
        self.verification_store = verification_store
