from __future__ import annotations

from collections.abc import Mapping
from contextlib import nullcontext
import contextvars
import math
import os
from pathlib import Path
import queue
import sys
import threading
import time
from typing import Any

from .agent_identity import AgentScope, ScopeContext
from .agent_task_models import (
    CompletionGateError,
    GoalContract,
    TaskCheckpoint,
    TaskState,
)
from .token_accounting import json_tokens


TaskStore = None


class TaskMemoryMixin:
    def set_laya_completion_observer(self, observer: Any | None) -> None:
        """Install a best-effort observer for typed completion-gate outcomes."""
        if observer is not None and not callable(observer):
            raise TypeError("Laya completion observer must be callable")
        self._laya_completion_observer = observer

    def _observe_laya_completion(
        self,
        task: TaskState,
        *,
        repository_root: str | Path,
        status: str,
        reason_code: str,
        started_at: float,
        repository_revision: str,
        mutation_generation: int,
    ) -> None:
        observer = getattr(self, "_laya_completion_observer", None)
        if not callable(observer):
            return
        operation = {
            "task_id": task.task_id,
            "session_id": str(getattr(task.context, "session_id", "") or ""),
            "outcome": {
                "status": status,
                "reason_code": reason_code,
                "duration_ms": max(0.0, (time.monotonic() - started_at) * 1000.0),
                "repository_revision": repository_revision,
                "mutation_generation": mutation_generation,
            },
        }
        try:
            observer(operation=operation, root=str(repository_root or ""))
        except Exception:
            # Observation is best effort and cannot change the completion gate.
            return

    def set_policy_engine(self, policy_engine: Any) -> None:
        self.policy_engine = policy_engine

    @staticmethod
    def _completion_content_snapshot(
        task: TaskState,
    ) -> tuple[Any, Any, str, float, TaskCheckpoint, dict[str, str], str]:
        return (
            task.contract, task.context, task.lease_id, task.created_at,
            task.checkpoint, dict(task.verification_receipts), task.owner,
        )

    def set_verification_store(self, verification_store: Any) -> None:
        self.verification_store = verification_store

    def set_memory_adoption(
        self,
        *,
        memory_store: Any,
        context_compiler: Any,
        incident_store: Any | None = None,
    ) -> None:
        self.memory_store = memory_store
        self.memory_context_compiler = context_compiler
        self.incident_store = incident_store

    @staticmethod
    def _canonical_memory_root(value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            return os.path.normcase(str(Path(raw).expanduser().resolve(strict=False))).replace("\\", "/")
        except (OSError, RuntimeError, TypeError, ValueError):
            return ""

    @staticmethod
    def _memory_token_count(value: str) -> int:
        return max(1, len(value.strip()) // 4)

    @staticmethod
    def _memory_warning(code: str) -> dict[str, Any]:
        return TaskStore._account_memory_snapshot({
            "schema_version": 2, "context": {}, "instruction": "",
            "items": [], "warnings": [{"code": code}], "estimated_tokens": 0,
        })

    @staticmethod
    def _account_memory_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
        for _ in range(16):
            measured = json_tokens(snapshot)
            if snapshot.get("estimated_tokens") == measured:
                return snapshot
            snapshot["estimated_tokens"] = measured
        raise ValueError("memory snapshot accounting did not converge")

    def _check_memory_deadline(self, deadline: float, cancelled: threading.Event) -> None:
        if cancelled.is_set() or time.monotonic() >= deadline:
            raise self._MemoryDeadlineExceeded()

    @staticmethod
    def _run_memory_lookup_jobs(jobs: queue.Queue[Any], slots: threading.BoundedSemaphore) -> None:
        # A stuck backend occupies this single daemon worker/slot, never a
        # growing executor queue or a non-daemon interpreter shutdown hook.
        while not sys.is_finalizing():
            try:
                job = jobs.get(timeout=0.25)
            except queue.Empty:
                continue
            if job is None:
                jobs.task_done()
                return
            context, callback, completed, outcome = job
            try:
                outcome["value"] = context.run(callback)
            except BaseException as exc:
                outcome["error"] = "deadline" if isinstance(exc, TaskStore._MemoryDeadlineExceeded) else "unavailable"
            finally:
                jobs.task_done()
                slots.release()
                completed.set()
            del job, context, callback, completed, outcome

    @staticmethod
    def _fit_memory_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
        if snapshot is None:
            return None
        if (type(snapshot.get("schema_version")) is not int or snapshot.get("schema_version") != 2
                or "tenant_key" in snapshot or not isinstance(snapshot.get("context"), Mapping)):
            raise ValueError("retired memory snapshot contract requires explicit offline conversion")
        result = dict(snapshot)
        source_items = list(result.get("items", ()))
        result["items"] = []
        if not source_items:
            result["instruction"] = ""
            if not result.get("warnings"):
                return None
            result = TaskStore._account_memory_snapshot(result)
            return result if json_tokens(result) <= 512 else TaskStore._memory_warning("memory_snapshot_budget_exceeded")

        def fits(candidate: dict[str, Any]) -> bool:
            for _ in range(16):
                measured = json_tokens(candidate)
                if candidate.get("estimated_tokens") == measured:
                    return measured <= 512
                candidate["estimated_tokens"] = measured
            return False

        for source_item in source_items[:8]:
            item = dict(source_item)
            candidate = {**result, "items": [*result["items"], item]}
            if not fits(candidate):
                content = str(item.get("content", ""))
                low, high = 0, len(content)
                best = None
                while low <= high:
                    size = (low + high) // 2
                    bounded = {**item, "content": content[:size], "estimated_tokens": json_tokens(content[:size])}
                    trial = {**result, "items": [*result["items"], bounded]}
                    if fits(trial):
                        best = trial
                        low = size + 1
                    else:
                        high = size - 1
                if best is None or not best["items"][-1]["content"]:
                    continue  # Never shorten identity/provenance to fit an item.
                candidate = best
            result = candidate
        if not result["items"]:
            return TaskStore._memory_warning("memory_snapshot_budget_exceeded")
        return result if fits(result) else TaskStore._memory_warning("memory_snapshot_budget_exceeded")

    def _task_memory_context(
        self,
        task_id: str,
        contract: GoalContract,
        context: ScopeContext,
        *,
        root_override: str = "",
        previous: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if self.memory_context_compiler is None or self.memory_store is None:
            return self._memory_warning("memory_context_unavailable") if previous is not None else None

        deadline = time.monotonic() + 1.0
        if not self._memory_lookup_slots.acquire(blocking=False):
            return self._memory_warning("memory_lookup_busy")
        if time.monotonic() >= deadline:
            self._memory_lookup_slots.release()
            return self._memory_warning("memory_lookup_deadline_exceeded")
        cancelled, completed = threading.Event(), threading.Event()
        outcome: dict[str, Any] = {}

        def lookup() -> dict[str, Any] | None:
            self._check_memory_deadline(deadline, cancelled)
            root = str(root_override or "").strip()
            guard = getattr(self.memory_store, "task_retrieval_scope", None)
            with guard(contract.goal, root=root, task_id=task_id) if callable(guard) else nullcontext():
                self._check_memory_deadline(deadline, cancelled)
                snapshot = self._collect_task_memory_context(
                    task_id, contract, context, root_override=root, previous=previous,
                    deadline=deadline, cancelled=cancelled,
                )
                self._check_memory_deadline(deadline, cancelled)
                snapshot = self._fit_memory_snapshot(snapshot)
                self._check_memory_deadline(deadline, cancelled)
                return snapshot

        try:
            if self._memory_lookup_worker is None:
                worker = threading.Thread(
                    target=self._run_memory_lookup_jobs,
                    args=(self._memory_lookup_queue, self._memory_lookup_slots),
                    name="agent-task-memory-lookup", daemon=True,
                )
                worker.start()
                self._memory_lookup_worker = worker
            self._memory_lookup_queue.put_nowait((contextvars.copy_context(), lookup, completed, outcome))
        except Exception:
            self._memory_lookup_slots.release()
            return self._memory_warning("memory_context_unavailable")
        if not completed.wait(max(0.0, deadline - time.monotonic())):
            cancelled.set()
            return self._memory_warning("memory_lookup_deadline_exceeded")
        if outcome.get("error"):
            code = "memory_lookup_deadline_exceeded" if outcome["error"] == "deadline" else "memory_context_unavailable"
            return self._memory_warning(code)
        return outcome.get("value")

    def _collect_task_memory_context(
        self, task_id: str, contract: GoalContract, context: ScopeContext, *,
        root_override: str = "", previous: Mapping[str, Any] | None = None,
        deadline: float, cancelled: threading.Event,
    ) -> dict[str, Any] | None:
        compiler = self.memory_context_compiler
        memory_store = self.memory_store
        if compiler is None or memory_store is None:
            return None
        try:
            from .agent_context import ContextRequest

            root = str(root_override or "").strip()
            coordination_id = ""
            if root:
                try:
                    from .project_config import resolve_project_context

                    project = resolve_project_context(
                        root, Path(self.state_store.db_path).parent
                    )
                    resolved_identity = project.coordination_id
                    if not isinstance(resolved_identity, str) or not resolved_identity or resolved_identity != resolved_identity.strip() or "\x00" in resolved_identity:
                        raise ValueError("invalid project coordination identity")
                    coordination_id = resolved_identity
                except Exception:
                    # Missing repository identity excludes repository memory;
                    # independently scoped task/session/global records remain eligible.
                    coordination_id = ""
            self._check_memory_deadline(deadline, cancelled)
            snapshot_context = {
                "root": root, "coordination_id": coordination_id, "task_id": task_id,
                "session_id": context.session_id, "clone_id": context.clone_id,
                "worktree_id": context.worktree_id, "branch": context.branch,
            }
            warnings: list[dict[str, str]] = []
            if previous is not None:
                if (type(previous.get("schema_version")) is not int or previous.get("schema_version") != 2 or "tenant_key" in previous
                        or not isinstance(previous.get("context"), Mapping)):
                    return self._memory_warning("memory_snapshot_requires_offline_conversion")
                if previous.get("items") and previous["context"] != snapshot_context:
                    return {
                        "schema_version": 2, "context": snapshot_context,
                        "instruction": "Memory scope changed; verify memory against current context before use.",
                        "items": [], "warnings": [{"code": "memory_scope_mismatch"}], "estimated_tokens": 0,
                    }

            request = ContextRequest(
                task_id=task_id,
                token_budget=512,
                root=root,
                session_id=context.session_id,
                clone_id=context.clone_id,
                worktree_id=context.worktree_id,
                branch=context.branch,
                repository_id=context.repository_id,
                coordination_id=coordination_id,
            )
            compiled = compiler.compile(request)
            self._check_memory_deadline(deadline, cancelled)

            items: list[dict[str, Any]] = []
            warnings.extend(
                {"code": str(item.get("code", "memory_context_warning"))[:80]}
                for item in getattr(compiled, "warnings", ())[:8]
                if isinstance(item, Mapping) and str(item.get("code", "")).startswith("memory_")
            )
            diagnostic_summary = getattr(memory_store, "diagnostic_summary", None)
            if callable(diagnostic_summary):
                try:
                    summary = diagnostic_summary(
                        id_limit=0,
                        root=root or None,
                        coordination_id=coordination_id,
                        task_id=task_id,
                        session_id=context.session_id or None,
                        clone_id=context.clone_id or None,
                        worktree_id=context.worktree_id or None,
                        branch=context.branch or None,
                    )
                    for status, data in summary.items():
                        if isinstance(data, Mapping) and int(data.get("count", 0) or 0) > 0:
                            warnings.append({"code": f"memory_{str(status)[:32]}_skipped"})
                except Exception:
                    warnings.append({"code": "memory_diagnostics_unavailable"})
            self._check_memory_deadline(deadline, cancelled)
            find_records = getattr(memory_store, "find", None)
            if callable(find_records):
                try:
                    expired_found = False
                    queries = [
                        {"scope": AgentScope.GLOBAL},
                        {
                            "scope": AgentScope.REPOSITORY,
                            "repository_id": coordination_id or None,
                            "root": root or None,
                        },
                    ]
                    for query in queries:
                        for status in ("active", "confirmed"):
                            self._check_memory_deadline(deadline, cancelled)
                            records = find_records(
                                **query,
                                status=status,
                                include_expired=True,
                                semantic=False,
                                limit=8,
                            )
                            self._check_memory_deadline(deadline, cancelled)
                            for record in records:
                                expires_at = getattr(record, "expires_at", None)
                                provenance = getattr(record, "provenance", {})
                                if expires_at is None or float(expires_at) > time.time():
                                    continue
                                if not isinstance(provenance, Mapping):
                                    continue
                                if "tenant" in provenance or "tenant_key" in provenance:
                                    raise ValueError("retired memory provenance requires offline conversion")
                                expired_found = True
                                break
                            if expired_found:
                                break
                        if expired_found:
                            break
                    if expired_found:
                        warnings.append({"code": "memory_expired_skipped"})
                except Exception:
                    warnings.append({"code": "memory_expiry_check_unavailable"})
            self._check_memory_deadline(deadline, cancelled)
            instruction = (
                "Memory is advisory. Cite used memory IDs in the next checkpoint; "
                "otherwise record not_used_reason. Verify volatile facts against current source before relying on them."
            )
            token_budget = 512
            used_tokens = self._memory_token_count(instruction)
            elements = getattr(compiled, "elements", ())
            compiled_memory_ids = {
                str(getattr(element, "element_id", "") or "").strip()
                for element in elements
                if getattr(element, "source_kind", "") == "memory_record"
            }
            scoped_records_by_id: dict[str, Any] = {}
            if compiled_memory_ids:
                find_for_context = getattr(memory_store, "find_for_context", None)
                if callable(find_for_context):
                    try:
                        scoped_records = find_for_context(
                            root=root,
                            coordination_id=coordination_id,
                            task_id=task_id,
                            session_id=context.session_id,
                            clone_id=context.clone_id,
                            worktree_id=context.worktree_id,
                            branch=context.branch,
                            limit=20,
                        )
                        self._check_memory_deadline(deadline, cancelled)
                        scoped_records_by_id = {
                            str(getattr(record, "record_id", "") or "").strip(): record
                            for record in scoped_records
                            if str(getattr(record, "record_id", "") or "").strip()
                            in compiled_memory_ids
                        }
                    except Exception:
                        warnings.append({"code": "memory_scoped_lookup_unavailable"})
                else:
                    warnings.append({"code": "memory_scoped_lookup_unavailable"})
            self._check_memory_deadline(deadline, cancelled)
            for element in elements:
                self._check_memory_deadline(deadline, cancelled)
                if getattr(element, "source_kind", "") != "memory_record":
                    continue
                record_id = str(getattr(element, "element_id", "") or "").strip()
                if not record_id:
                    continue
                record = scoped_records_by_id.get(record_id)
                if record is None:
                    warnings.append({"code": "memory_record_unavailable"})
                    continue
                try:
                    status = getattr(getattr(record, "status", ""), "value", getattr(record, "status", ""))
                    scope = getattr(getattr(record, "scope", ""), "value", getattr(record, "scope", ""))
                    provenance = record.provenance
                    if not isinstance(provenance, Mapping):
                        raise ValueError("invalid provenance")
                    if status not in {"active", "confirmed"}:
                        continue
                    expires_at = getattr(record, "expires_at", None)
                    if expires_at is not None and float(expires_at) <= time.time():
                        continue
                    sensitivity = str(getattr(record, "sensitivity", "normal") or "normal").strip().lower()
                    if sensitivity not in {"normal", "low", "public"}:
                        continue
                    if "tenant" in provenance or "tenant_key" in provenance:
                        raise ValueError("retired memory provenance requires offline conversion")
                    if scope == "repository":
                        if not coordination_id or provenance.get("repository_id") != coordination_id:
                            continue
                    elif scope != "global":
                        expected_scope_ids = {
                            "clone": context.clone_id,
                            "worktree": context.worktree_id,
                            "branch": context.branch,
                            "task": task_id,
                            "session": context.session_id,
                        }
                        expected_scope_id = str(expected_scope_ids.get(str(scope), "") or "")
                        record_scope_id = str(getattr(record, "scope_id", "") or "")
                        if not expected_scope_id or expected_scope_id != record_scope_id:
                            continue
                    record_root = provenance.get("root")
                    if scope in {"task", "clone", "worktree", "branch"} and (not isinstance(record_root, str) or not record_root):
                        continue
                    if scope not in {"repository", "global"} and record_root and (
                        not root
                        or self._canonical_memory_root(record_root) != self._canonical_memory_root(root)
                    ):
                        continue
                    if scope == "repository" and not root:
                        continue
                    content = str(getattr(element, "content", "") or "").strip()
                    if not content:
                        continue
                    item_tokens = self._memory_token_count(content)
                    evidence_ids = [str(value)[:160] for value in tuple(getattr(record, "evidence_ids", ()) or ())[:8]]
                    safe_provenance: dict[str, Any] = {"evidence_ids": evidence_ids} if evidence_ids else {}
                    revision = provenance.get("repository_revision")
                    if isinstance(revision, str) and len(revision) <= 128:
                        safe_provenance["repository_revision"] = revision
                    version = provenance.get("version") or revision or getattr(record, "updated_at", "")
                    items.append({
                        "id": record_id,
                        "origin": "memory_store",
                        "content": content,
                        "source": str(getattr(record, "source", "") or "")[:64],
                        "scope": str(scope)[:32],
                        "scope_id": str(getattr(record, "scope_id", "") or "")[:256],
                        "status": str(status),
                        "version": str(version)[:128],
                        "validity": {
                            "created_at": float(getattr(record, "created_at", 0.0) or 0.0),
                            "updated_at": float(getattr(record, "updated_at", 0.0) or 0.0),
                            "expires_at": float(expires_at) if expires_at is not None else None,
                        },
                        "confidence": float(getattr(record, "confidence", 0.0) or 0.0),
                        "volatile": bool(provenance.get("volatile", False)),
                        "provenance": safe_provenance,
                        "estimated_tokens": item_tokens,
                    })
                except (AttributeError, TypeError, ValueError, OverflowError):
                    warnings.append({"code": "memory_record_invalid"})

            scorer = getattr(memory_store, "task_relevance_score", None)
            if callable(scorer):
                ranked = []
                for index, item in enumerate(items):
                    self._check_memory_deadline(deadline, cancelled)
                    try:
                        score = float(scorer(scoped_records_by_id[item["id"]], contract.goal, task_id=task_id))
                        if not math.isfinite(score):
                            raise ValueError("invalid relevance score")
                    except Exception:
                        score = 0.0
                        warnings.append({"code": "memory_relevance_unavailable"})
                    self._check_memory_deadline(deadline, cancelled)
                    ranked.append((score, index, item))
                items = [item for _, _, item in sorted(ranked, key=lambda entry: (-entry[0], entry[1]))]
            selected_items = []
            for item in items:
                remaining_tokens = token_budget - used_tokens
                if len(selected_items) >= 5 or remaining_tokens <= 0:
                    break
                content = item["content"][:remaining_tokens * 4].rstrip()
                item_tokens = self._memory_token_count(content)
                selected_items.append({**item, "content": content, "estimated_tokens": item_tokens})
                used_tokens += item_tokens
            items = selected_items

            incident_store = self.incident_store
            if root and incident_store is not None:
                finder = getattr(incident_store, "find_negative_knowledge", None)
                if callable(finder):
                    try:
                        incidents = finder(contract.goal, limit=3, root=root)
                        self._check_memory_deadline(deadline, cancelled)
                        for incident in incidents[:3]:
                            self._check_memory_deadline(deadline, cancelled)
                            if not isinstance(incident, Mapping):
                                continue
                            incident_id = str(incident.get("incident_id", "") or "").strip()
                            provenance = incident.get("provenance")
                            if not incident_id or not isinstance(provenance, Mapping):
                                continue
                            if not provenance.get("repository_key"):
                                continue
                            expires_at = incident.get("expires_at")
                            if "expires_at" not in incident:
                                getter = getattr(incident_store, "get", None)
                                if not callable(getter):
                                    warnings.append({"code": "negative_knowledge_invalid"})
                                    continue
                                full = getter(incident_id)
                                self._check_memory_deadline(deadline, cancelled)
                                if full is None or getattr(full, "repository_key", "") != provenance["repository_key"]:
                                    continue
                                expires_at = getattr(full, "expires_at", None)
                            try:
                                expires_at = float(expires_at) if expires_at is not None else None
                                if expires_at is not None and (not math.isfinite(expires_at) or expires_at <= time.time()):
                                    continue
                            except (TypeError, ValueError, OverflowError):
                                warnings.append({"code": "negative_knowledge_invalid"})
                                continue
                            detail = str(
                                incident.get("verified_fix") or incident.get("root_cause")
                                or incident.get("redacted_message") or ""
                            ).strip()
                            if not detail:
                                continue
                            content = f"[NEGATIVE KNOWLEDGE] {str(incident.get('error_class', ''))[:100]}: {detail[:700]}"
                            remaining_tokens = token_budget - used_tokens
                            if remaining_tokens <= 0:
                                break
                            content = content[:remaining_tokens * 4].rstrip()
                            item_tokens = self._memory_token_count(content)
                            if item_tokens > remaining_tokens:
                                continue
                            items.append({
                                "id": incident_id,
                                "origin": "incident_store",
                                "content": content,
                                "source": "incident_store",
                                "scope": "repository",
                                "scope_id": "",
                                "status": "active",
                                "version": str(incident.get("state_revision", "") or "")[:128],
                                "validity": {"updated_at": float(incident.get("updated_at", 0.0) or 0.0), "expires_at": expires_at},
                                "confidence": float(incident.get("confidence", 0.0) or 0.0),
                                "volatile": True,
                                "provenance": dict(provenance),
                                "estimated_tokens": item_tokens,
                            })
                            used_tokens += item_tokens
                    except Exception:
                        warnings.append({"code": "negative_knowledge_unavailable"})
            self._check_memory_deadline(deadline, cancelled)
            if not items and not warnings:
                return None
            return {
                "schema_version": 2,
                "context": snapshot_context,
                "instruction": instruction,
                "items": items,
                "warnings": warnings[:8],
                "estimated_tokens": used_tokens if items else 0,
            }
        except self._MemoryDeadlineExceeded:
            raise
        except Exception:
            return {
                "schema_version": 2,
                "context": {},
                "instruction": "Memory unavailable; continue without memory claims. Cite used memory IDs or record not_used_reason in the next checkpoint.",
                "items": [],
                "warnings": [{"code": "memory_context_unavailable"}],
                "estimated_tokens": 0,
            }

    @staticmethod
    def _validate_memory_audit(task: TaskState) -> None:
        state_data = task.checkpoint.state_data
        memory_context = state_data.get("memory_context")
        if not isinstance(memory_context, Mapping):
            return
        if (type(memory_context.get("schema_version")) is not int or memory_context.get("schema_version") != 2 or "tenant_key" in memory_context
                or not isinstance(memory_context.get("context"), Mapping)):
            raise CompletionGateError("Retired memory snapshot contract requires explicit offline conversion")
        items = memory_context.get("items")
        warnings = memory_context.get("warnings")
        snapshot_context = memory_context["context"]
        expected_fields = {"root", "coordination_id", "task_id", "session_id", "clone_id", "worktree_id", "branch"}
        if snapshot_context and (
            set(snapshot_context) != expected_fields
            or any(not isinstance(value, str) or value != value.strip() or "\x00" in value for value in snapshot_context.values())
            or snapshot_context.get("task_id") != task.task_id
        ):
            raise CompletionGateError("Invalid checkpoint memory context identity")
        if items and not snapshot_context:
            raise CompletionGateError("Checkpoint memory items require explicit task context identity")
        if not isinstance(items, list) or not isinstance(warnings, list):
            raise CompletionGateError("Invalid checkpoint memory items/warnings contract")
        if not items and not warnings:
            return
        audit = state_data.get("memory_audit")
        if not isinstance(audit, Mapping):
            raise CompletionGateError(
                "Invalid checkpoint memory audit: memory context requires checkpoint memory_audit at state_data.memory_audit"
            )
        available_ids = {
            str(item.get("id", ""))
            for item in items
            if isinstance(item, Mapping) and str(item.get("id", "")).strip()
        }
        used_ids = audit.get("used_ids", ())
        if not isinstance(used_ids, (list, tuple)) or any(not isinstance(value, str) for value in used_ids):
            raise CompletionGateError(
                "Invalid checkpoint memory audit: state_data.memory_audit.used_ids must be a list of IDs"
            )
        if not set(used_ids).issubset(available_ids):
            raise CompletionGateError(
                "Invalid checkpoint memory audit: state_data.memory_audit references unavailable memory IDs"
            )
        raw_not_used_reason = audit.get("not_used_reason", "")
        not_used_reason = raw_not_used_reason.strip() if isinstance(raw_not_used_reason, str) else ""
        if not used_ids and not not_used_reason:
            raise CompletionGateError(
                "Invalid checkpoint memory audit: record used memory IDs or not_used_reason in state_data.memory_audit (used_ids or a nonempty reason)"
            )
        volatile_used = {
            str(item.get("id", ""))
            for item in items
            if isinstance(item, Mapping) and item.get("volatile") and str(item.get("id", "")) in used_ids
        }
        source_checks = audit.get("source_checks", {})
        if volatile_used and not isinstance(source_checks, Mapping):
            raise CompletionGateError(
                "Invalid checkpoint memory audit: volatile memory requires state_data.memory_audit.source_checks"
            )
        for record_id in volatile_used:
            check = source_checks.get(record_id) if isinstance(source_checks, Mapping) else None
            if not isinstance(check, Mapping):
                has_current_source = False
            else:
                source = str(check.get("source", "") or "").strip()
                evidence_ids = check.get("evidence_ids", ())
                has_current_source = bool(source) or (
                    isinstance(evidence_ids, (list, tuple))
                    and any(isinstance(value, str) and value.strip() for value in evidence_ids)
                )
            if not has_current_source:
                raise CompletionGateError(
                    f"Invalid checkpoint memory audit: volatile memory '{record_id}' lacks a current-source check in state_data.memory_audit.source_checks"
                )

