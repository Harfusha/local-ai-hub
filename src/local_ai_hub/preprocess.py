from __future__ import annotations

from .json_utils import dumps as json_dumps, loads_generated_json as _parse_generated_json  # noqa: F401

import copy  # noqa: F401
import json  # noqa: F401
import logging
import math
import os
import shlex  # noqa: F401
import sqlite3
import stat
import tempfile  # noqa: F401
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, nullcontext  # noqa: F401
from pathlib import Path, PurePosixPath, PureWindowsPath  # noqa: F401
from typing import Any, NamedTuple
from uuid import uuid4  # noqa: F401

# Stable identity for semantic preprocessing output. Bump only when the card
# contract, prompts, or deterministic card derivation makes cached cards stale.
PREPROCESS_ANALYZER_VERSION = "7.0.0"
FILE_CARD_PROMPT_VERSION = "file-card-v6"
_PROJECT_TOUCH_WRITE_TIMEOUT_SECONDS = 0.5
_LEXICAL_WRITE_BATCH_SIZE = 32
_MISSING_REF_WRITE_BATCH_SIZE = 8
from .cache import stable_hash  # noqa: F401
from .preprocess_barrels import derive_barrel_card_data as derive_barrel_card_data, is_trivial_barrel_module as is_trivial_barrel_module
from .preprocess_status import (
    _project_git_identity as _project_git_identity,
    derive_preprocess_status,
)
from .project_config import (
    ProjectPathPolicy,
    path_is_allowed,  # noqa: F401
    phase_is_allowed,  # noqa: F401
    resolve_project_config,  # noqa: F401
    resolve_project_context,  # noqa: F401
)
from .sqlite_support import (
    connect_sqlite,  # noqa: F401
    ensure_incremental_vacuum,
    incremental_vacuum,  # noqa: F401
    initialize_wal,  # noqa: F401
    is_busy_error,
    retry_busy,  # noqa: F401
    sqlite_batches as sqlite_batches,
    write_transaction,  # noqa: F401
)
from .worktrees import discover_worktree_roots  # noqa: F401
from .preprocess_lexical import (
    LEGACY_FTS, SHARED_FTS_ROWS, advance_fts_migration, delete_fts_rows, fts_layout, has_retired_fts,  # noqa: F401
    has_canonical_shared_fts as has_canonical_shared_fts,
    initialize_fts_rows, insert_fts_rows, writable_fts_layout,  # noqa: F401
)
from .preprocess_write_actor import WriteQueueTimeout  # noqa: F401
from .process_utils import (
    canonical_root,  # noqa: F401
    is_rooted_path,
    is_safe_path,
    set_current_thread_priority,
)


def checked_relative_source(root: str | Path, rel: str | Path) -> str:
    """Classify a relative repository path with strict root containment.

    Returns one of:
      - 'inside_regular_file'
      - 'missing'
      - 'escaped'
      - 'directory'
      - 'inaccessible'
    """
    if not is_safe_path(rel) or is_rooted_path(rel):
        return "escaped"
    try:
        base = Path(root).resolve()
        norm_rel = PurePosixPath(str(rel).replace("\\", "/"))
        if ".." in norm_rel.parts:
            return "escaped"
        target = (base / rel).resolve(strict=False)
        target.relative_to(base)
    except (ValueError, OSError):
        return "escaped"
    try:
        st = target.stat()
        if stat.S_ISDIR(st.st_mode):
            return "directory"
        if stat.S_ISREG(st.st_mode):
            return "inside_regular_file"
        return "inaccessible"
    except (FileNotFoundError, NotADirectoryError):
        return "missing"
    except (PermissionError, OSError):
        return "inaccessible"


logger = logging.getLogger(__name__)


