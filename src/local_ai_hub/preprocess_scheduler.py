from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .preprocess import ProjectPreprocessor


class PreprocessSchedulerMixin:
    @staticmethod
    def _scheduler_order(now: float) -> tuple[str, tuple[float, ...]]:
        """Share bounded age, activity, and phase ordering across workers."""
        return (
            """CASE WHEN status='queued' AND last_requested_at>=? THEN 0 ELSE 1 END,
               CASE WHEN status='queued' AND last_requested_at>=? THEN last_requested_at END DESC,
               CASE WHEN updated_at<=? THEN 0 ELSE 1 END,
               CASE WHEN updated_at<=? AND last_requested_at>=? THEN 0 ELSE 1 END,
               CASE WHEN updated_at<=? AND last_requested_at>=? THEN last_requested_at END DESC,
               CASE WHEN last_requested_at>=? THEN 0 ELSE 1 END,
               CASE phase
                   WHEN 'inventory' THEN 0 WHEN 'hash' THEN 1
                   WHEN 'code_index' THEN 2 WHEN 'deterministic' THEN 3
                   WHEN 'lexical' THEN 4 WHEN 'rag' THEN 5
                   WHEN 'files' THEN 6 WHEN 'serena' THEN 7
                   WHEN 'serena_optional' THEN 8 WHEN 'modules' THEN 9
                   WHEN 'project' THEN 10 WHEN 'hot_queries' THEN 11
                   WHEN 'file_card_enrichment' THEN 12
                   WHEN 'diagnostics' THEN 13 ELSE 14 END,
               force_refresh DESC,
               CASE WHEN last_requested_at>=? THEN 0 ELSE 1 END,
               updated_at-CASE WHEN last_requested_at>=? THEN 60 ELSE 0 END ASC,
               CASE status WHEN 'queued' THEN 0 WHEN 'running' THEN 1 ELSE 2 END,
               root ASC""",
            (now - 300.0, now - 300.0, now - 300.0, now - 300.0,
             now - 300.0, now - 300.0, now - 300.0, now - 86_400.0,
             now - 60.0, now - 300.0),
        )

    def _next_cpu_project(self, *, rebalance: bool = True) -> sqlite3.Row | None:
        from . import preprocess as services_module
        now = services_module.time.time()
        order_sql, order_params = self._scheduler_order(now)
        watcher_active = bool(getattr(self, "_watcher_active", False))
        if rebalance:
            try:
                self._write_retry(
                    self._rebalance_processing_slots,
                    actor_timeout=0.25,
                    actor_priority=0,
                )
            except (TimeoutError, services_module._RetryablePreprocessingError):
                # Slot bookkeeping is advisory; a busy writer must not stall selection.
                pass
        # Auto-recover projects paused by legacy embedding_space_rebuild_required (NEW-001)
        with self._db_lock, services_module.closing(self._connect()) as con:
            recovered_count = con.execute(
                "UPDATE projects SET paused=0, status='queued', last_error=NULL, retry_after=0 "
                "WHERE last_error='embedding_space_rebuild_required' AND paused=1"
            ).rowcount
            if recovered_count > 0:
                con.commit()
                services_module.logger.info("Auto-recovered %d projects paused by embedding_space_rebuild_required", recovered_count)

        with self._db_lock, services_module.closing(self._connect()) as con:
            rows = con.execute(
                """SELECT * FROM projects
                   WHERE paused=0 AND retry_after<=?
                     AND status IN ('queued','running','error')
                     AND phase IN ('inventory', 'hash', 'code_index', 'deterministic', 'serena', 'lexical', 'rag', 'files', 'serena_optional', 'file_card_enrichment', 'modules', 'project', 'hot_queries', 'diagnostics')
                   ORDER BY """ + order_sql + " LIMIT ?",
                (now, *order_params, self._project_limit()),
            ).fetchall()
            if rows:
                return self._first_unowned_project(rows)
            processing = int(con.execute(
                "SELECT COUNT(*) FROM projects WHERE paused=0 AND status IN ('queued','running','error') AND phase<>?",
                (self.PHASES[-1],),
            ).fetchone()[0] or 0)
            if processing >= self._project_limit():
                return None
            # A healthy filesystem watcher queues only changed paths. Avoid waking
            # completed projects into a full-tree inventory while that signal is
            # available. Still reconcile completed RAG indexes on their existing
            # recheck cadence; chunk-store loss does not produce filesystem events.
            if not watcher_active:
                # Periodic inventory remains the fallback when watching is
                # disabled or unavailable.
                return con.execute(
                    """SELECT * FROM projects
                       WHERE paused=0 AND next_check_at<=? AND retry_after<=?
                         AND status='complete' AND phase='complete'
                       ORDER BY next_check_at ASC LIMIT 1""",
                    (now, now),
                ).fetchone()
        return self._reconcile_completed_rag_index(now)

    def _reconcile_completed_rag_index(self, now: float) -> sqlite3.Row | None:
        """Requeue only completed projects whose chunk rows disappeared."""
        from . import preprocess as services_module
        if self.rag is None:
            return None
        with self._db_lock, services_module.closing(self._connect()) as con:
            project = con.execute(
                """SELECT root,workspace,generation,next_check_at
                   FROM projects
                   WHERE paused=0 AND retry_after<=? AND next_check_at<=?
                     AND status='complete' AND phase='complete'
                   ORDER BY next_check_at ASC,root ASC LIMIT 1""",
                (now, now),
            ).fetchone()
        if project is None:
            return None

        try:
            return self._reconcile_completed_rag_candidate(project, now)
        except Exception as exc:
            interval = max(30, int(self.cfg.get("auto_recheck_seconds", 1800)))
            retry_at = now + min(300, interval)
            try:
                with self._db_lock, services_module.closing(self._connect()) as con:
                    con.execute(
                        """UPDATE projects SET next_check_at=?,updated_at=?
                           WHERE root=? AND generation=? AND status='complete' AND phase='complete'
                             AND paused=0 AND next_check_at=?""",
                        (
                            retry_at, services_module.time.time(), str(project["root"]),
                            int(project["generation"]), float(project["next_check_at"]),
                        ),
                    )
                    con.commit()
            except Exception as defer_exc:
                services_module.logger.error(
                    "Completed RAG integrity retry scheduling failed (root=%s error=%s)",
                    project["root"], type(defer_exc).__name__,
                )
            services_module.logger.warning(
                "Completed RAG integrity check deferred (root=%s error=%s)",
                project["root"], type(exc).__name__,
            )
            return None

    def _reconcile_completed_rag_candidate(
        self, project: sqlite3.Row, now: float,
    ) -> sqlite3.Row | None:
        from . import preprocess as services_module
        root = str(project["root"])
        workspace = str(project["workspace"])
        generation = int(project["generation"])
        checked_at = float(project["next_check_at"])
        semantic_rows: list[services_module.sqlite3.Row] = []
        rag_allowed = self._project_phase_allowed(root, "rag")
        if rag_allowed:
            with self._db_lock, services_module.closing(self._connect()) as con:
                semantic_rows = con.execute(
                    """SELECT path,content_hash FROM file_refs
                       WHERE root=? AND needs_hash=0 AND content_hash<>''
                       ORDER BY path""",
                    (root,),
                ).fetchall()
        skip_declarative = (
            self.deterministic is not None
            and bool(self.cfg.get("skip_rag_for_deterministic_declarative", True))
        )
        semantic_rows = [
            item for item in semantic_rows
            if not skip_declarative or self.deterministic.semantic_needed(root, str(item["path"]))
        ]
        semantic_paths = [str(item["path"]) for item in semantic_rows]
        if rag_allowed:
            indexed_paths = self.rag.indexed_paths(workspace=workspace, paths=semantic_paths)
            if not isinstance(indexed_paths, set):
                raise RuntimeError("RAG indexed-path check returned an invalid result")
            indexed_file_paths = indexed_paths.intersection(semantic_paths)
            indexed_chunk_paths = self.rag.indexed_chunk_paths(
                workspace=workspace, paths=sorted(indexed_file_paths),
            ) if indexed_file_paths else set()
            if not isinstance(indexed_chunk_paths, set):
                raise RuntimeError("RAG indexed-chunk check returned an invalid result")
        else:
            indexed_paths = set()
            indexed_file_paths = set()
            indexed_chunk_paths = set()
        hashes = {str(item["path"]): str(item["content_hash"]) for item in semantic_rows}
        missing_paths = [path for path in semantic_paths if path not in indexed_paths]
        missing_paths.extend(
            path for path in sorted(indexed_file_paths - indexed_chunk_paths)
            if self._completed_rag_path_has_content(root, path)
        )
        interval = max(30, int(self.cfg.get("auto_recheck_seconds", 1800)))
        updated_at = services_module.time.time()

        with self._db_lock, services_module.closing(self._connect()) as con:
            if missing_paths:
                cur = con.execute(
                    """UPDATE projects SET status='queued',phase='rag',next_check_at=0,updated_at=?
                       WHERE root=? AND generation=? AND status='complete' AND phase='complete'
                         AND paused=0 AND retry_after<=? AND next_check_at=?""",
                    (updated_at, root, generation, now, checked_at),
                )
                if cur.rowcount != 1:
                    return None
                con.executemany(
                    """UPDATE file_refs SET rag_hash=NULL,updated_at=?
                       WHERE root=? AND path=? AND content_hash=? AND needs_hash=0""",
                    [(updated_at, root, path, hashes[path]) for path in missing_paths],
                )
                con.commit()
                return con.execute("SELECT * FROM projects WHERE root=?", (root,)).fetchone()

            con.execute(
                """UPDATE projects SET next_check_at=?,updated_at=?
                   WHERE root=? AND generation=? AND status='complete' AND phase='complete'
                     AND paused=0 AND retry_after<=? AND next_check_at=?""",
                (now + interval, updated_at, root, generation, now, checked_at),
            )
            con.commit()
        return None

    @staticmethod
    def _completed_rag_path_has_content(root: str, relative_path: str) -> bool:
        """Distinguish lost chunks from indexed empty/whitespace-only files."""
        from . import preprocess as services_module
        root_path = services_module.Path(root).resolve(strict=True)
        relative = services_module.PureWindowsPath(relative_path)
        parts = relative.parts
        if relative.is_absolute() or relative.drive or not parts or any(
            part in {"", ".", ".."} for part in parts
        ):
            raise ValueError("RAG integrity path must stay relative to its project root")

        candidate = root_path
        try:
            for part in parts:
                candidate = candidate / part
                info = services_module.os.lstat(candidate)
                if services_module.stat.S_ISLNK(info.st_mode) or (
                    getattr(info, "st_file_attributes", 0)
                    & getattr(services_module.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                ):
                    raise ValueError("RAG integrity path cannot traverse symlinks or junctions")
        except FileNotFoundError:
            return True
        if not services_module.stat.S_ISREG(info.st_mode):
            return True
        with candidate.open("r", encoding="utf-8", errors="replace") as stream:
            for text in iter(lambda: stream.read(64 * 1024), ""):
                if text.strip():
                    return True
        return False

    def _next_gpu_project(self) -> sqlite3.Row | None:
        from . import preprocess as services_module
        now = services_module.time.time()
        order_sql, order_params = self._scheduler_order(now)
        self._write_retry(self._rebalance_processing_slots, actor_priority=0)
        with self._db_lock, services_module.closing(self._connect()) as con:
            # GPU-bound phases: files, modules, project, hot_queries
            rows = con.execute(
                """SELECT * FROM projects
                   WHERE paused=0 AND retry_after<=? AND status IN ('queued','running','error')
                     AND phase IN ('inventory', 'hash', 'code_index', 'deterministic', 'serena', 'lexical', 'rag', 'files', 'serena_optional', 'file_card_enrichment', 'modules', 'project', 'hot_queries', 'diagnostics')
                   ORDER BY """ + order_sql + " LIMIT ?",
                (now, *order_params, self._project_limit()),
            ).fetchall()
            if rows:
                preferred_phase = str(rows[0]["phase"])
                gpu_phases = {"files", "file_card_enrichment", "modules", "project", "hot_queries"}
                if preferred_phase not in gpu_phases:
                    return None
                # A project already owned by a CPU worker is unavailable to this
                # worker. Select another admitted root in the same preferred
                # phase, while keeping later GPU phases behind it.
                same_phase = [row for row in rows if str(row["phase"]) == preferred_phase]
                return self._first_unowned_project(same_phase)

            # Completed projects can predate model enrichment. Schedule only roots
            # with eligible provisional cards, through the ordinary bounded GPU
            # worker path, without replaying inventory or unrelated phases.
            if not self._file_card_enrichment_enabled():
                return None
            active = int(con.execute(
                """SELECT COUNT(*) FROM projects WHERE paused=0
                   AND status IN ('queued','running','error') AND phase<>?""",
                (self.PHASES[-1],),
            ).fetchone()[0] or 0)
            if active >= self._project_limit():
                return None
            model = self._configured_preprocessing_model()
            pipeline = self._file_card_pipeline_version()
            max_bytes = int(self.cfg.get("file_card_max_bytes", 180000))
            legacy = con.execute(
                """SELECT p.root FROM projects p
                   WHERE p.paused=0 AND p.retry_after<=? AND p.status='complete' AND p.phase='complete'
                     AND EXISTS (
                       SELECT 1 FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key
                       WHERE f.root=p.root AND f.size<=?
                         AND c.model IN ('deterministic','deterministic-stub','deterministic-barrel')
                         AND NOT EXISTS (
                           SELECT 1 FROM file_card_enrichment e
                           WHERE e.content_hash=f.content_hash AND e.model=? AND e.pipeline_version=?
                             AND ((e.status='running' AND e.lease_until>?)
                                  OR (e.status='failed' AND (e.attempts>=3 OR e.retry_after>?)))
                         )
                     )
                   ORDER BY p.next_check_at ASC,p.updated_at ASC LIMIT 1""",
                (now, max_bytes, model, pipeline, now, now),
            ).fetchone()
            if legacy is None:
                return None
            root = str(legacy[0])
            con.execute(
                """UPDATE projects SET status='queued',phase='file_card_enrichment',
                   next_check_at=0,updated_at=? WHERE root=? AND status='complete' AND phase='complete'""",
                (now, root),
            )
            self._rebalance_processing_slots(con, preferred_root=root)
            con.commit()
            return con.execute("SELECT * FROM projects WHERE root=?", (root,)).fetchone()

    def _record_failure_telemetry(self, current: sqlite3.Row | dict[str, Any] | None, error: Exception) -> None:
        """Keep telemetry callback failures separate from project recovery."""
        from . import preprocess as services_module
        if self.telemetry is None:
            return
        try:
            # sqlite3.Row supports indexing and keys(), but has no dict.get().
            raw_phase = current["phase"] if current is not None else "step"
        except (KeyError, IndexError, TypeError):
            raw_phase = "step"
        phase = str(raw_phase or "step")
        if phase not in {"inventory", "files", "modules", "project", "hot_queries", "rag", "complete"}:
            phase = "step"
        try:
            error_code = getattr(error, "error_code", "")
            error_code_fields = (
                {"error_code_override": error_code}
                if isinstance(error_code, str) and error_code else {}
            )
            self.telemetry.record_error(
                "preprocess", phase, error,
                retryable=getattr(error, "retryable", True) is not False,
                recovered=False,
                **error_code_fields,
            )
        except Exception as telemetry_exc:
            # Metadata only: no exception message, repository path or payload.
            fingerprint = services_module.stable_hash(f"preprocess:{phase}:{type(telemetry_exc).__name__}")[:20]
            with self._stats_lock:
                self._stats["lost_error_count"] = self._stats.get("lost_error_count", 0) + 1
            services_module.logger.warning(
                "Preprocessing telemetry write failed (phase=%s type=%s fingerprint=%s)",
                phase, type(telemetry_exc).__name__, fingerprint,
            )

    def _cpu_loop(self, worker_index: int = 0) -> None:
        from . import preprocess as services_module
        services_module.set_current_thread_priority(self.cpu_priority)
        startup_delay = max(0.0, float(self.cfg.get("startup_delay_seconds", 2.0)))
        if startup_delay > 0:
            self._stop.wait(startup_delay)
        poll = max(0.2, float(self.cfg.get("poll_seconds", 1.0)))
        while not self._stop.is_set():
            with self._stats_lock:
                self._stats["loops"] += 1
            if worker_index and not self._exclusive_mode_active():
                self._cpu_wakeup.wait(poll)
                self._cpu_wakeup.clear()
                continue
            if self._paused.is_set():
                self._cpu_wakeup.wait(poll)
                self._cpu_wakeup.clear()
                continue
            if not self._background_work_allowed():
                self._cpu_wakeup.wait(min(0.1, poll))
                self._cpu_wakeup.clear()
                continue
            if not self.cpu_runs_during_foreground and not self._scheduler_background_allowed():
                # Foreground activity interrupts every project's recovery streak
                # even when the scheduler defers the step before _step_rag runs.
                with self._db_lock:
                    getattr(self, "_rag_batch_successes", {}).clear()
                self._cpu_wakeup.wait(poll)
                self._cpu_wakeup.clear()
                continue
            try:
                row = self._next_cpu_project(rebalance=worker_index == 0)
            except services_module._RetryablePreprocessingError as exc:
                services_module.logger.warning("CPU preprocessing project selection deferred (%s)", type(exc).__name__)
                with self._stats_lock:
                    self._stats["yields"] += 1
                self._stop.wait(min(300.0, max(1.0, float(exc.retry_after_seconds))))
                self._cpu_wakeup.clear()
                continue
            except TimeoutError as exc:
                services_module.logger.warning("CPU preprocessing project selection timed out (%s)", type(exc).__name__)
                self._cpu_wakeup.wait(poll)
                self._cpu_wakeup.clear()
                continue
            except Exception as exc:
                if not self._is_locked_error(exc):
                    raise
                with self._stats_lock:
                    self._stats["yields"] += 1
                self._cpu_wakeup.wait(min(0.5, poll))
                self._cpu_wakeup.clear()
                continue
            if row is None:
                self._run_idle_database_maintenance()
                self._cpu_wakeup.wait(poll)
                self._cpu_wakeup.clear()
                continue
            root = str(row["root"])
            try:
                progressed = (self._run_project_step(dict(row), exclusive_only=True) if worker_index
                              else self._run_project_step(dict(row)))
                if progressed is None:
                    self._cpu_wakeup.wait(min(0.1, poll))
                    self._cpu_wakeup.clear()
                    continue
                self._mark_step_recovered(root)
                if progressed:
                    with self._stats_lock:
                        self._stats["steps"] += 1
                    worker_sleep = max(0.0, float(self.cfg.get("cpu_worker_sleep_seconds", 0.0)))
                    if worker_sleep > 0 and not self._exclusive_mode_active():
                        self._stop.wait(worker_sleep)
                else:
                    with self._stats_lock:
                        self._stats["yields"] += 1
                    self.scheduler.note_background_yield()
                    self._stop.wait(min(0.5, poll))
            except services_module._RetryablePreprocessingError as exc:
                with self._stats_lock:
                    self._stats["yields"] += 1
                try:
                    delay = min(300.0, max(1.0, float(exc.retry_after_seconds)))
                    self._set_project(
                        root,
                        status="waiting",
                        last_error=str(exc)[:1000],
                        retry_after=services_module.time.time() + delay,
                        actor_priority=0,
                    )
                except Exception as record_exc:
                    services_module.logger.error("Could not record deferred preprocessing state (%s)", type(record_exc).__name__)
                    self._stop.wait(min(0.5, poll))
            except Exception as exc:
                with self._stats_lock:
                    self._stats["errors"] += 1
                current = None
                try:
                    current = self._project_row(root)
                    prev = 0
                    if current:
                        try:
                            saved_stats = services_module.json.loads(current["stats_json"] or "{}")
                            if isinstance(saved_stats, dict):
                                prev = int(saved_stats.get("consecutive_errors", 0))
                        except (services_module.json.JSONDecodeError, TypeError, ValueError) as stats_exc:
                            services_module.logger.warning("Preprocessing error counter reset (%s)", type(stats_exc).__name__)
                    errors = prev + 1
                    retryable = getattr(exc, "retryable", True) is not False
                    backoff = min(float(self.cfg.get("max_error_backoff_seconds", 300)), 2 ** min(errors, 8))
                    self._set_project(
                        root,
                        status="error",
                        paused=not retryable,
                        last_error=str(exc)[:1000],
                        retry_after=services_module.time.time() + backoff if retryable else 0,
                        stats_json=services_module.json_dumps({"consecutive_errors": errors}),
                        actor_priority=0,
                    )
                except Exception:
                    services_module.logger.exception(
                        "Could not record preprocessing failure state for root %s after %s: %s",
                        root,
                        type(exc).__name__,
                        exc,
                    )
                    self._stop.wait(min(0.5, poll))
                finally:
                    self._record_failure_telemetry(current, exc)

    def _gpu_loop(self) -> None:
        from . import preprocess as services_module
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
            try:
                row = self._next_gpu_project()
            except TimeoutError as exc:
                services_module.logger.warning("GPU preprocessing project selection timed out (%s)", type(exc).__name__)
                self._gpu_wakeup.wait(poll)
                self._gpu_wakeup.clear()
                continue
            except Exception as exc:
                if not self._is_locked_error(exc):
                    raise
                self._gpu_wakeup.wait(min(0.5, poll))
                self._gpu_wakeup.clear()
                continue
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
        """Allow processing only in modes that explicitly permit it."""
        from . import preprocess as services_module
        path = self.state_dir / "operational_mode.json"
        try:
            payload = services_module.json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return True
        except (OSError, services_module.json.JSONDecodeError, UnicodeError):
            return False
        if not isinstance(payload, dict):
            return False
        mode = payload.get("mode")
        revision = payload.get("revision")
        updated_at = payload.get("updated_at")
        if (
            mode not in {"active", "gaming", "maintenance", "preprocessing"}
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
            or not isinstance(updated_at, str)
            or not updated_at
        ):
            return False
        if mode == "active":
            return True
        if mode == "preprocessing":
            from .operational_mode import load_operational_mode, preprocessing_mode_ready
            return preprocessing_mode_ready(self.state_dir, load_operational_mode(self.state_dir))
        return False

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
        from . import preprocess as services_module
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            self._watcher_active = False
            return

        class _Handler(FileSystemEventHandler):
            def __init__(self, preprocessor: "ProjectPreprocessor", root: str):
                self._preprocessor = preprocessor
                self._root = root

            def on_any_event(self, event: Any) -> None:
                if not self._preprocessor._background_work_allowed():
                    return
                # Watchdog also reports access/close events on some backends. They
                # are not repository mutations and treating them as edits makes
                # sync tools such as Mutagen continuously requeue preprocessing.
                event_kind = str(getattr(event, "event_type", ""))
                if event_kind not in {"created", "deleted", "modified", "moved"}:
                    return
                if getattr(event, "is_directory", True):
                    return
                src = str(getattr(event, "src_path", ""))
                dst = str(getattr(event, "dest_path", ""))
                if src:
                    self._preprocessor.notify_path_changed(src, root_hint=self._root, watcher_event=event_kind)
                if dst and dst != src:
                    self._preprocessor.notify_path_changed(dst, root_hint=self._root, watcher_event=event_kind)

        observer = Observer()
        watches: dict[str, Any] = {}
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
                    with self._db_lock, services_module.closing(self._connect()) as con:
                        roots = {str(r[0]) for r in con.execute(
                            "SELECT root FROM projects WHERE paused=0"
                        ).fetchall() if services_module.Path(str(r[0])).is_dir()}

                    # Drop watches for paused, unregistered or deleted roots.
                    for root in list(watches):
                        if root not in roots:
                            try:
                                observer.unschedule(watches.pop(root))
                            except Exception:
                                watches.pop(root, None)

                    for root in sorted(roots):
                        if root not in watches:
                            handler = _Handler(self, root)
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
                    services_module.logger.debug("Filesystem watcher cleanup failed (%s)", type(cleanup_exc).__name__)
            watches.clear()
            try:
                observer.stop()
                observer.join(timeout=3.0)
            except Exception as cleanup_exc:
                services_module.logger.debug("Filesystem watcher stop failed (%s)", type(cleanup_exc).__name__)

    def _step(self, row: dict[str, Any]) -> bool:
        # An in-flight step finishes as its existing durable checkpoint boundary.
        # The next step observes mode again; active resumes from saved phase/cursor.
        from . import preprocess as services_module
        if not self._background_work_allowed():
            if str(row.get("status")) == "running":
                self._set_project(str(row["root"]), status="paused")
            return False
        root = str(row["root"])
        if not services_module.Path(root).is_dir():
            self.unregister(root, purge_data=True)
            return True
        if self._yield():
            if str(row.get("status")) == "running":
                self._set_project(str(row["root"]), status="paused")
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
            # Older durable rows placed optional Serena before the built-in
            # lexical phase. Preserve their external index state, but defer
            # optional work until the new post-files checkpoint.
            self._set_project(root, phase="lexical")
            return True
        if phase == "serena_optional":
            return self._step_external_index(row, "serena", "modules")
        if phase == "files":
            return self._step_file_card(row)
        if phase == "file_card_enrichment":
            if not self._file_card_enrichment_enabled():
                return self._refresh_deferred_card_summaries(row)
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

    def _step_complete(self, row: dict[str, Any]) -> bool:
        from . import preprocess as services_module
        root = str(row["root"])
        now = services_module.time.time()
        self._run_idle_database_maintenance()
        self._set_project(
            root, status="queued", phase="inventory", next_check_at=now,
            last_error=None, retry_after=0,
        )
        return True
