from __future__ import annotations

import queue
import sys
import threading
import time
import types
import weakref
from pathlib import Path
from typing import Any

from .agent_events import AgentEvent, AgentStateStore
from .agent_identity import AgentScope, ScopeContext
from .sqlite_support import connect_sqlite, retry_busy, write_transaction
from .task_memory_wire import mcp_wire_tokens, task_memory_wire_tokens
from .agent_task_core import TaskCoreMixin
from .agent_task_lifecycle import TaskLifecycleMixin
from .agent_task_memory import TaskMemoryMixin
from .agent_task_models import (
    MAX_AGENT_QUESTION_BYTES,
    MAX_TASK_QUERY_SCAN_ROWS,
    MAX_TASK_REAP_BATCH,
    MAX_TRAINING_DATASET_BYTES,
    VALID_TRANSITIONS,
    CheckpointResponseBudgetError,
    CompletionGateError,
    ConcurrentTaskUpdateError,
    GoalContract,
    InvalidTransitionError,
    TaskCheckpoint,
    TaskIdempotencyConflictError,
    TaskPage,
    TaskState,
    TaskStatus,
    TaskWorktreeError,
    _AGENT_TASK_WRITE_TIMEOUT_SECONDS,
    _canonical_repository_root,
    _checkpoint_with_scheduled_worktree_cleanup,
    _preserve_checkpoint_memory_state,
    _task_matches_scope,
    _task_scope_root,
    _validate_checkpoint_memory_context,
)
from .agent_task_mutation import TaskMutationMixin
from .agent_task_plan import TaskPlanSyncMixin
from .agent_task_questions import TaskQuestionMixin
from .agent_task_training import TaskTrainingMixin
from .agent_task_worktree import TaskWorktreeMixin
from . import (
    agent_task_core as _agent_task_core,
    agent_task_lifecycle as _agent_task_lifecycle,
    agent_task_memory as _agent_task_memory,
    agent_task_mutation as _agent_task_mutation,
    agent_task_plan as _agent_task_plan,
    agent_task_questions as _agent_task_questions,
    agent_task_training as _agent_task_training,
    agent_task_worktree as _agent_task_worktree,
)

__all__ = [
    "TaskStore",
    "AgentEvent",
    "AgentStateStore",
    "AgentScope",
    "ScopeContext",
    "TaskStatus",
    "VALID_TRANSITIONS",
    "GoalContract",
    "TaskCheckpoint",
    "TaskState",
    "TaskPage",
    "CompletionGateError",
    "CheckpointResponseBudgetError",
    "TaskWorktreeError",
    "TaskIdempotencyConflictError",
    "InvalidTransitionError",
    "ConcurrentTaskUpdateError",
    "MAX_TASK_QUERY_SCAN_ROWS",
    "MAX_TASK_REAP_BATCH",
    "MAX_AGENT_QUESTION_BYTES",
    "_AGENT_TASK_WRITE_TIMEOUT_SECONDS",
    "MAX_TRAINING_DATASET_BYTES",
    "_validate_checkpoint_memory_context",
    "_preserve_checkpoint_memory_state",
    "_checkpoint_with_scheduled_worktree_cleanup",
    "_canonical_repository_root",
    "_task_scope_root",
    "_task_matches_scope",
    "Path",
    "time",
    "connect_sqlite",
    "retry_busy",
    "write_transaction",
    "mcp_wire_tokens",
    "task_memory_wire_tokens",
]


class TaskStore(
    TaskMemoryMixin,
    TaskQuestionMixin,
    TaskCoreMixin,
    TaskLifecycleMixin,
    TaskMutationMixin,
    TaskWorktreeMixin,
    TaskPlanSyncMixin,
    TaskTrainingMixin,
):
    def __init__(
        self,
        state_store: AgentStateStore,
        *,
        default_heartbeat_ttl: float = 300.0,
        policy_engine: Any | None = None,
    ) -> None:
        self.state_store = state_store
        self.default_heartbeat_ttl = float(default_heartbeat_ttl)
        self.policy_engine = policy_engine
        self.verification_store: Any | None = None
        self.memory_store: Any | None = None
        self.memory_context_compiler: Any | None = None
        self.incident_store: Any | None = None
        self._laya_completion_observer: Any | None = None
        self._memory_lookup_slots = threading.BoundedSemaphore(1)
        self._memory_lookup_queue: queue.Queue[Any] = queue.Queue(maxsize=1)
        self._memory_lookup_worker: threading.Thread | None = None
        self._memory_lookup_finalizer = weakref.finalize(self, self._memory_lookup_queue.put_nowait, None)
        self._memory_lookup_finalizer.atexit = False
        self._lock = threading.RLock()
        self._idle_worktree_cursor: tuple[float, str] = (0.0, "")
        self._initialized = False
        self._init_projection_table()

    class _MemoryDeadlineExceeded(Exception):
        pass


for _task_module in (
    _agent_task_memory,
    _agent_task_questions,
    _agent_task_core,
    _agent_task_lifecycle,
    _agent_task_mutation,
    _agent_task_worktree,
    _agent_task_plan,
    _agent_task_training,
):
    _task_module.TaskStore = TaskStore


class _TaskStoreModuleProxy(types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        for module in (
            _agent_task_memory,
            _agent_task_questions,
            _agent_task_core,
            _agent_task_lifecycle,
            _agent_task_mutation,
            _agent_task_worktree,
            _agent_task_plan,
            _agent_task_training,
        ):
            if hasattr(module, name):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _TaskStoreModuleProxy
