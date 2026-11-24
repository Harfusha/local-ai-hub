from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .project_config import ProjectPathPolicy


class PreprocessControlsMixin:
    def _wake_all(self) -> None:
        self._cpu_wakeup.set()
        self._gpu_wakeup.set()

    def _exclusive_mode_active(self) -> bool:
        try:
            from .operational_mode import load_operational_mode
            snapshot = load_operational_mode(self.state_dir)
            return not snapshot.degraded and snapshot.mode == "preprocessing"
        except (AttributeError, OSError, ValueError, TypeError):
            return False

    def _project_limit(self) -> int:
        if self._exclusive_mode_active():
            return getattr(self, "exclusive_max_projects", self.max_preprocessing_projects)
        return self.max_preprocessing_projects

    def _hash_pool(self) -> ThreadPoolExecutor:
        if self._exclusive_mode_active():
            return getattr(self, "_exclusive_cpu_pool", self._cpu_pool)
        return self._cpu_pool

    def _configured_preprocessing_model(self) -> str:
        config = getattr(self, "config", {})
        if not isinstance(config, dict):
            return ""
        prep_cfg = config.get("preprocessing", {})
        models = config.get("models", {})
        configured = (prep_cfg.get("model") if isinstance(prep_cfg, dict) else None)
        configured = configured or (models.get("background_code") if isinstance(models, dict) else None)
        return str(configured or "").strip()

    def _configured_preprocessing_draft_model(self) -> str:
        config = getattr(self, "config", {})
        if not isinstance(config, dict):
            return ""
        prep_cfg = config.get("preprocessing", {})
        if isinstance(prep_cfg, dict) and prep_cfg.get("cascade_enabled") is False:
            return ""
        configured = (prep_cfg.get("draft_model") if isinstance(prep_cfg, dict) else None)
        return str(configured or "").strip()

    def _file_card_enrichment_enabled(self) -> bool:
        if bool(self.cfg.get("disable_llm_card_synthesis", False)):
            return False
        if not self._configured_preprocessing_model():
            return False
        exclusive = self.cfg.get("exclusive", {})
        if (self._exclusive_mode_active() and isinstance(exclusive, dict)
                and exclusive.get("enrich_stub_cards", True) is False):
            return False
        return self._background_work_allowed()

    def _pending_stub_cards(self, root: str) -> int:
        from . import preprocess as services_module
        if not self._file_card_enrichment_enabled():
            return 0
        background_model = self._configured_preprocessing_model()
        with self._db_lock, services_module.closing(self._connect()) as con:
            return int(con.execute(
                "SELECT COUNT(*) FROM file_refs f JOIN content_cards c ON c.card_key=f.card_key "
                "WHERE f.root=? AND c.model IN ('deterministic','deterministic-stub','deterministic-barrel') "
                "AND f.size<=? AND NOT EXISTS (SELECT 1 FROM file_card_enrichment e "
                "WHERE e.content_hash=f.content_hash AND e.model=? AND e.pipeline_version=? "
                "AND e.status='failed' AND e.attempts>=3)",
                (root, int(self.cfg.get("file_card_max_bytes", 180000)), background_model,
                 self._file_card_pipeline_version()),
            ).fetchone()[0])

    @staticmethod
    def _valid_enriched_file_card(data: Any) -> bool:
        from . import preprocess as services_module
        if not isinstance(data, dict):
            return False
        properties = services_module.CARD_SCHEMA["properties"]
        required_fields = ("purpose", "symbols", "dependencies", "side_effects", "risks", "tests", "keywords")
        if any(field not in data for field in required_fields):
            return False
        purpose = data.get("purpose")
        if (not isinstance(purpose, str) or len(purpose) > properties["purpose"]["maxLength"]
                or not purpose.strip()):
            return False
        populated = bool(purpose and purpose.strip())
        for field, rule in properties.items():
            if rule["type"] != "array" or field == "evidence":
                continue
            values = data.get(field)
            if not isinstance(values, list) or len(values) > rule["maxItems"]:
                return False
            item_limit = rule["items"]["maxLength"]
            if any(not isinstance(item, str) or not item.strip() or len(item) > item_limit for item in values):
                return False
            populated = populated or bool(values)
        evidence = data.get("evidence")
        if evidence:
            if not isinstance(evidence, list) or len(evidence) > properties["evidence"]["maxItems"]:
                return False
            for item in evidence:
                if (not isinstance(item, dict) or set(item) != {"field", "value", "quote"}
                        or not isinstance(item["field"], str)
                        or item["field"] not in {"purpose", "symbols", "dependencies", "side_effects", "risks", "tests", "keywords"}
                        or not all(isinstance(item[key], str) and item[key].strip() for key in ("value", "quote"))
                        or len(item["value"]) > 500 or len(item["quote"]) > 500):
                    return False
        return populated

    def _scheduler_background_allowed(self) -> bool:
        if self._exclusive_mode_active():
            return self._background_work_allowed() and not self.scheduler.foreground_busy()
        return self.scheduler.background_allowed()

    def _rebalance_processing_slots(self, con: sqlite3.Connection, preferred_root: str | None = None) -> None:
        """Keep all registered projects active; cap only runnable preprocessing work."""
        from . import preprocess as services_module
        limit = self._project_limit()
        now = services_module.time.time()
        fairness_cutoff = now - 300.0
        candidates = con.execute(
            """SELECT root,status FROM projects
               WHERE paused=0 AND phase<>?
                 AND (status='running' OR (status IN ('queued','waiting','error') AND retry_after<=?))
               ORDER BY force_refresh DESC,
                        CASE WHEN status IN ('queued','waiting') AND last_requested_at>=? THEN 0 ELSE 1 END,
                        CASE WHEN status IN ('queued','waiting') AND last_requested_at>=? THEN last_requested_at END DESC,
                        CASE WHEN updated_at<=? THEN 0 ELSE 1 END,
                        CASE WHEN updated_at<=? AND last_requested_at>=? THEN 0 ELSE 1 END,
                        CASE WHEN updated_at<=? AND last_requested_at>=? THEN last_requested_at END DESC,
                        CASE WHEN updated_at<=? THEN updated_at END ASC,
                        CASE WHEN root=? THEN 0 ELSE 1 END,
                        last_requested_at DESC,updated_at DESC""",
            (self.PHASES[-1], now, fairness_cutoff, fairness_cutoff, fairness_cutoff, fairness_cutoff, fairness_cutoff,
             fairness_cutoff, fairness_cutoff, fairness_cutoff, preferred_root or ""),
        ).fetchall()
        guard = getattr(self, "_step_locks_guard", None)
        with guard if guard is not None else services_module.nullcontext():
            locks = getattr(self, "_step_locks", {})
            candidates.sort(key=lambda row: not bool(locks.get(str(row["root"])) and locks[str(row["root"])].locked()))
            for index, row in enumerate(candidates):
                root = str(row["root"])
                cur_status = str(row["status"])
                if index < limit:
                    if cur_status == "waiting":
                        con.execute("UPDATE projects SET status='queued',retry_after=0 WHERE root=?", (root,))
                elif cur_status in ("queued", "running") and not (locks.get(root) and locks[root].locked()):
                    con.execute("UPDATE projects SET status='waiting' WHERE root=?", (root,))

    def _project_phase_allowed(self, root: str, phase: str) -> bool:
        from . import preprocess as services_module
        api, context = self._project_config_context(root)
        if context is None:
            return services_module.phase_is_allowed(services_module.resolve_project_config(root).settings, phase)
        checker = getattr(api, "phase_is_allowed", services_module.phase_is_allowed)
        return bool(checker(context.settings, phase))

    def _project_path_allowed(
        self,
        root: str,
        relative: str,
        settings: Any,
        *,
        phase: str,
        size_bytes: int,
        path_policy: ProjectPathPolicy | None = None,
    ) -> bool:
        from . import preprocess as services_module
        parts = services_module.Path(relative).parts
        ignored_dirs = getattr(self.repo_tools, "ignore_dirs", set())
        hard_dirs = {".git", ".svn", ".hg", ".serena", ".local-ai-hub"}
        hard_denied = any(part.lower() in hard_dirs for part in parts[:-1])
        ignore_extensions = getattr(self.repo_tools, "ignore_extensions", set())
        hard_denied = hard_denied or services_module.Path(relative).suffix.lower() in ignore_extensions
        extensions = getattr(self.repo_tools, "extensions", set())
        project_extensions = {str(value).lower() for value in getattr(settings, "text_extensions", ())}
        for override in getattr(settings, "language_overrides", {}).values():
            project_extensions.update(str(value).lower() for value in override.get("text_extensions", ()))
        binary_extensions = {str(value).lower() for value in getattr(settings, "binary_extensions", ())}
        project_extensions.difference_update(binary_extensions)
        hard_denied = hard_denied or services_module.Path(relative).suffix.lower() in binary_extensions
        special_filenames = getattr(self.repo_tools, "special_filenames", set())
        if extensions and services_module.Path(relative).suffix.lower() not in extensions and services_module.Path(relative).suffix.lower() not in project_extensions and services_module.Path(relative).name.lower() not in special_filenames:
            hard_denied = True
        checker = path_policy.allows if path_policy is not None else None
        if checker is None:
            return services_module.path_is_allowed(
                root,
                services_module.Path(root) / relative,
                settings,
                phase=phase,
                soft_ignored=any(part.lower() in ignored_dirs for part in parts[:-1]),
                hard_denied=hard_denied,
                size_bytes=size_bytes,
            )
        return checker(
            services_module.Path(root) / relative,
            phase=phase,
            soft_ignored=any(part.lower() in ignored_dirs for part in parts[:-1]),
            hard_denied=hard_denied,
            size_bytes=size_bytes,
        )

    def _forced_preprocess_files(self, root: str, settings: Any) -> dict[str, dict[str, Any]]:
        from . import preprocess as services_module
        base = services_module.Path(root).resolve(strict=True)
        path_policy = services_module.ProjectPathPolicy(base, settings)
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
                        str(base), relative, settings, phase="preprocess", size_bytes=size,
                        path_policy=path_policy,
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

    def _first_unowned_project(self, rows: list[sqlite3.Row]) -> sqlite3.Row | None:
        guard = getattr(self, "_step_locks_guard", None)
        if guard is None:
            return rows[0] if rows else None
        with guard:
            for row in rows:
                lock = self._step_locks.get(str(row["root"]))
                if lock is None or not lock.locked():
                    return row
        return None

    def _ensure_extra_cpu_threads(self) -> None:
        from . import preprocess as services_module
        existing = {int(t.name.rsplit("-", 1)[-1]): t for t in self._extra_cpu_threads if t.is_alive()}
        for index in range(1, self.exclusive_max_projects):
            if index not in existing:
                thread = services_module.threading.Thread(target=self._cpu_loop, args=(index,), name=f"local-ai-preprocessor-cpu-{index}", daemon=True)
                existing[index] = thread
                thread.start()
        self._extra_cpu_threads = list(existing.values())

    def ensure_running(self) -> bool:
        from . import preprocess as services_module
        if not self.enabled or self._stop.is_set():
            return False
        if self._cpu_thread is None or not self._cpu_thread.is_alive():
            self._cpu_thread = services_module.threading.Thread(target=self._cpu_loop, name="local-ai-preprocessor-cpu", daemon=True)
            self._cpu_thread.start()
        self._ensure_extra_cpu_threads()
        if self._gpu_thread is None or not self._gpu_thread.is_alive():
            self._gpu_thread = services_module.threading.Thread(target=self._gpu_loop, name="local-ai-preprocessor-gpu", daemon=True)
            self._gpu_thread.start()
        if bool(self.cfg.get("fs_watcher_enabled", True)) and (self._fs_watcher_thread is None or not self._fs_watcher_thread.is_alive()):
            self._fs_watcher_thread = services_module.threading.Thread(target=self._fs_watcher_loop, name="local-ai-fs-watcher", daemon=True)
            self._fs_watcher_thread.start()
            with self._stats_lock:
                self._stats["watcher_restarts"] += 1
        return True

    def close(self) -> None:
        from . import preprocess as services_module
        self._stop.set()
        self._wake_all()
        for t in (self._cpu_thread, self._gpu_thread, self._fs_watcher_thread, *self._extra_cpu_threads):
            if t and t.is_alive() and services_module.threading.current_thread() is not t:
                t.join(timeout=3.0)
        self._cpu_pool.shutdown(wait=False, cancel_futures=True)
        exclusive_pool = getattr(self, "_exclusive_cpu_pool", None)
        if exclusive_pool is not None and exclusive_pool is not self._cpu_pool:
            exclusive_pool.shutdown(wait=False, cancel_futures=True)
        if getattr(self, "_write_actor", None) is not None:
            self._write_actor.stop()
