from __future__ import annotations

import base64 as base64
import codecs as codecs
from contextlib import contextmanager as contextmanager
import getpass  # noqa: F401
import hashlib as hashlib
import inspect as inspect
import io as io
import json as json
import logging as logging
import math as math
import os
import queue as queue
import re
import ntpath as ntpath
import shlex as shlex
import shutil as shutil
import signal  # noqa: F401
import subprocess as subprocess
import sys
import types
import tempfile as tempfile
import threading
import time as time
import uuid as uuid
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import command_streams as _command_streams
from .command_policy import (
    DANGEROUS_EXES,
    KNOWN_PYTHON_MODULES,
    MUTATING_WORDS,
    PURE_VALIDATORS,
    READ_FILTERS,
    READ_ONLY,
    SHELL_INTERPRETERS,
    VALIDATORS,
    VOLATILE_READS,
    _classification_result as _classification_result,
    classify_dangerous_or_whitelisted_tool as classify_dangerous_or_whitelisted_tool,
    classify_command_sequence as classify_command_sequence,
    classify_pipeline_filter as classify_pipeline_filter,
    command_executable_identity as command_executable_identity,
    contains_user_whitelisted_tool as contains_user_whitelisted_tool,
    is_interactive_command_prompt,
    is_interactive_output_prompt,
    normalize_user_whitelisted_tools as normalize_user_whitelisted_tools,
)
from .command_git import classify_git_command as classify_git_command
from .command_patch_paths import (
    _parse_git_apply_numstat as _parse_git_apply_numstat_impl,
    _patch_relative_parts as _patch_relative_parts,
    _patch_target_path as _patch_target_path,
)
_parse_git_apply_numstat = _parse_git_apply_numstat_impl
from .command_project_cache import _project_config_cache_key as _project_config_cache_key
from .command_models import CommandInvocation, ProjectContextLike as ProjectContextLike, _ResolvedProjectCommand as _ResolvedProjectCommand
from .command_environment import (
    PROJECT_COMMAND_ENV_KEY_RE as _PROJECT_COMMAND_ENV_KEY_RE,  # noqa: F401
    is_valid_project_command_env_key as _is_valid_project_command_env_key,  # noqa: F401
    resolve_project_environment as resolve_project_environment,
)
from .command_python import (
    classify_python_command as classify_python_command,
    classify_hubctl_command as classify_hubctl_command,
    is_well_formed_command_input as is_well_formed_command_input,
    is_python_interpreter_name as is_python_interpreter_name,
    python_inline_code_syntax_is_valid,
)
from .command_build import classify_build_command as classify_build_command
from .command_powershell import classify_powershell_command as classify_powershell_command
from .command_read import classify_read_only_command as classify_read_only_command
from .command_shell import (
    classify_raw_shell_subshell as classify_raw_shell_subshell,
    is_powershell_command as is_powershell_command,
    needs_shell as needs_shell,
    split_shell_command as split_shell_command,
    strip_null_redirections as strip_null_redirections,
    tokenize_command as tokenize_command,
)
from .command_validation import (
    classify_formatter_command as classify_formatter_command,
    classify_php_validation_script as classify_php_validation_script,
    classify_validation_tool as classify_validation_tool,
)
from .trace_utils import cluster_stack_traces, deduplicate_stack_traces as deduplicate_stack_traces


def _is_interactive_prompt(text: str) -> bool:
    return is_interactive_command_prompt(text) or is_interactive_output_prompt(text)


