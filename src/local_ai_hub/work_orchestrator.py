from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any

from .features import rollout_feature_enabled
from .json_utils import dumps as json_dumps
from .process_utils import hidden_run_kwargs, is_rooted_path
from .response_protocol import project_response
from .sqlite_support import (
    begin_write_transaction,
    connect_sqlite,
    retry_busy,
    write_transaction,
)
from .work_contracts import (
    _TERMINAL,
    _WORK_CANCEL_EVENT,
    _WORK_PERMISSION_FIELDS,
    _bounded_int,
    _bounded_work_scope,
    _budget_int,
    _certain_work_model_response,
    _json_object,
    _permission_map,
    _safe_float,
    _stable_toposort_steps,
    _string_list,
    _work_model_response_error,
)
from .work_executor import WorkExecutorMixin
from .work_fencing import (
    FencingLeaseStore,
    LeaseLostError,
    WorkAttemptFence,
)
from .work_recovery import WorkRecoveryMixin
from .work_rollback import WorkRollbackMixin

logger = logging.getLogger(__name__)


from .work_contracts import (
    _FinalizationLookupTimeout,
    _JournalEntry,
    _UNCERTAIN_COMMAND_FLAGS,
    _UNCERTAIN_MODEL_FLAGS,
    _WORK_DEADLINE,
    _bounded_tool_qualification,
    _broker_receipt_from_result,
    _delete_windows_rollback_file,
    _diff_from_text,
    _local_exploration_status,
    _mark_rolled_back_validation_stale,
    _patch_changes,
    _patch_paths,
    _pin_windows_rollback_files,
    _pin_windows_work_directories,
    _quarantine_failed_rollback_receipts,
    _run_git_patch,
    _safe_patch_header_path,
    _safe_work_target,
    _usable_work_artifact_id,
    _work_edit_context,
    _work_model_observation,
    _work_model_uncertainty,
    _write_windows_rollback_file,
    is_terminal_work_status,
    is_valid_work_order_id,
)

__all__ = [
    "WorkOrchestrator",
    "subprocess",
    "write_transaction",
    "connect_sqlite",
    "retry_busy",
    "begin_write_transaction",
    "hidden_run_kwargs",
    "is_rooted_path",
    "_FinalizationLookupTimeout",
    "_JournalEntry",
    "_TERMINAL",
    "_UNCERTAIN_COMMAND_FLAGS",
    "_UNCERTAIN_MODEL_FLAGS",
    "_WORK_CANCEL_EVENT",
    "_WORK_DEADLINE",
    "_WORK_PERMISSION_FIELDS",
    "_bounded_int",
    "_bounded_tool_qualification",
    "_bounded_work_scope",
    "_broker_receipt_from_result",
    "_budget_int",
    "_certain_work_model_response",
    "_delete_windows_rollback_file",
    "_diff_from_text",
    "_json_object",
    "_local_exploration_status",
    "_mark_rolled_back_validation_stale",
    "_patch_changes",
    "_patch_paths",
    "_permission_map",
    "_pin_windows_rollback_files",
    "_pin_windows_work_directories",
    "_quarantine_failed_rollback_receipts",
    "_run_git_patch",
    "_safe_float",
    "_safe_patch_header_path",
    "_safe_work_target",
    "_stable_toposort_steps",
    "_string_list",
    "_usable_work_artifact_id",
    "_work_edit_context",
    "_work_model_observation",
    "_work_model_response_error",
    "_work_model_uncertainty",
    "_write_windows_rollback_file",
    "is_terminal_work_status",
    "is_valid_work_order_id",
]


