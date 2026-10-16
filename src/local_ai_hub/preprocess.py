from __future__ import annotations

from .json_utils import dumps as json_dumps

import copy
import json
import logging
import math
import os
import shlex
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any

from . import __version__
from .cache import stable_hash
from .project_config import (
    path_is_allowed,
    phase_is_allowed,
    resolve_project_config,
    resolve_project_context,
)
from .sqlite_support import (
    connect_sqlite,
    ensure_incremental_vacuum,
    incremental_vacuum,
    initialize_wal,
    is_busy_error,
    retry_busy,
)
from .worktrees import discover_worktree_roots
from .process_utils import canonical_root, set_current_thread_priority


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


CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "purpose": {"type": "string"},
        "symbols": {"type": "array", "items": {"type": "string"}},
        "dependencies": {"type": "array", "items": {"type": "string"}},
        "side_effects": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "tests": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["purpose", "symbols", "dependencies", "side_effects", "risks", "tests", "keywords"],
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


def _project_git_identity(root: str) -> tuple[str, bool]:
    """Return a local Git common-dir identity without guessing from path names."""
    try:
        raw = str(root or "").replace("\x00", "").strip()
        if not raw:
            return "", False
        resolved_root = Path(raw).resolve(strict=False)
        marker = resolved_root / ".git"
        if marker.is_dir():
            return str(marker.resolve(strict=False)), False
        if not marker.is_file():
            return str(resolved_root), False

        marker_text = marker.read_text(encoding="utf-8", errors="replace")[:1024]
        prefix, separator, raw_git_dir = marker_text.partition(":")
        if prefix.strip().casefold() != "gitdir" or not separator or not raw_git_dir.strip():
            return str(resolved_root), False
        git_dir = Path(raw_git_dir.strip())
        if not git_dir.is_absolute():
            git_dir = resolved_root / git_dir
        git_dir = git_dir.resolve(strict=False)

        common_dir_file = git_dir / "commondir"
        if not common_dir_file.is_file():
            return str(git_dir), False
        raw_common_dir = common_dir_file.read_text(encoding="utf-8", errors="replace")[:1024].strip()
        if not raw_common_dir:
            return str(resolved_root), False
        common_dir = Path(raw_common_dir)
        if not common_dir.is_absolute():
            common_dir = git_dir / common_dir
        common_dir = common_dir.resolve(strict=False)
        return str(common_dir), common_dir != git_dir
    except (OSError, RuntimeError, ValueError):
        return str(root or "").replace("\x00", "").strip(), False