MultiplexEvent = _command_streams.MultiplexEvent
StreamMultiplexer = _command_streams.StreamMultiplexer
_SECRET_PATTERNS = _command_streams._SECRET_PATTERNS
_redact_secrets = _command_streams._redact_secrets
_BoundedStreamBuffer = _command_streams._BoundedStreamBuffer
from .cache import SQLiteCache, TieredCache, stable_hash as stable_hash
from .command_transactions import (
    PatchFileSnapshot as PatchFileSnapshot,
    PatchTargetsSnapshot as PatchTargetsSnapshot,
    RollbackFileSnapshot as RollbackFileSnapshot,
    RollbackPostimage as RollbackPostimage,
    RollbackSnapshot as RollbackSnapshot,
    create_private_transaction_snapshot_with_manifest as create_private_transaction_snapshot_with_manifest,
    validate_transaction_output as validate_transaction_output,
    verify_transaction_source_unchanged as verify_transaction_source_unchanged,
)
from .leases import ScopeLeaseStore
from .work_fencing import WorkAttemptFence as WorkAttemptFence
from .features import rollout_feature_enabled as rollout_feature_enabled
from .process_utils import (
    _resume_suspended_process as _resume_suspended_process,
    canonical_root as canonical_root,
    create_job_object_kill_on_close,
    hidden_run_kwargs as hidden_run_kwargs,
    process_identity as process_identity,
    terminate_tree as terminate_tree,
)
from .state_paths import configured_state_dir
from .json_utils import dumps as json_dumps  # noqa: F401










_GLOBAL_WINDOWS_JOB = create_job_object_kill_on_close() if os.name == "nt" else None
from .command_constants import (
    _COMMAND_LOG_QUEUE_MAX_CHUNKS as _COMMAND_LOG_QUEUE_MAX_CHUNKS,
    _MAX_INVOCATION_ERROR_CHARS as _MAX_INVOCATION_ERROR_CHARS,
    _MAX_PROJECT_COMMAND_ARGS as _MAX_PROJECT_COMMAND_ARGS,
    _MAX_PROJECT_COMMAND_ENV_BYTES as _MAX_PROJECT_COMMAND_ENV_BYTES,
    _MAX_PROJECT_COMMAND_ENV_ENTRIES as _MAX_PROJECT_COMMAND_ENV_ENTRIES,
    _PROJECT_COMMAND_ALIAS_RE as _PROJECT_COMMAND_ALIAS_RE,
)