class WorkOrchestrator(WorkRecoveryMixin, WorkRollbackMixin, WorkExecutorMixin):
    """Durable, serial whole-task executor for local coding work.

    The orchestrator intentionally reuses Local AI Hub's deterministic services,
    command broker, leases, artifacts and local model scheduler. It does not create
    a second agent runtime. Mutations are journalled outside git and rolled back on
    failed final verification unless the caller explicitly asks to preserve failure.
    """

    def __init__(
        self, config: dict[str, Any] | None, state_dir: Path, services: Any, commands: Any,
        leases: Any, artifacts: Any, telemetry: Any | None = None,
        verification_store: Any | None = None,
        fencing_store: FencingLeaseStore | None = None,
        execution_pool: Any | None = None,
    ):
        raw_cfg = config.get("work_orchestrator") if isinstance(config, dict) else {}
        cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
        self.enabled = bool(cfg.get("enabled", True))
        self.max_active = _bounded_int(cfg.get("max_active_work_orders"), 1, 1, 32)
        self.max_pending = _bounded_int(cfg.get("max_pending_work_orders"), 32, 1, 256)
        self.worker_idle_seconds = _safe_float(cfg.get("worker_idle_seconds"), 120.0, 5.0, 3600.0)
        self.max_steps = _bounded_int(cfg.get("max_steps"), 32, 1, 64)
        self.max_llm_calls = _bounded_int(cfg.get("max_llm_steps"), 16, 1, 32)
        self.max_replans = _bounded_int(cfg.get("max_replans"), 2, 0, 4)
        self.parallel_deterministic = _bounded_int(cfg.get("parallel_deterministic_steps"), 2, 1, 4)
        self.default_seconds = _bounded_int(cfg.get("max_seconds"), 900, 30, 7200)
        self.max_patch_files = _bounded_int(cfg.get("max_patch_files"), 24, 1, 128)
        self.max_patch_bytes = _bounded_int(cfg.get("max_patch_bytes"), 524288, 4096, 4 * 1024 * 1024)
        self.step_retry_limit = _bounded_int(cfg.get("step_retry_limit"), 2, 0, 4)
        self.rollback_on_failure = bool(cfg.get("rollback_on_failure", True))
        self.allow_edits = bool(cfg.get("allow_edits", True))
        self.allow_create = bool(cfg.get("allow_create", True))
        self.allow_delete = bool(cfg.get("allow_delete", True))
        self.validation_limit = _bounded_int(cfg.get("validation_commands"), 3, 1, 8)
        self.default_response_profile = str(cfg.get("default_response_profile", "compact") or "compact")
        self.default_max_output_tokens = max(0, _bounded_int(cfg.get("default_max_output_tokens"), 350, 0, 100000))
        self.services, self.commands, self.leases, self.artifacts = services, commands, leases, artifacts
        self.execution_pool = execution_pool
        self._tool_qualification_config = config if isinstance(config, dict) else {}
        self.local_diagnostic_dispatch = rollout_feature_enabled(config or {}, "local_diagnostic_dispatch")
        clean_state_dir = str(state_dir).replace("\x00", "")
        self.fencing_store = fencing_store or FencingLeaseStore(Path(clean_state_dir) / "work_fencing.sqlite3")
        set_fencing_store = getattr(self.commands, "set_fencing_lease_store", None)
        if callable(set_fencing_store):
            set_fencing_store(self.fencing_store)
        self.telemetry = telemetry
        self.verification_store = (
            verification_store
            if verification_store is not None
            else getattr(services, "verification_store", None)
        )
        self.path = Path(state_dir) / "work_orders.sqlite3"
        self.journal_dir = Path(state_dir) / "work_journals"
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._waiters: dict[str, threading.Event] = {}
        self._active_cancellations: dict[str, threading.Event] = {}
        self._active_deadlines: dict[str, float] = {}
        self._workers: list[threading.Thread] = []
        self._lock = threading.RLock()
        self._recovery_timer: threading.Timer | None = None
        self._recovery_retry_requested = False
        self._terminal_recovery_cursor = ""
        self._terminal_cleanup_cursor = ""
        self._init_db()
        self._worker: threading.Thread | None = None
        set_work_authorizer = getattr(self.commands, "set_bounded_work_authorizer", None)
        if callable(set_work_authorizer):
            set_work_authorizer(self.authorize_bounded_command)
        self._recover()
        # Work execution is lazy. Most LocalAIApp instances only use retrieval or
        # status APIs; eagerly starting another polling thread for each instance
        # caused avoidable background load in embedded/test workloads.
        if self._has_queued_work():
            self._ensure_workers()

    def is_enabled(self) -> bool:
        """Return True if whole-task orchestrator is enabled."""
        return bool(self.enabled)

    def max_active_orders(self) -> int:
        """Return maximum number of concurrently active work orders."""
        return int(self.max_active)

    def default_timeout_seconds(self) -> int:
        """Return default maximum run duration for work orders in seconds."""
        return int(self.default_seconds)

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout_seconds=2.0, isolation_level=None, row_factory=sqlite3.Row)

    def _coordination_id(self, root: str | Path) -> str | None:
        """Use producer identity for lease scope; keep root identity physical."""
        from .project_config import resolve_project_context

        return resolve_project_context(root, self.path.parent).coordination_id

    def _init_db(self) -> None:
        expected_columns = {
            "work_id", "root", "task", "state", "payload_json", "result_json",
            "cancel_requested", "created_at", "updated_at",
        }
        if self.path.exists():
            read_only_uri = self.path.resolve().as_uri() + "?mode=ro"
            with closing(connect_sqlite(read_only_uri, uri=True, timeout_seconds=2.0, read_only=True)) as check:
                check.execute("PRAGMA query_only=ON")
                table = check.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='work_orders'"
                ).fetchone()
                if table:
                    columns = {
                        str(row[1])
                        for row in check.execute("PRAGMA table_info(work_orders)").fetchall()
                    }
                    if columns != expected_columns:
                        raise RuntimeError(
                            "unsupported work_orders database schema; explicit offline conversion required"
                        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS work_orders(
              work_id TEXT PRIMARY KEY, root TEXT NOT NULL, task TEXT NOT NULL,
              state TEXT NOT NULL, payload_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}',
              cancel_requested INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_work_orders_state_created ON work_orders(state, created_at);
            CREATE INDEX IF NOT EXISTS idx_work_orders_updated ON work_orders(updated_at DESC);
            """)


    def _has_queued_work(self) -> bool:
        with closing(self._connect()) as con:
            row = con.execute("SELECT 1 FROM work_orders WHERE state='queued' LIMIT 1").fetchone()
        return row is not None

    def _ensure_workers(self) -> None:
        if not self.enabled or self._stop.is_set():
            return
        with self._lock:
            self._workers = [worker for worker in self._workers if worker.is_alive()]
            needed = max(0, self.max_active - len(self._workers))
            for _ in range(needed):
                index = len(self._workers) + 1
                worker = threading.Thread(
                    target=self._loop,
                    name=f"local-ai-work-orchestrator-{index}",
                    daemon=True,
                )
                self._workers.append(worker)
                if self._worker is None or not self._worker.is_alive():
                    self._worker = worker
                worker.start()

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "tenant" in payload:
            return {"success": False, "error": "retired work-order field: tenant", "terminal": True}
        if not self.enabled:
            return {"success": False, "unsupported": True, "error": "work orchestrator disabled"}
        raw_root = str(payload.get("root", "")).strip()
        if not raw_root or not is_rooted_path(raw_root):
            return {"success": False, "error": "root must be an explicit absolute repository directory", "terminal": True}
        root = Path(raw_root).expanduser().resolve(strict=False)
        raw_task = payload.get("task", "")
        if not isinstance(raw_task, str) or "\x00" in raw_task or len(raw_task) > 24000:
            return {"success": False, "error": "task must be a string of at most 24000 characters without NUL", "terminal": True}
        task = raw_task.strip()
        if not root.is_dir():
            return {"success": False, "error": "root must be an existing absolute repository directory", "terminal": True}
        if not task:
            return {"success": False, "error": "task is required", "terminal": True}
        work_id = str(payload.get("work_id", "")).strip() or f"wo_{uuid.uuid4().hex[:20]}"
        if len(work_id) > 128 or any(ord(ch) < 32 for ch in work_id):
            return {"success": False, "error": "work_id must be at most 128 printable characters", "terminal": True}
        raw_task_id = payload.get("task_id", "")
        if raw_task_id is None:
            raw_task_id = ""
        if not isinstance(raw_task_id, str):
            return {"success": False, "error": "task_id must be a string when supplied", "terminal": True}
        task_id = raw_task_id.strip()
        if len(task_id) > 128 or any(ord(ch) < 32 for ch in task_id):
            return {"success": False, "error": "task_id must be at most 128 printable characters", "terminal": True}
        raw_acceptance = payload.get("acceptance_criteria")
        if (not isinstance(raw_acceptance, list) or not raw_acceptance or len(raw_acceptance) > 24
                or any(not isinstance(item, str) or not item.strip() or "\x00" in item or len(item.strip()) > 2000
                       for item in raw_acceptance)):
            return {"success": False, "error": "work order requires explicit non-empty string acceptance criteria", "terminal": True}
        acceptance = [item.strip() for item in raw_acceptance]
        permissions = payload.get("permissions", {})
        if (not isinstance(permissions, dict) or set(permissions) - _WORK_PERMISSION_FIELDS
                or any(type(value) is not bool for value in permissions.values())):
            return {"success": False, "error": "work order permissions must contain only supported boolean fields", "terminal": True}
        if permissions.get("read") is False:
            return {"success": False, "error": "work orders require repository read permission", "terminal": True}
        budgets = payload.get("budget", {})
        if not isinstance(budgets, dict):
            return {"success": False, "error": "work order budget must be an object", "terminal": True}
        if set(budgets) - {"max_steps", "max_llm_calls", "max_seconds", "max_tokens", "max_edits", "max_commands"}:
            return {"success": False, "error": "work order budget contains unsupported fields", "terminal": True}
        hard_max_steps = min(self.max_steps, 16)
        try:
            requested_max_steps = _budget_int(budgets.get("max_steps", hard_max_steps), "max_steps")
        except ValueError as exc:
            return {"success": False, "error": str(exc), "terminal": True}
        if requested_max_steps < 1 or requested_max_steps > hard_max_steps:
            return {"success": False, "error": f"work order max_steps must be between 1 and {hard_max_steps}", "terminal": True}
        execution_budgets: dict[str, int] = {}
        for name, default, lower, upper in (
            ("max_llm_calls", self.max_llm_calls, 1, self.max_llm_calls),
            ("max_seconds", self.default_seconds, 30, 7200),
        ):
            if name not in budgets:
                execution_budgets[name] = default
                continue
            try:
                value = _budget_int(budgets[name], name)
            except ValueError as exc:
                return {"success": False, "error": str(exc), "terminal": True}
            if value < lower or value > upper:
                return {"success": False, "error": f"work order {name} must be between {lower} and {upper}", "terminal": True}
            execution_budgets[name] = value
        planner_budgets: dict[str, int] = {}
        for name, lower, upper in (
            ("max_tokens", 128, 1400),
            ("max_edits", 0, requested_max_steps),
            ("max_commands", 0, requested_max_steps),
        ):
            if name not in budgets:
                continue
            try:
                limit = _budget_int(budgets[name], name)
            except ValueError as exc:
                return {"success": False, "error": str(exc), "terminal": True}
            if limit < lower or limit > upper:
                return {"success": False, "error": f"work order {name} must be between {lower} and {upper}", "terminal": True}
            planner_budgets[name] = limit
        raw_mode = payload.get("mode", "execute")
        if not isinstance(raw_mode, str) or not raw_mode.strip():
            return {"success": False, "error": "work order mode must be a non-empty string", "terminal": True}
        mode = raw_mode.strip().lower().replace("-", "_")
        if mode not in {"execute", "bounded", "plan", "plan_only", "dry_run"}:
            return {"success": False, "error": "mode must be execute, bounded, plan, plan_only, or dry_run", "terminal": True}
        if mode in {"execute", "bounded"} and (permissions.get("tests") is False or permissions.get("build") is False):
            return {"success": False, "error": "execute mode requires both test and build permissions; selective validation is unsupported", "terminal": True}
        allowed_paths: list[str] = []
        approved_commands: list[str] = []
        if mode == "bounded":
            try:
                allowed_paths, approved_commands = _bounded_work_scope(
                    root, payload.get("allowed_paths"), payload.get("approved_commands")
                )
            except ValueError as exc:
                return {"success": False, "error": str(exc), "terminal": True}
            if "max_seconds" not in budgets or requested_max_steps > 8 or execution_budgets["max_seconds"] > 1800:
                return {"success": False, "error": "bounded mode requires an explicit max_seconds <= 1800 and max_steps <= 8", "terminal": True}
            if len(approved_commands) > planner_budgets.get("max_commands", requested_max_steps):
                return {"success": False, "error": "approved commands exceed the bounded command budget", "terminal": True}
            if "edit" not in permissions or permissions.get("tests") is not True or permissions.get("build") is not True:
                return {"success": False, "error": "bounded mode requires an explicit edit choice and tests/build permissions", "terminal": True}
            if not permissions["edit"] and (permissions.get("create") is True or permissions.get("delete") is True):
                return {"success": False, "error": "create/delete permissions require edit permission", "terminal": True}
        keep_failed = payload.get("keep_failed_workspace", False)
        if type(keep_failed) is not bool:
            return {"success": False, "error": "keep_failed_workspace must be a boolean", "terminal": True}
        profile = str(payload.get("response_profile", self.default_response_profile) or self.default_response_profile).strip().lower()
        if profile not in {"minimal", "compact", "standard", "debug"}:
            profile = self.default_response_profile if self.default_response_profile in {"minimal", "compact", "standard", "debug"} else "compact"
        return_fields = _string_list(payload.get("return_fields"), limit=32, item_chars=80)
        normalized_permissions = _permission_map(permissions)
        if mode == "bounded":
            normalized_permissions["create"] = permissions.get("create") is True
            normalized_permissions["delete"] = permissions.get("delete") is True
        normalized = {
            "task_id": task_id,
            "acceptance_criteria": acceptance,
            "constraints": _string_list(payload.get("constraints"), limit=24, item_chars=2000),
            "mode": mode,
            "allowed_paths": allowed_paths,
            "approved_commands": approved_commands,
            "permissions": normalized_permissions,
            "budget": {
                "max_steps": requested_max_steps,
                **execution_budgets,
                **planner_budgets,
            },
            "response_profile": profile,
            "return_fields": return_fields,
            "max_output_tokens": _bounded_int(payload.get("max_output_tokens"), self.default_max_output_tokens, 0, 4096),
            "keep_failed_workspace": keep_failed,
        }
        now = time.time()
        # Keep cross-store task validation outside the work-order write transaction.
        # Preserve idempotent retries for an existing work_id before consulting the
        # task store, then recheck under the admission transaction before insertion.
        preexisting = self._row(work_id)
        if preexisting is not None:
            existing_payload = json.loads(str(preexisting["payload_json"] or "{}"))
            if (
                str(preexisting["root"]) != str(root)
                or str(preexisting["task"]) != task
                or existing_payload != normalized
            ):
                return {
                    "success": False,
                    "error": "work_id already exists with different request",
                    "work_id": work_id,
                    "terminal": True,
                }
            return self._canonical(preexisting)
        if mode == "bounded" and task_id and normalized_permissions["edit"]:
            task_store = getattr(self.verification_store, "task_store", None)
            if task_store is None:
                return {"success": False, "error": "bounded work task store is unavailable", "terminal": True}
            try:
                from .agent_tasks import TaskStatus, _task_matches_scope, _task_scope_root

                record = task_store.get(task_id)
                valid_task = (
                    record is not None
                    and record.status is TaskStatus.ACTIVE
                    and bool(str(record.owner or "").strip())
                    and _task_matches_scope(record, str(root), task_id)
                    and _task_scope_root(record) == str(root)
                )
            except Exception:
                return {"success": False, "error": "bounded work task state lookup failed",
                        "operation_not_started": True, "retryable": True, "terminal": False}
            if not valid_task:
                return {"success": False, "error": "bounded work requires an active task in the same repository",
                        "operation_not_started": True, "terminal": True}
        try:
            with closing(self._connect()) as con:
                # Serialize admission so concurrent submitters cannot all observe the
                # same free slot and overflow the configured bounded queue.
                transaction = begin_write_transaction(
                    con, max_duration_seconds=5.0, rollback_label="work-order admission"
                )
                try:
                    existing = con.execute(
                        "SELECT * FROM work_orders WHERE work_id=?",
                        (work_id,),
                    ).fetchone()
                    if existing is not None:
                        existing_payload = json.loads(str(existing["payload_json"] or "{}"))
                        if (
                            str(existing["root"]) != str(root)
                            or str(existing["task"]) != task
                            or existing_payload != normalized
                        ):
                            transaction.rollback()
                            return {
                                "success": False,
                                "error": "work_id already exists with different request",
                                "work_id": work_id,
                                "terminal": True,
                            }
                        transaction.commit()
                        return self._canonical(existing)
                    pending = con.execute(
                        "SELECT COUNT(*) FROM work_orders WHERE state IN ('queued','planning','executing','integrating','verifying')"
                    ).fetchone()
                    if pending and int(pending[0]) >= self.max_pending:
                        transaction.rollback()
                        return {"success": False, "error": "work-order queue is full", "retryable": True, "terminal": False}
                    con.execute("INSERT INTO work_orders(work_id,root,task,state,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                                (work_id, str(root), task, "queued", json_dumps(normalized, separators=(",", ":")), now, now))
                    transaction.commit()
                except BaseException:
                    transaction.rollback()
                    raise
        except sqlite3.IntegrityError:
            return {"success": False, "error": "work_id already exists", "work_id": work_id, "terminal": True}
        self._ensure_workers(); self._wake.set()
        return self._project({"success": True, "status": "queued", "work_id": work_id, "summary": "whole task accepted"}, normalized)

    def _row(self, work_id: str) -> sqlite3.Row | None:
        def query() -> sqlite3.Row | None:
            with closing(self._connect()) as con:
                return con.execute("SELECT * FROM work_orders WHERE work_id=?", (work_id,)).fetchone()
        return retry_busy(query, retries=5, base_delay_seconds=0.02)

    def authorize_bounded_command(self, work_id: str, task_id: str, root: str, command: str) -> bool:
        """Bind broker admission to the live, server-stored work order."""
        if any(not isinstance(value, str) or "\x00" in value for value in (work_id, task_id, root, command)):
            return False
        if not work_id or not root or not command:
            return False
        try:
            row = self._row(work_id)
            if row is None or row["state"] not in {"executing", "verifying"} or row["cancel_requested"]:
                return False
            payload = json.loads(str(row["payload_json"]))
            if not isinstance(payload, dict) or payload.get("mode") != "bounded":
                return False
            commands = payload.get("approved_commands")
            permissions = payload.get("permissions")
            return (payload.get("task_id") == task_id and isinstance(commands, list) and command in commands
                    and isinstance(permissions, dict) and permissions.get("tests") is True
                    and permissions.get("build") is True
                    and os.path.normcase(str(Path(row["root"]).resolve(strict=True)))
                    == os.path.normcase(str(Path(root).resolve(strict=True))))
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
            return False

    def _canonical(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(str(row["payload_json"] or "{}"))
        result = json.loads(str(row["result_json"] or "{}"))
        out = {"success": str(row["state"]) in {"queued", "planning", "executing", "integrating", "verifying", "complete", "needs_agent", "partial"},
               "status": str(row["state"]), "work_id": str(row["work_id"]), **result}
        if payload.get("mode") == "bounded" and str(row["state"]) in {"partial", "needs_agent", "failed", "cancelled"}:
            out["success"] = False
        self._report_active_deadline(out, payload)
        out.setdefault("progress", result.get("progress", {}))
        return self._project(out, payload)

    def _report_active_deadline(self, output: dict[str, Any], payload: dict[str, Any]) -> None:
        if payload.get("mode") != "bounded" or output.get("status") in _TERMINAL:
            return
        with self._lock:
            deadline = self._active_deadlines.get(str(output.get("work_id", "")))
        if deadline is not None and time.monotonic() >= deadline:
            output.update({"success": False, "timed_out": True, "in_progress": True})

    @staticmethod
    def _project(value: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        return project_response(value, profile=str(payload.get("response_profile", "compact")),
                                return_fields=payload.get("return_fields") or None,
                                max_output_tokens=int(payload.get("max_output_tokens", 0) or 0))

    def status(self, work_id: str) -> dict[str, Any]:
        row = self._row(work_id)
        return self._canonical(row) if row else {"success": False, "error": "work order not found", "work_id": work_id}

    def get(self, work_id: str, *, profile: str = "", return_fields: list[str] | None = None, max_output_tokens: int = 0) -> dict[str, Any]:
        row = self._row(work_id)
        if not row:
            return {"success": False, "error": "work order not found", "work_id": work_id}
        payload = json.loads(str(row["payload_json"] or "{}"))
        if profile: payload["response_profile"] = profile
        if return_fields is not None: payload["return_fields"] = return_fields
        if max_output_tokens: payload["max_output_tokens"] = max_output_tokens
        result = json.loads(str(row["result_json"] or "{}"))
        success = str(row["state"]) not in {"failed", "cancelled"}
        if payload.get("mode") == "bounded" and str(row["state"]) in {"partial", "needs_agent"}:
            success = False
        output = {"success": success, "status": str(row["state"]), "work_id": work_id, **result}
        if payload.get("mode") == "bounded" and str(row["state"]) in {"partial", "needs_agent", "failed", "cancelled"}:
            output["success"] = False
        self._report_active_deadline(output, payload)
        return self._project(output, payload)

    def wait(self, work_id: str, timeout_seconds: float = 90) -> dict[str, Any]:
        started = time.perf_counter()
        deadline = time.monotonic() + max(0.0, min(float(timeout_seconds), 90.0))
        while time.monotonic() < deadline:
            row = self._row(work_id)
            if not row:
                result = {"success": False, "error": "work order not found", "work_id": work_id}
                self._record_wait(result, started)
                return result
            if str(row["state"]) in _TERMINAL:
                result = self._canonical(row)
                self._record_wait(result, started)
                return result
            event = self._event(work_id)
            event.wait(min(0.5, max(0.0, deadline - time.monotonic())))
            event.clear()
        result = self.status(work_id)
        result["in_progress"] = result.get("status") not in _TERMINAL
        self._record_wait(result, started)
        return result

    def _record_wait(self, result: dict[str, Any], started: float) -> None:
        if self.telemetry is None:
            return
        try:
            elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            self.telemetry.record(
                event_type="coordination", action="work_wait",
                success=bool(result.get("success")), duration_ms=elapsed_ms,
                wait_count=1, wait_duration_ms=elapsed_ms,
            )
        except Exception:
            pass

    def cancel(self, work_id: str) -> dict[str, Any]:
        row = self._row(work_id)
        if not row:
            return {"success": False, "error": "work order not found", "work_id": work_id}
        terminal_marks = ",".join("?" for _ in _TERMINAL)
        with closing(self._connect()) as con:
            changed = con.execute(
                f"UPDATE work_orders SET cancel_requested=1,updated_at=? WHERE work_id=? AND state NOT IN ({terminal_marks})",
                (time.time(), work_id, *sorted(_TERMINAL)),
            ).rowcount
        if not changed:
            current = self._row(work_id)
            return self._canonical(current) if current else {"success": False, "error": "work order not found", "work_id": work_id}
        with self._lock:
            active_event = self._active_cancellations.get(work_id)
            if active_event is not None:
                active_event.set()
        self._wake.set(); self._event(work_id).set()
        return {"success": True, "status": "cancelling", "work_id": work_id}

    def continue_work(self, work_id: str, answer: str) -> dict[str, Any]:
        row = self._row(work_id)
        if not row:
            return {"success": False, "error": "work order not found", "work_id": work_id}
        if str(row["state"]) != "needs_agent":
            return {"success": False, "error": "work order is not waiting for agent input", "work_id": work_id}
        payload_json = str(row["payload_json"] or "{}")
        result_json = str(row["result_json"] or "{}")
        try:
            payload = json.loads(payload_json)
            previous_result = json.loads(result_json)
        except (TypeError, ValueError):
            return {"success": False, "error": "work order handoff is invalid", "work_id": work_id}
        if not isinstance(payload, dict) or not isinstance(previous_result, dict):
            return {"success": False, "error": "work order handoff is invalid", "work_id": work_id}
        if payload.get("mode") == "bounded":
            if previous_result.get("outcome_unknown", False) is not False:
                return {"success": False, "error": "work outcome is unknown; inspect and reconcile before any new task", "work_id": work_id, "outcome_unknown": True}
            if (previous_result.get("task_barrier_status", "released") != "released"
                    or previous_result.get("rollback_status", "clear") != "clear"):
                return {"success": False, "error": "work handoff requires reconciliation before continuing", "work_id": work_id}
            if previous_result.get("handoff_id") or not isinstance(previous_result.get("question"), str) or not previous_result["question"].strip():
                return {"success": False, "error": "work handoff requires primary review, not continuation", "work_id": work_id}
        payload["agent_answer"] = str(answer).strip()[:8000]
        if not payload["agent_answer"]:
            return {"success": False, "error": "answer is required", "work_id": work_id}
        with closing(self._connect()) as con:
            changed = con.execute(
                "UPDATE work_orders SET state='queued',payload_json=?,cancel_requested=0,updated_at=? WHERE work_id=? AND state='needs_agent' AND cancel_requested=0 AND payload_json=? AND result_json=?",
                (json_dumps(payload, separators=(",", ":")), time.time(), work_id, payload_json, result_json),
            ).rowcount
        if not changed:
            return {"success": False, "error": "work order state changed", "work_id": work_id}
        self._ensure_workers(); self._wake.set(); self._event(work_id).set()
        return {"success": True, "status": "queued", "work_id": work_id}

    def stats(self) -> dict[str, Any]:
        with closing(self._connect()) as con:
            rows = con.execute("SELECT state,COUNT(*) c FROM work_orders GROUP BY state").fetchall()
        with self._lock:
            alive = sum(1 for worker in self._workers if worker.is_alive())
        return {"enabled": self.enabled, "states": {str(r[0]): int(r[1]) for r in rows}, "worker_alive": alive > 0, "active_workers": alive}

    def _event(self, work_id: str) -> threading.Event:
        with self._lock:
            return self._waiters.setdefault(work_id, threading.Event())

    def _set_state(
        self, work_id: str, state: str, result: dict[str, Any], *,
        attempt: WorkAttemptFence | None = None,
    ) -> None:
        guard = self._state_attempt_guard(work_id, attempt)
        with guard:
            with closing(self._connect()) as con:
                terminal_marks = ",".join("?" for _ in _TERMINAL)
                changed = con.execute(
                    f"UPDATE work_orders SET state=?,result_json=?,updated_at=? "
                    f"WHERE work_id=? AND state NOT IN ({terminal_marks})",
                    (state, json_dumps(result, ensure_ascii=False, separators=(",", ":")), time.time(), work_id, *sorted(_TERMINAL)),
                ).rowcount
        if int(changed or 0) != 1:
            raise LeaseLostError("work order is terminal or unavailable")
        with self._lock:
            event = self._waiters.get(work_id)
            if event is not None:
                event.set()
                if state in _TERMINAL:
                    self._waiters.pop(work_id, None)

    def _state_attempt_guard(
        self, work_id: str, attempt: WorkAttemptFence | None
    ):
        if attempt is None:
            return nullcontext()
        if attempt.work_id != work_id:
            raise LeaseLostError("work attempt does not own this work order")
        return self.fencing_store.attempt_guard(attempt)

    def _persist_handoff_receipts(
        self, work_id: str, receipts: list[Any], validation: list[dict[str, Any]], *,
        attempt: WorkAttemptFence | None = None,
    ) -> list[Any]:
        from .agent_verification import VerificationReceipt

        guard = self._state_attempt_guard(work_id, attempt)
        with guard:
            serialized = [receipt.to_dict() for receipt in receipts]
            with closing(self._connect()) as con:
                row = con.execute(
                    "SELECT result_json FROM work_orders WHERE work_id=?", (work_id,)
                ).fetchone()
                if row is None:
                    raise RuntimeError("verification receipt work record is unavailable")
                result = json.loads(str(row[0] or "{}"))
                if not isinstance(result, dict):
                    raise RuntimeError("verification receipt work record is invalid")
                result["validation"] = validation
                result["verification_receipts"] = serialized
                con.execute(
                    "UPDATE work_orders SET result_json=?,updated_at=? WHERE work_id=?",
                    (json_dumps(result, ensure_ascii=False, separators=(",", ":")), time.time(), work_id),
                )

            with closing(self._connect()) as con:
                row = con.execute(
                    "SELECT result_json FROM work_orders WHERE work_id=?", (work_id,)
                ).fetchone()
            if row is None:
                raise RuntimeError("persisted verification receipt work record is unavailable")
            stored = json.loads(str(row[0] or "{}"))
            if not isinstance(stored, dict) or not isinstance(stored.get("verification_receipts"), list):
                raise RuntimeError("persisted verification receipts are invalid")
            return [VerificationReceipt.from_dict(item) for item in stored["verification_receipts"]]

    def _complete_if_not_cancelled(
        self, work_id: str, result: dict[str, Any], *, expected_state: str = "verifying",
        attempt: WorkAttemptFence | None = None,
    ) -> bool:
        guard = self._state_attempt_guard(work_id, attempt)
        with guard:
            with closing(self._connect()) as con:
                changed = con.execute(
                    "UPDATE work_orders SET state='complete',result_json=?,updated_at=? WHERE work_id=? AND state=? AND cancel_requested=0",
                    (json_dumps(result, ensure_ascii=False, separators=(",", ":")), time.time(), work_id, expected_state),
                ).rowcount
        if changed:
            with self._lock:
                event = self._waiters.get(work_id)
                if event is not None:
                    event.set()
                    self._waiters.pop(work_id, None)
        return bool(changed)

    def _set_terminal_if_active(
        self, work_id: str, state: str, result: dict[str, Any], *,
        attempt: WorkAttemptFence | None = None,
    ) -> bool:
        terminal_marks = ",".join("?" for _ in _TERMINAL)
        guard = self._state_attempt_guard(work_id, attempt)
        with guard:
            with closing(self._connect()) as con:
                changed = con.execute(
                    f"UPDATE work_orders SET state=?,result_json=?,updated_at=? WHERE work_id=? AND state NOT IN ({terminal_marks})",
                    (state, json_dumps(result, ensure_ascii=False, separators=(",", ":")), time.time(), work_id, *sorted(_TERMINAL)),
                ).rowcount
        if changed:
            with self._lock:
                event = self._waiters.get(work_id)
                if event is not None:
                    event.set()
                    self._waiters.pop(work_id, None)
        return bool(changed)

    def _fail_if_not_cancelled(
        self, work_id: str, result: dict[str, Any], *, attempt: WorkAttemptFence | None = None
    ) -> bool:
        terminal_marks = ",".join("?" for _ in _TERMINAL)
        guard = self._state_attempt_guard(work_id, attempt)
        with guard:
            with closing(self._connect()) as con:
                changed = con.execute(
                    f"UPDATE work_orders SET state='failed',result_json=?,updated_at=? WHERE work_id=? AND state NOT IN ({terminal_marks}) AND cancel_requested=0",
                    (json_dumps(result, ensure_ascii=False, separators=(",", ":")), time.time(), work_id, *sorted(_TERMINAL)),
                ).rowcount
        if changed:
            with self._lock:
                event = self._waiters.get(work_id)
                if event is not None:
                    event.set()
                    self._waiters.pop(work_id, None)
        return bool(changed)

    def _set_terminal_if_not_cancelled(
        self, work_id: str, state: str, result: dict[str, Any], *,
        attempt: WorkAttemptFence | None = None,
    ) -> bool:
        terminal_marks = ",".join("?" for _ in _TERMINAL)
        guard = self._state_attempt_guard(work_id, attempt)
        with guard:
            with closing(self._connect()) as con:
                changed = con.execute(
                    f"UPDATE work_orders SET state=?,result_json=?,updated_at=? WHERE work_id=? AND state NOT IN ({terminal_marks}) AND cancel_requested=0",
                    (state, json_dumps(result, ensure_ascii=False, separators=(",", ":")), time.time(), work_id, *sorted(_TERMINAL)),
                ).rowcount
        if changed:
            with self._lock:
                event = self._waiters.get(work_id)
                if event is not None:
                    event.set()
                    self._waiters.pop(work_id, None)
        return bool(changed)

    def _cancelled(self, work_id: str) -> bool:
        row = self._row(work_id)
        return bool(row and int(row["cancel_requested"] or 0)) or self._stop.is_set()

    def _next(self) -> sqlite3.Row | None:
        """Atomically claim one queued order for a worker."""
        with closing(self._connect()) as con:
            with write_transaction(
                con,
                max_duration_seconds=5.0,
                rollback_label="work-order queue claim",
            ):
                row = con.execute(
                    "SELECT * FROM work_orders WHERE state='queued' ORDER BY created_at LIMIT 1"
                ).fetchone()
                if row is None:
                    return None
                updated = con.execute(
                    "UPDATE work_orders SET state='planning',updated_at=? WHERE work_id=? AND state='queued'",
                    (time.time(), str(row["work_id"])),
                )
                if int(updated.rowcount or 0) != 1:
                    return None
                return row

    def _loop(self) -> None:
        idle_since = time.monotonic()
        current = threading.current_thread()
        try:
            while not self._stop.is_set():
                row = self._next()
                if row is None:
                    if time.monotonic() - idle_since >= self.worker_idle_seconds:
                        return
                    self._wake.wait(0.5); self._wake.clear(); continue
                idle_since = time.monotonic()
                try:
                    if self.execution_pool is None:
                        self._execute(row)
                    else:
                        self.execution_pool.submit("io", self._execute, row).result()
                except Exception as exc:
                    try:
                        work_id = str(row["work_id"])
                        failure = {"summary": "work order failed", "error": f"{type(exc).__name__}: {exc}"}
                        if not self._fail_if_not_cancelled(work_id, failure):
                            self._set_terminal_if_active(work_id, "cancelled", {"summary": "work order cancelled during worker recovery"})
                    except Exception:
                        pass
        finally:
            # Retire the worker under the same lock used by _ensure_workers. If a
            # submit races with idle retirement, either the submit sees this worker
            # removed and starts a replacement, or this worker observes queued work
            # below and starts one itself. This closes the otherwise possible
            # queued-with-no-worker window.
            with self._lock:
                self._workers = [worker for worker in self._workers if worker is not current and worker.is_alive()]
                if self._worker is current:
                    self._worker = next((worker for worker in self._workers if worker.is_alive()), None)
            if not self._stop.is_set() and self._has_queued_work():
                self._ensure_workers()

    def _ask(
        self,
        root: str,
        task: str,
        context: str,
        max_tokens: int = 4096,
        *,
        review: bool = False,
        complexity: str = "auto",
        task_type: str = "auto",
    ) -> dict[str, Any]:
        event = _WORK_CANCEL_EVENT.get()
        options = {"cancel_event": event} if event is not None else {}
        if review:
            return self.services.second_opinion({"question": task, "candidate": context, "context": "", "max_tokens": max_tokens, "complexity": "auto"}, **options)
        return self.services.delegate_repo({"root": root, "task": task, "context": context, "max_tokens": max_tokens, "complexity": complexity, "task_type": task_type}, **options)

    def _plan(self, root: str, task: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        acceptance = _string_list(payload.get("acceptance_criteria"), limit=24, item_chars=2000)
        if not acceptance:
            raise ValueError("work order requires explicit acceptance criteria")
        budget = payload.get("budget")
        if budget is None:
            budget = {}
        if not isinstance(budget, dict):
            raise ValueError("work order budget must be an object")
        hard_max_steps = min(self.max_steps, 16)
        requested_max_steps = _budget_int(budget.get("max_steps", hard_max_steps), "max_steps")
        if requested_max_steps < 1 or requested_max_steps > hard_max_steps:
            raise ValueError(f"work order max_steps must be between 1 and {hard_max_steps}")
        requested_max_tokens = _budget_int(budget.get("max_tokens", 1400), "max_tokens")
        if requested_max_tokens < 128 or requested_max_tokens > 1400:
            raise ValueError("work order max_tokens must be between 128 and 1400")
        prompt = (
            "PLAN A CODING WORK ORDER. Return STRICT JSON only: "
            '{"summary":"...","needs_agent":false,"question":"","steps":[{"id":"s1","kind":"inspect|edit|validate|review|integrate","task":"...","depends_on":[],"acceptance":["..."]}],"validation_commands":[]}.'
            " Make steps the smallest independently executable+verifiable units, not trivial microsteps. Max 16 steps. "
            "Use deterministic inspection before edits. Include edit steps only if requested. Do not invent files unless evidence supports them.\n"
            f"ORIGINAL TASK:\n{task}\nACCEPTANCE:\n{json_dumps(acceptance, ensure_ascii=False)}\n"
            f"CONSTRAINTS:\n{json_dumps(payload.get('constraints') or [], ensure_ascii=False)}"
            + (f"\nALLOWED FILES:\n{json_dumps(payload.get('allowed_paths'))}\nAPPROVED COMMANDS:\n{json_dumps(payload.get('approved_commands'))}" if payload.get("mode") == "bounded" else "")
            + ("\nEdits are disabled; do not plan edit steps." if payload.get("mode") == "bounded" and not payload.get("permissions", {}).get("edit") else "")
            + (f"\nAGENT ANSWER TO PRIOR BLOCKER:\n{str(payload.get('agent_answer',''))[:8000]}" if payload.get("agent_answer") else "")
        )
        res = self._ask(root, prompt, json_dumps(context, ensure_ascii=False)[:14000], requested_max_tokens)
        if payload.get("mode") == "bounded" and not _certain_work_model_response(res):
            raise ValueError(_work_model_response_error(res, "work planner"))
        parsed = _json_object(str(res.get("text", ""))) if isinstance(res, dict) and res.get("success", True) else None
        if not parsed or not isinstance(parsed.get("steps"), list):
            if payload.get("mode") == "bounded":
                raise ValueError("bounded work planner returned an invalid or unsuccessful response")
            parsed = {"summary": task[:240], "needs_agent": False, "question": "", "steps": [
                {"id": "s1", "kind": "inspect", "task": task, "depends_on": [], "acceptance": []},
                {"id": "s2", "kind": "edit", "task": task, "depends_on": ["s1"], "acceptance": acceptance},
                {"id": "s3", "kind": "validate", "task": "Run the smallest relevant validation commands", "depends_on": ["s2"], "acceptance": acceptance},
                {"id": "s4", "kind": "review", "task": "Review the integrated change against the original task", "depends_on": ["s3"], "acceptance": acceptance},
            ], "validation_commands": []}
        raw_steps = parsed.get("steps", [])
        if len(raw_steps) > requested_max_steps:
            raise ValueError(f"planner returned more than the {requested_max_steps} step budget")
        cleaned=[]; seen=set()
        for i, raw in enumerate(raw_steps):
            if not isinstance(raw, dict):
                raise ValueError("planner returned a non-object step")
            sid = str(raw.get("id") or "").strip()[:40]
            if not sid:
                raise ValueError("planner returned an empty step id")
            if sid in seen:
                raise ValueError("planner returned duplicate planner step ids")
            seen.add(sid)
            kind=str(raw.get("kind", "inspect")).strip().lower()
            if kind not in {"inspect","edit","validate","review","integrate"}:
                raise ValueError(f"planner returned unknown planner step kind: {kind[:40]}")
            raw_dependencies = raw.get("depends_on", [])
            if not isinstance(raw_dependencies, list):
                raise ValueError(f"planner step {sid} dependencies must be a list")
            if any(not isinstance(dep, str) or not dep.strip() for dep in raw_dependencies):
                raise ValueError(f"planner step {sid} contains an invalid dependency")
            deps = [dep.strip() for dep in raw_dependencies]
            step_task=str(raw.get("task", "")).strip()[:2000] or f"{kind} work-order evidence"
            step_acceptance = _string_list(raw.get("acceptance"), limit=12, item_chars=2000) or acceptance[:12]
            cleaned.append({
                "id":sid, "kind":kind, "task":step_task, "depends_on":deps,
                "acceptance":step_acceptance,
                "state":"pending",
            })
        def declared_limit(name: str, default: int) -> int:
            limit = _budget_int(budget.get(name, default), name)
            if limit < 0 or limit > requested_max_steps:
                raise ValueError(f"work order {name} must be between 0 and {requested_max_steps}")
            return limit

        max_edit_steps = declared_limit("max_edits", requested_max_steps)
        if sum(step["kind"] == "edit" for step in cleaned) > max_edit_steps:
            raise ValueError(f"planner returned more than the {max_edit_steps} edit-step budget")
        raw_commands = parsed.get("validation_commands", [])
        if not isinstance(raw_commands, list) or any(not isinstance(command, str) or not command.strip() for command in raw_commands):
            raise ValueError("planner validation_commands must be a list of non-empty strings")
        max_commands = declared_limit("max_commands", requested_max_steps)
        if len(raw_commands) > max_commands:
            raise ValueError(f"planner returned more than the {max_commands} command budget")
        parsed["validation_commands"] = [command.strip() for command in raw_commands]
        parsed["acceptance_criteria"] = acceptance
        parsed["steps"] = _stable_toposort_steps(cleaned) if cleaned else [{"id":"s1","kind":"inspect","task":task,"depends_on":[],"acceptance":acceptance,"state":"pending"}]
        return parsed

    def close(self) -> None:
        self._stop.set(); self._wake.set()
        with self._lock:
            recovery_timer = self._recovery_timer
            self._recovery_timer = None
        if recovery_timer is not None:
            recovery_timer.cancel()
        current = threading.current_thread()
        with self._lock:
            workers = list(self._workers)
        for worker in workers:
            if worker is not current and worker.is_alive():
                worker.join(timeout=2.0)