class ProjectPreprocessor:
    """Durable idle-time project preprocessing.

    Work is represented by durable project phase/cursor state. CPU retrieval/indexing
    runs independently of the foreground GPU queue; semantic-card generation uses
    Local AI's disposable idle GPU runtime. A crash loses at most the current micro-step;
    content-addressed cards and RAG commits remain reusable.
    """

    # Local AI keeps deterministic parsing first, then performs CPU-only semantic
    # indexing before any idle-GPU card generation. This lets embeddings run even
    # while foreground model work is active instead of waiting behind GPU-idle work.
    PHASES = ("inventory", "hash", "code_index", "deterministic", "serena", "lexical", "rag", "files", "modules", "project", "hot_queries", "diagnostics", "complete")

    def __init__(self, config: dict[str, Any], services: Any, rag: Any, scheduler: Any, runtime: Any, repo_tools: Any, code_index: Any | None = None, learner: Any | None = None, deterministic: Any | None = None, telemetry: Any | None = None, background_gpu: Any | None = None, external_tools: Any | None = None):
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
        self.cfg = config.get("preprocessing", {}) if isinstance(config, dict) else {}
        if not isinstance(self.cfg, dict):
            self.cfg = {}
        self.enabled = bool(self.cfg.get("enabled", True))
        self.cpu_priority = str(self.cfg.get("cpu_priority", "idle"))
        self.cpu_runs_during_foreground = bool(self.cfg.get("cpu_runs_during_foreground", True))
        server_cfg = config.get("server", {}) if isinstance(config, dict) else {}
        if not isinstance(server_cfg, dict):
            server_cfg = {}
        raw_state_dir = server_cfg.get("state_dir")
        if not raw_state_dir or "\x00" in str(raw_state_dir):
            raw_state_dir = tempfile.gettempdir()
        self.state_dir = Path(raw_state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
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
        self.discover_worktrees = bool(self.cfg.get("discover_worktrees", True))
        self.max_discovered_worktrees = max(1, _safe_int(self.cfg.get("max_discovered_worktrees"), 32))
        self.worktree_discovery_ttl = max(30.0, _safe_float(self.cfg.get("worktree_discovery_ttl_seconds"), 300.0))
        self._worktree_lock = threading.Lock()
        self._worktree_cache: dict[str, tuple[float, list[str]]] = {}
        self.cpu_workers = max(1, _safe_int(self.cfg.get("cpu_workers"), min(8, os.cpu_count() or 4)))
        self.reject_temp_projects = bool(self.cfg.get("reject_temp_projects", False))
        self.require_project_markers = bool(self.cfg.get("require_project_markers", False))
        self._touch_lock = threading.Lock()
        self._last_touch: dict[str, float] = {}
        self._touch_debounce_seconds = max(1.0, _safe_float(self.cfg.get("touch_debounce_seconds"), 15.0))
        self._watcher_active = False
        # Filesystem events are coalesced in memory. A normal edit should not force a
        # full repository inventory nor one SQLite write per editor event.
        self._dirty_lock = threading.RLock()
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
        # One Git blob map serves every bounded hash batch for a root/generation.
        # Without this, long hash phases can relaunch `git ls-files` + `git diff`
        # once per batch after the short RepositoryTools TTL expires.
        self._hash_git_maps: dict[tuple[str, int], dict[str, str]] = {}
        self._hash_git_maps_lock = threading.RLock()
        # Pruning the per-root code indexes is a consistency operation, not part
        # of every bounded parse batch. Keep it once per generation and invalidate
        # it only when the watcher reports a real file change.
        self._code_index_pruned_generations: set[tuple[str, int]] = set()
        self._deterministic_pruned_generations: set[tuple[str, int]] = set()
        self._missing_refs_checked_generations: set[tuple[str, int]] = set()
        # CPU and GPU loops may observe the same durable phase at the same time. A
        # per-project non-blocking step lock guarantees exactly one owner for that
        # project while still allowing independent projects to progress concurrently.
        self._step_locks_guard = threading.Lock()
        self._step_locks: dict[str, threading.Lock] = {}
        self._sqlite_busy_seconds = max(0.25, _safe_float(self.cfg.get("sqlite_busy_timeout_seconds"), 0.5))
        self._sqlite_write_retries = max(1, _safe_int(self.cfg.get("sqlite_write_retries"), 6))
        self._lookup_cache_lock = threading.Lock()
        self._lookup_cache: dict[str, tuple[float, str, dict[str, Any]]] = {}
        self._lookup_cache_ttl = max(1.0, _safe_float(self.cfg.get("lookup_l1_ttl_seconds"), 30.0))
        self._stats_lock = threading.Lock()
        self._last_db_maintenance = 0.0
        self._stats = {
            "loops": 0, "steps": 0, "yields": 0, "errors": 0, "file_card_hits": 0,
            "file_card_generations": 0, "module_generations": 0, "project_generations": 0,
            "deterministic_card_hits": 0, "deterministic_module_hits": 0, "deterministic_project_hits": 0,
            "deterministic_hot_query_hits": 0, "rag_steps": 0, "hot_queries": 0, "major_invalidations": 0,
            "code_index_files": 0, "deterministic_files": 0, "external_indexes": 0, "external_index_failures": 0,
            "project_step_contention": 0, "watcher_restarts": 0, "watcher_errors": 0,
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
        self._requeue_available_external_indexes()
        self._cpu_thread: threading.Thread | None = None
        self._gpu_thread: threading.Thread | None = None
        self._fs_watcher_thread: threading.Thread | None = None
        if self.enabled:
            self._cpu_thread = threading.Thread(target=self._cpu_loop, name="local-ai-preprocessor-cpu", daemon=True)
            self._cpu_thread.start()
            self._gpu_thread = threading.Thread(target=self._gpu_loop, name="local-ai-preprocessor-gpu", daemon=True)
            self._gpu_thread.start()
            if bool(self.cfg.get("fs_watcher_enabled", True)):
                self._fs_watcher_thread = threading.Thread(target=self._fs_watcher_loop, name="local-ai-fs-watcher", daemon=True)
                self._fs_watcher_thread.start()

    def is_enabled(self) -> bool:
        return self.enabled

    def is_paused(self) -> bool:
        return self._paused.is_set()

    def stats(self) -> dict[str, Any]:
        with self._stats_lock:
            return dict(self._stats)

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

    def _connect(self) -> sqlite3.Connection:
        con = connect_sqlite(
            self.db_path,
            timeout_seconds=self._sqlite_busy_seconds,
            row_factory=sqlite3.Row,
        )
        try:
            con.execute("PRAGMA cache_size=-65536")
            con.execute("PRAGMA mmap_size=536870912")
        except sqlite3.OperationalError:
            pass
        return con

    @staticmethod
    def _is_locked_error(exc: BaseException) -> bool:
        return is_busy_error(exc)

    def _write_retry(self, operation: Any) -> Any:
        def attempt() -> Any:
            with self._db_lock, closing(self._connect()) as con:
                con.execute("BEGIN IMMEDIATE")
                value = operation(con)
                con.commit()
                return value

        return retry_busy(
            attempt,
            retries=self._sqlite_write_retries,
            base_delay_seconds=0.015,
        )

    def _wake_all(self) -> None:
        self._cpu_wakeup.set()
        self._gpu_wakeup.set()

    def _project_step_lock(self, root: str) -> threading.Lock:
        with self._step_locks_guard:
            lock = self._step_locks.get(root)
            if lock is None:
                lock = threading.Lock()
                self._step_locks[root] = lock
            return lock

    def _run_project_step(self, row: dict[str, Any]) -> bool | None:
        """Run one durable project step with a single in-process owner.

        ``None`` means another loop already owns this project. Callers should simply
        retry later; this is contention, not a foreground-yield or an error.
        """
        if self._paused.is_set() or not self._background_work_allowed():
            return None
        root = str(row.get("root", ""))
        lock = self._project_step_lock(root)
        if not lock.acquire(blocking=False):
            with self._stats_lock:
                self._stats["project_step_contention"] += 1
            return None
        try:
            return self._step(row)
        finally:
            lock.release()

    def _forget_project_runtime(self, root: str) -> None:
        with self._dirty_lock:
            self._dirty_paths.pop(root, None)
            self._watch_revisions.pop(root, None)
        with self._touch_lock:
            self._last_touch.pop(root, None)
        with self._step_locks_guard:
            lock = self._step_locks.get(root)
            if lock is not None and not lock.locked():
                self._step_locks.pop(root, None)
        with self._hash_git_maps_lock:
            for key in [key for key in self._hash_git_maps if key[0] == root]:
                self._hash_git_maps.pop(key, None)
        self._missing_refs_checked_generations = {
            key for key in self._missing_refs_checked_generations if key[0] != root
        }

    def _init_db(self) -> None:
        with self._db_lock, closing(self._connect()) as con:
            # Set WAL once. The mode is persisted in the database header.
            try:
                initialize_wal(con)
            except sqlite3.OperationalError as exc:
                if not self._is_locked_error(exc):
                    raise
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    root TEXT PRIMARY KEY,
                    workspace TEXT NOT NULL,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    force_refresh INTEGER NOT NULL DEFAULT 0,
                    inventory_hash TEXT,
                    structural_hash TEXT,
                    registered_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_complete_at REAL,
                    next_check_at REAL NOT NULL DEFAULT 0,
                    retry_after REAL NOT NULL DEFAULT 0,
                    last_error TEXT,
                    stats_json TEXT NOT NULL DEFAULT '{}',
                    paused INTEGER NOT NULL DEFAULT 0,
                    last_requested_at REAL NOT NULL DEFAULT 0,
                    registration_source TEXT NOT NULL DEFAULT 'agent'
                );
                CREATE TABLE IF NOT EXISTS file_refs (
                    root TEXT NOT NULL,
                    path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL DEFAULT 0,
                    needs_hash INTEGER NOT NULL DEFAULT 0,
                    rag_hash TEXT,
                    last_accessed_at REAL NOT NULL DEFAULT 0,
                    generation INTEGER NOT NULL,
                    card_key TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(root,path)
                );
                CREATE INDEX IF NOT EXISTS idx_file_refs_root_card ON file_refs(root,card_key);
                CREATE INDEX IF NOT EXISTS idx_file_refs_status ON file_refs(root,card_key,needs_hash,content_hash,rag_hash);
                CREATE TABLE IF NOT EXISTS source_index (
                    root TEXT NOT NULL,
                    path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    text TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(root,path)
                );
                CREATE INDEX IF NOT EXISTS idx_source_index_root_hash ON source_index(root,content_hash);
                CREATE TABLE IF NOT EXISTS content_cards (
                    card_key TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    model TEXT NOT NULL,
                    analyzer_version TEXT NOT NULL,
                    card_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    accessed_at REAL NOT NULL,
                    hits INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_content_cards_hash ON content_cards(content_hash,model,analyzer_version);
                CREATE TABLE IF NOT EXISTS module_cards (
                    root TEXT NOT NULL,
                    module TEXT NOT NULL,
                    revision_hash TEXT NOT NULL,
                    card_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(root,module)
                );
                CREATE TABLE IF NOT EXISTS project_cards (
                    root TEXT PRIMARY KEY,
                    revision_hash TEXT NOT NULL,
                    card_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS diagnostic_baselines (
                    root TEXT PRIMARY KEY,
                    command TEXT NOT NULL,
                    exit_code INTEGER NOT NULL,
                    error_count INTEGER NOT NULL,
                    stdout_preview TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS hot_query_state (
                    root TEXT NOT NULL,
                    query TEXT NOT NULL,
                    revision_hash TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(root,query)
                );
                CREATE TABLE IF NOT EXISTS task_capsules (
                    root TEXT NOT NULL,
                    query TEXT NOT NULL,
                    revision_hash TEXT NOT NULL,
                    capsule_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(root,query)
                );
                CREATE TABLE IF NOT EXISTS external_index_state (
                    root TEXT NOT NULL,
                    backend TEXT NOT NULL,
                    revision_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    error TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(root,backend)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS source_fts USING fts5(root UNINDEXED, path UNINDEXED, content);
                """
            )
            columns = {
                str(row[1])
                for row in con.execute("PRAGMA table_info(external_index_state)").fetchall()
            }
            if "retry_count" not in columns:
                # This is disposable derived state. Rebuild the small table
                # instead of adding a migration shim to the initial-release
                # schema; project/file indexes remain authoritative.
                con.execute("DROP TABLE IF EXISTS external_index_state")
                con.execute(
                    """CREATE TABLE external_index_state (
                        root TEXT NOT NULL,
                        backend TEXT NOT NULL,
                        revision_hash TEXT NOT NULL,
                        status TEXT NOT NULL,
                        updated_at REAL NOT NULL,
                        error TEXT,
                        retry_count INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY(root,backend)
                    )"""
                )
            con.commit()

    def _invalidate_rag_sync_state(self) -> None:
        try:
            now = time.time()
            with self._db_lock, closing(self._connect()) as con:
                con.execute("UPDATE file_refs SET rag_hash=NULL")
                con.execute("DELETE FROM hot_query_state")
                con.execute("DELETE FROM task_capsules")
                con.execute(
                    """UPDATE projects SET phase='rag',
                       status=CASE WHEN paused=1 THEN 'paused' ELSE 'waiting' END,
                       retry_after=0,next_check_at=0,updated_at=?""",
                    (now,),
                )
                self._rebalance_processing_slots(con)
                con.commit()
        except Exception:
            # Both DBs are derived acceleration layers. If sync-marker repair fails,
            # normal inventory/recheck remains the foreground correctness fallback.
            pass

    def _repair_registry(self) -> None:
        """Discard unsafe registrations and restore preprocessing slots."""
        try:
            with self._db_lock, closing(self._connect()) as con:
                rows = con.execute("SELECT root FROM projects").fetchall()
                for row in rows:
                    root = str(row["root"])
                    if self._is_internal_root(root) or self._is_ephemeral_root(root):
                        con.execute("DELETE FROM projects WHERE root=?", (root,))
                        con.execute("DELETE FROM file_refs WHERE root=?", (root,))
                        con.execute("DELETE FROM source_index WHERE root=?", (root,))
                        con.execute("DELETE FROM source_fts WHERE root=?", (root,))
                        con.execute("DELETE FROM module_cards WHERE root=?", (root,))
                        con.execute("DELETE FROM project_cards WHERE root=?", (root,))
                        con.execute("DELETE FROM hot_query_state WHERE root=?", (root,))
                        con.execute("DELETE FROM task_capsules WHERE root=?", (root,))
                        con.execute("DELETE FROM external_index_state WHERE root=?", (root,))
                        self._forget_project_runtime(root)
                    elif not Path(root).is_dir():
                        # Keep the durable root and file refs as the retry marker for
                        # cleanup_deleted_projects once the secondary indexes are ready.
                        con.execute(
                            "UPDATE projects SET status='error',paused=1,retry_after=0,"
                            "next_check_at=0,updated_at=? WHERE root=?",
                            (time.time(), root),
                        )
                con.execute("UPDATE projects SET status='queued' WHERE status='running'")
                self._rebalance_processing_slots(con)
                con.commit()
        except (sqlite3.Error, OSError, RuntimeError) as exc:
            # Registry repair is optional; keep startup available, but expose
            # expected storage/filesystem failures without leaking project paths.
            logger.warning("Preprocessing registry repair skipped (%s)", type(exc).__name__)

    def _requeue_available_external_indexes(self) -> None:
        """Wake completed projects whose cached optional index can now run."""
        checker = getattr(self.external_tools, "backend_available", None)
        if not callable(checker):
            return
        try:
            with self._db_lock, closing(self._connect()) as con:
                rows = con.execute(
                    """SELECT root,backend FROM external_index_state
                       WHERE status IN ('skipped','unavailable','degraded')"""
                ).fetchall()
                desired: dict[str, str] = {}
                for row in rows:
                    root = str(row["root"])
                    backend = str(row["backend"])
                    try:
                        available = bool(checker(backend))
                    except Exception:
                        available = False
                    if not available:
                        continue
                    # Serena is the earlier phase, so it wins when both cached
                    # backend states need to be retried for the same project.
                    if backend == "serena" or root not in desired:
                        desired[root] = backend
                now = time.time()
                for root, phase in desired.items():
                    con.execute(
                        """UPDATE projects SET phase=?,status='waiting',retry_after=0,
                           next_check_at=0,updated_at=?
                           WHERE root=? AND phase='complete'""",
                        (phase, now, root),
                    )
                con.commit()
        except Exception:
            # Requeue is a recovery optimization; normal registration remains the
            # correctness path if a derived state read is temporarily unavailable.
            return

    def _rebalance_processing_slots(self, con: sqlite3.Connection, preferred_root: str | None = None) -> None:
        """Keep all registered projects active; cap only runnable preprocessing work."""
        limit = self.max_preprocessing_projects
        candidates = con.execute(
            """SELECT root,status FROM projects
               WHERE paused=0 AND phase<>?
               ORDER BY CASE WHEN root=? THEN 0 ELSE 1 END,
                        force_refresh DESC,last_requested_at DESC,updated_at DESC""",
            (self.PHASES[-1], preferred_root or ""),
        ).fetchall()
        for index, row in enumerate(candidates):
            root = str(row["root"])
            cur_status = str(row["status"])
            if index < limit:
                if cur_status == "waiting":
                    con.execute("UPDATE projects SET status='queued',retry_after=0 WHERE root=?", (root,))
            else:
                if cur_status in ("queued", "running"):
                    con.execute("UPDATE projects SET status='waiting' WHERE root=?", (root,))

    def _recover_db(self) -> None:
        """Quarantine the derived preprocessing DB and rebuild it.

        Preprocessing is an acceleration layer, never a foreground correctness
        dependency, so corruption must degrade to a cold rebuild rather than fail startup.
        """
        stamp = int(time.time())
        with self._db_lock:
            try:
                if self.db_path.exists():
                    self.db_path.replace(self.db_path.with_name(self.db_path.name + f".corrupt-{stamp}"))
                for suffix in ("-wal", "-shm"):
                    side = Path(str(self.db_path) + suffix)
                    if side.exists():
                        side.unlink()
            except OSError:
                pass
        self._init_db()

    @staticmethod
    def _root(root: str) -> str:
        return canonical_root(root)

    def _is_internal_root(self, resolved: str) -> bool:
        if not bool(self.cfg.get("ignore_internal_install", True)):
            return False
        path = Path(resolved).resolve()
        # State directory contains runtime databases and cache - always internal
        try:
            state_p = self.state_dir.resolve()
            if path == state_p or path.is_relative_to(state_p):
                return True
        except (ValueError, AttributeError):
            try:
                path.relative_to(self.state_dir); return True
            except ValueError:
                pass
        try:
            install_p = self.install_root.resolve()
            # If the user is actively working on the local-ai-hub repo itself (it has .git or pyproject.toml)
            if (path == install_p or path.is_relative_to(install_p)) and ((install_p / ".git").exists() or (install_p / "pyproject.toml").exists()):
                return False
            if path == install_p or path.is_relative_to(install_p):
                return True
        except (ValueError, AttributeError):
            pass
        return False

    def _is_ephemeral_root(self, resolved: str) -> bool:
        """Reject obvious OS/temp/runtime directories from project registration."""
        path = Path(resolved)
        low = str(path).replace("\\", "/").lower().rstrip("/")
        bad_suffixes = ("/windows/system32", "/windows/syswow64", "/windows", "/program files", "/program files (x86)")
        if any(low.endswith(x) for x in bad_suffixes):
            return True
        if self.reject_temp_projects:
            try:
                temp = Path(tempfile.gettempdir()).resolve()
            except (OSError, RuntimeError) as exc:
                logger.warning("temporary project boundary unavailable (%s)", type(exc).__name__)
                return True
            if path == temp or path.is_relative_to(temp):
                return True
        return False

    @staticmethod
    def _has_project_marker(path: Path) -> bool:
        markers = (
            ".git", "pyproject.toml", "package.json", "composer.json", "Cargo.toml", "go.mod",
            "pom.xml", "build.gradle", "build.gradle.kts", "CMakeLists.txt", "Makefile",
            "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
        )
        if any((path / name).exists() for name in markers):
            return True
        try:
            if any(path.glob("*.sln")) or any(path.glob("*.csproj")):
                return True
        except OSError:
            pass
        # Generic source repositories without a manifest are accepted when they
        # contain a small but real source tree; random cwd folders are not.
        source_exts = {".py", ".php", ".js", ".ts", ".tsx", ".jsx", ".cs", ".java", ".go", ".rs", ".cpp", ".c", ".h"}
        seen = 0
        try:
            for child in path.iterdir():
                if child.is_file() and child.suffix.lower() in source_exts:
                    seen += 1
                elif child.is_dir() and not child.name.startswith(".") and child.name.lower() not in {"node_modules", "vendor", "venv", ".venv", "build", "dist"}:
                    try:
                        for f in child.iterdir():
                            if f.is_file() and f.suffix.lower() in source_exts:
                                seen += 1
                                if seen >= 3:
                                    return True
                    except OSError:
                        pass
                if seen >= 3:
                    return True
        except OSError:
            return False
        return False

    def touch_if_registered(self, root: str) -> bool:
        """Refresh project LRU priority without turning reads into SQLite write storms.

        Foreground agents often issue bursts of repository operations. Persisting an
        LRU timestamp for every operation contends with preprocessing WAL writes and
        changes ``updated_at`` even though project content did not change. Touches are
        therefore debounced in memory and only ``last_requested_at`` is persisted.
        """
        resolved = self._root(root)
        now = time.time()
        with self._touch_lock:
            last = self._last_touch.get(resolved, 0.0)
            if now - last < self._touch_debounce_seconds:
                return True
            self._last_touch[resolved] = now
        try:
            cur = self._write_retry(lambda con: con.execute("UPDATE projects SET last_requested_at=? WHERE root=?", (now, resolved)))
            return bool(getattr(cur, "rowcount", 0))
        except sqlite3.Error as exc:
            logger.debug("preprocessor project touch failed error_type=%s", type(exc).__name__)
            return False

    def _watch_relevant(self, root: Path, changed: Path) -> str | None:
        if not root.is_dir():
            return None
        try:
            rel_path = changed.relative_to(root)
        except ValueError:
            return None
        if any(part.lower() in self.repo_tools.ignore_dirs for part in rel_path.parts[:-1]):
            return None
        name = rel_path.name.lower()
        if name in {".local-ai.toml", ".local-ai.worktree.toml"}:
            return str(rel_path).replace("\\", "/")
        suffix = rel_path.suffix.lower()
        project_extensions: set[str] = set()
        _api, project_context = self._project_config_context(str(root))
        if project_context is not None:
            settings = project_context.settings
            project_extensions.update(
                str(value).lower() for value in getattr(settings, "text_extensions", ())
            )
            for override in getattr(settings, "language_overrides", {}).values():
                project_extensions.update(
                    str(value).lower() for value in override.get("text_extensions", ())
                )
            project_extensions.difference_update(
                str(value).lower() for value in getattr(settings, "binary_extensions", ())
            )
        if (
            self.repo_tools.extensions
            and suffix not in self.repo_tools.extensions
            and suffix not in project_extensions
            and name not in self.repo_tools.special_filenames
        ):
            return None
        return str(rel_path).replace("\\", "/")

    def _consume_dirty_paths(self, root: str) -> set[str]:
        with self._dirty_lock:
            return self._dirty_paths.pop(root, set())

    def _project_config_context(self, root: str) -> tuple[Any | None, Any | None]:
        """Resolve optional project policy lazily for the owning repository."""
        try:
            from importlib import import_module

            api = import_module("local_ai_hub.project_config")
        except ModuleNotFoundError as exc:
            if exc.name == "local_ai_hub.project_config":
                return None, None
            raise
        state_dir = self.config.get("server", {}).get("state_dir", "state")
        return api, api.resolve_project_context(root, state_dir)

    def _project_profile(self, root: str, profile: Any) -> Any:
        _api, context = self._project_config_context(root)
        if context is None or not isinstance(profile, dict):
            return profile
        profile = dict(profile)
        settings = context.settings
        for name in ("project_type", "solution_path"):
            value = getattr(settings, name, None)
            if value:
                profile[name] = value
        return profile

    def _add_project_text_extensions(self, root: str, files: dict[str, dict[str, Any]], api: Any | None, context: Any | None) -> None:
        if api is None or context is None:
            return
        settings = context.settings
        extensions = {str(value).lower() for value in getattr(settings, "text_extensions", ())}
        for override in getattr(settings, "language_overrides", {}).values():
            extensions.update(str(value).lower() for value in override.get("text_extensions", ()))
        extensions.difference_update(str(value).lower() for value in getattr(settings, "binary_extensions", ()))
        extensions.difference_update(str(value).lower() for value in getattr(self.repo_tools, "extensions", ()))
        if not extensions:
            return
        base = Path(root)
        ignored = {str(value).lower() for value in getattr(self.repo_tools, "ignore_dirs", ())}
        may_descend = getattr(api, "may_descend", None)
        for current, directories, filenames in os.walk(base, followlinks=False):
            current_path = Path(current)
            retained = []
            for name in directories:
                child = current_path / name
                if name.lower() in ignored or (callable(may_descend) and not may_descend(
                    base, child, settings, phase="preprocess", hard_denied=False,
                )):
                    continue
                retained.append(name)
            directories[:] = retained
            for name in filenames:
                candidate = current_path / name
                if candidate.suffix.lower() not in extensions:
                    continue
                try:
                    stat = candidate.stat()
                    relative = candidate.relative_to(base).as_posix()
                except (OSError, ValueError):
                    continue
                if int(stat.st_size) > int(getattr(self.repo_tools, "max_file_bytes", stat.st_size)) or not self._project_path_allowed(
                    root, relative, settings, phase="preprocess", size_bytes=int(stat.st_size),
                ):
                    continue
                files.setdefault(relative, {
                    "path": relative, "size": int(stat.st_size),
                    "mtime_ns": int(stat.st_mtime_ns), "extension": candidate.suffix.lower(),
                })

    def notify_path_changed(self, changed_path: str) -> bool:
        """Coalesce watcher events and queue only the owning registered project."""
        if not self._background_work_allowed():
            return False
        try:
            changed = Path(changed_path).resolve(strict=False)
        except Exception:
            return False
        try:
            with self._db_lock, closing(self._connect()) as con:
                rows = con.execute("SELECT root FROM projects WHERE paused=0").fetchall()
        except Exception:
            return False

        matched_roots: list[str] = []
        matched_any = False
        for row in rows:
            root_path = Path(str(row[0])).resolve(strict=False)
            rel = self._watch_relevant(root_path, changed)
            if rel is None:
                continue
            root = str(root_path)
            matched_any = True
            with self._dirty_lock:
                paths = self._dirty_paths.setdefault(root, set())
                first = not paths
                paths.add(rel)
                self._watch_revisions[root] = self._watch_revisions.get(root, 0) + 1
            with self._hash_git_maps_lock:
                for key in [key for key in self._hash_git_maps if key[0] == root]:
                    self._hash_git_maps.pop(key, None)
            self._code_index_pruned_generations = {
                key for key in getattr(self, "_code_index_pruned_generations", set()) if key[0] != root
            }
            self._deterministic_pruned_generations = {
                key for key in getattr(self, "_deterministic_pruned_generations", set()) if key[0] != root
            }
            if first:
                matched_roots.append(root)

        for root in matched_roots:
            try:
                def _queue_changed(con: sqlite3.Connection, r: str = root) -> None:
                    con.execute(
                        "UPDATE projects SET status='queued',phase=CASE WHEN phase='complete' THEN 'inventory' ELSE phase END,next_check_at=0 WHERE root=?", (r,)
                    )
                    self._rebalance_processing_slots(con, preferred_root=r)
                self._write_retry(_queue_changed)
            except Exception:
                # The in-memory dirty set is retained. A periodic recheck remains the
                # correctness fallback if another process owns the WAL writer briefly.
                pass
        if matched_any:
            self._cpu_wakeup.set()
        return matched_any

    def cache_fingerprint(self, root: str) -> dict[str, Any] | None:
        """Return a zero-process watcher revision for any initialized project.

        The watcher revision changes immediately on relevant filesystem events, so
        foreground caches invalidate without waiting for preprocessing to finish and
        without spawning Git while a project is being incrementally refreshed.
        """
        if not self._watcher_active:
            return None
        resolved = self._root(root)
        try:
            with self._db_lock, closing(self._connect()) as con:
                row = con.execute("SELECT status,phase,generation,inventory_hash,structural_hash FROM projects WHERE root=? AND paused=0", (resolved,)).fetchone()
            if not row or not row["inventory_hash"]:
                return None
            with self._dirty_lock:
                watch_revision = int(self._watch_revisions.get(resolved, 0))
                dirty_paths = sorted(self._dirty_paths.get(resolved, set()))[:256]
                dirty_count = len(self._dirty_paths.get(resolved, set()))
            _api, project_context = self._project_config_context(resolved)
            config_digest = str(getattr(project_context, "config_digest", ""))
            fp = stable_hash({
                "root": resolved, "generation": int(row["generation"] or 0),
                "inventory": row["inventory_hash"], "structure": row["structural_hash"],
                "watch_revision": watch_revision, "project_config": config_digest,
            })
            return {
                "success": True, "root": resolved, "kind": "preprocessed-watcher",
                "fingerprint": fp, "dirty": dirty_count > 0, "changed_files": dirty_count,
                "changed_paths": dirty_paths, "status": str(row["status"]),
                "phase": str(row["phase"]), "project_config_digest": config_digest,
                "created_at": time.time(),
            }
        except (ImportError, OSError, OverflowError, sqlite3.Error, TypeError, ValueError) as exc:
            logger.debug("watcher cache fingerprint unavailable error_type=%s", type(exc).__name__)
            return None

    def indexed_paths(self, root: str) -> list[str]:
        """Return watcher-owned file paths without walking the working tree."""
        resolved = self._root(root)
        with self._db_lock, closing(self._connect()) as con:
            rows = con.execute(
                "SELECT path FROM file_refs WHERE root=? ORDER BY path",
                (resolved,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def context_revision(self, root: str) -> str:
        """Cheap revision for local-model answer caching and preprocessed context."""
        resolved = self._root(root)
        try:
            with self._db_lock, closing(self._connect()) as con:
                p = con.execute("SELECT generation,inventory_hash,structural_hash,status FROM projects WHERE root=?", (resolved,)).fetchone()
                project = con.execute("SELECT revision_hash FROM project_cards WHERE root=?", (resolved,)).fetchone()
                cap = con.execute("SELECT MAX(updated_at) FROM task_capsules WHERE root=?", (resolved,)).fetchone()
            return stable_hash({"project": tuple(p) if p else None, "project_card": project[0] if project else None, "capsules": cap[0] if cap else None})
        except Exception:
            return "cold"

    def _related_worktrees(self, root: str) -> list[str]:
        if not self.discover_worktrees:
            return []
        now = time.monotonic()
        with self._worktree_lock:
            cached = self._worktree_cache.get(root)
            if cached and now - cached[0] < self.worktree_discovery_ttl:
                return list(cached[1])
        try:
            roots = discover_worktree_roots(root)
        except Exception:
            roots = []
        related = [item for item in roots if item != root][:self.max_discovered_worktrees]
        with self._worktree_lock:
            if len(self._worktree_cache) > 256:
                oldest_roots = sorted(self._worktree_cache.keys(), key=lambda k: self._worktree_cache[k][0])[:128]
                for k in oldest_roots:
                    self._worktree_cache.pop(k, None)
            self._worktree_cache[root] = (now, related)
        return related

    def _register_discovered_worktrees(self, root: str) -> None:
        # A linked Git worktree can discover the same sibling set as its parent.
        # Never recurse from it; otherwise one explicit registration fans out into
        # every worktree and bloats all derived indexes.
        git_marker = Path(root) / ".git"
        if git_marker.is_file():
            return
        siblings = self._related_worktrees(root)
        if not siblings:
            return
        now = time.time()

        def register_siblings(con: sqlite3.Connection) -> None:
            for sibling in siblings:
                if self._is_internal_root(sibling) or self._is_ephemeral_root(sibling):
                    continue
                workspace = self.rag.workspace_id(sibling)
                row = con.execute("SELECT root FROM projects WHERE root=?", (sibling,)).fetchone()
                if row is None:
                    con.execute(
                        """INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (sibling, workspace, "waiting", "inventory", 0, 0, now, now, 0, 0, 0, "worktree-discovery"),
                    )
                else:
                    con.execute(
                        "UPDATE projects SET workspace=?,paused=0,status='waiting',registration_source='worktree-discovery' WHERE root=?",
                        (workspace, sibling),
                    )

        try:
            self._write_retry(register_siblings)
        except Exception:
            # Discovery is an acceleration feature. A Git/SQLite failure must not
            # turn foreground project registration into a failure.
            pass


    def _seed_from_parent(self, root: str, parent_root: str) -> dict[str, int]:
        """Inherit precomputed caches from parent repository into a worktree."""
        stats = {"file_refs": 0, "code_index": 0, "deterministic": 0}
        resolved = self._root(root)
        parent_resolved = self._root(parent_root)
        if not Path(resolved).is_dir() or not Path(parent_resolved).is_dir():
            return stats
        if resolved == parent_resolved:
            return stats

        now = time.time()
        base = Path(resolved)

        # 1. Seed file_refs & source_index from preprocess.sqlite3
        try:
            with closing(self._connect()) as con:
                p_rows = con.execute(
                    "SELECT path, size, content_hash FROM file_refs WHERE root=? AND needs_hash=0 AND content_hash<>''",
                    (parent_resolved,),
                ).fetchall()
            try:
                clean_git_hashes = self.repo_tools.git_blob_map(resolved)
            except Exception:
                clean_git_hashes = {}

            candidates: list[tuple[str, str, int, int, tuple[int, ...]]] = []
            stale_candidates: list[tuple[str, str]] = []
            for row in p_rows:
                rel = str(row["path"]).replace("\\", "/")
                parent_hash = str(row["content_hash"] or "")
                child_file = (base / rel).resolve(strict=False)
                if not child_file.is_file():
                    continue
                try:
                    before = child_file.stat()
                    child_size = int(before.st_size)
                    if child_size != int(row["size"]):
                        stale_candidates.append((rel, parent_hash))
                        continue
                    if parent_hash.startswith("git:"):
                        child_hash = str(clean_git_hashes.get(rel) or "")
                    else:
                        child_hash = str(self.repo_tools._hash_file_only(child_file) or "")
                    after = child_file.stat()
                    identity_before = (
                        int(before.st_size), int(before.st_mtime_ns),
                        int(getattr(before, "st_ctime_ns", 0)), int(getattr(before, "st_ino", 0)),
                        int(getattr(before, "st_dev", 0)),
                    )
                    identity_after = (
                        int(after.st_size), int(after.st_mtime_ns),
                        int(getattr(after, "st_ctime_ns", 0)), int(getattr(after, "st_ino", 0)),
                        int(getattr(after, "st_dev", 0)),
                    )
                    if not child_hash or child_hash != parent_hash or identity_before != identity_after:
                        stale_candidates.append((rel, parent_hash))
                        continue
                    candidates.append((rel, parent_hash, child_size, int(after.st_mtime_ns), identity_after))
                except OSError:
                    stale_candidates.append((rel, parent_hash))

            if candidates or stale_candidates:
                with self._db_lock, closing(self._connect()) as con:
                    con.execute("BEGIN IMMEDIATE")
                    for rel, parent_hash in stale_candidates:
                        con.execute(
                            """UPDATE file_refs
                               SET content_hash='',needs_hash=1,rag_hash=NULL,card_key=NULL,updated_at=?
                               WHERE root=? AND path=? AND content_hash=? AND needs_hash=0
                                 AND EXISTS (
                                     SELECT 1 FROM file_refs p
                                     WHERE p.root=? AND p.path=? AND p.content_hash=? AND p.needs_hash=0
                                 )""",
                            (now, resolved, rel, parent_hash, parent_resolved, rel, parent_hash),
                        )
                        con.execute(
                            """DELETE FROM source_index
                               WHERE root=? AND path=? AND content_hash=?
                                 AND EXISTS (
                                     SELECT 1 FROM file_refs p
                                     WHERE p.root=? AND p.path=? AND p.content_hash=? AND p.needs_hash=0
                                 )""",
                            (resolved, rel, parent_hash, parent_resolved, rel, parent_hash),
                        )
                    for rel, parent_hash, size, mtime_ns, identity in candidates:
                        child_file = (base / rel).resolve(strict=False)
                        try:
                            st = child_file.stat()
                        except OSError:
                            continue
                        current_identity = (
                            int(st.st_size), int(st.st_mtime_ns),
                            int(getattr(st, "st_ctime_ns", 0)), int(getattr(st, "st_ino", 0)),
                            int(getattr(st, "st_dev", 0)),
                        )
                        if current_identity != identity:
                            continue
                        parent = con.execute(
                            """SELECT card_key FROM file_refs
                               WHERE root=? AND path=? AND content_hash=? AND size=? AND needs_hash=0""",
                            (parent_resolved, rel, parent_hash, size),
                        ).fetchone()
                        if parent is None:
                            continue
                        inserted = con.execute(
                            """INSERT OR IGNORE INTO file_refs(
                                root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,
                                last_accessed_at,generation,card_key,updated_at
                            ) VALUES(?,?,?,?,?,0,NULL,?,1,?,?)""",
                            (resolved, rel, parent_hash, size, mtime_ns, now, parent["card_key"], now),
                        )
                        if inserted.rowcount > 0:
                            stats["file_refs"] += 1
                        child = con.execute(
                            "SELECT content_hash,needs_hash FROM file_refs WHERE root=? AND path=?",
                            (resolved, rel),
                        ).fetchone()
                        if child is not None and str(child["content_hash"] or "") == parent_hash and int(child["needs_hash"] or 0) == 0:
                            con.execute(
                                """INSERT OR IGNORE INTO source_index(root,path,content_hash,text,updated_at)
                                   SELECT ?,path,content_hash,text,? FROM source_index
                                   WHERE root=? AND path=? AND content_hash=?""",
                                (resolved, now, parent_resolved, rel, parent_hash),
                            )
                    con.commit()
        except (OSError, sqlite3.Error) as exc:
            logger.warning("worktree file cache seed skipped (%s)", type(exc).__name__)

        # 2. Seed deterministic.sqlite3 (test_source_links, hotspots_cache)
        if self.deterministic is not None:
            try:
                with closing(self.deterministic._connect()) as det_con:
                    det_con.execute(
                        """INSERT OR IGNORE INTO test_source_links(root, source_path, test_path, confidence, updated_at)
                           SELECT ?, source_path, test_path, confidence, ? FROM test_source_links WHERE root=?""",
                        (resolved, now, parent_resolved),
                    )
                    det_con.execute(
                        """INSERT OR REPLACE INTO hotspots_cache(root, days, cached_at, data_json)
                           SELECT ?, days, ?, data_json FROM hotspots_cache WHERE root=?""",
                        (resolved, now, parent_resolved),
                    )
                    det_con.commit()
                    stats["deterministic"] = 1
            except (OSError, sqlite3.Error) as exc:
                logger.warning("worktree deterministic cache seed skipped (%s)", type(exc).__name__)

        # 3. Seed code-index.sqlite3 (files, symbols, refs, edges)
        if self.code_index is not None:
            try:
                with closing(self.code_index._connect()) as ci_con:
                    ci_con.execute(
                        """INSERT OR IGNORE INTO files(root, path, content_hash, language, updated_at)
                           SELECT ?, path, content_hash, language, ? FROM files WHERE root=?""",
                        (resolved, now, parent_resolved),
                    )
                    ci_con.execute(
                        """INSERT OR IGNORE INTO symbols(root, path, name, kind, line, end_line, container, name_path, signature, access, docstring)
                           SELECT ?, path, name, kind, line, end_line, container, name_path, signature, access, docstring FROM symbols WHERE root=?""",
                        (resolved, parent_resolved),
                    )
                    ci_con.execute(
                        """INSERT OR IGNORE INTO refs(root, path, name, line, kind)
                           SELECT ?, path, name, line, kind FROM refs WHERE root=?""",
                        (resolved, parent_resolved),
                    )
                    ci_con.execute(
                        """INSERT OR IGNORE INTO edges(root, src, dst, kind, path, line)
                           SELECT ?, src, dst, kind, path, line FROM edges WHERE root=?""",
                        (resolved, parent_resolved),
                    )
                    ci_con.commit()
                    stats["code_index"] = 1
            except (OSError, sqlite3.Error) as exc:
                logger.warning("worktree code-index cache seed skipped (%s)", type(exc).__name__)

        return stats

    def register(self, root: str, *, force: bool = False, source: str = "agent", is_worktree: bool = False, parent_root: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {"success": False, "enabled": False, "error": "preprocessing disabled"}
        resolved = self._root(root)
        if not Path(resolved).is_dir():
            return {"success": False, "error": f"root directory does not exist: {resolved}"}
        if self._is_internal_root(resolved):
            return {"success": True, "ignored": True, "reason": "internal Local AI install/state directory", "project": Path(resolved).name}
        if self._is_ephemeral_root(resolved):
            return {"success": True, "ignored": True, "reason": "ephemeral/system directory is not a stable project", "project": Path(resolved).name}
        if self.require_project_markers and not self._has_project_marker(Path(resolved)):
            return {"success": True, "ignored": True, "reason": "directory has no stable project marker/source tree", "project": Path(resolved).name}
        workspace = self.rag.workspace_id(resolved)
        now = time.time()
        if force:
            self._code_index_pruned_generations = {
                key for key in getattr(self, "_code_index_pruned_generations", set()) if key[0] != resolved
            }
            self._deterministic_pruned_generations = {
                key for key in getattr(self, "_deterministic_pruned_generations", set()) if key[0] != resolved
            }
        def _register_tx(con: sqlite3.Connection) -> None:
            row = con.execute("SELECT root,generation FROM projects WHERE root=?", (resolved,)).fetchone()
            if row is None:
                con.execute(
                    "INSERT INTO projects(root,workspace,status,phase,generation,force_refresh,registered_at,updated_at,next_check_at,paused,last_requested_at,registration_source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (resolved, workspace, "queued", "inventory", 0, int(force), now, now, now, 0, now, str(source or "agent")[:32]),
                )
            elif force:
                con.execute(
                    "UPDATE projects SET status='queued', phase='inventory', paused=0, force_refresh=1, updated_at=?, last_requested_at=?, next_check_at=?, registration_source=? WHERE root=?",
                    (now, now, now, str(source or "agent")[:32], resolved),
                )
                # A forced rebuild must not expose old backend failures while the
                # refreshed Serena runs are still queued.
                con.execute("DELETE FROM external_index_state WHERE root=?", (resolved,))
            else:
                con.execute(
                    "UPDATE projects SET paused=0, status=CASE WHEN status IN ('paused','error','waiting') THEN 'queued' ELSE status END, last_requested_at=?, next_check_at=CASE WHEN status IN ('paused','error') THEN 0 ELSE next_check_at END, registration_source=? WHERE root=?",
                    (now, str(source or "agent")[:32], resolved),
                )
            self._rebalance_processing_slots(con, preferred_root=resolved)
        self._write_retry(_register_tx)
        if is_worktree or parent_root:
            p_root = parent_root or (self._related_worktrees(resolved)[0] if self._related_worktrees(resolved) else None)
            if p_root and p_root != resolved:
                self._seed_from_parent(resolved, p_root)
        self._register_discovered_worktrees(resolved)
        self._wake_all()
        return self.status(resolved)

    def refresh(self, root: str) -> dict[str, Any]:
        return self.register(root, force=True, source="agent")

    def pause(self, root: str | None = None) -> dict[str, Any]:
        if root is None:
            self._paused.set()
            try: self.pause_marker.write_text(f"paused {time.time()}\n", encoding="utf-8")
            except OSError: pass
            self._wake_all()
            return self.status()
        resolved = self._root(root)
        self._write_retry(lambda con: con.execute("UPDATE projects SET paused=1,status='paused',updated_at=? WHERE root=?", (time.time(), resolved)))
        self._wake_all(); return self.status(resolved)

    def resume(self, root: str | None = None) -> dict[str, Any]:
        if root is None:
            self._paused.clear()
            try: self.pause_marker.unlink(missing_ok=True)
            except OSError: pass
            def _resume_all(con: sqlite3.Connection) -> None:
                con.execute("UPDATE projects SET paused=0, status=CASE WHEN status='paused' THEN 'queued' ELSE status END, retry_after=0, next_check_at=?, updated_at=?", (time.time(), time.time()))
                self._rebalance_processing_slots(con)
            self._write_retry(_resume_all)
            self._wake_all()
            return self.status()
        resolved = self._root(root)
        def _resume_tx(con: sqlite3.Connection) -> None:
            con.execute("UPDATE projects SET paused=0,status='queued',retry_after=0,next_check_at=?,updated_at=?,last_requested_at=? WHERE root=?", (time.time(),time.time(),time.time(),resolved))
            self._rebalance_processing_slots(con, preferred_root=resolved)
        self._write_retry(_resume_tx)
        self._wake_all(); return self.status(resolved)

    def cancel(self, root: str) -> dict[str, Any]:
        # Cancel means stop scheduling this project but keep all reusable derived cache.
        return self.pause(root)

    def _live_workspace_paths(self, workspace: str, excluding_root: str) -> set[str]:
        with self._db_lock, closing(self._connect()) as con:
            aliases = con.execute(
                "SELECT projects.root,file_refs.path FROM file_refs "
                "JOIN projects ON projects.root=file_refs.root "
                "WHERE projects.workspace=? AND projects.root<>?",
                (workspace, excluding_root),
            ).fetchall()
        return {
            str(alias["path"]).replace("\\", "/")
            for alias in aliases
            if Path(str(alias["root"])).is_dir()
        }

    def _purge_project_secondary_indexes(self, root: str, workspace: str | None) -> bool:
        """Purge only project-owned rows; callers retain registry ownership on failure."""
        cascade_ok = True
        if self.code_index is not None:
            try:
                result = self.code_index.prune(root, [])
                if not isinstance(result, dict) or not result.get("success"):
                    cascade_ok = False
                    logger.warning(
                        "deleted-project code-index purge incomplete (%s)",
                        result.get("error", "unknown") if isinstance(result, dict) else "invalid result",
                    )
            except Exception as exc:
                cascade_ok = False
                logger.warning("deleted-project code-index purge incomplete (%s)", type(exc).__name__)
        if self.deterministic is not None:
            try:
                with closing(self.deterministic._connect()) as det_con:
                    det_con.execute("DELETE FROM files WHERE root=?", (root,))
                    det_con.execute("DELETE FROM facts WHERE root=?", (root,))
                    det_con.commit()
            except Exception as exc:
                cascade_ok = False
                logger.warning(
                    "deleted-project deterministic purge incomplete (%s: %s)",
                    type(exc).__name__, exc,
                )
        if self.rag is not None:
            try:
                rag_workspace = workspace
                if rag_workspace is None:
                    rag_workspace = str(self.rag.workspace_id(root))
                live_paths = self._live_workspace_paths(rag_workspace, root)
                self.rag.remove_project(
                    root, "__preprocess__", rag_workspace, preserve_paths=live_paths
                )
            except Exception as exc:
                cascade_ok = False
                logger.warning("deleted-project RAG purge incomplete (%s)", type(exc).__name__)
        return cascade_ok

    def _mark_project_cleanup_pending(self, root: str) -> None:
        with self._db_lock, closing(self._connect()) as con:
            con.execute(
                "UPDATE projects SET status='error',paused=1,retry_after=0,"
                "next_check_at=0,updated_at=? WHERE root=?",
                (time.time(), root),
            )
            con.commit()

    def unregister(self, root: str, purge_data: bool = False) -> dict[str, Any]:
        """Remove scheduler registration; optionally purge workspace derived data."""
        resolved = self._root(root)
        if purge_data:
            with self._db_lock, closing(self._connect()) as con:
                row = con.execute(
                    "SELECT workspace FROM projects WHERE root=?", (resolved,)
                ).fetchone()
            workspace = str(row["workspace"]) if row is not None else None
            if not self._purge_project_secondary_indexes(resolved, workspace):
                self._mark_project_cleanup_pending(resolved)
                self._wake_all()
                return {
                    "success": False,
                    "removed": 0,
                    "project": Path(resolved).name,
                    "purged": False,
                }
            try:
                with self._db_lock, closing(self._connect()) as con:
                    cur = con.execute("DELETE FROM projects WHERE root=?", (resolved,))
                    con.execute("DELETE FROM file_refs WHERE root=?", (resolved,))
                    con.execute("DELETE FROM source_index WHERE root=?", (resolved,))
                    con.execute("DELETE FROM source_fts WHERE root=?", (resolved,))
                    con.execute("DELETE FROM module_cards WHERE root=?", (resolved,))
                    con.execute("DELETE FROM project_cards WHERE root=?", (resolved,))
                    con.execute("DELETE FROM hot_query_state WHERE root=?", (resolved,))
                    con.commit()
            except Exception as exc:
                self._mark_project_cleanup_pending(resolved)
                logger.warning("worktree registry purge incomplete (%s)", type(exc).__name__)
                self._wake_all()
                return {
                    "success": False,
                    "removed": 0,
                    "project": Path(resolved).name,
                    "purged": False,
                }
            self._forget_project_runtime(resolved)
            self._wake_all()
            return {
                "success": True,
                "removed": int(cur.rowcount or 0),
                "project": Path(resolved).name,
                "purged": True,
            }

        with self._db_lock, closing(self._connect()) as con:
            cur = con.execute("DELETE FROM projects WHERE root=?", (resolved,))
            con.commit()
        self._forget_project_runtime(resolved)
        self._wake_all()
        return {"success": True, "removed": int(cur.rowcount or 0), "project": Path(resolved).name, "purged": False}

    def cleanup_deleted_projects(self) -> dict[str, Any]:
        """Scan all registered projects and remove projects whose root directory no longer exists on disk."""
        pruned: list[str] = []
        with self._db_lock, closing(self._connect()) as con:
            rows = con.execute("SELECT root,workspace FROM projects").fetchall()
        failed: list[str] = []
        for row in rows:
            root = str(row["root"])
            workspace = str(row["workspace"])
            if Path(root).exists():
                continue

            cascade_ok = self._purge_project_secondary_indexes(root, workspace)
            if not cascade_ok:
                self._mark_project_cleanup_pending(root)
                failed.append(root)
                continue

            try:
                with self._db_lock, closing(self._connect()) as con:
                    con.execute("DELETE FROM projects WHERE root=?", (root,))
                    con.execute("DELETE FROM file_refs WHERE root=?", (root,))
                    con.execute("DELETE FROM source_index WHERE root=?", (root,))
                    con.execute("DELETE FROM source_fts WHERE root=?", (root,))
                    con.execute("DELETE FROM module_cards WHERE root=?", (root,))
                    con.execute("DELETE FROM project_cards WHERE root=?", (root,))
                    con.execute("DELETE FROM hot_query_state WHERE root=?", (root,))
                    con.commit()
                self._forget_project_runtime(root)
                pruned.append(root)
            except Exception as exc:
                self._mark_project_cleanup_pending(root)
                failed.append(root)
                logger.warning("deleted-project registry purge incomplete (%s)", type(exc).__name__)

        self._vacuum_derived_databases()

        self._wake_all()
        return {
            "success": not failed,
            "pruned_count": len(pruned),
            "pruned_projects": pruned,
            "failed_count": len(failed),
            "failed_projects": failed,
            "message": (
                f"Successfully cleaned up {len(pruned)} missing worktree(s)/project(s)"
                if pruned
                else f"Cleanup incomplete for {len(failed)} missing project(s)"
                if failed
                else "No missing projects found (all active directories exist on disk)"
            ),
        }

    def _vacuum_derived_databases(self) -> None:
        """Reclaim a bounded batch of free pages from owned derived indexes."""
        vacuum_paths = [self.db_path]
        for owner in (self.code_index, self.deterministic, self.rag):
            path = getattr(owner, "db_path", None) if owner is not None else None
            if path is not None:
                vacuum_paths.append(Path(path))
        for path in dict.fromkeys(vacuum_paths):
            setup = ensure_incremental_vacuum(path)
            result = incremental_vacuum(path) if setup.get("success") else setup
            if not result.get("success"):
                logger.warning(
                    "deleted-project database vacuum incomplete (%s)",
                    result.get("error", "unknown"),
                )

    def cleanup_orphaned_indexes(self, max_roots: int | None = None) -> dict[str, Any]:
        """Bounded idle cleanup for derived index roots no longer registered."""
        with self._db_lock, closing(self._connect()) as con:
            active = {str(row[0]) for row in con.execute("SELECT root FROM projects").fetchall()}
        limit = max(1, int(max_roots or self.cfg.get("orphan_cleanup_roots_per_run", 4)))
        removed: dict[str, int] = {}
        stores = (
            (self.code_index, frozenset({"files", "symbols", "refs", "edges"})),
            (self.deterministic, frozenset({"files", "facts", "fact_fts", "dependencies", "scripts", "project_state", "query_cache"})),
        )
        for component, allowed_tables in stores:
            if component is None or not hasattr(component, "_connect"):
                continue
            try:
                lock = getattr(component, "_lock", nullcontext())
                with lock, closing(component._connect()) as con:
                    roots = [str(row[0]) for row in con.execute("SELECT DISTINCT root FROM files").fetchall()]
                    orphans = [root for root in roots if root not in active][:limit]
                    existing = {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                    for root in orphans:
                        for table in allowed_tables:
                            if table in existing:
                                # table is validated against frozenset — safe for f-string interpolation
                                con.execute(f"DELETE FROM {table} WHERE root=?", (root,))  # noqa: S608
                        removed[root] = removed.get(root, 0) + 1
                    if orphans:
                        con.commit()
            except (sqlite3.DatabaseError, OSError):
                continue
        return {"success": True, "removed_roots": sorted(removed), "removed_count": len(removed)}

    def _project_row(self, root: str) -> sqlite3.Row | None:
        with self._db_lock, closing(self._connect()) as con:
            return con.execute("SELECT * FROM projects WHERE root=?", (self._root(root),)).fetchone()

    def _project_settings(self, root: str) -> Any:
        _api, context = self._project_config_context(root)
        return context.settings if context is not None else resolve_project_config(root).settings

    def _project_phase_allowed(self, root: str, phase: str) -> bool:
        api, context = self._project_config_context(root)
        if context is None:
            return phase_is_allowed(resolve_project_config(root).settings, phase)
        checker = getattr(api, "phase_is_allowed", phase_is_allowed)
        return bool(checker(context.settings, phase))

    def _project_path_allowed(
        self,
        root: str,
        relative: str,
        settings: Any,
        *,
        phase: str,
        size_bytes: int,
    ) -> bool:
        parts = Path(relative).parts
        ignored_dirs = getattr(self.repo_tools, "ignore_dirs", set())
        hard_dirs = {".git", ".svn", ".hg", ".serena", ".local-ai-hub"}
        hard_denied = any(part.lower() in hard_dirs for part in parts[:-1])
        ignore_extensions = getattr(self.repo_tools, "ignore_extensions", set())
        hard_denied = hard_denied or Path(relative).suffix.lower() in ignore_extensions
        extensions = getattr(self.repo_tools, "extensions", set())
        project_extensions = {str(value).lower() for value in getattr(settings, "text_extensions", ())}
        for override in getattr(settings, "language_overrides", {}).values():
            project_extensions.update(str(value).lower() for value in override.get("text_extensions", ()))
        binary_extensions = {str(value).lower() for value in getattr(settings, "binary_extensions", ())}
        project_extensions.difference_update(binary_extensions)
        hard_denied = hard_denied or Path(relative).suffix.lower() in binary_extensions
        special_filenames = getattr(self.repo_tools, "special_filenames", set())
        if extensions and Path(relative).suffix.lower() not in extensions and Path(relative).suffix.lower() not in project_extensions and Path(relative).name.lower() not in special_filenames:
            hard_denied = True
        return path_is_allowed(
            root,
            Path(root) / relative,
            settings,
            phase=phase,
            soft_ignored=any(part.lower() in ignored_dirs for part in parts[:-1]),
            hard_denied=hard_denied,
            size_bytes=size_bytes,
        )

    def _forced_preprocess_files(self, root: str, settings: Any) -> dict[str, dict[str, Any]]:
        base = Path(root).resolve(strict=True)
        patterns = list(settings.force_include_paths)
        patterns.extend(
            pattern
            for pattern, action in settings.path_overrides.items()
            if action == "include"
        )
        maximum = max(1, int(getattr(self.repo_tools, "max_files", 8000)))
        files: dict[str, dict[str, Any]] = {}
        visited = 0
        for pattern in patterns:
            try:
                candidates = base.glob(pattern)
                for candidate in candidates:
                    visited += 1
                    if visited > maximum * 4:
                        return files
                    if not candidate.is_file():
                        continue
                    resolved = candidate.resolve(strict=True)
                    if not resolved.is_relative_to(base):
                        continue
                    relative = resolved.relative_to(base).as_posix()
                    stat = resolved.stat()
                    size = int(stat.st_size)
                    if size > int(getattr(self.repo_tools, "max_file_bytes", size)):
                        continue
                    if not self._project_path_allowed(
                        str(base), relative, settings, phase="preprocess", size_bytes=size
                    ):
                        continue
                    files[relative] = {
                        "path": relative,
                        "size": size,
                        "mtime_ns": int(stat.st_mtime_ns),
                        "extension": resolved.suffix.lower(),
                    }
                    if len(files) >= maximum:
                        return files
            except (OSError, RuntimeError, ValueError):
                continue
        return files

    def _record_progress(self, root: str, count: int = 1) -> None:
        now = time.time()
        with self._stats_lock:
            history = self._speed_tracker.setdefault(root, [])
            history.append((now, count))
            cutoff = now - 30.0
            self._speed_tracker[root] = [(t, c) for t, c in history if t >= cutoff]

    def status(self, root: str | None = None) -> dict[str, Any]:
        now_mono = time.monotonic()
        key = str(root or "__all__")
        mode_paused = not self._background_work_allowed()
        if not hasattr(self, "_status_cache"):
            self._status_cache = {}
        cached = self._status_cache.get(key)
        if cached and cached.get("mode_paused") == mode_paused and now_mono - cached["time"] < 0.5:
            return dict(cached["data"])
        with closing(self._connect()) as con:
            if root is not None:
                rows = con.execute("SELECT * FROM projects WHERE root=?", (self._root(root),)).fetchall()
            else:
                rows = con.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()

            roots = [str(row["root"]) for row in rows]
            incomplete_roots = [
                str(row["root"])
                for row in rows
                if str(row["status"] or "queued") != "complete"
                and str(row["phase"] or "inventory") != "complete"
            ]

            def root_batches(values: list[str]):
                for offset in range(0, len(values), 400):
                    yield values[offset : offset + 400]

            file_counts: dict[str, tuple[int, int, int, int]] = {}
            external_by_root: dict[str, dict[str, dict[str, Any]]] = {value: {} for value in roots}
            source_counts: dict[str, int] = {}
            module_counts: dict[str, int] = {}
            project_card_counts: dict[str, int] = {}
            code_index_counts: dict[str, int] = {}
            deterministic_counts: dict[str, int] = {}

            for batch in root_batches(roots):
                placeholders = ",".join("?" for _ in batch)
                count_rows = con.execute(
                    f"""SELECT root, COUNT(*),
                        SUM(CASE WHEN card_key IS NOT NULL THEN 1 ELSE 0 END),
                        SUM(CASE WHEN needs_hash=0 AND content_hash<>'' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN COALESCE(rag_hash,'')=content_hash AND content_hash<>'' THEN 1 ELSE 0 END)
                    FROM file_refs WHERE root IN ({placeholders}) GROUP BY root""",
                    batch,
                ).fetchall()
                file_counts.update({
                    str(count_row[0]): tuple(int(value or 0) for value in count_row[1:5])
                    for count_row in count_rows
                })
                external_rows = con.execute(
                    f"SELECT root,backend,status,error,updated_at FROM external_index_state WHERE root IN ({placeholders})",
                    batch,
                ).fetchall()
                for external_row in external_rows:
                    external_by_root[str(external_row[0])][str(external_row[1])] = {
                        "status": "unavailable" if str(external_row[2]) == "skipped" else str(external_row[2]),
                        "error": str(external_row[3] or ""),
                        "updated_at": float(external_row[4] or 0),
                    }

            for batch in root_batches(incomplete_roots):
                placeholders = ",".join("?" for _ in batch)
                for table, target in (
                    ("source_index", source_counts),
                    ("module_cards", module_counts),
                    ("project_cards", project_card_counts),
                ):
                    count_rows = con.execute(
                        f"SELECT root, COUNT(*) FROM {table} WHERE root IN ({placeholders}) GROUP BY root",
                        batch,
                    ).fetchall()
                    target.update({str(count_row[0]): int(count_row[1] or 0) for count_row in count_rows})

            def index_file_counts(index: Any | None, label: str) -> dict[str, int]:
                result: dict[str, int] = {}
                if index is None or not incomplete_roots:
                    return result
                try:
                    with closing(index._connect()) as index_con:
                        for batch in root_batches(incomplete_roots):
                            placeholders = ",".join("?" for _ in batch)
                            count_rows = index_con.execute(
                                f"SELECT root, COUNT(*) FROM files WHERE root IN ({placeholders}) GROUP BY root",
                                batch,
                            ).fetchall()
                            result.update({str(count_row[0]): int(count_row[1] or 0) for count_row in count_rows})
                except sqlite3.Error as exc:
                    logger.warning("%s status unavailable (%s)", label, type(exc).__name__)
                return result

            code_index_counts = index_file_counts(self.code_index, "Code-index")
            deterministic_counts = index_file_counts(self.deterministic, "Deterministic-index")

            projects: list[dict[str, Any]] = []
            for row in rows:
                git_common_dir, is_worktree = _project_git_identity(str(row["root"]))
                status_str = str(row["status"] or "queued")
                phase_str = "complete" if status_str == "complete" else str(row["phase"] or "inventory")
                total_phases = len(self.PHASES)
                try:
                    phase_index = self.PHASES.index(phase_str) + 1
                except ValueError:
                    phase_index = total_phases if status_str == "complete" else 1

                counts = file_counts.get(str(row["root"]), (0, 0, 0, 0))
                total_files = int(counts[0] or 0)
                file_cards = min(total_files, int(counts[1] or 0))
                hashed_files = min(total_files, int(counts[2] or 0))
                rag_files = min(total_files, int(counts[3] or 0))

                source_count = source_counts.get(str(row["root"]), 0)
                ci_count = 0
                det_count = 0
                module_count = 0
                project_card_count = 0
                external_indexes = external_by_root.get(str(row["root"]), {})
                if status_str != "complete" and phase_str != "complete":
                    ci_count = code_index_counts.get(str(row["root"]), 0)
                    det_count = deterministic_counts.get(str(row["root"]), 0)
                    module_count = module_counts.get(str(row["root"]), 0)
                    project_card_count = project_card_counts.get(str(row["root"]), 0)
                else:
                    file_cards = total_files
                    hashed_files = total_files
                    rag_files = total_files

                # A stale derived index can temporarily contain rows from an
                # older inventory. Never expose impossible progress such as
                # 2616/2470 in the dashboard.
                ci_count = min(total_files, max(0, ci_count))
                det_count = min(total_files, max(0, det_count))

                if status_str == "complete" or phase_str == "complete":
                    status_str = "complete"
                    phase_str = "complete"
                    phase_index = total_phases
                    phase_pct = 100.0
                    overall_progress = 100.0
                elif phase_str == "inventory":
                    phase_pct = 100.0
                    overall_progress = round((1.0 / total_phases) * 100, 1)
                elif phase_str == "hash" and total_files:
                    phase_pct = round((hashed_files / total_files) * 100, 1)
                    frac = phase_pct / 100.0
                    overall_progress = round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                elif phase_str == "code_index" and total_files:
                    phase_pct = round(min(100.0, (ci_count / total_files) * 100), 1)
                    frac = phase_pct / 100.0
                    overall_progress = round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                elif phase_str == "deterministic" and total_files:
                    phase_pct = round(min(100.0, (det_count / total_files) * 100), 1)
                    frac = phase_pct / 100.0
                    overall_progress = round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                elif phase_str == "serena":
                    ext_state = external_indexes.get(phase_str, {}).get("status", "")
                    phase_pct = 100.0 if ext_state in {"ready", "unavailable", "skipped", "degraded"} else 25.0
                    frac = phase_pct / 100.0
                    overall_progress = round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                elif phase_str == "lexical" and total_files:
                    phase_pct = round(min(100.0, (source_count / total_files) * 100), 1)
                    frac = phase_pct / 100.0
                    overall_progress = round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                elif phase_str == "rag" and total_files:
                    phase_pct = round((rag_files / total_files) * 100, 1)
                    frac = phase_pct / 100.0
                    overall_progress = round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                elif phase_str == "files" and total_files:
                    phase_pct = round((file_cards / total_files) * 100, 1)
                    frac = phase_pct / 100.0
                    overall_progress = round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                elif phase_str == "modules":
                    phase_pct = round(min(100.0, (module_count / max(1, module_count + 1)) * 100), 1) if module_count else 50.0
                    frac = phase_pct / 100.0
                    overall_progress = round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                elif phase_str == "project":
                    phase_pct = 100.0 if project_card_count else 50.0
                    frac = phase_pct / 100.0
                    overall_progress = round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                elif phase_str == "hot_queries":
                    phase_pct = 75.0
                    frac = phase_pct / 100.0
                    overall_progress = round(min(100.0, max(0.0, ((phase_index - 1 + frac) / total_phases) * 100)), 1)
                else:
                    phase_pct = 0.0
                    overall_progress = round(min(100.0, max(0.0, ((phase_index - 1) / total_phases) * 100)), 1)

                # Throughput speed and ETA calculation
                now = time.time()
                with self._stats_lock:
                    history = self._speed_tracker.get(row["root"], [])
                    cutoff = now - 30.0
                    valid = [(t, c) for t, c in history if t >= cutoff]
                    self._speed_tracker[row["root"]] = valid
                progress_at = valid[-1][0] if valid else float(row["updated_at"] or now)
                progress_age_seconds = max(0.0, time.time() - progress_at)
                
                speed_rate = 0.0
                speed_str = "idle"
                eta_str = "—"
                eta_seconds = 0
                
                if status_str == "complete" or phase_str == "complete":
                    speed_str = "ready"
                    eta_str = "0s"
                elif status_str == "running":
                    if len(valid) >= 2:
                        dt = max(0.5, valid[-1][0] - valid[0][0])
                        done_items = sum(c for _, c in valid[1:])
                        speed_rate = round(done_items / dt, 1)
                    
                    if phase_str in ("files", "modules", "project"):
                        unit = "cards/s"
                        remaining = max(0, total_files - file_cards)
                    elif phase_str == "rag":
                        unit = "chunks/s"
                        remaining = max(0, total_files - rag_files)
                    elif phase_str in ("hash", "code_index", "deterministic", "lexical"):
                        unit = "files/s"
                        remaining = max(0, total_files - (hashed_files if phase_str == "hash" else (ci_count if phase_str == "code_index" else (det_count if phase_str == "deterministic" else source_count))))
                    elif phase_str == "serena":
                        unit = "index"
                        remaining = 0 if external_indexes.get(phase_str, {}).get("status") in {"ready", "unavailable", "skipped", "degraded"} else 1
                    else:
                        unit = "ops/s"
                        remaining = max(0, total_files)
                    
                    if remaining <= 0 or phase_pct >= 100.0:
                        # The worker is still committing/advancing to the next
                        # phase. Calling this "ready" made live rows look stuck
                        # at 100% while their status was still running.
                        speed_str = "finalizing"
                        eta_str = "next phase"
                    elif speed_rate > 0.05:
                        speed_str = f"{speed_rate:.1f} {unit}"
                        eta_seconds = int(remaining / speed_rate)
                        if eta_seconds < 60:
                            eta_str = f"{eta_seconds}s"
                        elif eta_seconds < 3600:
                            eta_str = f"{eta_seconds // 60}m {eta_seconds % 60}s"
                        else:
                            eta_str = f"{eta_seconds // 3600}h {(eta_seconds % 3600) // 60}m"
                    else:
                        speed_str = "batch in progress"
                        eta_str = "measuring…"

                last_err = str(row["last_error"] or "")
                last_err_short = last_err.strip().splitlines()[0][:90] if last_err else ""
                retry_after_val = float(row["retry_after"] or 0)
                is_paused_row = bool(row["paused"])
                is_waiting_row = status_str == "waiting" and not is_paused_row

                waiting_reason = ""
                if is_paused_row:
                    waiting_reason = "Project is paused"
                elif is_waiting_row:
                    waiting_reason = f"Waiting for preprocessing slot (max {self.max_preprocessing_projects})"
                elif status_str == "error":
                    waiting_reason = f"Error: {last_err_short}" if last_err_short else "Project encountered an error"
                elif retry_after_val > time.time():
                    waiting_reason = f"Cooldown ({int(retry_after_val - time.time())}s remaining)"
                elif status_str == "complete":
                    waiting_reason = "100% complete and up to date"
                elif status_str == "running":
                    waiting_reason = f"Processing phase: {phase_str}"
                elif status_str == "queued":
                    if not self.scheduler.background_allowed():
                        waiting_reason = "Yielding to foreground agent requests"
                    else:
                        waiting_reason = "Queued for worker execution"

                active_detail = ""
                if status_str == "complete" or phase_str == "complete" or overall_progress >= 100.0:
                    active_detail = "100% ready · Real-time file sync"
                elif is_paused_row:
                    active_detail = "Project is paused"
                elif is_waiting_row:
                    active_detail = f"Waiting for preprocessing slot (max {self.max_preprocessing_projects})"
                elif status_str == "error":
                    active_detail = f"Error: {last_err_short}" if last_err_short else "Error during processing"
                elif phase_str == "inventory":
                    active_detail = f"Discovering file inventory ({total_files} files)"
                elif phase_str == "hash":
                    active_detail = f"Hashing content: {hashed_files}/{total_files} files ({phase_pct}%)"
                elif phase_str == "code_index":
                    active_detail = f"AST symbol extraction: {ci_count}/{total_files} files ({phase_pct}%)"
                elif phase_str == "deterministic":
                    active_detail = f"Facts & routes extraction: {det_count}/{total_files} files ({phase_pct}%)"
                elif phase_str == "serena":
                    ext = external_indexes.get("serena", {})
                    s_st = ext.get("status", "running")
                    reason = f": {ext.get('error')}" if s_st in {"unavailable", "skipped", "degraded"} and ext.get("error") else ""
                    active_detail = f"Serena LSP project indexing ({s_st}{reason})"
                elif phase_str == "lexical":
                    active_detail = f"FTS5 full-text indexing: {source_count}/{total_files} files ({phase_pct}%)"
                elif phase_str == "rag":
                    active_detail = f"Vector code embeddings: {rag_files}/{total_files} files ({phase_pct}%)"
                elif phase_str == "files":
                    active_detail = f"Generating semantic cards: {file_cards}/{total_files} files ({phase_pct}%)"
                elif phase_str == "modules":
                    active_detail = f"Module graph synthesis ({module_count} modules)"
                elif phase_str == "project":
                    active_detail = "Project architecture synthesis"
                elif phase_str == "hot_queries":
                    active_detail = "Pre-warming top query embeddings & capsules"
                else:
                    active_detail = f"Processing {phase_str} ({phase_pct}%)"

                project_stats = json.loads(row["stats_json"] or "{}")
                if isinstance(project_stats, dict):
                    # changed_paths is useful for recovery, but shipping thousands
                    # of paths on every dashboard poll made /api/live/status huge.
                    changed_paths = project_stats.pop("changed_paths", None)
                    if isinstance(changed_paths, list):
                        project_stats["changed_paths_count"] = len(changed_paths)
                else:
                    project_stats = {}
                projects.append({
                    "root": row["root"], "project": Path(row["root"]).name, "workspace": row["workspace"],
                    "git_common_dir": git_common_dir, "is_worktree": is_worktree,
                    "status": status_str, "phase": phase_str,
                    "paused": is_paused_row, "waiting": is_waiting_row, "last_error": last_err, "last_error_short": last_err_short,
                    "retry_after": retry_after_val, "waiting_reason": waiting_reason,
                    "active_detail": active_detail,
                    "phase_index": phase_index, "total_phases": total_phases,
                    "phase_progress_pct": phase_pct, "overall_progress_pct": overall_progress,
                    "speed_str": speed_str, "eta_str": eta_str, "last_complete_at": row["last_complete_at"],
                    "progress_age_seconds": round(progress_age_seconds, 1),
                    "files": total_files, "file_cards": file_cards, "hashed_files": hashed_files, "rag_files": rag_files,
                    "stats": project_stats, "external_indexes": external_indexes,
                })
        bg_allowed = self.scheduler.background_allowed()
        global_diagnostic = ""
        if not self.enabled:
            global_diagnostic = "Preprocessing is disabled in config (preprocessing.enabled = false)."
        elif self._paused.is_set():
            global_diagnostic = "Preprocessing is GLOBALLY PAUSED."
        elif not projects:
            global_diagnostic = "No projects registered. Register a repository path to start background preprocessing."
        elif any(p["status"] == "error" for p in projects):
            err_names = [p["project"] for p in projects if p["status"] == "error"]
            global_diagnostic = f"Errors detected in project(s): {', '.join(err_names)}."
        elif all(p["status"] == "complete" for p in projects):
            global_diagnostic = f"All {len(projects)} registered project(s) are 100% indexed and up to date."
        elif not bg_allowed:
            global_diagnostic = "Background processing is yielding to active foreground requests."
        else:
            global_diagnostic = "Background preprocessing is actively running."

        res = {
            "success": True, "enabled": self.enabled, "paused": self._paused.is_set() or mode_paused,
            "phases": list(self.PHASES), "projects": projects,
            "scheduler_background_allowed": bg_allowed,
            "global_diagnostic": global_diagnostic,
            "ingestion_reuse_rate": self.ingestion_reuse_rate(),
        }
        self._status_cache[key] = {"time": now_mono, "data": dict(res), "mode_paused": mode_paused}
        return res

    _PROJECT_COLUMNS = frozenset({
        "workspace", "status", "phase", "generation", "force_refresh",
        "inventory_hash", "structural_hash", "registered_at", "updated_at",
        "last_complete_at", "next_check_at", "retry_after", "last_error",
        "stats_json", "paused", "last_requested_at", "registration_source",
    })

    def _set_project(self, root: str, **values: Any) -> None:
        if not values:
            return
        root = self._root(root)
        values["updated_at"] = time.time()
        if not set(values) <= self._PROJECT_COLUMNS:
            bad = set(values) - self._PROJECT_COLUMNS
            raise ValueError(f"_set_project: invalid column(s): {bad}")
        columns = ",".join(f"{key}=?" for key in values)
        params = [*values.values(), root]
        self._write_retry(lambda con: con.execute(f"UPDATE projects SET {columns} WHERE root=?", params))
        if hasattr(self, "_status_cache"):
            self._status_cache.clear()

    def _mark_step_recovered(self, root: str) -> None:
        """Clear transient failure state after a preprocessing step succeeds or yields."""
        current = self._project_row(root)
        if current is None:
            return
        try:
            stats = json.loads(str(current["stats_json"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            stats = {}
        if not isinstance(stats, dict):
            stats = {}
        stats.pop("consecutive_errors", None)
        self._set_project(
            root,
            last_error=None,
            retry_after=0,
            stats_json=json_dumps(stats, ensure_ascii=False, separators=(",", ":")),
        )

    def _next_cpu_project(self) -> sqlite3.Row | None:
        now = time.time()
        with self._db_lock, closing(self._connect()) as con:
            # CPU/read-only phases. Serena indexing runs only while foreground is idle.
            self._rebalance_processing_slots(con)
            con.commit()
            row = con.execute(
                """SELECT * FROM projects
                   WHERE paused=0 AND retry_after<=?
                     AND status IN ('queued','running','error')
                     AND phase IN ('inventory', 'hash', 'code_index', 'deterministic', 'serena', 'lexical', 'rag', 'files', 'modules', 'project', 'hot_queries', 'diagnostics')
                   ORDER BY force_refresh DESC,
                            CASE status WHEN 'queued' THEN 0 WHEN 'running' THEN 1 ELSE 2 END,
                            updated_at ASC LIMIT 1""",
                (now,),
            ).fetchone()
            if row is not None:
                return row
            processing = int(con.execute(
                "SELECT COUNT(*) FROM projects WHERE paused=0 AND status IN ('queued','running','error') AND phase<>?",
                (self.PHASES[-1],),
            ).fetchone()[0] or 0)
            if processing >= self.max_preprocessing_projects:
                return None
            # A healthy filesystem watcher queues only changed paths. Avoid waking
            # completed projects into a full-tree inventory while that signal is
            # available; periodic inventory remains the fallback when watching is
            # disabled or unavailable.
            if self._watcher_active:
                return None
            # Complete projects needing auto-recheck
            return con.execute(
                """SELECT * FROM projects
                   WHERE paused=0 AND next_check_at<=? AND retry_after<=?
                     AND status='complete' AND phase='complete'
                   ORDER BY next_check_at ASC LIMIT 1""",
                (now, now),
            ).fetchone()

    def _next_gpu_project(self) -> sqlite3.Row | None:
        now = time.time()
        with self._db_lock, closing(self._connect()) as con:
            # GPU-bound phases: files, modules, project, hot_queries
            self._rebalance_processing_slots(con)
            con.commit()
            return con.execute(
                """SELECT * FROM projects
                   WHERE paused=0 AND retry_after<=?
                     AND phase IN ('files', 'modules', 'project', 'hot_queries')
                   ORDER BY force_refresh DESC,
                            CASE status WHEN 'queued' THEN 0 WHEN 'running' THEN 1 ELSE 2 END,
                            updated_at ASC LIMIT 1""",
                (now,),
            ).fetchone()

    def _cpu_loop(self) -> None:
        set_current_thread_priority(self.cpu_priority)
        startup_delay = max(0.0, float(self.cfg.get("startup_delay_seconds", 2.0)))
        if startup_delay > 0:
            self._stop.wait(startup_delay)
        poll = max(0.2, float(self.cfg.get("poll_seconds", 1.0)))
        while not self._stop.is_set():
            with self._stats_lock:
                self._stats["loops"] += 1
            if self._paused.is_set():
                self._cpu_wakeup.wait(poll)
                self._cpu_wakeup.clear()
                continue
            if not self._background_work_allowed():
                self._cpu_wakeup.wait(min(0.1, poll))
                self._cpu_wakeup.clear()
                continue
            if not self.cpu_runs_during_foreground and not self.scheduler.background_allowed():
                self._cpu_wakeup.wait(poll)
                self._cpu_wakeup.clear()
                continue
            row = self._next_cpu_project()
            if row is None:
                self._run_idle_database_maintenance()
                self._cpu_wakeup.wait(poll)
                self._cpu_wakeup.clear()
                continue
            root = str(row["root"])
            try:
                progressed = self._run_project_step(dict(row))
                if progressed is None:
                    self._cpu_wakeup.wait(min(0.1, poll))
                    self._cpu_wakeup.clear()
                    continue
                self._mark_step_recovered(root)
                if progressed:
                    with self._stats_lock:
                        self._stats["steps"] += 1
                else:
                    with self._stats_lock:
                        self._stats["yields"] += 1
                    self.scheduler.note_background_yield()
                    self._stop.wait(min(0.5, poll))
            except Exception as exc:
                with self._stats_lock:
                    self._stats["errors"] += 1
                try:
                    current = self._project_row(root)
                    prev = 0
                    if current:
                        try:
                            saved_stats = json.loads(current["stats_json"] or "{}")
                            if isinstance(saved_stats, dict):
                                prev = int(saved_stats.get("consecutive_errors", 0))
                        except (json.JSONDecodeError, TypeError, ValueError) as stats_exc:
                            logger.warning("Preprocessing error counter reset (%s)", type(stats_exc).__name__)
                    errors = prev + 1
                    backoff = min(float(self.cfg.get("max_error_backoff_seconds", 300)), 2 ** min(errors, 8))
                    self._set_project(root, status="error", last_error=str(exc)[:1000], retry_after=time.time() + backoff, stats_json=json_dumps({"consecutive_errors": errors}))
                    if self.telemetry is not None:
                        try:
                            self.telemetry.record_error("preprocess", str((current or {}).get("phase") or "step"), exc, retryable=True, recovered=True)
                        except Exception as telemetry_exc:
                            logger.warning("Preprocessing telemetry write failed (%s)", type(telemetry_exc).__name__)
                except Exception as record_exc:
                    logger.error("Could not record preprocessing failure state (%s)", type(record_exc).__name__)

    def _gpu_loop(self) -> None:
        startup_delay = max(0.0, float(self.cfg.get("startup_delay_seconds", 2.5)))
        if startup_delay > 0:
            self._stop.wait(startup_delay)
        poll = max(0.2, float(self.cfg.get("poll_seconds", 1.0)))
        while not self._stop.is_set():
            if self._paused.is_set():
                self._gpu_wakeup.wait(poll)
                self._gpu_wakeup.clear()
                continue
            if not self._background_work_allowed():
                self._gpu_wakeup.wait(min(0.1, poll))
                self._gpu_wakeup.clear()
                continue
            if self.background_gpu is None or not self.background_gpu.ready():
                self._gpu_wakeup.wait(poll)
                self._gpu_wakeup.clear()
                continue
            row = self._next_gpu_project()
            if row is None:
                self._gpu_wakeup.wait(poll)
                self._gpu_wakeup.clear()
                continue
            root = str(row["root"])
            try:
                progressed = self._run_project_step(dict(row))
                if progressed is None:
                    self._gpu_wakeup.wait(min(0.1, poll))
                    self._gpu_wakeup.clear()
                    continue
                self._mark_step_recovered(root)
                if progressed:
                    with self._stats_lock:
                        self._stats["gpu_card_steps"] = self._stats.get("gpu_card_steps", 0) + 1
                    self._gpu_wakeup.set()
                else:
                    self._stop.wait(min(0.5, poll))
            except Exception:
                with self._stats_lock:
                    self._stats["errors"] += 1
                self._stop.wait(1.0)

    def _yield(self) -> bool:
        if self._stop.is_set() or self._paused.is_set() or not self._background_work_allowed():
            return True
        if self.cpu_runs_during_foreground:
            return False
        return bool(self.scheduler.foreground_busy())

    def _background_work_allowed(self) -> bool:
        """Fail closed outside active mode; never load config from the state directory."""
        path = self.state_dir / "operational_mode.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return True
        except (OSError, json.JSONDecodeError, UnicodeError):
            return False
        if not isinstance(payload, dict):
            return False
        mode = payload.get("mode")
        revision = payload.get("revision")
        updated_at = payload.get("updated_at")
        if (
            mode not in {"active", "gaming", "maintenance"}
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
            or not isinstance(updated_at, str)
            or not updated_at
        ):
            return False
        return mode == "active"

    def _gpu_yield(self) -> bool:
        return (
            self._stop.is_set()
            or self._paused.is_set()
            or not self._background_work_allowed()
            or self.scheduler.foreground_busy()
        )

    def _fs_watcher_loop(self) -> None:
        """Keep one bounded watchdog observer synchronized with active projects.

        Watches are removed as soon as a project is paused/unregistered, preventing
        long-lived editors from accumulating recursive OS watch handles. Failures are
        degraded to polling and surfaced in stats; the resilience watchdog can restart
        this thread if it exits unexpectedly.
        """
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            self._watcher_active = False
            return

        class _Handler(FileSystemEventHandler):
            def __init__(self, preprocessor: "ProjectPreprocessor"):
                self._preprocessor = preprocessor

            def on_any_event(self, event: Any) -> None:
                if not self._preprocessor._background_work_allowed():
                    return
                # Watchdog also reports access/close events on some backends. They
                # are not repository mutations and treating them as edits makes
                # sync tools such as Mutagen continuously requeue preprocessing.
                if str(getattr(event, "event_type", "")) not in {"created", "deleted", "modified", "moved"}:
                    return
                if getattr(event, "is_directory", True):
                    return
                src = str(getattr(event, "src_path", ""))
                dst = str(getattr(event, "dest_path", ""))
                if src:
                    self._preprocessor.notify_path_changed(src)
                if dst and dst != src:
                    self._preprocessor.notify_path_changed(dst)

        observer = Observer()
        watches: dict[str, Any] = {}
        handler = _Handler(self)
        refresh = max(1.0, float(self.cfg.get("watcher_refresh_seconds", 3.0)))
        try:
            observer.start()
            while not self._stop.is_set():
                if not self._background_work_allowed():
                    # Keep one observer thread, but detach every recursive watch.
                    # Active mode rebuilds this set from current project registry.
                    for root in list(watches):
                        watch = watches.pop(root)
                        try:
                            observer.unschedule(watch)
                        except Exception:
                            with self._stats_lock:
                                self._stats["watcher_errors"] += 1
                            raise
                    self._watcher_active = False
                    self._stop.wait(refresh)
                    continue
                self._watcher_active = True
                try:
                    with self._db_lock, closing(self._connect()) as con:
                        roots = {str(r[0]) for r in con.execute(
                            "SELECT root FROM projects WHERE paused=0"
                        ).fetchall() if Path(str(r[0])).is_dir()}

                    # Drop watches for paused, unregistered or deleted roots.
                    for root in list(watches):
                        if root not in roots:
                            try:
                                observer.unschedule(watches.pop(root))
                            except Exception:
                                watches.pop(root, None)

                    for root in sorted(roots):
                        if root not in watches:
                            watches[root] = observer.schedule(handler, root, recursive=True)
                except Exception:
                    with self._stats_lock:
                        self._stats["watcher_errors"] += 1
                self._stop.wait(refresh)
        except Exception:
            with self._stats_lock:
                self._stats["watcher_errors"] += 1
        finally:
            self._watcher_active = False
            for watch in list(watches.values()):
                try:
                    observer.unschedule(watch)
                except Exception as cleanup_exc:
                    logger.debug("Filesystem watcher cleanup failed (%s)", type(cleanup_exc).__name__)
            watches.clear()
            try:
                observer.stop()
                observer.join(timeout=3.0)
            except Exception as cleanup_exc:
                logger.debug("Filesystem watcher stop failed (%s)", type(cleanup_exc).__name__)

    def _step(self, row: dict[str, Any]) -> bool:
        # An in-flight step finishes as its existing durable checkpoint boundary.
        # The next step observes mode again; active resumes from saved phase/cursor.
        if not self._background_work_allowed():
            return False
        root = str(row["root"])
        if not Path(root).is_dir():
            self.unregister(root, purge_data=True)
            return True
        if self._yield():
            return False
        phase = str(row.get("phase") or "inventory")
        self._set_project(root, status="running")
        optional_phase = {
            "code_index": ("call_graph", "deterministic"),
            "rag": ("rag", "files"),
            "modules": ("modules", "project"),
        }.get(phase)
        if optional_phase is not None:
            project_phase, next_phase = optional_phase
            if not self._project_phase_allowed(root, project_phase):
                if phase == "code_index" and self.code_index is not None:
                    prune_result = self.code_index.prune(root, [])
                    if not isinstance(prune_result, dict) or prune_result.get("success") is not True:
                        raise RuntimeError("code index cleanup failed")
                self._set_project(root, phase=next_phase)
                return True
        if phase == "inventory":
            return self._step_inventory(row)
        if phase == "hash":
            return self._step_hash(row)
        if phase == "rag":
            return self._step_rag(row)
        if phase == "lexical":
            return self._step_lexical(row)
        if phase == "code_index":
            return self._step_code_index(row)
        if phase == "deterministic":
            return self._step_deterministic(row)
        if phase == "serena":
            return self._step_external_index(row, "serena", "lexical")
        if phase == "files":
            return self._step_file_card(row)
        if phase == "modules":
            return self._step_module(row)
        if phase == "project":
            return self._step_project(row)
        if phase == "hot_queries":
            return self._step_hot_query(row)
        if phase == "diagnostics":
            return self._step_diagnostics(row)
        return self._step_complete(row)

    def _step_incremental_inventory(self, row: dict[str, Any], dirty_paths: set[str]) -> bool:
        """Apply watcher-confirmed path changes without rescanning the repository."""
        root = str(row["root"])
        base = Path(root)
        settings = self._project_settings(root)
        now = time.time()
        paths = sorted(set(str(x).replace("\\", "/") for x in dirty_paths if x))[:1024]
        if not paths:
            return False
        if any(Path(rel).name in {".local-ai.toml", ".local-ai.worktree.toml"} for rel in paths):
            # Policy changes can affect paths outside the dirty batch. Recompute full inventory.
            return False
        placeholders = ",".join("?" for _ in paths)
        with self._db_lock, closing(self._connect()) as con:
            old_rows = con.execute(
                f"SELECT path,content_hash,size,mtime_ns,card_key,rag_hash FROM file_refs WHERE root=? AND path IN ({placeholders})",
                (root, *paths),
            ).fetchall()
        old = {str(r["path"]): r for r in old_rows}

        manifest_names = {
            "package.json", "deno.json", "deno.jsonc", "pyproject.toml", "composer.json", "composer.lock", "package-lock.json", "pnpm-lock.yaml",
            "yarn.lock", "Cargo.toml", "Cargo.lock", "go.mod", "go.sum", "go.work", "pom.xml", "build.gradle", "build.gradle.kts",
            "requirements.txt", "Pipfile", "poetry.lock", "uv.lock", "Gemfile", "Gemfile.lock", "packages.lock.json", "global.json",
            "Directory.Build.props", "Directory.Build.targets", "Directory.Packages.props", "libs.versions.toml",
        }
        present: dict[str, tuple[int, int]] = {}
        deleted: set[str] = set()
        topology_changed = False
        for rel in paths:
            target = (base / rel).resolve(strict=False)
            try:
                target.relative_to(base)
            except ValueError:
                continue
            if target.is_file():
                try:
                    stat = target.stat()
                except OSError:
                    continue
                size, mtime_ns = int(stat.st_size), int(stat.st_mtime_ns)
                if size > int(getattr(self.repo_tools, "max_file_bytes", size)) or not self._project_path_allowed(
                    root, rel, settings, phase="preprocess", size_bytes=size
                ):
                    if rel in old:
                        deleted.add(rel)
                        topology_changed = True
                    continue
                present[rel] = (size, mtime_ns)
                topology_changed = topology_changed or rel not in old
            elif rel in old:
                deleted.add(rel)
                topology_changed = True

        if not present and not deleted:
            # Editors can emit transient create/delete events before the file is visible.
            # Keep the full periodic inventory as the fallback instead of spinning.
            return False

        # A watcher event is only a candidate change. Mutagen and some editors can
        # rewrite timestamps/metadata while preserving bytes, so verify content for
        # the coalesced batch before invalidating indexes or bumping generation.
        # Hash only those paths; building a full Git snapshot defeats incremental work.
        def _content_identity(rel: str) -> tuple[str, bool]:
            try:
                path = Path(root) / rel
                invalidate = getattr(self.repo_tools, "invalidate_snapshot", None)
                if callable(invalidate):
                    invalidate(path)
                digest = str(self.repo_tools._hash_file_only(path) or "")
            except Exception:
                digest = ""
            return digest, bool(digest)

        content_hashes: dict[str, str] = {}
        hash_ok: set[str] = set()
        for rel in sorted(present):
            digest, ok = _content_identity(rel)
            if ok:
                content_hashes[rel] = digest
                hash_ok.add(rel)

        content_changed = set(deleted)
        for rel in present:
            existing = old.get(rel)
            old_hash = str(existing["content_hash"] or "") if existing else ""
            if existing is None or rel not in hash_ok or content_hashes[rel] != old_hash:
                content_changed.add(rel)

        manifest_changed = any(Path(path).name in manifest_names for path in content_changed)
        changed_count = len(content_changed)
        major = topology_changed or manifest_changed or changed_count >= int(self.cfg.get("major_change_files", 60))
        if changed_count and not topology_changed:
            changed_ratio = changed_count / max(1, len(old))
            ratio_min_files = max(2, int(self.cfg.get("major_change_ratio_min_files", 12)))
            major = major or (changed_count >= ratio_min_files and changed_ratio >= float(self.cfg.get("major_change_ratio", 0.15)))
        generation = int(row.get("generation", 0)) + (1 if major else 0)

        def _apply(con: sqlite3.Connection) -> None:
            for rel in deleted:
                con.execute("DELETE FROM file_refs WHERE root=? AND path=?", (root, rel))
                con.execute("DELETE FROM source_index WHERE root=? AND path=?", (root, rel))
                con.execute("DELETE FROM source_fts WHERE root=? AND path=?", (root, rel))
            for rel in content_changed.difference(deleted):
                con.execute("DELETE FROM source_index WHERE root=? AND path=?", (root, rel))
                con.execute("DELETE FROM source_fts WHERE root=? AND path=?", (root, rel))
            for rel, (size, mtime_ns) in present.items():
                existing = old.get(rel)
                old_hash = str(existing["content_hash"] or "") if existing else ""
                old_rag_hash = str(existing["rag_hash"] or "") if existing else ""
                old_card = existing["card_key"] if existing else None
                digest = content_hashes.get(rel)
                content_same = bool(existing is not None and digest and digest == old_hash)
                stored_hash = digest or old_hash
                needs_hash = int(not digest)
                stored_card = old_card if content_same else None
                stored_rag_hash = old_rag_hash if content_same else None
                con.execute(
                    """INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,card_key,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(root,path) DO UPDATE SET
                       content_hash=excluded.content_hash,size=excluded.size,mtime_ns=excluded.mtime_ns,
                       needs_hash=excluded.needs_hash,rag_hash=excluded.rag_hash,generation=excluded.generation,
                       card_key=excluded.card_key,updated_at=excluded.updated_at""",
                    (root, rel, stored_hash, size, mtime_ns, needs_hash, stored_rag_hash, generation, stored_card, now),
                )
            if major:
                con.execute("DELETE FROM module_cards WHERE root=?", (root,))
                con.execute("DELETE FROM project_cards WHERE root=?", (root,))
                con.execute("DELETE FROM hot_query_state WHERE root=?", (root,))
                con.execute("DELETE FROM task_capsules WHERE root=?", (root,))
        self._write_retry(_apply)

        structural_hash = row.get("structural_hash")
        if topology_changed:
            with self._db_lock, closing(self._connect()) as con:
                all_paths = [str(r[0]) for r in con.execute("SELECT path FROM file_refs WHERE root=? ORDER BY path", (root,)).fetchall()]
            structural_hash = stable_hash({
                "structure": [(path, Path(path).suffix.lower()) for path in all_paths],
                "models": {k: self.config.get("models", {}).get(k) for k in ("fast_code", "heavy_code", "reasoning")},
                "analyzer": __version__,
                "project_config": getattr(self._project_config_context(root)[1], "config_digest", ""),
            })
        inventory_hash = stable_hash({"previous": row.get("inventory_hash"), "dirty": sorted(content_changed)})
        if not content_changed:
            interval = max(30, int(self.cfg.get("auto_recheck_seconds", 1800)))
            self._set_project(
                root, phase="complete", status="complete", force_refresh=0,
                next_check_at=now + interval, last_error=None, retry_after=0,
                inventory_hash=row.get("inventory_hash"), structural_hash=structural_hash,
                stats_json=json_dumps({
                    "changed_files": 0, "changed_paths": [], "major_change": False,
                    "incremental_watcher": True, "ignored_metadata_events": len(paths),
                }),
            )
            with self._stats_lock:
                self._stats["watcher_noop_events"] = self._stats.get("watcher_noop_events", 0) + len(paths)
                self._stats["watcher_incremental_runs"] = self._stats.get("watcher_incremental_runs", 0) + 1
                self._stats["watcher_incremental_files"] = self._stats.get("watcher_incremental_files", 0) + len(paths)
            return True
        self._set_project(
            root, phase="hash", status="running", generation=generation, force_refresh=0,
            inventory_hash=inventory_hash, structural_hash=structural_hash,
            last_error=None, retry_after=0,
            stats_json=json_dumps({
                "changed_files": len(content_changed), "changed_paths": sorted(content_changed)[:256], "major_change": major,
                "incremental_watcher": True,
            }),
        )
        if major:
            with self._stats_lock:
                self._stats["major_invalidations"] += 1
        with self._stats_lock:
            self._stats["watcher_incremental_runs"] = self._stats.get("watcher_incremental_runs", 0) + 1
            self._stats["watcher_incremental_files"] = self._stats.get("watcher_incremental_files", 0) + len(content_changed)
        return True

    def _step_inventory(self, row: dict[str, Any]) -> bool:
        root = str(row["root"])
        _api, project_context = self._project_config_context(root)
        settings = project_context.settings if project_context is not None else resolve_project_config(root).settings
        config_digest = str(getattr(project_context, "config_digest", ""))
        if not Path(root).exists():
            self.unregister(root, purge_data=True)
            return True
        dirty_paths = self._consume_dirty_paths(root)
        if dirty_paths and row.get("last_complete_at") and not bool(row.get("force_refresh")):
            if self._step_incremental_inventory(row, dirty_paths):
                return True
        # Metadata-only inventory: do not read/hash every file in one uninterruptible
        # pass. Content hashes are filled by the next checkpointed phase.
        inventory = self.repo_tools.file_inventory(root, include_hashes=False)
        if not inventory.get("success"):
            if not Path(root).exists():
                self.unregister(root, purge_data=True)
                return True
            raise RuntimeError(str(inventory.get("error", "inventory failed")))
        if self._yield():
            return False
        policy_api, project_context = self._project_config_context(root)
        inventory_files = {str(item["path"]): item for item in inventory.get("files", []) if item.get("path")}
        self._add_project_text_extensions(root, inventory_files, policy_api, project_context)
        new_files: dict[str, dict[str, Any]] = {}
        for item in inventory_files.values():
            relative = str(item.get("path") or "")
            if not relative:
                continue
            try:
                size = int(item.get("size", 0))
            except (TypeError, ValueError, OverflowError):
                continue
            if self._project_path_allowed(
                root, relative, settings, phase="preprocess", size_bytes=size
            ):
                new_files[relative] = item
        new_files.update(self._forced_preprocess_files(root, settings))
        with self._db_lock, closing(self._connect()) as con:
            old_rows = con.execute(
                "SELECT path,content_hash,size,mtime_ns,card_key,rag_hash FROM file_refs WHERE root=?", (root,)
            ).fetchall()
            old = {r["path"]: r for r in old_rows}
        changed = {
            path for path, item in new_files.items()
            if path not in old or int(old[path]["size"] or 0) != int(item.get("size", 0))
            or int(old[path]["mtime_ns"] or 0) != int(item.get("mtime_ns", 0))
        }
        deleted = set(old) - set(new_files)
        changed.update(deleted)
        changed_ratio = len(changed) / max(1, max(len(old), len(new_files)))
        manifest_names = {
            "package.json", "deno.json", "deno.jsonc", "pyproject.toml", "composer.json", "composer.lock", "package-lock.json", "pnpm-lock.yaml",
            "yarn.lock", "Cargo.toml", "Cargo.lock", "go.mod", "go.sum", "go.work", "pom.xml", "build.gradle", "build.gradle.kts",
            "requirements.txt", "Pipfile", "poetry.lock", "uv.lock", "Gemfile", "Gemfile.lock", "packages.lock.json", "global.json",
            "Directory.Build.props", "Directory.Build.targets", "Directory.Packages.props", "libs.versions.toml",
        }
        manifest_changed = any(Path(path).name in manifest_names for path in changed)
        # Structural identity is intentionally deterministic/cheap and independent
        # of local LLM output. Content-sensitive manifests are re-hashed next.
        structure = [(p, Path(p).suffix.lower()) for p, x in sorted(new_files.items())]
        structural_hash = stable_hash({
            "structure": structure,
            "models": {k: self.config.get("models", {}).get(k) for k in ("fast_code", "heavy_code", "reasoning")},
            "analyzer": __version__,
            "project_config": config_digest,
            "project_type": getattr(settings, "project_type", None),
            "solution_path": getattr(settings, "solution_path", None),
            "language_overrides": getattr(settings, "language_overrides", {}),
        })
        force = bool(row.get("force_refresh"))
        now = time.time()
        if (
            not changed
            and not force
            and row.get("last_complete_at")
            and row.get("structural_hash") == structural_hash
        ):
            with self._db_lock, closing(self._connect()) as con:
                uncarded = con.execute("SELECT COUNT(*) FROM file_refs WHERE root=? AND card_key IS NULL", (root,)).fetchone()[0]
                unragged = (
                    con.execute("SELECT COUNT(*) FROM file_refs WHERE root=? AND (rag_hash IS NULL OR rag_hash<>content_hash)", (root,)).fetchone()[0]
                    if self._project_phase_allowed(root, "rag")
                    else 0
                )
            if uncarded == 0 and unragged == 0:
                self._set_project(root, phase="complete", status="complete", force_refresh=0, next_check_at=now + float(self.cfg.get("auto_recheck_seconds", 1800)), updated_at=now)
                return True

        ratio_min_files = max(2, int(self.cfg.get("major_change_ratio_min_files", 12)))
        major = force or row.get("structural_hash") not in {None, structural_hash} or manifest_changed \
            or len(changed) >= int(self.cfg.get("major_change_files", 60)) \
            or (len(changed) >= ratio_min_files and changed_ratio >= float(self.cfg.get("major_change_ratio", 0.15)))
        generation = int(row.get("generation", 0)) + (1 if major else 0)
        try:
            git_hashes = self.repo_tools.git_blob_map(root)
        except Exception:
            git_hashes = {}
        with self._db_lock, closing(self._connect()) as con:
            for path in deleted:
                con.execute("DELETE FROM file_refs WHERE root=? AND path=?", (root, path))
                con.execute("DELETE FROM source_index WHERE root=? AND path=?", (root, path))
                con.execute("DELETE FROM source_fts WHERE root=? AND path=?", (root, path))
            for path, item in new_files.items():
                existing = old.get(path)
                stat_changed = force or path in changed
                old_hash = str(existing["content_hash"] or "") if existing else ""
                old_rag_hash = str(existing["rag_hash"] or "") if existing else ""
                old_card = existing["card_key"] if existing else None
                git_hash = str(git_hashes.get(path) or "")
                seeded_hash = git_hash or old_hash
                needs_hash = int(stat_changed and not git_hash)
                con.execute(
                    """INSERT INTO file_refs(root,path,content_hash,size,mtime_ns,needs_hash,rag_hash,generation,card_key,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(root,path) DO UPDATE SET
                       content_hash=excluded.content_hash,size=excluded.size,mtime_ns=excluded.mtime_ns,
                       needs_hash=excluded.needs_hash,rag_hash=excluded.rag_hash,generation=excluded.generation,
                       card_key=excluded.card_key,updated_at=excluded.updated_at""",
                    (
                        root, path, seeded_hash, int(item.get("size", 0)), int(item.get("mtime_ns", 0)), needs_hash,
                        old_rag_hash, generation, old_card, now,
                    ),
                )
            if major:
                con.execute("DELETE FROM module_cards WHERE root=?", (root,))
                con.execute("DELETE FROM project_cards WHERE root=?", (root,))
                con.execute("DELETE FROM hot_query_state WHERE root=?", (root,))
                con.execute("DELETE FROM task_capsules WHERE root=?", (root,))
            con.commit()
        self._link_content_reuse(root)
        if major:
            with self._stats_lock:
                self._stats["major_invalidations"] += 1
        inventory_hash = stable_hash([(p, int(x.get("size", 0)), int(x.get("mtime_ns", 0))) for p, x in sorted(new_files.items())])
        self._set_project(
            root, phase="hash", status="running", generation=generation, force_refresh=int(force),
            inventory_hash=inventory_hash, structural_hash=structural_hash,
            last_error=None, retry_after=0,
            stats_json=json_dumps({"changed_files": len(changed), "changed_paths": sorted(changed)[:256], "changed_ratio": round(changed_ratio, 4), "major_change": major, "incremental_watcher": False}),
        )
        return True

    def _link_content_reuse(self, root: str) -> None:
        """Link content-addressed cards and lexical text from other worktrees."""
        now = time.time()
        with self._db_lock, closing(self._connect()) as con:
            con.execute(
                """UPDATE file_refs
                   SET card_key = (
                       SELECT card_key FROM content_cards
                       WHERE content_cards.content_hash = file_refs.content_hash AND analyzer_version=?
                       LIMIT 1
                   )
                   WHERE root=? AND card_key IS NULL AND content_hash<>''
                     AND EXISTS (SELECT 1 FROM content_cards WHERE content_cards.content_hash = file_refs.content_hash AND analyzer_version=?)""",
                (__version__, root, __version__),
            )
            con.execute(
                """INSERT OR IGNORE INTO source_index(root, path, content_hash, text, updated_at)
                   SELECT ?, file_refs.path, file_refs.content_hash, other.text, ?
                   FROM file_refs
                   JOIN source_index AS other ON other.content_hash = file_refs.content_hash
                   WHERE file_refs.root = ? AND file_refs.content_hash <> ''
                     AND NOT EXISTS (SELECT 1 FROM source_index AS s WHERE s.root = ? AND s.path = file_refs.path)""",
                (root, now, root, root),
            )
            con.execute(
                """INSERT INTO source_fts(root, path, content)
                   SELECT s.root, s.path, s.path || char(10) || s.text
                   FROM source_index s
                   WHERE s.root = ? AND NOT EXISTS (SELECT 1 FROM source_fts f WHERE f.root = ? AND f.path = s.path)""",
                (root, root),
            )
            con.commit()

    def _step_hash(self, row: dict[str, Any]) -> bool:
        root = str(row["root"])
        limit = max(1, int(self.cfg.get("hash_files_per_step", 256)))
        hash_key = (root, int(row.get("generation", 0) or 0))
        with self._db_lock, closing(self._connect()) as con:
            pending = con.execute(
                "SELECT path,content_hash,rag_hash FROM file_refs WHERE root=? AND needs_hash=1 ORDER BY path LIMIT ?",
                (root, limit),
            ).fetchall()
        if not pending:
            with self._hash_git_maps_lock:
                self._hash_git_maps.pop(hash_key, None)
            self._set_project(root, phase="code_index")
            return True
        base = Path(root)
        with self._hash_git_maps_lock:
            git_hashes = self._hash_git_maps.get(hash_key)
        if git_hashes is None:
            git_hashes = self.repo_tools.git_blob_map(root)
            with self._hash_git_maps_lock:
                self._hash_git_maps[hash_key] = git_hashes
        def _hash_one(item: sqlite3.Row) -> tuple[str, str, bool]:
            rel = str(item["path"])
            path = (base / rel).resolve(strict=False)
            try:
                path.relative_to(base)
                digest = git_hashes.get(rel)
                if not digest:
                    invalidate = getattr(self.repo_tools, "invalidate_snapshot", None)
                    if callable(invalidate):
                        invalidate(path)
                    digest = self.repo_tools._hash_file_only(path)
            except Exception:
                digest = ""
            old_hash = str(item["content_hash"] or "")
            same = bool(digest and digest == old_hash)
            return rel, digest, same

        hashed_results = list(self._cpu_pool.map(_hash_one, pending))

        now = time.time()
        with self._db_lock, closing(self._connect()) as con:
            con.executemany(
                "UPDATE file_refs SET content_hash=?,needs_hash=0,card_key=CASE WHEN ? THEN card_key ELSE NULL END,updated_at=? WHERE root=? AND path=?",
                [(digest, int(same), now, root, rel) for rel, digest, same in hashed_results],
            )
            # Instantly link pre-existing content cards across branches/worktrees
            con.execute(
                """UPDATE file_refs
                   SET card_key = (
                       SELECT card_key FROM content_cards
                       WHERE content_cards.content_hash = file_refs.content_hash AND analyzer_version=?
                       LIMIT 1
                   )
                   WHERE root=? AND card_key IS NULL AND content_hash<>''
                     AND EXISTS (SELECT 1 FROM content_cards WHERE content_cards.content_hash = file_refs.content_hash AND analyzer_version=?)""",
                (__version__, root, __version__),
            )
            # Instantly link matching lexical source index across branches/worktrees
            con.execute(
                """INSERT OR IGNORE INTO source_index(root, path, content_hash, text, updated_at)
                   SELECT ?, file_refs.path, file_refs.content_hash, other.text, ?
                   FROM file_refs
                   JOIN source_index AS other ON other.content_hash = file_refs.content_hash
                   WHERE file_refs.root = ? AND file_refs.content_hash <> ''
                     AND NOT EXISTS (SELECT 1 FROM source_index AS s WHERE s.root = ? AND s.path = file_refs.path)""",
                (root, now, root, root),
            )
            con.execute(
                """INSERT INTO source_fts(root, path, content)
                   SELECT s.root, s.path, s.path || char(10) || s.text
                   FROM source_index s
                   WHERE s.root = ? AND NOT EXISTS (SELECT 1 FROM source_fts f WHERE f.root = ? AND f.path = s.path)""",
                (root, root),
            )
            # Do not mark RAG complete from another worktree. Each worktree has a
            # separate path namespace, so it still needs its own chunk rows. The
            # RAG step reuses global content-hash embeddings without re-embedding.
            con.commit()
        with self._stats_lock:
            self._stats["hashed_files"] = self._stats.get("hashed_files", 0) + len(hashed_results)
        self._record_progress(root, len(hashed_results))
        return True

    def _step_rag(self, row: dict[str, Any]) -> bool:
        if self._yield():
            return False
        root = str(row["root"])
        workspace = str(row["workspace"])
        limit = max(1, int(self.cfg.get("rag_files_per_step", 128)))
        with self._db_lock, closing(self._connect()) as con:
            pending = con.execute(
                """SELECT path,content_hash FROM file_refs
                   WHERE root=? AND needs_hash=0 AND content_hash<>''
                     AND COALESCE(rag_hash,'')<>content_hash
                   ORDER BY
                     -- Recently accessed files first (set by agent interactions)
                     (COALESCE(last_accessed_at, 0) > 0) DESC,
                     -- Entry-points and key architectural files
                     CASE
                       WHEN path LIKE '%/Controllers/%' THEN 0
                       WHEN path LIKE '%/Runtime/%'     THEN 0
                       WHEN path LIKE '%/Core/%'        THEN 0
                       WHEN path LIKE '%/Services/%'    THEN 0
                       WHEN path LIKE '%Main%'          THEN 0
                       WHEN path LIKE '%Bootstrap%'     THEN 0
                       WHEN path LIKE '%/Tests/%'       THEN 2
                       WHEN path LIKE '%/test/%'        THEN 2
                       WHEN path LIKE '%_test%'         THEN 2
                       WHEN path LIKE '%.test.%'        THEN 2
                       WHEN path LIKE '%/Generated/%'   THEN 3
                       ELSE 1
                     END ASC,
                     size ASC,
                     path ASC
                   LIMIT ?""",
                (root, limit),
            ).fetchall()
            all_paths = [str(r[0]) for r in con.execute("SELECT path FROM file_refs WHERE root=? ORDER BY path", (root,)).fetchall()]
        if not pending:
            deleted = self.rag.prune_missing(root, "__preprocess__", workspace, all_paths)
            if deleted:
                with self._stats_lock:
                    self._stats["rag_deleted_files"] = self._stats.get("rag_deleted_files", 0) + deleted
            self._set_project(root, phase="files")
            return True
        # Deterministically well-described declarative files do not need a
        # semantic vector index. Mark them synchronized and remove stale
        # RAG rows from older releases so they cannot pollute future retrieval.
        skipped: list[str] = []
        if self.deterministic is not None and bool(self.cfg.get("skip_rag_for_deterministic_declarative", True)):
            for item in pending:
                rel = str(item["path"])
                needed = bool(self.deterministic.semantic_needed(root, rel))
                if not needed:
                    skipped.append(rel)
        if skipped:
            self.rag.remove_paths("__preprocess__", workspace, skipped)
            now = time.time()
            with self._db_lock, closing(self._connect()) as con:
                con.executemany(
                    "UPDATE file_refs SET rag_hash=content_hash,updated_at=? WHERE root=? AND path=?",
                    [(now, root, rel) for rel in skipped],
                )
                con.commit()
            with self._stats_lock:
                self._stats["rag_skipped_files"] = self._stats.get("rag_skipped_files", 0) + len(skipped)

        needed_items = [p for p in pending if str(p["path"]) not in set(skipped)]
        if not needed_items:
            return True
        paths = [str(p["path"]) for p in needed_items]
        content_overrides: dict[str, str] = {}
        placeholders = ",".join("?" for _ in paths)
        with self._db_lock, closing(self._connect()) as con:
            rows = con.execute(
                f"SELECT path,text FROM source_index WHERE root=? AND path IN ({placeholders})",
                (root, *paths),
            ).fetchall()
        content_overrides.update({str(item["path"]): str(item["text"]) for item in rows})
        result = self.rag.index_paths_step(
            root, "__preprocess__", workspace, paths,
            should_yield=self._yield,
            content_overrides=content_overrides or None,
        )
        with self._stats_lock:
            self._stats["rag_steps"] += 1
        if result.get("preempted"):
            return False
        if not result.get("success"):
            raise RuntimeError(str(result.get("error", "RAG preprocessing failed")))
        processed = set(str(x) for x in result.get("processed_paths", []))
        # A watcher event can leave a deleted file_ref behind after the file has
        # disappeared. RAG intentionally ignores missing paths, so without this
        # cleanup the same pending path is selected forever and the phase spins.
        missing = [
            rel for rel in paths
            if not ((Path(root) / rel).resolve(strict=False)).is_file()
        ]
        if missing:
            self.rag.remove_paths("__preprocess__", workspace, missing)
            placeholders = ",".join("?" for _ in missing)
            with self._db_lock, closing(self._connect()) as con:
                con.execute(
                    f"DELETE FROM file_refs WHERE root=? AND path IN ({placeholders})",
                    (root, *missing),
                )
                con.execute(
                    f"DELETE FROM source_index WHERE root=? AND path IN ({placeholders})",
                    (root, *missing),
                )
                con.execute(
                    f"DELETE FROM source_fts WHERE root=? AND path IN ({placeholders})",
                    (root, *missing),
                )
                con.commit()
        if processed:
            now = time.time()
            with self._db_lock, closing(self._connect()) as con:
                con.executemany(
                    "UPDATE file_refs SET rag_hash=content_hash,updated_at=? WHERE root=? AND path=?",
                    [(now, root, rel) for rel in processed],
                )
                con.commit()
            self._record_progress(root, len(processed))
        return True

    def _find_lexical_pending(self, root: str, limit: int) -> list[sqlite3.Row]:
        with self._db_lock, closing(self._connect()) as con:
            return con.execute(
                """SELECT f.path,f.content_hash FROM file_refs f
                   LEFT JOIN source_index s ON s.root=f.root AND s.path=f.path AND s.content_hash=f.content_hash
                   WHERE f.root=? AND f.needs_hash=0 AND f.content_hash<>'' AND s.path IS NULL
                   ORDER BY f.path LIMIT ?""",
                (root, max(1, limit)),
            ).fetchall()

    def _step_lexical(self, row: dict[str, Any]) -> bool:
        root = str(row["root"])
        limit = max(1, int(self.cfg.get("lexical_files_per_step", 128)))
        pending = self._find_lexical_pending(root, limit)
        if not pending:
            # Defensive recovery for interrupted state: lexical indexing
            # must never spin on files whose content hash has not been reconciled.
            # Return to the checkpointed hash phase instead of indexing uncertain
            # bytes or advancing to semantic cards with an empty/stale hash.
            with self._db_lock, closing(self._connect()) as con:
                unhashed = int(con.execute(
                    "SELECT COUNT(*) FROM file_refs WHERE root=? AND (needs_hash=1 OR content_hash='')",
                    (root,),
                ).fetchone()[0])
            if unhashed:
                self._set_project(root, phase="hash")
                return True
            self._set_project(root, phase="rag")
            return True
        base = Path(root)
        def _lex_one(item: sqlite3.Row) -> tuple[str, str, str]:
            rel = str(item["path"])
            path = (base / rel).resolve(strict=False)
            path.relative_to(base)
            file_hash, lines = self.repo_tools._read_snapshot(path)
            text = "\n".join(lines)
            if self.deterministic is not None and bool(self.cfg.get("compact_lexical_for_deterministic_declarative", True)):
                try:
                    compact = self.deterministic.lexical_projection(
                        root, rel, int(self.cfg.get("deterministic_lexical_max_chars", 12000))
                    )
                    if compact is not None:
                        text = compact
                except sqlite3.Error as exc:
                    logger.warning("Deterministic lexical projection unavailable (%s)", type(exc).__name__)
            return rel, str(item["content_hash"]), text

        lex_results = list(self._cpu_pool.map(_lex_one, pending))

        now = time.time()
        with self._db_lock, closing(self._connect()) as con:
            con.executemany(
                "INSERT OR REPLACE INTO source_index(root,path,content_hash,text,updated_at) VALUES(?,?,?,?,?)",
                [(root, rel, chash, text, now) for rel, chash, text in lex_results],
            )
            for rel, _, text in lex_results:
                con.execute("DELETE FROM source_fts WHERE root=? AND path=?", (root, rel))
                # Include path in indexed content so filename/class/module searches
                # can narrow candidates without a full repository scan.
                con.execute("INSERT INTO source_fts(root,path,content) VALUES(?,?,?)", (root, rel, rel + "\n" + text))
            con.commit()
        with self._stats_lock:
            self._stats["lexical_files"] = self._stats.get("lexical_files", 0) + len(lex_results)
        self._record_progress(root, len(lex_results))
        return True

    def _prune_missing_file_refs(self, root: str) -> int:
        """Remove files deleted without a file-level watcher event."""
        base = Path(root)
        with self._db_lock, closing(self._connect()) as con:
            paths = [str(r[0]) for r in con.execute("SELECT path FROM file_refs WHERE root=?", (root,)).fetchall()]
        missing: list[str] = []
        for rel in paths:
            target = (base / rel).resolve(strict=False)
            try:
                target.relative_to(base)
                target.stat()
            except FileNotFoundError:
                missing.append(rel)
            except (NotADirectoryError, ValueError):
                missing.append(rel)
            except OSError:
                # Preserve paths that are temporarily inaccessible.
                continue
        if not missing:
            return 0

        def remove_refs(con: sqlite3.Connection) -> None:
            con.executemany("DELETE FROM file_refs WHERE root=? AND path=?", [(root, path) for path in missing])
            con.executemany("DELETE FROM source_index WHERE root=? AND path=?", [(root, path) for path in missing])
            con.executemany("DELETE FROM source_fts WHERE root=? AND path=?", [(root, path) for path in missing])
            con.execute("DELETE FROM module_cards WHERE root=?", (root,))
            con.execute("DELETE FROM project_cards WHERE root=?", (root,))
            con.execute("DELETE FROM hot_query_state WHERE root=?", (root,))
            con.execute("DELETE FROM task_capsules WHERE root=?", (root,))

        self._write_retry(remove_refs)
        for index in (self.code_index, self.deterministic):
            if index is None:
                continue
            try:
                with closing(index._connect()) as con:
                    for table in ("files", "symbols", "refs", "edges") if index is self.code_index else ("files", "facts"):
                        con.executemany(f"DELETE FROM {table} WHERE root=? AND path=?", [(root, path) for path in missing])
                    con.commit()
            except (sqlite3.Error, OSError) as exc:
                logger.warning("Could not prune deleted-file derived index (%s)", type(exc).__name__)
        with self._stats_lock:
            self._stats["missing_files_pruned"] = self._stats.get("missing_files_pruned", 0) + len(missing)
        return len(missing)

    def _step_code_index(self, row: dict[str, Any]) -> bool:
        root = str(row["root"])
        if self.code_index is None:
            self._set_project(root, phase="deterministic")
            return True
        limit = max(1, int(self.cfg.get("code_index_files_per_step", 256)))
        generation_key = (root, int(row.get("generation", 0) or 0))
        if generation_key not in self._missing_refs_checked_generations:
            self._prune_missing_file_refs(root)
            self._missing_refs_checked_generations.add(generation_key)
            self._missing_refs_checked_generations = self._bound_generation_set(self._missing_refs_checked_generations)
        with self._db_lock, closing(self._connect()) as con:
            refs = [
                (str(r["path"]), str(r["content_hash"]), int(r["size"] or 0))
                for r in con.execute(
                    "SELECT path,content_hash,size FROM file_refs WHERE root=? AND needs_hash=0 AND content_hash<>'' ORDER BY path",
                    (root,),
                ).fetchall()
            ]
        settings = self._project_settings(root)
        refs = [
            (path, digest)
            for path, digest, size_bytes in refs
            if not any(part.lower() in self.repo_tools.ignore_dirs for part in Path(path).parts[:-1])
            and self._project_path_allowed(
                root, path, settings, phase="call_graph", size_bytes=size_bytes,
            )
        ]
        pruned_generations = getattr(self, "_code_index_pruned_generations", set())
        if generation_key not in pruned_generations:
            prune_result = self.code_index.prune(root, [p for p,_ in refs])
            if not isinstance(prune_result, dict) or prune_result.get("success") is not True:
                raise RuntimeError("code index prune failed")
            pruned_generations.add(generation_key)
            self._code_index_pruned_generations = self._bound_generation_set(pruned_generations)
        try:
            select_pending = getattr(self.code_index, "files_needing_reindex", None)
            if callable(select_pending):
                pending = select_pending(root, refs)[:limit]
            else:
                with closing(self.code_index._connect()) as ci_con:
                    existing = dict(ci_con.execute("SELECT path, content_hash FROM files WHERE root=?", (root,)).fetchall())
                pending = [(p, h) for p, h in refs if existing.get(p) != h][:limit]
        except Exception:
            pending = refs[:limit]
        if not pending:
            self._set_project(root, phase="deterministic")
            return True

        try:
            result = self.code_index.update_files_batch(root, pending)
            progressed = int(result.get("files_processed", 0)) + int(result.get("cached", 0))
        except Exception:
            progressed = 0
            for p, digest in pending:
                try:
                    progressed += int(bool(self.code_index.update_file(root, p, digest).get("success")))
                except Exception as index_exc:
                    logger.warning("Code-index file update failed (%s)", type(index_exc).__name__)
        with self._stats_lock:
            self._stats["code_index_files"] += progressed
        self._record_progress(root, len(pending))
        return True

    @staticmethod
    def _bound_generation_set(s: set[tuple[str, int]], max_size: int = 512) -> set[tuple[str, int]]:
        if len(s) > max_size:
            return set(sorted(s, key=lambda item: item[1])[-max_size // 2:])
        return s

    def _step_deterministic(self, row: dict[str, Any]) -> bool:
        root = str(row["root"])
        if self.deterministic is None:
            self._set_project(root, phase="serena")
            return True
        limit = max(1, int(self.cfg.get("deterministic_files_per_step", 256)))
        generation_key = (root, int(row.get("generation", 0) or 0))
        if generation_key not in self._missing_refs_checked_generations:
            self._prune_missing_file_refs(root)
            self._missing_refs_checked_generations.add(generation_key)
            self._missing_refs_checked_generations = self._bound_generation_set(self._missing_refs_checked_generations)
        with self._db_lock, closing(self._connect()) as con:
            refs = [(str(r["path"]), str(r["content_hash"])) for r in con.execute(
                "SELECT path,content_hash FROM file_refs WHERE root=? AND needs_hash=0 AND content_hash<>'' ORDER BY path", (root,)
            ).fetchall()]
        generation_key = (root, int(row.get("generation", 0) or 0))
        pruned_generations = getattr(self, "_deterministic_pruned_generations", set())
        if generation_key not in pruned_generations:
            self.deterministic.prune(root, [p for p, _ in refs])
            pruned_generations.add(generation_key)
            self._deterministic_pruned_generations = self._bound_generation_set(pruned_generations)
        try:
            with closing(self.deterministic._connect()) as det_con:
                existing = dict(det_con.execute("SELECT path, content_hash FROM files WHERE root=?", (root,)).fetchall())
        except Exception:
            existing = {}
        pending = [(p, h) for p, h in refs if existing.get(p) != h][:limit]
        if not pending:
            try:
                self.deterministic.refresh_manifests(root)
            except Exception as index_exc:
                logger.warning("Deterministic manifest refresh failed (%s)", type(index_exc).__name__)
            try:
                self.deterministic.precompute_test_mappings(root)
            except Exception as index_exc:
                logger.warning("Deterministic test-map refresh failed (%s)", type(index_exc).__name__)
            try:
                self.deterministic.find_hotspots(root, days=30, limit=20)
            except Exception as index_exc:
                logger.warning("Deterministic hotspot refresh failed (%s)", type(index_exc).__name__)
            self._set_project(root, phase="serena")
            return True

        try:
            if hasattr(self.deterministic, "update_files_batch"):
                result = self.deterministic.update_files_batch(root, pending)
                progressed = int(result.get("updated", 0)) + int(result.get("cached", 0))
            else:
                raise AttributeError("batch API unavailable")
        except Exception:
            progressed = 0
            for p, digest in pending:
                try:
                    progressed += int(bool(self.deterministic.update_file(root, p, digest).get("success")))
                except Exception as index_exc:
                    logger.warning("Deterministic file update failed (%s)", type(index_exc).__name__)
        with self._stats_lock:
            self._stats["deterministic_files"] += progressed
        self._record_progress(root, len(pending))
        return True

    def _external_revision(self, root: str) -> str:
        with self._db_lock, closing(self._connect()) as con:
            rows = con.execute(
                "SELECT path,content_hash FROM file_refs WHERE root=? AND needs_hash=0 AND content_hash<>'' ORDER BY path",
                (root,),
            ).fetchall()
        return stable_hash([(str(row[0]), str(row[1])) for row in rows])

    def _step_external_index(self, row: dict[str, Any], backend: str, next_phase: str) -> bool:
        root = str(row["root"])
        intelligence_cfg = self.config.get("code_intelligence", {})
        enabled = bool(intelligence_cfg.get(f"preprocess_{backend}", True)) and bool(intelligence_cfg.get(f"{backend}_enabled", True))
        if self.external_tools is None or not enabled:
            self._set_project(root, phase=next_phase)
            return True
        # External language-server/graph indexing can be CPU/RAM intensive. Never
        # start it while foreground inference is active; this is a background phase.
        if not self.scheduler.background_allowed() or self.scheduler.foreground_busy():
            return False
        revision = self._external_revision(root)
        force_refresh = bool(row.get("force_refresh"))
        retry_count = 0
        with self._db_lock, closing(self._connect()) as con:
            state = con.execute(
                "SELECT revision_hash,status,error,retry_count,updated_at FROM external_index_state WHERE root=? AND backend=?",
                (root, backend),
            ).fetchone()
        if not force_refresh and state is not None and str(state[0]) == revision:
            prior_status = str(state[1])
            prior_error = str(state[2] or "")
            retry_count = max(0, int(state[3] or 0))
            permanent_error = self._external_error_is_revision_scoped(prior_error)
            if prior_status in {"ready", "skipped"} or permanent_error:
                if prior_status != "ready" and retry_count < 1 and self._external_backend_available(backend):
                    # A previous process may have timed out before the optional
                    # backend was installed/discovered. Retry it now instead of
                    # treating the old derived state as a permanent skip. Once
                    # that recovery attempt has failed, do not loop forever on
                    # the same unchanged revision.
                    pass
                else:
                    if prior_status not in {"unavailable"}:
                        with self._db_lock, closing(self._connect()) as con:
                            con.execute(
                                "UPDATE external_index_state SET status='unavailable' WHERE root=? AND backend=? AND revision_hash=?",
                                (root, backend, revision),
                            )
                            con.commit()
                    self._set_project(root, phase=next_phase)
                    return True
            if prior_status in {"degraded", "unavailable"} and retry_count > 0:
                elapsed = max(0.0, time.time() - float(state[4] or 0.0))
                if elapsed < self._external_retry_delay(retry_count):
                    # External indexes are optional; advance preprocessing while
                    # this revision's bounded transient retry is cooling down.
                    self._set_project(root, phase=next_phase)
                    self._record_progress(root, 1)
                    return True
        if not Path(root).is_dir():
            result = {"success": False, "skipped": True, "error": "project root is missing"}
        else:
            # Publish the active state before the potentially long subprocess so
            # the dashboard cannot display a stale prior failure as RUNNING.
            with self._db_lock, closing(self._connect()) as con:
                con.execute(
                    "INSERT OR REPLACE INTO external_index_state(root,backend,revision_hash,status,updated_at,error,retry_count) VALUES(?,?,?,?,?,?,?)",
                    (root, backend, revision, "running", time.time(), "", retry_count),
                )
                con.commit()
            try:
                result = self.external_tools.index(backend, root)
            except Exception as exc:
                # Optional external indexes must degrade to built-in preprocessing when
                # their client crashes, just like an explicit unsuccessful response.
                result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        if not isinstance(result, dict):
            result = {"success": False, "error": f"invalid {backend} index response"}
        success = bool(result.get("success"))
        unavailable = bool(result.get("skipped"))
        error = "" if success else str(result.get("error") or result.get("reason") or "index failed")[:1000]
        if not success and not unavailable and self._external_error_is_revision_scoped(error):
            unavailable = True
        status = "ready" if success else "unavailable" if unavailable else "degraded"
        with self._db_lock, closing(self._connect()) as con:
            con.execute(
                "INSERT OR REPLACE INTO external_index_state(root,backend,revision_hash,status,updated_at,error,retry_count) VALUES(?,?,?,?,?,?,?)",
                (root, backend, revision, status, time.time(), error, retry_count + 1),
            )
            con.commit()
        with self._stats_lock:
            if success:
                self._stats["external_indexes"] += 1
            elif not unavailable:
                self._stats["external_index_failures"] += 1
        # A missing/broken optional backend must never strand preprocessing. Its
        # circuit/status remains visible and the built-in indexes stay authoritative.
        self._set_project(root, phase=next_phase)
        self._record_progress(root, 1)
        return True

    def _external_backend_available(self, backend: str) -> bool:
        checker = getattr(self.external_tools, "backend_available", None)
        if not callable(checker):
            return False
        try:
            return bool(checker(backend))
        except Exception:
            return False

    @staticmethod
    def _external_error_is_revision_scoped(error: str) -> bool:
        """Errors a retry cannot fix until project revision or tool setup changes."""
        normalized = str(error).lower()
        return (
            "no associated project configuration" in normalized
            or "no configuration file found" in normalized
            or "project configuration auto-generation failed" in normalized
            or "project root is missing" in normalized
        )

    @staticmethod
    def _external_retry_delay(retry_count: int) -> float:
        """Exponential retry delay for transient optional-index failures, capped at 15m."""
        exponent = min(5, max(0, int(retry_count) - 1))
        return min(900.0, 30.0 * (2 ** exponent))

    def candidate_paths(self, root: str, query: str, limit: int = 32) -> list[str]:
        """Fast deterministic candidate selection; exact source verification happens later."""
        resolved = self._root(root)
        limit = max(0, min(int(limit), 64))
        if not limit:
            return []
        settings = self._project_settings(resolved)
        terms = self.repo_tools._terms(query)
        paths: list[str] = []
        if terms:
            expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms[:12])
            try:
                with self._db_lock, closing(self._connect()) as con:
                    rows = con.execute(
                        "SELECT path FROM source_fts WHERE root=? AND source_fts MATCH ? ORDER BY bm25(source_fts) LIMIT ?",
                        (resolved, expression, max(1, min(int(limit), 64))),
                    ).fetchall()
                paths.extend(str(r[0]) for r in rows)
            except sqlite3.OperationalError as fts_exc:
                logger.debug("Preprocessing FTS candidate search unavailable (%s)", type(fts_exc).__name__)
                pass
        # Semantic cards cover vocabulary mismatch and FTS-unavailable builds.
        try:
            cards = self.lookup(resolved, query, limit=max(5, min(int(limit), 16)))
            paths.extend(str(x.get("path")) for x in cards.get("files", []) if x.get("path"))
        except Exception as lookup_exc:
            logger.debug("Semantic card candidate lookup unavailable (%s)", type(lookup_exc).__name__)
            pass
        out: list[str] = []
        seen: set[str] = set()
        for path in paths:
            relative = str(path).replace("\\", "/")
            try:
                candidate = (Path(resolved) / relative).resolve(strict=True)
                candidate.relative_to(Path(resolved))
                if not candidate.is_file():
                    continue
                size = int(candidate.stat().st_size)
            except (OSError, RuntimeError, ValueError):
                continue
            relative = candidate.relative_to(Path(resolved)).as_posix()
            if relative not in seen and self._project_path_allowed(
                resolved, relative, settings, phase="search", size_bytes=size
            ):
                seen.add(relative)
                out.append(relative)
            if len(out) >= limit:
                break
        try:
            context = resolve_project_context(resolved, self.state_dir)
            usage = context.prioritize_paths(
                out,
                purpose="preprocess_search",
                scope="candidate_paths",
                repository_revision=self._external_revision(resolved),
            )
            out = list(usage.paths)
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
        return out[:limit]

    def _content_card_key(self, content_hash: str) -> str:
        return stable_hash({
            "app_version": __version__, "sha": content_hash,
                    "model": self.config.get("models", {}).get("background_code", "qwen2.5-coder:0.5b"),
        })

    def _find_next_files(self, root: str, limit: int) -> list[sqlite3.Row]:
        max_bytes = int(self.cfg.get("file_card_max_bytes", 180000))
        with self._db_lock, closing(self._connect()) as con:
            return con.execute(
                """SELECT * FROM file_refs
                   WHERE root=? AND card_key IS NULL AND size<=?
                   ORDER BY
                     (COALESCE(last_accessed_at, 0) > 0) DESC,
                     CASE
                       WHEN path LIKE '%/Controllers/%' THEN 0
                       WHEN path LIKE '%/Runtime/%'     THEN 0
                       WHEN path LIKE '%/Core/%'        THEN 0
                       WHEN path LIKE '%/Services/%'    THEN 0
                       WHEN path LIKE '%Main%'          THEN 0
                       WHEN path LIKE '%Bootstrap%'     THEN 0
                       WHEN path LIKE '%/Tests/%'       THEN 2
                       WHEN path LIKE '%/test/%'        THEN 2
                       WHEN path LIKE '%_test%'         THEN 2
                       WHEN path LIKE '%.test.%'        THEN 2
                       WHEN path LIKE '%/Generated/%'   THEN 3
                       ELSE 1
                     END ASC,
                     size ASC, path ASC
                   LIMIT ?""",
                (root, max_bytes, max(1, int(limit))),
            ).fetchall()

    def _find_next_file(self, root: str) -> sqlite3.Row | None:
        rows = self._find_next_files(root, 1)
        return rows[0] if rows else None

    def _store_file_card(self, root: str, item: sqlite3.Row, card_key: str, data: dict[str, Any], model: str) -> None:
        now = time.time()
        with self._db_lock, closing(self._connect()) as con:
            con.execute(
                "INSERT OR REPLACE INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,COALESCE((SELECT hits FROM content_cards WHERE card_key=?),0))",
                (card_key, str(item["content_hash"]), model, __version__, json_dumps(data, ensure_ascii=False), now, now, card_key),
            )
            con.execute("UPDATE file_refs SET card_key=?,updated_at=? WHERE root=? AND path=?", (card_key, now, root, item["path"]))
            con.commit()

    def _run_background_generate(self, model: str, prompt: str, system: str, schema: dict[str, Any], max_tokens: int, source: str) -> dict[str, Any]:
        from .operational_mode import load_operational_mode, operational_mode_gate_error

        state_dir = getattr(self, "state_dir", None) or self.config.get("server", {}).get("state_dir")
        if state_dir is not None:
            try:
                mode = load_operational_mode(state_dir)
            except Exception:
                mode = None
            rejection = operational_mode_gate_error(mode, "preprocess")
            if rejection is not None:
                return rejection
        if self._gpu_yield():
            return {"success": False, "preempted": True, "error": "foreground work pending"}

        # Local AI production path: a dedicated Ollama server owns the small background
        # model only after the foreground GPU has been idle long enough. Embeddings
        # and reranking never enter this path.
        if self.background_gpu is not None:
            result = self.background_gpu.generate(
                prompt=prompt, system=system, schema=schema, max_tokens=int(max_tokens), source=source
            )
            return result

        # Defensive fallback for tests/minimal embeddings that construct the
        # preprocessor without the Local AI idle GPU worker.
        def execute() -> dict[str, Any]:
            payload, _profile = self.services.model_policy.apply_payload(
                model,
                {
                    "model": model, "prompt": prompt, "system": system, "format": schema,
                    "keep_alive": self.config.get("ollama", {}).get("keep_alive", "-1"),
                    "options": {"num_predict": int(max_tokens), "temperature": 0.2},
                },
                role="background", input_tokens=max(1, (len(prompt) + len(system)) // 4),
                output_tokens=int(max_tokens), background=True, preserve_explicit_think=False,
            )
            # A queued scheduler closure must recheck mode at the runtime handoff.
            if state_dir is not None:
                try:
                    mode = load_operational_mode(state_dir)
                except Exception:
                    mode = None
                rejection = operational_mode_gate_error(mode, "preprocess")
                if rejection is not None:
                    return {
                        **rejection,
                        "preempted": True,
                        "error_code": "operational_mode_paused",
                    }
            response = self.runtime.request_interruptible(
                "/api/generate", payload, self.scheduler.foreground_busy,
                timeout=float(self.cfg.get("background_request_timeout_seconds", 300)),
            )
            if response.get("preempted"):
                return response
            if "error" in response:
                return {"success": False, "error": response["error"]}
            text = str(response.get("response", "")).strip()
            try:
                data = json.loads(text)
            except Exception:
                data = {"purpose": text[:1200], "symbols": [], "dependencies": [], "side_effects": [], "risks": [], "tests": [], "keywords": []}
            return {"success": True, "model": model, "data": data, "load_duration_ns": response.get("load_duration", 0)}

        try:
            return self.scheduler.submit(
                model, "__preprocess__", source, execute, priority=0,
                wait_timeout=float(self.cfg.get("background_scheduler_timeout_seconds", 120)), background=True,
            )
        except TimeoutError:
            return {"success": False, "preempted": True, "error": "background scheduler wait timed out"}

    def _step_file_card(self, row: dict[str, Any]) -> bool:
        root = str(row["root"])
        bg_cfg = self.config.get("background_gpu", {})
        batch_size = max(64, int(bg_cfg.get("file_batch_size", 64)))
        items = self._find_next_files(root, batch_size)
        if not items:
            with self._db_lock, closing(self._connect()) as con:
                oversized = con.execute("SELECT * FROM file_refs WHERE root=? AND card_key IS NULL", (root,)).fetchall()
                for item in oversized:
                    content_hash = str(item["content_hash"])
                    card_key = stable_hash({"app_version": __version__, "sha": content_hash, "source": "deterministic-oversized"})
                    data = {"purpose": "oversized source file", "symbols": [], "dependencies": [], "side_effects": [], "risks": [], "tests": [], "keywords": []}
                    con.execute(
                        "INSERT OR REPLACE INTO content_cards(card_key,content_hash,model,analyzer_version,card_json,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,0)",
                        (card_key, content_hash, "deterministic-oversized", __version__, json_dumps(data), time.time(), time.time()),
                    )
                    con.execute("UPDATE file_refs SET card_key=?,updated_at=? WHERE root=? AND path=?", (card_key, time.time(), root, item["path"]))
                con.commit()
            if str(row.get("phase")) == "files":
                self._set_project(root, phase="modules", force_refresh=0)
            return True

        background_model = str(self.config.get("models", {}).get("background_code", "qwen2.5-coder:0.5b"))
        pending_tasks: list[dict[str, Any]] = []
        pending_meta: list[tuple[sqlite3.Row, str]] = []
        progressed = False

        for item in items:
            content_hash = str(item["content_hash"])

            # 1. Instant global content-addressed cache hit across all branches & worktrees
            with self._db_lock, closing(self._connect()) as con:
                cached = con.execute(
                    "SELECT card_key, card_json FROM content_cards WHERE content_hash=? AND analyzer_version=? ORDER BY hits DESC LIMIT 1",
                    (content_hash, __version__),
                ).fetchone()
                if cached and not bool(row.get("force_refresh")):
                    cached_key = str(cached["card_key"])
                    con.execute("UPDATE content_cards SET hits=hits+1,accessed_at=? WHERE card_key=?", (time.time(), cached_key))
                    con.execute("UPDATE file_refs SET card_key=?,updated_at=? WHERE root=? AND path=?", (cached_key, time.time(), root, item["path"]))
                    con.commit()
                    with self._stats_lock:
                        self._stats["file_card_hits"] += 1
                    progressed = True
                    continue

            # 2. Deterministic AST/facts fallback
            if self.deterministic is not None and bool(self.cfg.get("prefer_deterministic_cards", True)):
                try:
                    det = self.deterministic.file_card(root, str(item["path"]))
                except Exception:
                    det = {"success": False}
                if det.get("success"):
                    card_key = stable_hash({"app_version": __version__, "sha": content_hash, "source": "deterministic"})
                    self._store_file_card(root, item, card_key, det.get("card", {}), "deterministic")
                    with self._stats_lock:
                        self._stats["deterministic_card_hits"] = self._stats.get("deterministic_card_hits", 0) + 1
                    progressed = True
                    continue

            if bool(self.cfg.get("disable_llm_card_synthesis", True)):
                # Skip slow local LLM card synthesis on unparsed files; store compact deterministic metadata
                data = {"purpose": f"source file ({Path(str(item['path'])).suffix})", "symbols": [], "dependencies": [], "side_effects": [], "risks": [], "tests": [], "keywords": [Path(str(item["path"])).stem]}
                card_key = stable_hash({"app_version": __version__, "sha": content_hash, "source": "deterministic-stub"})
                self._store_file_card(root, item, card_key, data, "deterministic-stub")
                progressed = True
                continue

            card_key = self._content_card_key(content_hash)

            slice_result = self.repo_tools.file_slice(
                root, str(item["path"]), 1, int(self.cfg.get("file_card_max_lines", 900)),
                int(self.cfg.get("file_card_max_chars", 18000)),
            )
            if not slice_result.get("success"):
                data = {"purpose": "unreadable/skipped", "symbols": [], "dependencies": [], "side_effects": [], "risks": [], "tests": [], "keywords": []}
                self._store_file_card(root, item, card_key, data, "deterministic-unreadable")
                progressed = True
                continue

            item_model = background_model

            # Diff-based update: if old card exists and fewer than 15% lines changed, use diff prompt
            old_card_text: str | None = None
            with self._db_lock, closing(self._connect()) as con:
                prev = con.execute(
                    "SELECT card_key, card_json FROM content_cards WHERE content_hash<>? AND analyzer_version=? AND card_key IN "
                    "(SELECT card_key FROM file_refs WHERE root=? AND path=?)",
                    (content_hash, __version__, root, str(item["path"])),
                ).fetchone()
                if prev:
                    old_card_text = str(prev[1])

            file_text = slice_result.get("text", "")
            if old_card_text:
                prompt_text = (
                    f"FILE: {item['path']}\n\nPREVIOUS SUMMARY:\n{old_card_text[:800]}\n\nCURRENT SOURCE:\n{file_text}"
                )
            else:
                prompt_text = f"FILE: {item['path']}\n\nSOURCE:\n{file_text}"

            pending_tasks.append({
                "prompt": prompt_text,
                "model": item_model,
                "system": "Build a dense reusable semantic card for this source file. Extract facts only. Do not explain or restate source. Keep strings short and useful for later repository search/reasoning.",
                "schema": CARD_SCHEMA,
                "max_tokens": int(self.cfg.get("file_card_output_tokens", 320)),
                "source": "preprocess:file-card",
            })
            pending_meta.append((item, card_key))

        if not pending_tasks:
            return progressed or True

        # Do not even start/lease the background GPU until the full foreground idle
        # grace is satisfied. This avoids pointless unload/reload churn between users.
        if self.background_gpu is not None:
            if not self.background_gpu.ready():
                return progressed
            results = self.background_gpu.generate_many(pending_tasks)
        else:
            results = [
                self._run_background_generate(background_model, t["prompt"], t["system"], t["schema"], int(t["max_tokens"]), str(t["source"]))
                for t in pending_tasks
            ]

        for (item, card_key), generated in zip(pending_meta, results):
            if generated.get("preempted"):
                continue
            if not generated.get("success"):
                fallback_data = {"purpose": f"generation error: {str(generated.get('error', ''))[:200]}", "symbols": [], "dependencies": [], "side_effects": [], "risks": [], "tests": [], "keywords": []}
                self._store_file_card(root, item, card_key, fallback_data, "fallback-error")
                progressed = True
                continue
            self._store_file_card(root, item, card_key, generated.get("data", {}), background_model)
            progressed = True
            with self._stats_lock:
                self._stats["file_card_generations"] = self._stats.get("file_card_generations", 0) + 1
            self._record_progress(root, 1)
        return progressed

    @staticmethod
    def _module_for(path: str) -> str:
        parts = path.replace("\\", "/").split("/")
        return parts[0] if len(parts) > 1 else "<root>"

    def _modules_needing_card(self, root: str) -> list[tuple[str, str, list[dict[str, Any]]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        with self._db_lock, closing(self._connect()) as con:
            rows = con.execute(
                """SELECT f.path,f.content_hash,f.card_key,c.card_json FROM file_refs f
                   LEFT JOIN content_cards c ON c.card_key=f.card_key WHERE f.root=? AND f.card_key IS NOT NULL ORDER BY f.path""",
                (root,),
            ).fetchall()
            existing = {r["module"]: r["revision_hash"] for r in con.execute("SELECT module,revision_hash FROM module_cards WHERE root=?", (root,)).fetchall()}
        for r in rows:
            module = self._module_for(str(r["path"]))
            try:
                card = json.loads(r["card_json"] or "{}")
            except Exception:
                card = {}
            groups.setdefault(module, []).append({"path": r["path"], "hash": r["content_hash"], "card": card})
        needed: list[tuple[str, str, list[dict[str, Any]]]] = []
        for module, cards in sorted(groups.items()):
            revision = stable_hash([(x["path"], x["hash"]) for x in cards])
            if existing.get(module) != revision:
                needed.append((module, revision, cards))
        return needed

    def _store_module_card(self, root: str, module: str, revision: str, module_data: dict[str, Any]) -> None:
        with self._db_lock, closing(self._connect()) as con:
            con.execute(
                "INSERT OR REPLACE INTO module_cards(root,module,revision_hash,card_json,updated_at) VALUES(?,?,?,?,?)",
                (root, module, revision, json_dumps(module_data, ensure_ascii=False), time.time()),
            )
            con.commit()

    def _step_module(self, row: dict[str, Any]) -> bool:
        root = str(row["root"])
        needed = self._modules_needing_card(root)
        if not needed:
            self._set_project(root, phase="project")
            return True

        bg_cfg = self.config.get("background_gpu", {})
        batch_size = max(1, int(bg_cfg.get("module_batch_size", bg_cfg.get("parallel", 4))))
        background_model = str(self.config.get("models", {}).get("background_code", "qwen2.5-coder:0.5b"))
        pending_tasks: list[dict[str, Any]] = []
        pending_meta: list[tuple[str, str]] = []
        progressed = False

        bg_ready = bool(self.background_gpu and self.background_gpu.ready())
        for module, revision, cards in needed[:batch_size]:
            compact_cards = [{"path": x["path"], "card": x["card"]} for x in cards[: int(self.cfg.get("module_max_files", 80))]]
            module_data = None
            if self.deterministic is not None and bool(self.cfg.get("prefer_deterministic_modules", True)):
                try:
                    det = self.deterministic.module_card(root, module, compact_cards)
                except Exception:
                    det = {"success": False}
                if det.get("success") and (float(det.get("confidence", 0.0)) >= float(self.cfg.get("deterministic_module_confidence", 0.75)) or not bg_ready):
                    module_data = det.get("card", {})
                    with self._stats_lock:
                        self._stats["deterministic_module_hits"] += 1
            if module_data is not None:
                self._store_module_card(root, module, revision, module_data)
                progressed = True
                continue

            llm_cards = [{"path": x["path"], **x["card"]} for x in cards[: int(self.cfg.get("module_max_files", 80))]]
            pending_tasks.append({
                "prompt": f"MODULE: {module}\nFILE CARDS:\n{json_dumps(llm_cards, ensure_ascii=False)[:30000]}",
                "system": "Synthesize a compact module card from supplied factual file cards. Do not invent code. Optimize for future debugging/refactor/navigation queries.",
                "schema": MODULE_SCHEMA,
                "max_tokens": int(self.cfg.get("module_output_tokens", 420)),
                "source": "preprocess:module",
            })
            pending_meta.append((module, revision))

        if not pending_tasks:
            return progressed or True
        if self.background_gpu is not None:
            if not self.background_gpu.ready():
                return False
            results = self.background_gpu.generate_many(pending_tasks)
        else:
            results = [
                self._run_background_generate(background_model, t["prompt"], t["system"], t["schema"], int(t["max_tokens"]), str(t["source"]))
                for t in pending_tasks
            ]

        preempted = False
        for (module, revision), generated in zip(pending_meta, results):
            if generated.get("preempted"):
                preempted = True
                continue
            if not generated.get("success"):
                fallback_data = {"summary": f"module generation error: {str(generated.get('error', ''))[:200]}", "responsibilities": [], "entry_points": [], "key_symbols": [], "dependencies": [], "tests": []}
                self._store_module_card(root, module, revision, fallback_data)
                progressed = True
                continue
            self._store_module_card(root, module, revision, generated.get("data", {}))
            progressed = True
            with self._stats_lock:
                self._stats["module_generations"] += 1
        return False if preempted else progressed

    def _step_project(self, row: dict[str, Any]) -> bool:
        root = str(row["root"])
        with self._db_lock, closing(self._connect()) as con:
            modules = con.execute("SELECT module,revision_hash,card_json FROM module_cards WHERE root=? ORDER BY module", (root,)).fetchall()
            current = con.execute("SELECT revision_hash FROM project_cards WHERE root=?", (root,)).fetchone()
        revision = stable_hash([(x["module"], x["revision_hash"]) for x in modules] + [("struct", row.get("structural_hash"))])
        if current and current["revision_hash"] == revision:
            self._set_project(root, phase="hot_queries")
            return True
        profile = self._project_profile(root, self.services.repo_profile(root))
        repo_map = self.services.repo_map(root, int(self.cfg.get("preprocess_symbol_sample", 300)))
        module_data = []
        for x in modules:
            try:
                module_data.append({"module": x["module"], **json.loads(x["card_json"] or "{}")})
            except (KeyError, json.JSONDecodeError, TypeError, ValueError) as card_exc:
                logger.warning("Malformed module card skipped (%s)", type(card_exc).__name__)
                pass
        project_data = None
        bg_ready = bool(self.background_gpu and self.background_gpu.ready())
        if self.deterministic is not None and bool(self.cfg.get("prefer_deterministic_project", True)):
            try:
                det = self.deterministic.project_card(root, profile, repo_map, module_data)
            except Exception:
                det = {"success": False}
            if det.get("success") and (float(det.get("confidence", 0.0)) >= float(self.cfg.get("deterministic_project_confidence", 0.75)) or not bg_ready):
                project_data = det.get("card", {})
                with self._stats_lock:
                    self._stats["deterministic_project_hits"] += 1
        if project_data is None:
            if self._gpu_yield():
                return False
            prompt = json_dumps({"profile": profile, "repo_map": repo_map, "modules": module_data}, ensure_ascii=False)[:40000]
            generated = self._run_background_generate(
                str(self.config.get("models", {}).get("background_code", "qwen2.5-coder:0.5b")), prompt,
                "Build a compact factual project navigation card. Optimize it for future coding agents: architecture, entry points, tests, config, data flow, security/concurrency hot spots and validation. Do not invent unseen facts.",
                PROJECT_SCHEMA, int(self.cfg.get("project_output_tokens", 650)), "preprocess:project",
            )
            if generated.get("preempted"):
                return False
            if not generated.get("success"):
                project_data = {"summary": f"project generation error: {str(generated.get('error', ''))[:200]}", "architecture": {}, "entry_points": [], "modules": module_data[:10], "tests": []}
            else:
                project_data = generated.get("data", {})
            with self._stats_lock:
                self._stats["project_generations"] += 1
        with self._db_lock, closing(self._connect()) as con:
            con.execute(
                "INSERT OR REPLACE INTO project_cards(root,revision_hash,card_json,updated_at) VALUES(?,?,?,?)",
                (root, revision, json_dumps(project_data, ensure_ascii=False), time.time()),
            )
            con.commit()
        self._set_project(root, phase="hot_queries")
        return True

    def _hot_queries(self) -> list[str]:
        configured = self.cfg.get("hot_queries")
        if isinstance(configured, list) and configured:
            return [str(x) for x in configured]
        return [
            "architecture entry points core modules dependencies",
            "tests validation lint static analysis build",
            "configuration environment startup bootstrap",
            "API routes controllers endpoints handlers",
            "database schema models persistence transactions",
            "authentication authorization permissions security",
            "errors exceptions retries recovery logging",
            "concurrency async threads locks queues background jobs",
        ]

    def _step_hot_query(self, row: dict[str, Any]) -> bool:
        root = str(row["root"])
        workspace = str(row["workspace"])
        revision = self.rag.revision("__preprocess__", workspace)
        queries = []
        if self.learner is not None:
            try:
                for q in self.learner.hot_queries(root, int(self.cfg.get("learned_hot_queries", 12))):
                    q_str = str(q).strip()
                    if q_str and len(q_str) <= 120 and len(q_str.split()) <= 15 and "\n" not in q_str:
                        queries.append(q_str)
            except Exception as learner_exc:
                logger.debug("Learned hot-query lookup unavailable (%s)", type(learner_exc).__name__)
                pass
        for q in self._hot_queries():
            if q not in queries:
                queries.append(q)
        with self._db_lock, closing(self._connect()) as con:
            existing = {r["query"]: r["revision_hash"] for r in con.execute("SELECT query,revision_hash FROM hot_query_state WHERE root=?", (root,)).fetchall()}
        query = next((q for q in queries if existing.get(q) != revision), None)
        if query is None:
            self._set_project(root, phase="diagnostics")
            return True
        if self._yield():
            return False
        # Local AI: do not spend embeddings/reranking on hot intents that parser/index facts
        # already answer with high confidence. The RAG path remains the fallback for
        # architecture/general intents that need semantic synthesis.
        det = {}
        if self.deterministic is not None:
            try:
                det = self.deterministic.query(root, query, limit=30)
            except Exception:
                det = {}
        deterministic_hot = bool(det.get("direct_answer")) and float(det.get("confidence", 0.0)) >= float(self.cfg.get("deterministic_hot_query_confidence", 0.94))
        graph = self.code_index.query(root, query, 20) if self.code_index is not None else {}
        pre = self.lookup(root, query, limit=4)
        if deterministic_hot:
            result = {"success": True, "results": [], "deterministic": True}
            paths = self.deterministic.related_paths(root, query, 8) if self.deterministic is not None else []
            evidence_ids = [str(x.get("evidence_id")) for x in det.get("evidence", []) if x.get("evidence_id")][:10]
            with self._stats_lock:
                self._stats["deterministic_hot_query_hits"] += 1
        else:
            use_reranker = bool(self.cfg.get("hot_query_use_reranker", False))
            result = self.rag.search(query, "__preprocess__", workspace, top_k=int(self.cfg.get("hot_query_top_k", 8)), use_reranker=use_reranker, priority=0)
            if not result.get("success"):
                raise RuntimeError(str(result.get("error", "hot query failed")))
            hybrid = self.services._hybrid_context(root, query, "__preprocess__", workspace, int(self.cfg.get("hot_context_tokens", 1800)))
            paths = [str(x.get("path")) for x in result.get("results", [])[:8] if x.get("path")]
            evidence_ids = [str(x.get("evidence_id")) for x in (hybrid.get("evidence", []) if isinstance(hybrid, dict) else []) if x.get("evidence_id")][:10]
        capsule = {
            "intent": query,
            "paths": paths,
            "evidence_ids": evidence_ids,
            "symbols": graph.get("symbols", [])[:12] if isinstance(graph, dict) else [],
            "references": graph.get("references", [])[:12] if isinstance(graph, dict) else [],
            "modules": pre.get("modules", [])[:3] if isinstance(pre, dict) else [],
            "deterministic": deterministic_hot,
        }
        with self._db_lock, closing(self._connect()) as con:
            con.execute(
                "INSERT OR REPLACE INTO hot_query_state(root,query,revision_hash,updated_at) VALUES(?,?,?,?)",
                (root, query, revision, time.time()),
            )
            con.execute(
                "INSERT OR REPLACE INTO task_capsules(root,query,revision_hash,capsule_json,updated_at) VALUES(?,?,?,?,?)",
                (root, query, revision, json_dumps(capsule, ensure_ascii=False), time.time()),
            )
            con.commit()
        with self._stats_lock:
            self._stats["hot_queries"] += 1
        return True

    def _step_diagnostics(self, row: dict[str, Any]) -> bool:
        root = str(row["root"])
        if not bool(self.cfg.get("idle_diagnostics_enabled", False)):
            completed_at = time.time()
            interval = max(30, int(self.cfg.get("auto_recheck_seconds", 1800)))
            self._set_project(root, phase="complete", status="complete", last_complete_at=completed_at, next_check_at=completed_at + interval, force_refresh=0)
            return True
        if self._gpu_yield() or not self.scheduler.background_allowed():
            return False

        profile = self._project_profile(root, self.services.repo_profile(root))
        validation_cmds = profile.get("validation_commands", [])
        if not validation_cmds:
            completed_at = time.time()
            interval = max(30, int(self.cfg.get("auto_recheck_seconds", 1800)))
            self._set_project(root, phase="complete", status="complete", last_complete_at=completed_at, next_check_at=completed_at + interval, force_refresh=0)
            return True

        cmd_info = validation_cmds[0]
        cmd_value = (
            cmd_info.get("argv", cmd_info.get("command"))
            if isinstance(cmd_info, dict)
            else cmd_info
        )
        cmd_str = (
            json_dumps(cmd_value)
            if isinstance(cmd_value, (list, tuple))
            else str(cmd_value or "")
        )
        if not cmd_value:
            completed_at = time.time()
            interval = max(30, int(self.cfg.get("auto_recheck_seconds", 1800)))
            self._set_project(root, phase="complete", status="complete", last_complete_at=completed_at, next_check_at=completed_at + interval, force_refresh=0)
            return True

        import subprocess
        from .process_utils import (
            ProcessCancelledError,
            hidden_run_kwargs,
            run_hidden,
        )
        cleanup_error: BaseException | None = None

        class _DiagnosticCancelEvent:
            def is_set(cancel_event_self) -> bool:
                return self._gpu_yield()

        try:
            if isinstance(cmd_value, (list, tuple)):
                argv = [str(value) for value in cmd_value]
            else:
                argv = shlex.split(cmd_str, posix=(os.name != "nt"))
                if os.name == "nt":
                    argv = [
                        value[1:-1]
                        if len(value) >= 2
                        and (
                            (value.startswith('"') and value.endswith('"'))
                            or (value.startswith("'") and value.endswith("'"))
                        )
                        else value
                        for value in argv
                    ]
            if not argv or not argv[0]:
                raise ValueError("diagnostic command must contain an executable")
            if os.name == "nt" and Path(argv[0]).suffix.casefold() in {".cmd", ".bat"}:
                raise ValueError(
                    "Windows batch files are not permitted as idle diagnostic commands"
                )
            completed = run_hidden(
                argv,
                shell=False,
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15.0,
                cancel_event=_DiagnosticCancelEvent(),
                **hidden_run_kwargs(),
            )
            stdout, stderr = completed.stdout or "", completed.stderr or ""
            exit_code = completed.returncode
            preview = (stderr or stdout or "")[:2000]
            error_count = preview.lower().count("error")
        except ProcessCancelledError as exc:
            if getattr(exc, "cleanup_confirmed", True):
                return False
            cleanup_error = exc
            exit_code = -1
            detail = "diagnostic process-tree cleanup could not be verified"
            output = str(getattr(exc, "stderr", None) or getattr(exc, "output", None) or "").strip()
            preview = f"{detail}: {output}"[:2000] if output else detail
            error_count = 1
        except subprocess.TimeoutExpired as exc:
            exit_code = -1
            if getattr(exc, "cleanup_confirmed", True) is False:
                cleanup_error = exc
                output = str(exc.stderr or exc.output or "").strip()
                detail = "diagnostic process-tree cleanup could not be verified"
                preview = f"{detail}: {output}"[:2000] if output else detail
            else:
                preview = "diagnostic timed out after 15s"
            error_count = 1
        except Exception as exc:
            exit_code = -1
            cleanup_unconfirmed = (
                getattr(exc, "cleanup_confirmed", True) is False
                or getattr(exc, "tree_termination_confirmed", True) is False
            )
            if cleanup_unconfirmed:
                cleanup_error = exc
                detail = "diagnostic process-tree cleanup could not be verified"
                output = str(getattr(exc, "stderr", None) or getattr(exc, "output", None) or "").strip()
                preview = f"{detail}: {output}"[:2000] if output else detail
            else:
                preview = f"diagnostic failed: {exc}"
            error_count = 1

        with self._db_lock, closing(self._connect()) as con:
            con.execute(
                "INSERT OR REPLACE INTO diagnostic_baselines(root, command, exit_code, error_count, stdout_preview, updated_at) VALUES(?, ?, ?, ?, ?, ?)",
                (root, cmd_str, exit_code, error_count, preview, time.time()),
            )
            con.commit()

        if cleanup_error is not None:
            raise cleanup_error

        completed_at = time.time()
        interval = max(30, int(self.cfg.get("auto_recheck_seconds", 1800)))
        self._set_project(root, phase="complete", status="complete", last_complete_at=completed_at, next_check_at=completed_at + interval, force_refresh=0)
        return True

    def _run_idle_database_maintenance(self) -> bool:
        """Run coarse derived-index maintenance from an existing idle worker turn."""
        now = time.time()
        maintenance_interval = max(300, int(self.cfg.get("db_maintenance_interval_seconds", 1800)))
        if now - self._last_db_maintenance < maintenance_interval or self._yield():
            return False
        try:
            with self._db_lock, closing(self._connect()) as con:
                # Prune orphan content cards not referenced by any active file and older than 30 days
                cutoff_30d = now - (30 * 86400)
                con.execute(
                    """DELETE FROM content_cards
                       WHERE accessed_at < ?
                         AND card_key NOT IN (SELECT DISTINCT card_key FROM file_refs WHERE card_key IS NOT NULL)""",
                    (cutoff_30d,),
                )
                con.execute("PRAGMA optimize")
                con.execute("PRAGMA wal_checkpoint(PASSIVE)")
                con.commit()
        except sqlite3.DatabaseError as maintenance_exc:
            logger.warning("Preprocessing database maintenance skipped (%s)", type(maintenance_exc).__name__)
        for component in (self.code_index, self.deterministic):
            try:
                if component is not None and hasattr(component, "optimize"):
                    component.optimize()
            except Exception as maintenance_exc:
                logger.debug("Derived-index optimization skipped (%s)", type(maintenance_exc).__name__)
        # cleanup_deleted_projects also performs the same bounded incremental vacuum.
        self.cleanup_deleted_projects()
        self.cleanup_orphaned_indexes()
        self._last_db_maintenance = now
        with self._stats_lock:
            self._stats["db_maintenance_runs"] = self._stats.get("db_maintenance_runs", 0) + 1
        return True

    def _step_complete(self, row: dict[str, Any]) -> bool:
        root = str(row["root"])
        max(30, int(self.cfg.get("auto_recheck_seconds", 1800)))
        now = time.time()
        self._run_idle_database_maintenance()
        self._set_project(
            root, status="queued", phase="inventory", next_check_at=now,
            last_error=None, retry_after=0,
        )
        return True

    def lookup(self, root: str, query: str, limit: int = 5) -> dict[str, Any]:
        """Return tiny precomputed context without scanning hundreds of cards in Python."""
        resolved = self._root(root)
        terms = set(self.repo_tools._terms(query))
        revision = self.context_revision(resolved)
        cache_key = stable_hash({"root": resolved, "query": " ".join(sorted(terms)) or str(query).lower().strip(), "limit": int(limit)})
        now = time.time()
        with self._lookup_cache_lock:
            cached = self._lookup_cache.get(cache_key)
            if cached and cached[1] == revision and now - cached[0] <= self._lookup_cache_ttl:
                return copy.deepcopy(cached[2])

        with self._db_lock, closing(self._connect()) as con:
            project_row = con.execute("SELECT card_json,revision_hash FROM project_cards WHERE root=?", (resolved,)).fetchone()
            module_rows = con.execute("SELECT module,card_json FROM module_cards WHERE root=?", (resolved,)).fetchall()
            # Let SQLite narrow candidate cards. This avoids JSON-decoding up to 800
            # cards for every local-model/tool request on a warm repository.
            term_list = list(sorted(terms))[:8]
            if term_list:
                clauses = []
                params: list[Any] = [resolved]
                for term in term_list:
                    clauses.append("(lower(f.path) LIKE ? OR lower(c.card_json) LIKE ?)")
                    needle = "%" + term.lower() + "%"
                    params.extend([needle, needle])
                params.append(max(40, min(160, int(self.cfg.get("lookup_candidate_cards", 120)))))
                file_rows = con.execute(
                    "SELECT f.path,c.card_json,c.card_key FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key WHERE f.root=? AND (" + " OR ".join(clauses) + ") ORDER BY f.last_accessed_at DESC,f.updated_at DESC LIMIT ?",
                    tuple(params),
                ).fetchall()
            else:
                file_rows = con.execute(
                    "SELECT f.path,c.card_json,c.card_key FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key WHERE f.root=? ORDER BY f.last_accessed_at DESC,f.updated_at DESC LIMIT ?",
                    (resolved, max(20, min(80, int(self.cfg.get("lookup_candidate_cards", 80))))),
                ).fetchall()
            capsule_rows = con.execute("SELECT query,capsule_json FROM task_capsules WHERE root=? ORDER BY updated_at DESC LIMIT 32", (resolved,)).fetchall()

        project: dict[str, Any] = {}
        if project_row:
            try:
                decoded_project = json.loads(project_row["card_json"] or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
                logger.debug(
                    "Skipping invalid preprocessing card (kind=project, error_type=%s)",
                    type(exc).__name__,
                )
            else:
                if isinstance(decoded_project, dict):
                    project = decoded_project
                else:
                    logger.debug(
                        "Skipping invalid preprocessing card (kind=project, value_type=%s)",
                        type(decoded_project).__name__,
                    )
        scored_modules: list[tuple[int, dict[str, Any]]] = []
        for row in module_rows:
            try:
                card = json.loads(row["card_json"] or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
                logger.debug(
                    "Skipping invalid preprocessing card (kind=module, error_type=%s)",
                    type(exc).__name__,
                )
                continue
            if not isinstance(card, dict):
                logger.debug(
                    "Skipping invalid preprocessing card (kind=module, value_type=%s)",
                    type(card).__name__,
                )
                continue
            blob = (str(row["module"]) + " " + json_dumps(card, ensure_ascii=False)).lower()
            score = sum(2 for t in terms if t in str(row["module"]).lower()) + sum(1 for t in terms if t in blob)
            scored_modules.append((score, {"module": row["module"], **card}))
        scored_modules.sort(key=lambda x: -x[0])
        scored_files: list[tuple[int, dict[str, Any]]] = []
        for row in file_rows:
            try:
                card = json.loads(row["card_json"] or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
                logger.debug(
                    "Skipping invalid preprocessing card (kind=file, error_type=%s)",
                    type(exc).__name__,
                )
                continue
            if not isinstance(card, dict):
                logger.debug(
                    "Skipping invalid preprocessing card (kind=file, value_type=%s)",
                    type(card).__name__,
                )
                continue
            blob = (str(row["path"]) + " " + json_dumps(card, ensure_ascii=False)).lower()
            score = sum(3 for t in terms if t in str(row["path"]).lower()) + sum(1 for t in terms if t in blob)
            if score or not terms:
                scored_files.append((score, {"path": row["path"], **card}))
        scored_files.sort(key=lambda x: (-x[0], x[1]["path"]))
        scored_capsules: list[tuple[int, dict[str, Any]]] = []
        for row in capsule_rows:
            try:
                capsule = json.loads(row["capsule_json"] or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
                logger.debug(
                    "Skipping invalid preprocessing card (kind=capsule, error_type=%s)",
                    type(exc).__name__,
                )
                continue
            if not isinstance(capsule, dict):
                logger.debug(
                    "Skipping invalid preprocessing card (kind=capsule, value_type=%s)",
                    type(capsule).__name__,
                )
                continue
            blob = (str(row["query"]) + " " + json_dumps(capsule, ensure_ascii=False)).lower()
            score = sum(3 for t in terms if t in str(row["query"]).lower()) + sum(1 for t in terms if t in blob)
            if score:
                scored_capsules.append((score, capsule))
        scored_capsules.sort(key=lambda x: -x[0])
        result = {
            "success": True, "root": resolved, "project": project,
            "modules": [x[1] for x in scored_modules[: max(1, min(limit, 4))] if x[0] > 0][:4],
            "files": [x[1] for x in scored_files[: max(1, limit)]],
            "capsules": [x[1] for x in scored_capsules[:2]],
            "preprocessed": bool(project_row or file_rows or capsule_rows),
            "context_revision": revision,
        }
        with self._lookup_cache_lock:
            if len(self._lookup_cache) >= 1024:
                oldest = min(self._lookup_cache.items(), key=lambda x: x[1][0])[0]
                self._lookup_cache.pop(oldest, None)
            self._lookup_cache[cache_key] = (now, revision, result)
        return copy.deepcopy(result)

    def compact_context(self, root: str, query: str, max_chars: int = 3500) -> str:
        found = self.lookup(root, query, limit=int(self.cfg.get("lookup_file_cards", 5)))
        if not found.get("preprocessed"):
            return ""
        payload = {
            "project": found.get("project", {}),
            "modules": found.get("modules", []),
            "files": found.get("files", []),
            "capsules": found.get("capsules", []),
        }
        text = json_dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return text[: max(256, int(max_chars))]

    def stats(self) -> dict[str, Any]:
        now_mono = time.monotonic()
        if not hasattr(self, "_stats_summary_cache"):
            self._stats_summary_cache = {}
        cached = self._stats_summary_cache.get("summary")
        if cached and now_mono - cached["time"] < 3.0:
            return dict(cached["data"])
        with self._stats_lock:
            stats = dict(self._stats)
        try:
            with closing(self._connect()) as con:
                projects = int(con.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
                active_projects = int(con.execute("SELECT COUNT(*) FROM projects WHERE paused=0").fetchone()[0])
                paused_projects = int(con.execute("SELECT COUNT(*) FROM projects WHERE paused=1").fetchone()[0])
                waiting_projects = int(con.execute("SELECT COUNT(*) FROM projects WHERE paused=0 AND status='waiting'").fetchone()[0])
                processing_projects = int(con.execute("SELECT COUNT(*) FROM projects WHERE paused=0 AND status IN ('queued','running','error') AND phase<>?", (self.PHASES[-1],)).fetchone()[0])
                cards = int(con.execute("SELECT COUNT(*) FROM content_cards").fetchone()[0])
                refs = int(con.execute("SELECT COUNT(*) FROM file_refs").fetchone()[0])
                modules = int(con.execute("SELECT COUNT(*) FROM module_cards").fetchone()[0])
                source_files = int(con.execute("SELECT COUNT(*) FROM source_index").fetchone()[0])
                capsules = int(con.execute("SELECT COUNT(*) FROM task_capsules").fetchone()[0])
            stats.update({"enabled": self.enabled, "paused": self._paused.is_set(), "projects": projects, "active_projects": active_projects, "processing_projects": processing_projects, "max_preprocessing_projects": self.max_preprocessing_projects, "waiting_projects": waiting_projects, "paused_projects": paused_projects, "content_cards": cards, "file_refs": refs, "module_cards": modules, "source_index_files": source_files, "task_capsules": capsules})
            self._stats_summary_cache["summary"] = {"time": now_mono, "data": stats}
            return stats
        except Exception:
            return stats

    def ensure_running(self) -> bool:
        if not self.enabled or self._stop.is_set():
            return False
        if self._cpu_thread is None or not self._cpu_thread.is_alive():
            self._cpu_thread = threading.Thread(target=self._cpu_loop, name="local-ai-preprocessor-cpu", daemon=True)
            self._cpu_thread.start()
        if self._gpu_thread is None or not self._gpu_thread.is_alive():
            self._gpu_thread = threading.Thread(target=self._gpu_loop, name="local-ai-preprocessor-gpu", daemon=True)
            self._gpu_thread.start()
        if bool(self.cfg.get("fs_watcher_enabled", True)) and (self._fs_watcher_thread is None or not self._fs_watcher_thread.is_alive()):
            self._fs_watcher_thread = threading.Thread(target=self._fs_watcher_loop, name="local-ai-fs-watcher", daemon=True)
            self._fs_watcher_thread.start()
            with self._stats_lock:
                self._stats["watcher_restarts"] += 1
        return True

    def close(self) -> None:
        self._stop.set()
        self._wake_all()
        for t in (self._cpu_thread, self._gpu_thread, self._fs_watcher_thread):
            if t and t.is_alive() and threading.current_thread() is not t:
                t.join(timeout=3.0)
        self._cpu_pool.shutdown(wait=False, cancel_futures=True)