_DIAGNOSTIC_PATTERNS = [
    re.compile(r"^(?P<path>[^:\n]+):(?P<line>\d+)(?::(?P<col>\d+))?[:\s]+(?P<msg>.+)$"),
    re.compile(r"^FAILED\s+(?P<path>[^:\s]+)(?:::(?P<msg>.+))?$"),
]
from . import command_jobs as _command_jobs
from . import command_rollback as _command_rollback
from . import command_rollback_windows as _command_rollback_windows
from .command_jobs import (
    assign_process_to_job as assign_process_to_job,
    close_job_object as close_job_object,
    create_job_object_kill_on_close as create_job_object_kill_on_close,
    create_named_daemon_job as create_named_daemon_job,
    daemon_job_name as daemon_job_name,
    duplicate_job_handle_into_process as duplicate_job_handle_into_process,
    is_windows_process_alive as is_windows_process_alive,
    open_named_daemon_job as open_named_daemon_job,
    set_windows_job_kill_on_close as set_windows_job_kill_on_close,
    stop_windows_job_process as stop_windows_job_process,
    terminate_and_confirm_windows_job_empty as terminate_and_confirm_windows_job_empty,
    terminate_job_object as terminate_job_object,
    wait_windows_job_empty as wait_windows_job_empty,
    windows_job_contains_process as windows_job_contains_process,
    windows_job_has_processes as windows_job_has_processes,
    _create_named_daemon_job as _create_named_daemon_job,
    _daemon_job_name as _daemon_job_name,
    _duplicate_job_handle_into_process as _duplicate_job_handle_into_process,
    _open_named_daemon_job as _open_named_daemon_job,
    _set_windows_job_kill_on_close as _set_windows_job_kill_on_close,
    _terminate_and_confirm_windows_job_empty as _terminate_and_confirm_windows_job_empty,
    _wait_windows_job_empty as _wait_windows_job_empty,
    _windows_job_contains_process as _windows_job_contains_process,
    _windows_job_has_processes as _windows_job_has_processes,
)
from .command_rollback import (
    _MAX_ROLLBACK_PATHS as _MAX_ROLLBACK_PATHS,
    _MAX_ROLLBACK_FILE_BYTES as _MAX_ROLLBACK_FILE_BYTES,
    _MAX_ROLLBACK_TOTAL_BYTES as _MAX_ROLLBACK_TOTAL_BYTES,
    _MAX_ROLLBACK_METADATA_BYTES as _MAX_ROLLBACK_METADATA_BYTES,
    _MAX_ROLLBACK_PATCH_BYTES as _MAX_ROLLBACK_PATCH_BYTES,
    _RollbackPostimageChanged as _RollbackPostimageChanged,
    _snapshot_patch_targets as _snapshot_patch_targets,
    _assert_patch_root as _assert_patch_root,
    _hash_patch_target as _hash_patch_target,
    _restore_patch_targets as _restore_patch_targets,
    _get_windows_dacl as _get_windows_dacl,
    _set_windows_dacl as _set_windows_dacl,
    _set_windows_dacl_path as _set_windows_dacl_path,
    _restore_windows_file_attributes as _restore_windows_file_attributes,
    _restore_windows_file_times as _restore_windows_file_times,
    _restore_windows_atime as _restore_windows_atime,
    _delete_windows_handle as _delete_windows_handle,
    _rename_windows_handle as _rename_windows_handle,
    _windows_dacl_bytes as _windows_dacl_bytes,
    _acquire_rollback_root as _acquire_rollback_root,
    _close_rollback_root as _close_rollback_root,
    _rollback_snapshot_open_flags as _rollback_snapshot_open_flags,
    _open_rollback_snapshot_file as _open_rollback_snapshot_file,
    _open_rollback_parent_handle as _open_rollback_parent_handle,
    _open_rollback_relative_handle as _open_rollback_relative_handle,
    _windows_handle_attributes as _windows_handle_attributes,
    _windows_handle_identity as _windows_handle_identity,
    _rollback_root_identity as _rollback_root_identity,
    _snapshot_rollback_scope as _snapshot_rollback_scope,
    _rename_exchange_at as _rename_exchange_at,
    _rename_noreplace_at as _rename_noreplace_at,
    _restore_existing_rollback_leaf as _restore_existing_rollback_leaf,
    _restore_rollback_scope as _restore_rollback_scope,
    _rollback_postimage_at as _rollback_postimage_at,
    _capture_rollback_postimages as _capture_rollback_postimages,
    _same_rollback_postimage_after_owned_rename as _same_rollback_postimage_after_owned_rename,
    _patch_write_paths as _patch_write_paths,
    simulate_patch as simulate_patch,
    patch_dry_run as patch_dry_run,
)