def _safe_float(val: Any, default: float, min_val: float = 0.0, max_val: float | None = None) -> float:
    if val is None or isinstance(val, bool):
        return default
    try:
        f = float(val)
        if not math.isfinite(f):
            return default
        if f < min_val:
            return min_val
        if max_val is not None and f > max_val:
            return max_val
        return f
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any, default: int, min_val: int = 0) -> int:
    if val is None or isinstance(val, bool):
        return default
    try:
        if isinstance(val, float) and not math.isfinite(val):
            return default
        i = int(val)
        return max(min_val, i)
    except (ValueError, TypeError, OverflowError):
        return default


def _ensure_file_refs_revision_tracking(con: sqlite3.Connection) -> None:
    """Track source-identity changes without rescanning file_refs per batch."""
    columns = {str(row[1]) for row in con.execute("PRAGMA table_info(file_refs)").fetchall()}
    update_columns = [
        column for column in ("root", "path", "content_hash", "size", "mtime_ns", "needs_hash")
        if column in columns
    ]
    if not {"root", "path"}.issubset(columns):
        return
    update_fields = ", ".join(update_columns)
    update_condition = " OR ".join(f"OLD.{column} IS NOT NEW.{column}" for column in update_columns)
    trigger_row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND name='file_refs_revision_update'"
    ).fetchone()
    if trigger_row is not None:
        trigger_sql = str(trigger_row[0] or "")
        if any(f"OLD.{column} IS NOT NEW.{column}" not in trigger_sql for column in update_columns):
            # Upgrade only an outdated derived trigger; avoid schema writes on
            # every Hub start when the stored invalidation contract is current.
            con.execute("DROP TRIGGER file_refs_revision_update")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS file_refs_revision (
            root TEXT PRIMARY KEY,
            revision INTEGER NOT NULL DEFAULT 0
        );
        CREATE TRIGGER IF NOT EXISTS file_refs_revision_insert
        AFTER INSERT ON file_refs
        BEGIN
            INSERT INTO file_refs_revision(root, revision) VALUES(NEW.root, 1)
            ON CONFLICT(root) DO UPDATE SET revision=revision+1;
        END;
        CREATE TRIGGER IF NOT EXISTS file_refs_revision_delete
        AFTER DELETE ON file_refs
        BEGIN
            INSERT INTO file_refs_revision(root, revision) VALUES(OLD.root, 1)
            ON CONFLICT(root) DO UPDATE SET revision=revision+1;
        END;
        """
    )
    con.executescript(
        f"""
        CREATE TRIGGER IF NOT EXISTS file_refs_revision_update
        AFTER UPDATE OF {update_fields} ON file_refs
        WHEN {update_condition}
        BEGIN
            INSERT INTO file_refs_revision(root, revision) VALUES(NEW.root, 1)
            ON CONFLICT(root) DO UPDATE SET revision=revision+1;
            INSERT INTO file_refs_revision(root, revision)
            SELECT OLD.root, 1 WHERE OLD.root IS NOT NEW.root
            ON CONFLICT(root) DO UPDATE SET revision=revision+1;
        END;
        """
    )


_DETERMINISTIC_FILE_CARD_MODELS = frozenset({
    "deterministic", "deterministic-stub", "deterministic-barrel",
    "deterministic-oversized", "deterministic-unreadable",
})


CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "purpose": {"type": "string", "maxLength": 500},
        "symbols": {"type": "array", "maxItems": 32, "items": {"type": "string", "maxLength": 180}},
        "dependencies": {"type": "array", "maxItems": 32, "items": {"type": "string", "maxLength": 180}},
        "side_effects": {"type": "array", "maxItems": 24, "items": {"type": "string", "maxLength": 240}},
        "risks": {"type": "array", "maxItems": 24, "items": {"type": "string", "maxLength": 240}},
        "tests": {"type": "array", "maxItems": 32, "items": {"type": "string", "maxLength": 180}},
        "keywords": {"type": "array", "maxItems": 32, "items": {"type": "string", "maxLength": 80}},
        "evidence": {
            "type": "array", "maxItems": 192,
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": ["purpose", "symbols", "dependencies", "side_effects", "risks", "tests", "keywords"]},
                    "value": {"type": "string", "maxLength": 500},
                    "quote": {"type": "string", "maxLength": 500},
                },
                "required": ["field", "value", "quote"],
                "additionalProperties": False,
            },
        },
        "epistemic_class": {
            "type": "string",
            "enum": ["deterministic_fact", "source_verified_fact", "llm_draft", "llm_enriched", "verified_fact"],
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["purpose", "symbols", "dependencies", "side_effects", "risks", "tests", "keywords", "evidence"],
    "additionalProperties": False,
}

MODULE_SCHEMA = {
    "type": "object",
    "properties": {
        "purpose": {"type": "string"},
        "entry_points": {"type": "array", "items": {"type": "string"}},
        "dependencies": {"type": "array", "items": {"type": "string"}},
        "invariants": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "validation": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["purpose", "entry_points", "dependencies", "invariants", "risks", "validation"],
}

PROJECT_SCHEMA = {
    "type": "object",
    "properties": {
        "architecture": {"type": "string"},
        "entry_points": {"type": "array", "items": {"type": "string"}},
        "hot_paths": {"type": "array", "items": {"type": "string"}},
        "testing": {"type": "array", "items": {"type": "string"}},
        "configuration": {"type": "array", "items": {"type": "string"}},
        "data_flow": {"type": "array", "items": {"type": "string"}},
        "security": {"type": "array", "items": {"type": "string"}},
        "concurrency": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "infrastructure": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["architecture", "entry_points", "hot_paths", "testing", "configuration", "data_flow", "security", "concurrency", "risks"],
}


class _CallablePathPolicy:
    """Adapt a callable path checker to the ProjectPathPolicy protocol."""

    def __init__(self, checker: Any, root: Any, settings: Any) -> None:
        self._checker = checker
        self._root = root
        self._settings = settings

    def allows(
        self,
        path: Any,
        *,
        phase: str,
        soft_ignored: bool = False,
        hard_denied: bool = False,
        binary: bool = False,
        size_bytes: int | None = None,
    ) -> bool:
        return bool(
            self._checker(
                self._root,
                path,
                self._settings,
                phase=phase,
                soft_ignored=soft_ignored,
                hard_denied=hard_denied,
                binary=binary,
                size_bytes=size_bytes,
            )
        )


def _resolve_preprocess_path_policy(api: Any | None, root: Any, settings: Any | None) -> Any | None:
    if settings is None:
        return None
    policy_cls = getattr(api, "ProjectPathPolicy", None)
    if policy_cls is not None:
        return policy_cls(root, settings)
    checker = getattr(api, "path_is_allowed", None)
    if callable(checker):
        return _CallablePathPolicy(checker, root, settings)
    return ProjectPathPolicy(root, settings)


class _RetryablePreprocessingError(RuntimeError):
    """A project step was deferred by a transient resource or backend state."""

    def __init__(self, message: str, retry_after_seconds: float = 60.0) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class _NonRetryablePreprocessingError(RuntimeError):
    """A project step needs an explicit repair or operator action before retry."""

    retryable = False


class _FileCardClaim(NamedTuple):
    content_hash: str
    model: str
    pipeline_version: str
    claim_id: str


from .preprocess_cards import PreprocessCardsMixin
from .preprocess_card_store import PreprocessCardStoreMixin
from .preprocess_inventory import PreprocessInventoryMixin
from .preprocess_rag import PreprocessRAGMixin
from .preprocess_code_index import PreprocessCodeIndexMixin
from .preprocess_phases import PreprocessPhaseMixin
from .preprocess_scheduler import PreprocessSchedulerMixin
from .preprocess_registry import PreprocessRegistryMixin
from .preprocess_indexes import PreprocessIndexesMixin
from .preprocess_controls import PreprocessControlsMixin
from .preprocess_storage import PreprocessStorageMixin

class ProjectPreprocessor(PreprocessCardsMixin, PreprocessCardStoreMixin, PreprocessInventoryMixin, PreprocessRAGMixin, PreprocessCodeIndexMixin, PreprocessPhaseMixin, PreprocessSchedulerMixin, PreprocessRegistryMixin, PreprocessStorageMixin, PreprocessIndexesMixin, PreprocessControlsMixin):
    """Durable idle-time project preprocessing.

    Work is represented by durable project phase/cursor state. CPU retrieval/indexing
    runs independently of the foreground GPU queue; semantic-card generation uses
    Local AI's disposable idle GPU runtime. A crash loses at most the current micro-step;
    content-addressed cards and RAG commits remain reusable.
    """

    # Fresh projects complete deterministic and lexical indexing before retrieval
    # and file cards. Optional Serena then runs after file cards. The legacy
    # "serena" phase remains resumable for projects already checkpointed there.
    PHASES = ("inventory", "hash", "code_index", "deterministic", "serena", "lexical", "rag", "files", "serena_optional", "modules", "project", "hot_queries", "file_card_enrichment", "diagnostics", "complete")
    PHASE_WEIGHTS = {
        "inventory": 2.0, "hash": 3.0, "code_index": 10.0, "deterministic": 5.0,
        "serena": 5.0, "lexical": 5.0, "rag": 40.0, "files": 20.0,
        "serena_optional": 5.0,
        "modules": 4.0, "project": 3.0, "hot_queries": 2.0, "diagnostics": 1.0,
    }

    @classmethod
    def calculate_overall_progress(cls, phase_str: str, phase_pct: float, is_complete: bool = False) -> float:
        if is_complete or phase_str == "complete":
            return 100.0
        base = 0.0
        for ph in cls.PHASES:
            if ph == phase_str:
                break
            base += cls.PHASE_WEIGHTS.get(ph, 0.0)
        curr_weight = cls.PHASE_WEIGHTS.get(phase_str, 0.0)
        progress = base + (curr_weight * (max(0.0, min(100.0, phase_pct)) / 100.0))
        return round(max(0.0, min(99.9, progress)), 1)

    def __init__(self, config: dict[str, Any], services: Any, rag: Any, scheduler: Any, runtime: Any, repo_tools: Any, code_index: Any | None = None, learner: Any | None = None, deterministic: Any | None = None, telemetry: Any | None = None, background_gpu: Any | None = None, external_tools: Any | None = None, debug_traces: Any | None = None):
        self.config = config
        self.services = services
        self.rag = rag
        self.scheduler = scheduler
        self.runtime = runtime
        self.repo_tools = repo_tools
        self.code_index = code_index
        self.learner = learner
        self.deterministic = deterministic
        self.telemetry = telemetry
        self.background_gpu = background_gpu
        self.external_tools = external_tools
        self.debug_traces = debug_traces
        self.cfg = config.get("preprocessing", {}) if isinstance(config, dict) else {}
        if not isinstance(self.cfg, dict):
            self.cfg = {}
        self.enabled = bool(self.cfg.get("enabled", True))
        self.cpu_priority = str(self.cfg.get("cpu_priority", "idle"))
        self.cpu_runs_during_foreground = bool(self.cfg.get("cpu_runs_during_foreground", True))
        from .state_paths import configured_state_dir

        self.state_dir = configured_state_dir(config)
        self.db_path = self.state_dir / "preprocess.sqlite3"
        if not ensure_incremental_vacuum(self.db_path).get("success"):
            logger.warning("preprocessing database incremental vacuum setup incomplete")
        self._db_lock = threading.RLock()
        self._stop = threading.Event()
        self._cpu_wakeup = threading.Event()
        self._gpu_wakeup = threading.Event()
        self._paused = threading.Event()
        self.pause_marker = self.state_dir / "preprocess.paused"
        if self.pause_marker.exists():
            self._paused.set()
        self.install_root = Path(__file__).resolve().parents[2]
        self.max_preprocessing_projects = max(1, _safe_int(self.cfg.get("max_preprocessing_projects"), 3))
        exclusive_cfg = self.cfg.get("exclusive", {})
        exclusive_cfg = exclusive_cfg if isinstance(exclusive_cfg, dict) else {}
        self.exclusive_max_projects = min(32, max(1, _safe_int(exclusive_cfg.get("max_projects"), 3)))
        self.discover_worktrees = bool(self.cfg.get("discover_worktrees", True))
        self.max_discovered_worktrees = max(1, _safe_int(self.cfg.get("max_discovered_worktrees"), 32))
        self.worktree_discovery_ttl = max(30.0, _safe_float(self.cfg.get("worktree_discovery_ttl_seconds"), 300.0))
        self._worktree_lock = threading.Lock()
        self._worktree_cache: dict[str, tuple[float, list[str]]] = {}
        self.cpu_workers = max(1, _safe_int(self.cfg.get("cpu_workers"), min(8, os.cpu_count() or 4)))
        self.exclusive_cpu_workers = min(64, max(1, os.cpu_count() or 1),
                                         max(1, _safe_int(exclusive_cfg.get("cpu_workers"), 8)))
        self.reject_temp_projects = bool(self.cfg.get("reject_temp_projects", False))
        self.require_project_markers = bool(self.cfg.get("require_project_markers", False))
        self._rag_inventory_digests: dict[str, tuple[tuple[int, int], float]] = {}
        self._touch_lock = threading.Lock()
        self._last_touch: dict[str, float] = {}
        self._touch_debounce_seconds = max(1.0, _safe_float(self.cfg.get("touch_debounce_seconds"), 15.0))
        self._watcher_active = False
        # Filesystem events are coalesced in memory. A normal edit should not force a
        # full repository inventory nor one SQLite write per editor event.
        self._dirty_lock = threading.RLock()
        self._watch_cache_lock = threading.Lock()
        self._watch_extensions_cache: dict[str, tuple[tuple[Any, ...], set[str]]] = {}
        self._dirty_paths: dict[str, set[str]] = {}
        self._watch_revisions: dict[str, int] = {}
        # CPU hashing/lexical work reuses one bounded pool instead of creating and
        # destroying worker threads on every preprocessing micro-step.
        self._cpu_pool = ThreadPoolExecutor(
            max_workers=self.cpu_workers,
            thread_name_prefix="local-ai-pre-cpu",
            initializer=set_current_thread_priority,
            initargs=(self.cpu_priority,),
        )
        self._exclusive_cpu_pool = ThreadPoolExecutor(
            max_workers=self.exclusive_cpu_workers,
            thread_name_prefix="local-ai-pre-exclusive",
            initializer=set_current_thread_priority,
            initargs=(self.cpu_priority,),
        )
        # One Git blob map serves every bounded hash batch for a root/generation.
        # Without this, long hash phases can relaunch `git ls-files` + `git diff`
        # once per batch after the short RepositoryTools TTL expires.
        self._hash_git_maps: dict[tuple[str, int], dict[str, str]] = {}
        self._hash_git_maps_lock = threading.RLock()
        # Prune the per-root code index only when source inventory or path policy
        # changes; reuse a revision-fenced allowlist across bounded parse batches.
        self._code_index_pruned_generations: set[tuple[Any, ...]] = set()
        self._deterministic_pruned_generations: set[tuple[str, int]] = set()
        self._missing_refs_checked_generations: set[tuple[str, int]] = set()
        self._code_index_allowed_cache_lock = threading.Lock()
        self._code_index_allowed_cache: dict[
            str, tuple[int, int, Any, dict[str, str]]
        ] = {}
        # CPU and GPU loops may observe the same durable phase at the same time. A
        # per-project non-blocking step lock guarantees exactly one owner for that
        # project while still allowing independent projects to progress concurrently.
        self._step_locks_guard = threading.Lock()
        self._step_locks: dict[str, threading.Lock] = {}
        self._sqlite_busy_seconds = max(1.0, _safe_float(self.cfg.get("sqlite_busy_timeout_seconds"), 5.0))
        self._sqlite_write_retries = max(1, _safe_int(self.cfg.get("sqlite_write_retries"), 6))
        from .preprocess_write_actor import PreprocessWriteActor
        self._write_actor = PreprocessWriteActor(
            self.db_path, connection_timeout_seconds=self._sqlite_busy_seconds
        )
        self._write_actor.start()
        self._lookup_cache_lock = threading.Lock()
        self._lookup_cache: dict[str, tuple[float, str, dict[str, Any]]] = {}
        self._lookup_cache_ttl = max(1.0, _safe_float(self.cfg.get("lookup_l1_ttl_seconds"), 30.0))
        self._demand_priority_lock = threading.Lock()
        self._demand_priority_cache: dict[
            str, tuple[float, tuple[str, ...], tuple[Any, ...], tuple[str, ...]]
        ] = {}
        from .preprocess_ingest import SinglePassIngestCache
        self.ingest_cache = SinglePassIngestCache(
            max_entries=max(50, _safe_int(self.cfg.get("ingest_cache_max_entries"), 500)),
            max_bytes=max(1024 * 1024, _safe_int(self.cfg.get("ingest_cache_max_bytes"), 64 * 1024 * 1024)),
        )
        self._stats_lock = threading.Lock()
        self._last_db_maintenance = time.time()
        self._db_maintenance_retry_interval: int | None = None
        self._stats = {
            "loops": 0, "steps": 0, "yields": 0, "errors": 0, "file_card_hits": 0,
            "file_card_generations": 0, "module_generations": 0, "project_generations": 0,
            "deterministic_card_hits": 0, "deterministic_module_hits": 0, "deterministic_project_hits": 0,
            "deterministic_hot_query_hits": 0, "rag_steps": 0, "hot_queries": 0, "major_invalidations": 0,
            "code_index_files": 0, "deterministic_files": 0, "external_indexes": 0, "external_index_failures": 0,
            "project_step_contention": 0, "watcher_restarts": 0, "watcher_errors": 0,
            "lost_error_count": 0,
        }
        self._speed_tracker: dict[str, list[tuple[float, int]]] = {}

        try:
            self._init_db()
        except sqlite3.DatabaseError as exc:
            if not is_busy_error(exc):
                self._recover_db()
        if bool(getattr(self.rag, "index_reset", False)):
            self._invalidate_rag_sync_state()
        self._repair_registry()
        set_active_roots_provider = getattr(self.code_index, "set_active_roots_provider", None)
        if callable(set_active_roots_provider):
            set_active_roots_provider(self._active_code_index_roots)
        self._requeue_available_external_indexes()
        self._cpu_thread: threading.Thread | None = None
        self._extra_cpu_threads: list[threading.Thread] = []
        self._gpu_thread: threading.Thread | None = None
        self._fs_watcher_thread: threading.Thread | None = None
        if self.enabled:
            self._cpu_thread = threading.Thread(target=self._cpu_loop, name="local-ai-preprocessor-cpu", daemon=True)
            self._cpu_thread.start()
            self._ensure_extra_cpu_threads()
            self._gpu_thread = threading.Thread(target=self._gpu_loop, name="local-ai-preprocessor-gpu", daemon=True)
            self._gpu_thread.start()
            if bool(self.cfg.get("fs_watcher_enabled", True)):
                self._fs_watcher_thread = threading.Thread(target=self._fs_watcher_loop, name="local-ai-fs-watcher", daemon=True)
                self._fs_watcher_thread.start()

    def is_enabled(self) -> bool:
        return self.enabled

    def is_paused(self) -> bool:
        return self._paused.is_set()

    @classmethod
    def phases(cls) -> tuple[str, ...]:
        return cls.PHASES

    def ingestion_reuse_rate(self) -> float:
        lock = getattr(self, "_stats_lock", None)
        with lock if lock is not None else nullcontext():
            stats = getattr(self, "_stats", {})
            hits = int(stats.get("file_card_hits", 0)) + int(stats.get("deterministic_card_hits", 0))
            generations = int(stats.get("file_card_generations", 0))
            total = hits + generations
            return round(hits / total, 4) if total > 0 else 0.0
































































    def status(self, root: str | None = None) -> dict[str, Any]:
        return derive_preprocess_status(self, root=root)

    _PROJECT_COLUMNS = frozenset({
        "workspace", "status", "phase", "generation", "force_refresh",
        "inventory_hash", "structural_hash", "registered_at", "updated_at",
        "last_complete_at", "next_check_at", "retry_after", "last_error",
        "stats_json", "paused", "last_requested_at", "registration_source",
    })






















    _delete_fts_rows = staticmethod(delete_fts_rows)


__all__ = [
    'Any',
    'CARD_SCHEMA',
    'FILE_CARD_PROMPT_VERSION',
    'LEGACY_FTS',
    'MODULE_SCHEMA',
    'NamedTuple',
    'PREPROCESS_ANALYZER_VERSION',
    'PROJECT_SCHEMA',
    'Path',
    'PreprocessCardStoreMixin',
    'PreprocessCardsMixin',
    'PreprocessCodeIndexMixin',
    'PreprocessControlsMixin',
    'PreprocessIndexesMixin',
    'PreprocessInventoryMixin',
    'PreprocessPhaseMixin',
    'PreprocessRAGMixin',
    'PreprocessRegistryMixin',
    'PreprocessSchedulerMixin',
    'PreprocessStorageMixin',
    'ProjectPathPolicy',
    'ProjectPreprocessor',
    'PurePosixPath',
    'PureWindowsPath',
    'SHARED_FTS_ROWS',
    'ThreadPoolExecutor',
    'WriteQueueTimeout',
    '_CallablePathPolicy',
    '_DETERMINISTIC_FILE_CARD_MODELS',
    '_FileCardClaim',
    '_LEXICAL_WRITE_BATCH_SIZE',
    '_MISSING_REF_WRITE_BATCH_SIZE',
    '_PROJECT_TOUCH_WRITE_TIMEOUT_SECONDS',
    '_RetryablePreprocessingError',
    '_ensure_file_refs_revision_tracking',
    '_parse_generated_json',
    '_project_git_identity',
    '_resolve_preprocess_path_policy',
    '_safe_float',
    '_safe_int',
    'advance_fts_migration',
    'annotations',
    'canonical_root',
    'checked_relative_source',
    'closing',
    'connect_sqlite',
    'copy',
    'delete_fts_rows',
    'derive_barrel_card_data',
    'derive_preprocess_status',
    'discover_worktree_roots',
    'ensure_incremental_vacuum',
    'fts_layout',
    'has_canonical_shared_fts',
    'has_retired_fts',
    'incremental_vacuum',
    'initialize_fts_rows',
    'initialize_wal',
    'insert_fts_rows',
    'is_busy_error',
    'is_rooted_path',
    'is_safe_path',
    'is_trivial_barrel_module',
    'json',
    'json_dumps',
    'logger',
    'logging',
    'math',
    'nullcontext',
    'os',
    'path_is_allowed',
    'phase_is_allowed',
    'resolve_project_config',
    'resolve_project_context',
    'retry_busy',
    'set_current_thread_priority',
    'shlex',
    'sqlite3',
    'sqlite_batches',
    'stable_hash',
    'stat',
    'tempfile',
    'threading',
    'time',
    'uuid4',
    'writable_fts_layout',
    'write_transaction',
]
