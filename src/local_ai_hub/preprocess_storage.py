from __future__ import annotations

import sqlite3
import threading
from typing import Any


class PreprocessStorageMixin:
    def _connect(self) -> sqlite3.Connection:
        from . import preprocess as services_module
        con = services_module.connect_sqlite(
            self.db_path,
            timeout_seconds=self._sqlite_busy_seconds,
            row_factory=services_module.sqlite3.Row,
        )
        try:
            con.execute("PRAGMA cache_size=-65536")
            con.execute("PRAGMA mmap_size=536870912")
        except services_module.sqlite3.OperationalError:
            pass
        return con

    @staticmethod
    def _is_locked_error(exc: BaseException) -> bool:
        from . import preprocess as services_module
        return services_module.is_busy_error(exc)

    def _write_retry(
        self,
        operation: Any,
        *,
        actor_timeout: float | None = None,
        best_effort: bool = False,
        actor_priority: int = 1,
    ) -> Any:
        from . import preprocess as services_module
        actor = getattr(self, "_write_actor", None)
        if actor is not None and actor.is_alive:
            if actor.is_current_thread():
                return actor.submit(operation, timeout=actor_timeout, priority=actor_priority)
            try:
                return actor.submit(operation, timeout=actor_timeout, priority=actor_priority)
            except services_module.WriteQueueTimeout as actor_exc:
                if best_effort:
                    raise
                raise services_module._RetryablePreprocessingError(
                    "preprocessing write queue is saturated",
                    retry_after_seconds=30.0,
                ) from actor_exc
            except Exception as actor_exc:
                if best_effort or not services_module.is_busy_error(actor_exc):
                    raise
        elif best_effort:
            raise TimeoutError("preprocessor write actor is unavailable")

        def attempt() -> Any:
            with self._db_lock, services_module.closing(self._connect()) as con:
                with services_module.write_transaction(con, max_duration_seconds=5.0, rollback_label="preprocessor state write"):
                    return operation(con)

        return services_module.retry_busy(
            attempt,
            retries=self._sqlite_write_retries,
            base_delay_seconds=0.015,
        )

    def _project_step_lock(self, root: str) -> threading.Lock:
        from . import preprocess as services_module
        with self._step_locks_guard:
            lock = self._step_locks.get(root)
            if lock is None:
                lock = services_module.threading.Lock()
                self._step_locks[root] = lock
            return lock

    def _run_project_step(self, row: dict[str, Any], *, exclusive_only: bool = False) -> bool | None:
        """Run one durable project step with a single in-process owner.

        ``None`` means another loop already owns this project. Callers should simply
        retry later; this is contention, not a foreground-yield or an error.
        """
        from . import preprocess as services_module
        if (self._paused.is_set() or not self._background_work_allowed()
                or (exclusive_only and not self._exclusive_mode_active())):
            return None
        root = str(row.get("root", ""))
        with self._step_locks_guard:
            lock = self._step_locks.setdefault(root, services_module.threading.Lock())
            acquired = lock.acquire(blocking=False)
        if not acquired:
            with self._stats_lock:
                self._stats["project_step_contention"] += 1
            return None
        try:
            current = self._project_row(root)
            if current is None:
                return None
            fresh = dict(current)
            if ((exclusive_only and not self._exclusive_mode_active())
                    or fresh.get("paused") or fresh.get("phase") != row.get("phase")
                    or fresh.get("status") not in {"queued", "running", "error", "complete"}
                    or (fresh.get("status") == "complete" and row.get("status") != "complete")
                    or float(fresh.get("retry_after") or 0) > services_module.time.time()):
                return None
            return self._step(fresh)
        finally:
            lock.release()

    def _forget_project_runtime(self, root: str) -> None:
        with self._db_lock:
            getattr(self, "_rag_batch_limits", {}).pop(root, None)
            getattr(self, "_rag_batch_successes", {}).pop(root, None)
            getattr(self, "_rag_inventory_digests", {}).pop(root, None)
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
        cache_lock = getattr(self, "_code_index_allowed_cache_lock", None)
        cache = getattr(self, "_code_index_allowed_cache", None)
        if cache_lock is not None and isinstance(cache, dict):
            with cache_lock:
                cache.pop(root, None)

    def _active_code_index_roots(self) -> tuple[str, ...] | None:
        """Snapshot roots currently owned by preprocessing workers for safe eviction."""
        from . import preprocess as services_module
        try:
            with self._db_lock, services_module.closing(self._connect()) as con:
                roots = [str(row[0]) for row in con.execute(
                    "SELECT root FROM projects WHERE status='running' ORDER BY root"
                ).fetchall()]
        except services_module.sqlite3.Error:
            return None
        return tuple(root for root in roots if root and services_module.Path(root).is_absolute())

    @staticmethod
    def _ensure_file_ref_centrality(con: sqlite3.Connection) -> None:
        """Upgrade a derived inventory without discarding its source identities."""
        from .sqlite_support import write_transaction

        def has_column() -> bool:
            return any(row[1] == "centrality_score" for row in con.execute("PRAGMA table_info(file_refs)"))

        if has_column():
            return
        # Recheck under the write lock for concurrent startup. Existing
        # inventories get a neutral priority, not a fabricated graph score.
        with write_transaction(con, rollback_label="preprocessor centrality schema"):
            if not has_column():
                con.execute("ALTER TABLE file_refs ADD COLUMN centrality_score REAL NOT NULL DEFAULT 0.0")

    def _init_db(self) -> None:
        from . import preprocess as services_module
        with self._db_lock, services_module.closing(self._connect()) as con:
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='source_fts'").fetchone() is not None:
                if not services_module.has_canonical_shared_fts(con):
                    raise services_module.sqlite3.DatabaseError(
                        "preprocess state requires the update-time lexical-index migration"
                    )
            # Set WAL once. The mode is persisted in the database header.
            try:
                services_module.initialize_wal(con)
            except services_module.sqlite3.OperationalError as exc:
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
                    centrality_score REAL NOT NULL DEFAULT 0.0,
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
                    text_origin TEXT NOT NULL DEFAULT 'unknown',
                    PRIMARY KEY(root,path)
                );
                CREATE INDEX IF NOT EXISTS idx_source_index_root_hash ON source_index(root,content_hash);
                CREATE INDEX IF NOT EXISTS idx_source_index_hash ON source_index(content_hash);
                CREATE TABLE IF NOT EXISTS content_lexical (
                    content_hash TEXT NOT NULL PRIMARY KEY,
                    text TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_content_lexical_updated ON content_lexical(updated_at,content_hash);
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
                CREATE TABLE IF NOT EXISTS file_card_enrichment (
                    content_hash TEXT NOT NULL,
                    model TEXT NOT NULL,
                    pipeline_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    retry_after REAL NOT NULL DEFAULT 0,
                    lease_until REAL NOT NULL DEFAULT 0,
                    claim_id TEXT,
                    last_error TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(content_hash,model,pipeline_version)
                );
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
                """
            )
            self._ensure_file_ref_centrality(con)
            services_module.initialize_fts_rows(con)
            services_module._ensure_file_refs_revision_tracking(con)
            con.commit()

    def _invalidate_rag_sync_state(self) -> None:
        from . import preprocess as services_module
        try:
            now = services_module.time.time()
            with self._db_lock, services_module.closing(self._connect()) as con:
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
        from . import preprocess as services_module
        try:
            with self._db_lock, services_module.closing(self._connect()) as con:
                rows = con.execute("SELECT root FROM projects").fetchall()
                for row in rows:
                    root = str(row["root"])
                    if self._is_internal_root(root) or self._is_ephemeral_root(root):
                        con.execute("DELETE FROM projects WHERE root=?", (root,))
                        con.execute("DELETE FROM file_refs WHERE root=?", (root,))
                        con.execute("DELETE FROM source_index WHERE root=?", (root,))
                        self._delete_fts_rows(con, "root=?", (root,))
                        con.execute("DELETE FROM module_cards WHERE root=?", (root,))
                        con.execute("DELETE FROM project_cards WHERE root=?", (root,))
                        con.execute("DELETE FROM hot_query_state WHERE root=?", (root,))
                        con.execute("DELETE FROM task_capsules WHERE root=?", (root,))
                        con.execute("DELETE FROM external_index_state WHERE root=?", (root,))
                        self._forget_project_runtime(root)
                    elif not services_module.Path(root).is_dir():
                        # Keep the durable root and file refs as the retry marker for
                        # cleanup_deleted_projects once the secondary indexes are ready.
                        con.execute(
                            "UPDATE projects SET status='error',paused=1,retry_after=0,"
                            "next_check_at=0,updated_at=? WHERE root=?",
                            (services_module.time.time(), root),
                        )
                con.execute("UPDATE projects SET status='queued' WHERE status='running'")
                self._rebalance_processing_slots(con)
                con.commit()
        except (services_module.sqlite3.Error, OSError, RuntimeError) as exc:
            # Registry repair is optional; keep startup available, but expose
            # expected storage/filesystem failures without leaking project paths.
            services_module.logger.warning("Preprocessing registry repair skipped (%s)", type(exc).__name__)

    def _recover_db(self) -> None:
        """Quarantine the derived preprocessing DB and rebuild it.

        Preprocessing is an acceleration layer, never a foreground correctness
        dependency, so corruption must degrade to a cold rebuild rather than fail startup.
        """
        from . import preprocess as services_module
        stamp = int(services_module.time.time())
        with self._db_lock:
            try:
                if self.db_path.exists():
                    self.db_path.replace(self.db_path.with_name(self.db_path.name + f".corrupt-{stamp}"))
                for suffix in ("-wal", "-shm"):
                    side = services_module.Path(str(self.db_path) + suffix)
                    if side.exists():
                        side.unlink()
            except OSError:
                pass
        self._init_db()

    def _project_row(self, root: str) -> sqlite3.Row | None:
        from . import preprocess as services_module
        with self._db_lock, services_module.closing(self._connect()) as con:
            return con.execute("SELECT * FROM projects WHERE root=?", (self._root(root),)).fetchone()

    def _project_settings(self, root: str) -> Any:
        from . import preprocess as services_module
        _api, context = self._project_config_context(root)
        return context.settings if context is not None else services_module.resolve_project_config(root).settings

    def _record_progress(self, root: str, count: int = 1) -> None:
        from . import preprocess as services_module
        now = services_module.time.time()
        with self._stats_lock:
            history = self._speed_tracker.setdefault(root, [])
            history.append((now, count))
            cutoff = now - 30.0
            self._speed_tracker[root] = [(t, c) for t, c in history if t >= cutoff]

    def _set_project(self, root: str, *, actor_priority: int | None = None, **values: Any) -> None:
        from . import preprocess as services_module
        if not values:
            return
        # Lifecycle writes jump ahead of queued background metadata writes.
        if actor_priority is None:
            actor_priority = 0 if "status" in values else 1
        root = self._root(root)
        complete_transition = values.get("status") == "complete" and values.get("phase") == "complete"
        dirty_before_complete = complete_transition and self._dirty_paths_pending(root)
        if dirty_before_complete:
            # A bounded watcher batch can leave more changed paths queued. Keep
            # the project runnable until they pass through dependent phases.
            values.update(status="queued", phase="inventory", next_check_at=0)
        values["updated_at"] = services_module.time.time()
        if not set(values) <= self._PROJECT_COLUMNS:
            bad = set(values) - self._PROJECT_COLUMNS
            raise ValueError(f"_set_project: invalid column(s): {bad}")
        columns = ",".join(f"{key}=?" for key in values)
        params = [*values.values(), root]
        self._write_retry(
            lambda con: con.execute(f"UPDATE projects SET {columns} WHERE root=?", params),
            actor_priority=actor_priority,
        )
        if complete_transition and not dirty_before_complete and self._dirty_paths_pending(root):
            # Close the race where an event arrives after the first in-memory
            # check but before the completion update reaches SQLite.
            now = services_module.time.time()
            self._write_retry(lambda con: con.execute(
                "UPDATE projects SET status='queued',phase='inventory',next_check_at=0,updated_at=? WHERE root=?",
                (now, root),
            ))
        if hasattr(self, "_status_cache"):
            self._status_cache.clear()

    def _mark_step_recovered(self, root: str) -> None:
        """Clear transient failure state after a preprocessing step succeeds or yields."""
        from . import preprocess as services_module
        current = self._project_row(root)
        if current is None:
            return
        try:
            stats = services_module.json.loads(str(current["stats_json"] or "{}"))
        except (TypeError, ValueError, services_module.json.JSONDecodeError):
            stats = {}
        if not isinstance(stats, dict):
            stats = {}
        stats.pop("consecutive_errors", None)
        self._set_project(
            root,
            last_error=None,
            retry_after=0,
            stats_json=services_module.json_dumps(stats, ensure_ascii=False, separators=(",", ":")),
        )

    def _run_idle_database_maintenance(self) -> bool:
        """Run coarse derived-index maintenance from an existing idle worker turn."""
        from . import preprocess as services_module
        now = services_module.time.time()
        configured_maintenance_interval = max(300, int(self.cfg.get("db_maintenance_interval_seconds", 1800)))
        retry_interval = getattr(self, "_db_maintenance_retry_interval", None)
        maintenance_interval = (
            min(configured_maintenance_interval, retry_interval)
            if type(retry_interval) is int and retry_interval >= 300
            else configured_maintenance_interval
        )
        if now - self._last_db_maintenance < maintenance_interval or self._yield():
            return False
        next_maintenance_interval = configured_maintenance_interval
        try:
            with self._db_lock, services_module.closing(self._connect()) as con:
                # Prune orphan content cards not referenced by any active file and older than 30 days
                cutoff_30d = now - (30 * 86400)
                con.execute(
                    """DELETE FROM content_cards
                       WHERE accessed_at < ?
                         AND card_key NOT IN (SELECT DISTINCT card_key FROM file_refs WHERE card_key IS NOT NULL)""",
                    (cutoff_30d,),
                )
                con.execute(
                    """DELETE FROM content_lexical WHERE content_hash IN (
                           SELECT c.content_hash FROM content_lexical c WHERE c.updated_at < ?
                             AND NOT EXISTS (SELECT 1 FROM source_index s
                                  WHERE s.content_hash=c.content_hash AND s.text_origin='source')
                           ORDER BY c.updated_at,c.content_hash LIMIT 256
                       )""",
                    (cutoff_30d,),
                )
                con.execute("PRAGMA optimize")
                # A checkpoint cannot run inside the DELETE's write transaction.
                # Commit pruning first so a busy checkpoint cannot roll it back.
                con.commit()
                con.execute("BEGIN IMMEDIATE")
                repair_cursor = self._repair_attached_file_cards(con, now)
                con.commit()
                self._file_card_repair_cursor = repair_cursor
                con.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except services_module.sqlite3.DatabaseError as maintenance_exc:
            services_module.logger.warning(
                "Preprocessing database maintenance skipped path=%s error_type=%s sqlite_error=%s error=%s",
                self.db_path, type(maintenance_exc).__name__,
                getattr(maintenance_exc, "sqlite_errorname", None), str(maintenance_exc),
            )
        for component in (self.code_index, self.deterministic, self.rag):
            try:
                if component is not None and hasattr(component, "optimize"):
                    component.optimize()
            except Exception as maintenance_exc:
                services_module.logger.debug("Derived-index optimization skipped (%s)", type(maintenance_exc).__name__)
        # Incremental vacuum can hold the code-index writer lock for seconds.
        # Keep it off the indexing path and run it only from this idle maintenance turn.
        enforce_budget = getattr(self.code_index, "enforce_size_limit", None)
        if callable(enforce_budget):
            try:
                with self._db_lock, services_module.closing(self._connect()) as con:
                    protected_roots = tuple(sorted(
                        str(row[0]) for row in con.execute(
                            "SELECT root FROM projects WHERE status='running'"
                        ).fetchall()
                    ))
                budget_result = enforce_budget(protected_roots=protected_roots, max_files=512)
                if not isinstance(budget_result, dict) or budget_result.get("success") is not True or budget_result.get("within_budget") is False:
                    next_maintenance_interval = min(maintenance_interval, 300)
                    services_module.logger.warning("Code-index size budget remains exceeded or could not be enforced")
            except Exception as maintenance_exc:
                services_module.logger.warning("Code-index size maintenance skipped (%s)", type(maintenance_exc).__name__)
        # cleanup_deleted_projects also performs the same bounded incremental vacuum.
        self.cleanup_deleted_projects()
        self.cleanup_orphaned_indexes()
        try:
            from .sqlite_support import clean_quarantined_files
            clean_quarantined_files(self.state_dir, max_age_seconds=86400 * 7)
        except Exception as clean_exc:
            services_module.logger.debug("Quarantined file cleanup skipped (%s)", type(clean_exc).__name__)
        self._last_db_maintenance = now
        self._db_maintenance_retry_interval = (
            next_maintenance_interval
            if next_maintenance_interval < configured_maintenance_interval
            else None
        )
        with self._stats_lock:
            self._stats["db_maintenance_runs"] = self._stats.get("db_maintenance_runs", 0) + 1
        return True

    def lookup(self, root: str, query: str, limit: int = 5) -> dict[str, Any]:
        """Return tiny precomputed context without scanning hundreds of cards in Python."""
        from . import preprocess as services_module
        resolved = self._root(root)
        terms = set(self.repo_tools._terms(query))
        revision = self.context_revision(resolved)
        cache_key = services_module.stable_hash({"root": resolved, "query": " ".join(sorted(terms)) or str(query).lower().strip(), "limit": int(limit)})
        now = services_module.time.time()
        with self._lookup_cache_lock:
            cached = self._lookup_cache.get(cache_key)
            if cached and cached[1] == revision and now - cached[0] <= self._lookup_cache_ttl:
                return services_module.copy.deepcopy(cached[2])

        with self._db_lock, services_module.closing(self._connect()) as con:
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
                decoded_project = services_module.json.loads(project_row["card_json"] or "{}")
            except (services_module.json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
                services_module.logger.debug(
                    "Skipping invalid preprocessing card (kind=project, error_type=%s)",
                    type(exc).__name__,
                )
            else:
                if isinstance(decoded_project, dict):
                    project = decoded_project
                else:
                    services_module.logger.debug(
                        "Skipping invalid preprocessing card (kind=project, value_type=%s)",
                        type(decoded_project).__name__,
                    )
        modules: list[tuple[str, str, dict[str, Any]]] = []
        for row in module_rows:
            try:
                card = services_module.json.loads(row["card_json"] or "{}")
            except (services_module.json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
                services_module.logger.debug(
                    "Skipping invalid preprocessing card (kind=module, error_type=%s)",
                    type(exc).__name__,
                )
                continue
            if not isinstance(card, dict):
                services_module.logger.debug(
                    "Skipping invalid preprocessing card (kind=module, value_type=%s)",
                    type(card).__name__,
                )
                continue
            name = str(row["module"]).lower()
            blob = name + " " + services_module.json_dumps(card, ensure_ascii=False).lower()
            modules.append((name, blob, {"module": row["module"], **card}))
        scored_files: list[tuple[int, dict[str, Any]]] = []
        for row in file_rows:
            try:
                card = services_module.json.loads(row["card_json"] or "{}")
            except (services_module.json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
                services_module.logger.debug(
                    "Skipping invalid preprocessing card (kind=file, error_type=%s)",
                    type(exc).__name__,
                )
                continue
            if not isinstance(card, dict):
                services_module.logger.debug(
                    "Skipping invalid preprocessing card (kind=file, value_type=%s)",
                    type(card).__name__,
                )
                continue
            blob = (str(row["path"]) + " " + services_module.json_dumps(card, ensure_ascii=False)).lower()
            score = sum(3 for t in terms if t in str(row["path"]).lower()) + sum(1 for t in terms if t in blob)
            if score or not terms:
                scored_files.append((score, {"path": row["path"], **card}))
        scored_files.sort(key=lambda x: (-x[0], x[1]["path"]))
        scored_capsules: list[tuple[int, dict[str, Any]]] = []
        for row in capsule_rows:
            try:
                capsule = services_module.json.loads(row["capsule_json"] or "{}")
            except (services_module.json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
                services_module.logger.debug(
                    "Skipping invalid preprocessing card (kind=capsule, error_type=%s)",
                    type(exc).__name__,
                )
                continue
            if not isinstance(capsule, dict):
                services_module.logger.debug(
                    "Skipping invalid preprocessing card (kind=capsule, value_type=%s)",
                    type(capsule).__name__,
                )
                continue
            capsule_query = str(row["query"])
            capsule["modules"] = self._matching_module_cards(
                modules, set(self.repo_tools._terms(capsule_query)), 3,
            )
            blob = (capsule_query + " " + services_module.json_dumps(capsule, ensure_ascii=False)).lower()
            score = sum(3 for t in terms if t in str(row["query"]).lower()) + sum(1 for t in terms if t in blob)
            if score:
                scored_capsules.append((score, capsule))
        scored_capsules.sort(key=lambda x: -x[0])
        result = {
            "success": True, "root": resolved, "project": project,
            "modules": self._matching_module_cards(modules, terms, max(1, min(limit, 4))),
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
        return services_module.copy.deepcopy(result)

    def compact_context(self, root: str, query: str, max_chars: int = 3500) -> str:
        from . import preprocess as services_module
        found = self.lookup(root, query, limit=int(self.cfg.get("lookup_file_cards", 5)))
        if not found.get("preprocessed"):
            return ""
        payload = {
            "project": found.get("project", {}),
            "modules": found.get("modules", []),
            "files": found.get("files", []),
            "capsules": found.get("capsules", []),
        }
        text = services_module.json_dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return text[: max(256, int(max_chars))]

    def stats(self) -> dict[str, Any]:
        from . import preprocess as services_module
        now_mono = services_module.time.monotonic()
        if not hasattr(self, "_stats_summary_cache"):
            self._stats_summary_cache = {}
        cached = self._stats_summary_cache.get("summary")
        if cached and now_mono - cached["time"] < 3.0:
            return dict(cached["data"])
        with self._stats_lock:
            stats = dict(self._stats)
        try:
            with services_module.closing(self._connect()) as con:
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
            stats.update({"enabled": self.enabled, "paused": self._paused.is_set(), "projects": projects, "active_projects": active_projects, "processing_projects": processing_projects, "max_preprocessing_projects": self._project_limit(), "waiting_projects": waiting_projects, "paused_projects": paused_projects, "content_cards": cards, "file_refs": refs, "module_cards": modules, "source_index_files": source_files, "task_capsules": capsules})
            self._stats_summary_cache["summary"] = {"time": now_mono, "data": stats}
            return stats
        except Exception:
            return stats