class _CommandsModuleProxy(types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        for mod in (
            _command_jobs, _command_rollback, _command_rollback_windows,
            *(sys.modules.get(f"{__package__}.{name}") for name in (
                "command_daemon_process", "command_daemon_registry", "command_daemon_lifecycle", "command_run", "command_patch", "command_repair", "command_execute", "command_transaction_journal", "command_transaction_execute", "command_verification", "command_authorization", "command_classification", "command_cache", "command_diagnostics", "command_output",
            )),
        ):
            if mod is None:
                continue
            if hasattr(mod, name):
                setattr(mod, name, value)
            if name.startswith('_') and hasattr(mod, name[1:]):
                setattr(mod, name[1:], value)
            elif not name.startswith('_') and hasattr(mod, '_' + name):
                setattr(mod, '_' + name, value)

    def __delattr__(self, name: str) -> None:
        super().__delattr__(name)
        for mod in (
            _command_jobs, _command_rollback, _command_rollback_windows,
            *(sys.modules.get(f"{__package__}.{name}") for name in (
                "command_daemon_process", "command_daemon_registry", "command_daemon_lifecycle", "command_run", "command_patch", "command_repair", "command_execute", "command_transaction_journal", "command_transaction_execute", "command_verification", "command_authorization", "command_classification", "command_cache", "command_diagnostics", "command_output",
            )),
        ):
            if mod is None:
                continue
            if hasattr(mod, name):
                try:
                    delattr(mod, name)
                except AttributeError:
                    pass
            if name.startswith('_') and hasattr(mod, name[1:]):
                try:
                    delattr(mod, name[1:])
                except AttributeError:
                    pass
            elif not name.startswith('_') and hasattr(mod, '_' + name):
                try:
                    delattr(mod, '_' + name)
                except AttributeError:
                    pass


sys.modules[__name__].__class__ = _CommandsModuleProxy



from .command_invocation_validation import (
    _invocation_cwd as _invocation_cwd,
    _invocation_error as _invocation_error,
    validate_invocation as validate_invocation,
)


def build_invocation(
    executable: str,
    args: Sequence[str] = (),
    *,
    cwd: str | os.PathLike[str] | None = None,
) -> CommandInvocation:
    """Build validated argv input for subprocess APIs; never construct shell text."""
    if isinstance(args, (str, bytes)) or not isinstance(args, (list, tuple)):
        raise ValueError("args must be a list or tuple of strings")
    result = validate_invocation({"argv": [executable, *args], "cwd": cwd, "shell": False})
    if not result["safe"]:
        raise ValueError(result["error"])
    return CommandInvocation(argv=result["argv"], cwd=result["cwd"], shell=False)


from .command_rollback import _stable_rollback_status as _stable_rollback_status
from .command_singleflight import _CommandSingleflightEvent as _CommandSingleflightEvent



from .command_daemon_process import (
    _RecoveredDaemonProcess as _RecoveredDaemonProcess,  # noqa: F401
    _daemon_process_group_alive as _daemon_process_group_alive,  # noqa: F401
    _daemon_process_group_owned as _daemon_process_group_owned,  # noqa: F401
    _linux_group_member_owns_token as _linux_group_member_owns_token,  # noqa: F401
    _process_exited_without_reaping as _process_exited_without_reaping,  # noqa: F401
    _process_group_liveness as _process_group_liveness,  # noqa: F401
    _process_leader_exited as _process_leader_exited,  # noqa: F401
    _stop_daemon_tree as _stop_daemon_tree,  # noqa: F401
    _terminate_owned_linux_daemon_group as _terminate_owned_linux_daemon_group,  # noqa: F401
)
from .command_daemon_registry import CommandDaemonRegistryMixin
from .command_daemon_lifecycle import CommandDaemonLifecycleMixin
from .command_run import CommandRunMixin
from .command_patch import CommandPatchMixin
from .command_repair import CommandRepairMixin
from .command_execute import CommandExecuteMixin
from .command_transaction_journal import CommandTransactionJournalMixin
from .command_transaction_execute import CommandTransactionExecuteMixin
from .command_verification import CommandVerificationMixin
from .command_authorization import CommandAuthorizationMixin
from .command_classification import CommandClassificationMixin
from .command_cache import CommandCacheMixin
from .command_diagnostics import CommandDiagnosticsMixin
from .command_output import CommandOutputMixin

class CommandBroker(CommandAuthorizationMixin, CommandClassificationMixin, CommandCacheMixin, CommandDiagnosticsMixin, CommandPatchMixin, CommandOutputMixin, CommandRunMixin, CommandExecuteMixin, CommandRepairMixin, CommandTransactionJournalMixin, CommandTransactionExecuteMixin, CommandVerificationMixin, CommandDaemonLifecycleMixin, CommandDaemonRegistryMixin):
    """Safe shared command runner with repo-state-aware cache and single-flight."""

    # Keep the historical class-level surface while policy data lives separately.
    READ_ONLY = READ_ONLY
    READ_FILTERS = READ_FILTERS
    VOLATILE_READS = VOLATILE_READS
    VALIDATORS = VALIDATORS
    PURE_VALIDATORS = PURE_VALIDATORS
    KNOWN_PYTHON_MODULES = KNOWN_PYTHON_MODULES
    MUTATING_WORDS = MUTATING_WORDS
    DANGEROUS_EXES = DANGEROUS_EXES

    def __init__(self, config: dict[str, Any], artifacts: Any = None, repo_state: Any = None):
        self.config = config
        self.artifacts = artifacts
        self._project_command_context_cache: OrderedDict[str, Any] = OrderedDict()
        self._project_command_context_cache_lock = threading.Lock()
        if repo_state is None:
            from .repo_state import RepoStateTracker
            repo_state = RepoStateTracker(config)
        self.repo_state = repo_state
        cfg = config.get("commands", {})
        self.enabled = bool(cfg.get("enabled", True))
        # Classification denial is mandatory; legacy policy_blocking=false cannot authorize execution.
        self.policy_blocking = True
        self.timeout = int(cfg.get("timeout_seconds", 1800))
        self.max_output_chars = int(cfg.get("max_output_chars", 2_000_000))
        self.max_output_bytes = int(cfg.get("max_output_bytes", 8_000_000))
        self.inline_chars = int(cfg.get("inline_output_chars", 5000))
        self.daemon_log_max_bytes = min(2 * 1024 * 1024, max(1024, int(cfg.get("daemon_log_max_bytes", 512 * 1024))))
        self.daemon_ttl_seconds = min(7 * 24 * 60 * 60, max(1, int(cfg.get("daemon_ttl_seconds", 24 * 60 * 60))))
        self.max_daemons = min(32, max(1, int(cfg.get("daemon_max_count", 16))))
        self._daemon_owner_id = self._get_daemon_owner_id()
        self.coalesce_wait_seconds = max(1.0, float(cfg.get("coalesced_wait_seconds", 90.0)))
        self.terminate_grace_seconds = max(0.1, float(cfg.get("terminate_grace_seconds", 2.0)))
        self.post_kill_drain_seconds = max(0.1, float(cfg.get("post_kill_drain_seconds", 2.0)))
        workspace_cache = config.get("workspace_cache", {})
        self.git_snapshot_timeout = max(0.5, float(workspace_cache.get("git_status_timeout_seconds", 2.5)))
        state_dir = configured_state_dir(config)
        self._transaction_state_dir = state_dir / "command-transactions"
        self._transaction_leases = ScopeLeaseStore(state_dir)
        self._active_transaction_roots: dict[str, Path] = {}
        self._active_transaction_sources: dict[str, Path] = {}
        self._transaction_roots_lock = threading.RLock()
        self._daemon_state_dir = state_dir / "daemons"
        self._daemon_registry_path = self._daemon_state_dir / "registry.json"
        l1_entries = int(cfg.get("l1_entries", 128))
        configured_l1_ttl = max(0, int(cfg.get("l1_ttl_seconds", 900)))

        def effective_l1_ttl(
            persistent_ttl: int, *, max_l1_ttl: int | None = None
        ) -> int:
            l1_ttl = configured_l1_ttl
            if max_l1_ttl is not None:
                l1_ttl = min(l1_ttl, max_l1_ttl)
            persistent_ttl = max(0, int(persistent_ttl))
            if persistent_ttl == 0:
                return l1_ttl
            if l1_ttl == 0:
                return persistent_ttl
            return min(l1_ttl, persistent_ttl)

        success_ttl = max(0, int(cfg.get("success_ttl_seconds", 43200)))
        failure_ttl = max(0, int(cfg.get("failure_ttl_seconds", 180)))
        suppression_ttl = max(0, int(cfg.get("suppression_ttl_seconds", 900)))
        self.success_cache = TieredCache(
            SQLiteCache(
                state_dir / "cache.sqlite3",
                "command:success",
                success_ttl,
                int(cfg.get("max_entries", 5000)),
            ),
            l1_entries,
            effective_l1_ttl(success_ttl),
        )
        self.failure_cache = TieredCache(
            SQLiteCache(
                state_dir / "cache.sqlite3",
                "command:failure",
                failure_ttl,
                int(cfg.get("max_failure_entries", 1000)),
            ),
            max(32, l1_entries // 2),
            effective_l1_ttl(failure_ttl, max_l1_ttl=300),
        )
        self.suppression_cache = TieredCache(
            SQLiteCache(
                state_dir / "cache.sqlite3",
                "command:suppression",
                suppression_ttl,
                int(cfg.get("max_suppression_entries", 2000)),
            ),
            max(32, l1_entries // 2),
            effective_l1_ttl(suppression_ttl, max_l1_ttl=300),
        )
        self._lock = threading.Lock()
        self._inflight: dict[str, threading.Event] = {}
        self._last: dict[str, dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0
        self.coalesced = 0
        self.coalesced_timeouts = 0
        self.executed = 0
        self.blocked = 0
        self.suppressed = 0
        self.cancelled = 0
        self._blocked_by_reason: dict[str, int] = {}
        self._active_commands: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._active_cancel_keys: dict[str, tuple[str, str]] = {}
        self._daemons: dict[str, dict[str, Any]] = {}
        self._daemons_lock = threading.Lock()
        self._daemon_slots = threading.BoundedSemaphore(self.max_daemons)
        self._load_daemon_registry()
        self.incident_store: Any = None
        self.verification_store: Any = None
        self.policy_engine: Any = None
        self.task_store: Any = None
        self.fencing_lease_store: Any = None
        self.error_distiller: Any = None

































































































































__all__ = [
    'Any',
    'CommandAuthorizationMixin',
    'CommandBroker',
    'CommandCacheMixin',
    'CommandClassificationMixin',
    'CommandDaemonLifecycleMixin',
    'CommandDaemonRegistryMixin',
    'CommandDiagnosticsMixin',
    'CommandExecuteMixin',
    'CommandInvocation',
    'CommandOutputMixin',
    'CommandPatchMixin',
    'CommandRepairMixin',
    'CommandRunMixin',
    'CommandTransactionExecuteMixin',
    'CommandTransactionJournalMixin',
    'CommandVerificationMixin',
    'DANGEROUS_EXES',
    'KNOWN_PYTHON_MODULES',
    'MUTATING_WORDS',
    'MultiplexEvent',
    'OrderedDict',
    'PURE_VALIDATORS',
    'PatchFileSnapshot',
    'PatchTargetsSnapshot',
    'Path',
    'ProjectContextLike',
    'READ_FILTERS',
    'READ_ONLY',
    'RollbackFileSnapshot',
    'RollbackPostimage',
    'RollbackSnapshot',
    'SHELL_INTERPRETERS',
    'SQLiteCache',
    'ScopeLeaseStore',
    'Sequence',
    'StreamMultiplexer',
    'TieredCache',
    'VALIDATORS',
    'VOLATILE_READS',
    'WorkAttemptFence',
    '_BoundedStreamBuffer',
    '_COMMAND_LOG_QUEUE_MAX_CHUNKS',
    '_CommandSingleflightEvent',
    '_CommandsModuleProxy',
    '_DIAGNOSTIC_PATTERNS',
    '_GLOBAL_WINDOWS_JOB',
    '_MAX_INVOCATION_ERROR_CHARS',
    '_MAX_PROJECT_COMMAND_ARGS',
    '_MAX_PROJECT_COMMAND_ENV_BYTES',
    '_MAX_PROJECT_COMMAND_ENV_ENTRIES',
    '_MAX_ROLLBACK_FILE_BYTES',
    '_MAX_ROLLBACK_METADATA_BYTES',
    '_MAX_ROLLBACK_PATCH_BYTES',
    '_MAX_ROLLBACK_PATHS',
    '_MAX_ROLLBACK_TOTAL_BYTES',
    '_PROJECT_COMMAND_ALIAS_RE',
    '_PROJECT_COMMAND_ENV_KEY_RE',
    '_RecoveredDaemonProcess',
    '_ResolvedProjectCommand',
    '_RollbackPostimageChanged',
    '_SECRET_PATTERNS',
    '_acquire_rollback_root',
    '_assert_patch_root',
    '_capture_rollback_postimages',
    '_classification_result',
    '_close_rollback_root',
    '_command_jobs',
    '_command_rollback',
    '_command_rollback_windows',
    '_command_streams',
    '_create_named_daemon_job',
    '_daemon_job_name',
    '_daemon_process_group_alive',
    '_daemon_process_group_owned',
    '_delete_windows_handle',
    '_duplicate_job_handle_into_process',
    '_get_windows_dacl',
    '_hash_patch_target',
    '_invocation_cwd',
    '_invocation_error',
    '_is_interactive_prompt',
    '_is_valid_project_command_env_key',
    '_linux_group_member_owns_token',
    '_open_named_daemon_job',
    '_open_rollback_parent_handle',
    '_open_rollback_relative_handle',
    '_open_rollback_snapshot_file',
    '_parse_git_apply_numstat',
    '_parse_git_apply_numstat_impl',
    '_patch_relative_parts',
    '_patch_target_path',
    '_patch_write_paths',
    '_process_exited_without_reaping',
    '_process_group_liveness',
    '_process_leader_exited',
    '_project_config_cache_key',
    '_redact_secrets',
    '_rename_exchange_at',
    '_rename_noreplace_at',
    '_rename_windows_handle',
    '_restore_existing_rollback_leaf',
    '_restore_patch_targets',
    '_restore_rollback_scope',
    '_restore_windows_atime',
    '_restore_windows_file_attributes',
    '_restore_windows_file_times',
    '_resume_suspended_process',
    '_rollback_postimage_at',
    '_rollback_root_identity',
    '_rollback_snapshot_open_flags',
    '_same_rollback_postimage_after_owned_rename',
    '_set_windows_dacl',
    '_set_windows_dacl_path',
    '_set_windows_job_kill_on_close',
    '_snapshot_patch_targets',
    '_snapshot_rollback_scope',
    '_stable_rollback_status',
    '_stop_daemon_tree',
    '_terminate_and_confirm_windows_job_empty',
    '_terminate_owned_linux_daemon_group',
    '_wait_windows_job_empty',
    '_windows_dacl_bytes',
    '_windows_handle_attributes',
    '_windows_handle_identity',
    '_windows_job_contains_process',
    '_windows_job_has_processes',
    'annotations',
    'assign_process_to_job',
    'base64',
    'build_invocation',
    'canonical_root',
    'classify_build_command',
    'classify_command_sequence',
    'classify_dangerous_or_whitelisted_tool',
    'classify_formatter_command',
    'classify_git_command',
    'classify_hubctl_command',
    'classify_php_validation_script',
    'classify_pipeline_filter',
    'classify_powershell_command',
    'classify_python_command',
    'classify_raw_shell_subshell',
    'classify_read_only_command',
    'classify_validation_tool',
    'close_job_object',
    'cluster_stack_traces',
    'codecs',
    'command_executable_identity',
    'configured_state_dir',
    'contains_user_whitelisted_tool',
    'contextmanager',
    'create_job_object_kill_on_close',
    'create_named_daemon_job',
    'create_private_transaction_snapshot_with_manifest',
    'daemon_job_name',
    'dataclass',
    'deduplicate_stack_traces',
    'duplicate_job_handle_into_process',
    'field',
    'getpass',
    'hashlib',
    'hidden_run_kwargs',
    'inspect',
    'io',
    'is_interactive_command_prompt',
    'is_interactive_output_prompt',
    'is_powershell_command',
    'is_python_interpreter_name',
    'is_well_formed_command_input',
    'is_windows_process_alive',
    'json',
    'json_dumps',
    'logging',
    'math',
    'needs_shell',
    'normalize_user_whitelisted_tools',
    'ntpath',
    'open_named_daemon_job',
    'os',
    'patch_dry_run',
    'process_identity',
    'python_inline_code_syntax_is_valid',
    'queue',
    're',
    'resolve_project_environment',
    'rollout_feature_enabled',
    'set_windows_job_kill_on_close',
    'shlex',
    'shutil',
    'signal',
    'simulate_patch',
    'split_shell_command',
    'stable_hash',
    'stop_windows_job_process',
    'strip_null_redirections',
    'subprocess',
    'sys',
    'tempfile',
    'terminate_and_confirm_windows_job_empty',
    'terminate_job_object',
    'terminate_tree',
    'threading',
    'time',
    'tokenize_command',
    'types',
    'uuid',
    'validate_invocation',
    'validate_transaction_output',
    'verify_transaction_source_unchanged',
    'wait_windows_job_empty',
    'windows_job_contains_process',
    'windows_job_has_processes',
]
