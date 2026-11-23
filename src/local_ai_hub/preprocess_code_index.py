from __future__ import annotations

from typing import Any


class PreprocessCodeIndexMixin:
    def _step_code_index(self, row: dict[str, Any]) -> bool:
        from . import preprocess as services_module
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
        settings = self._project_settings(root)
        path_policy = services_module.ProjectPathPolicy(root, settings)
        allowed: dict[str, str] | None = None
        source_revision: int | None = None
        allowed_cache_lock = getattr(self, "_code_index_allowed_cache_lock", None)
        allowed_cache = getattr(self, "_code_index_allowed_cache", None)
        with self._db_lock, services_module.closing(self._connect()) as con:
            con.execute("BEGIN")
            try:
                revision_row = con.execute(
                    "SELECT revision FROM file_refs_revision WHERE root=?", (root,),
                ).fetchone()
                source_revision = int(revision_row[0]) if revision_row is not None else 0
            except services_module.sqlite3.Error:
                # Older or damaged derived state has no usable revision fence;
                # rebuild the allowlist and prune on each bounded pass.
                source_revision = None
            if allowed_cache_lock is not None and isinstance(allowed_cache, dict) and source_revision is not None:
                with allowed_cache_lock:
                    cached = allowed_cache.get(root)
                    if (
                        cached is not None
                        and cached[0] == generation_key[1]
                        and cached[1] == source_revision
                        and cached[2] == settings
                    ):
                        allowed = cached[3]
                        allowed_cache.pop(root, None)
                        allowed_cache[root] = cached
            if allowed is None:
                allowed = {}
                cursor = con.execute(
                    "SELECT path,content_hash,size FROM file_refs WHERE root=? AND needs_hash=0 AND content_hash<>'' ORDER BY path",
                    (root,),
                )
                while True:
                    batch = cursor.fetchmany(256)
                    if not batch:
                        break
                    for row_ref in batch:
                        path = str(row_ref["path"])
                        if any(part.lower() in self.repo_tools.ignore_dirs for part in services_module.Path(path).parts[:-1]):
                            continue
                        if self._project_path_allowed(
                            root, path, settings, phase="call_graph",
                            size_bytes=int(row_ref["size"] or 0), path_policy=path_policy,
                        ):
                            allowed[path] = str(row_ref["content_hash"])
                if (
                    source_revision is not None
                    and allowed_cache_lock is not None
                    and isinstance(allowed_cache, dict)
                ):
                    if len(allowed) <= 50_000:
                        with allowed_cache_lock:
                            allowed_cache.pop(root, None)
                            allowed_cache[root] = (
                                generation_key[1], source_revision, settings, allowed,
                            )
                            while len(allowed_cache) > 4:
                                allowed_cache.pop(next(iter(allowed_cache)))
                    else:
                        with allowed_cache_lock:
                            allowed_cache.pop(root, None)
        pruned_generations = getattr(self, "_code_index_pruned_generations", set())
        prune_key = (root, generation_key[1], repr(settings), source_revision)
        if source_revision is None or prune_key not in pruned_generations:
            prune_result = self.code_index.prune(root, allowed.keys())
            if not isinstance(prune_result, dict) or prune_result.get("success") is not True:
                raise RuntimeError("code index prune failed")
            if source_revision is not None:
                pruned_generations.add(prune_key)
                self._code_index_pruned_generations = self._bound_generation_set(pruned_generations)
        # Evidence is a record of source material actually served to an agent.
        # The repository inventory alone is not a reason to grow the index.
        evidence_store = getattr(getattr(self, "services", None), "evidence_store", None)
        recent_paths = getattr(evidence_store, "recent_paths", None)
        if not callable(recent_paths):
            self._set_project(root, phase="deterministic", last_error="code_index_demand_unavailable")
            return True
        try:
            demand = recent_paths(root, limit=256)
            seeds = list(dict.fromkeys(str(item.get("path", "")).replace("\\", "/")
                                        for item in demand if isinstance(item, dict)))
            seeds = [path for path in seeds if path in allowed]
            if not seeds:
                seeds.extend(self._proactive_git_seeds(root, allowed))
            from .code_index_demand import one_hop_related_files, two_hop_related_files
            demand_hops = max(1, int(self.cfg.get("demand_hops", 1)))
            ic = getattr(self, "ingest_cache", None)
            if demand_hops >= 2:
                neighbors = two_hop_related_files(services_module.Path(root), seeds, set(allowed), self.repo_tools, ingest_cache=ic)
            else:
                neighbors = one_hop_related_files(services_module.Path(root), seeds, set(allowed), self.repo_tools, ingest_cache=ic)
            refs = [(path, allowed[path]) for path in [*seeds, *neighbors]]
            record_usage = getattr(self.code_index, "record_usage", None)
            if callable(record_usage):
                record_usage(root, [item for item in demand if isinstance(item, dict) and str(item.get("path", "")).replace("\\", "/") in seeds])
        except (services_module.sqlite3.Error, OSError, ValueError, TypeError) as exc:
            services_module.logger.warning("Code-index demand selection unavailable (%s)", type(exc).__name__)
            self._set_project(root, phase="deterministic", last_error="code_index_demand_unavailable")
            return True
        try:
            select_pending = getattr(self.code_index, "files_needing_reindex", None)
            if callable(select_pending):
                pending = select_pending(root, refs)[:limit]
            else:
                with services_module.closing(self.code_index._connect()) as ci_con:
                    existing = dict(ci_con.execute("SELECT path, content_hash FROM files WHERE root=?", (root,)).fetchall())
                pending = [(p, h) for p, h in refs if existing.get(p) != h][:limit]
        except Exception:
            pending = refs[:limit]
        if not pending:
            self._set_project(root, phase="deterministic")
            return True

        update_batch = getattr(self.code_index, "update_files_batch", None)
        if callable(update_batch):
            files_processed = 0
            cached = 0
            budget_limited = False
            try:
                batches = [pending]
                while batches:
                    batch = batches.pop()
                    try:
                        result = update_batch(root, batch)
                    except TimeoutError:
                        if len(batch) == 1:
                            raise
                        midpoint = len(batch) // 2
                        batches.extend((batch[midpoint:], batch[:midpoint]))
                    else:
                        files_processed += int(result.get("files_processed", 0))
                        cached += int(result.get("cached", 0))
                        if result.get("budget_limited") is True:
                            budget_limited = True
                            break
            except Exception as batch_exc:
                from .project_config import ProjectConfigError
                if isinstance(batch_exc, ProjectConfigError):
                    services_module.logger.warning("Code-index batch skipped due to project configuration error (%s)", batch_exc)
                    self._set_project(root, phase="deterministic", last_error=str(batch_exc))
                    return True
                services_module.logger.warning("Code-index batch update failed (%s)", type(batch_exc).__name__)
                progressed = files_processed + cached
                if progressed:
                    with self._stats_lock:
                        self._stats["code_index_files"] += progressed
                    self._record_progress(root, progressed)
                retry_at = services_module.time.time() + 60.0
                self._set_project(
                    root, phase="code_index", status="waiting",
                    last_error=f"code_index_batch_failed:{type(batch_exc).__name__}",
                    retry_after=retry_at, next_check_at=retry_at,
                )
                return True
            progressed = files_processed + cached
            if budget_limited:
                if progressed:
                    with self._stats_lock:
                        self._stats["code_index_files"] += progressed
                self._record_progress(root, progressed)
                retry_at = services_module.time.time() + 300.0
                self._set_project(
                    root, phase="code_index", status="waiting",
                    last_error="code_index_budget_limited", retry_after=retry_at, next_check_at=retry_at,
                )
                return True
        else:
            files_processed = 0
            progressed = 0
            failed_update = False
            from .project_config import ProjectConfigError
            for p, digest in pending:
                try:
                    updated = bool(self.code_index.update_file(root, p, digest).get("success"))
                    progressed += int(updated)
                    failed_update |= not updated
                    if updated:
                        files_processed += 1
                except ProjectConfigError as cfg_exc:
                    services_module.logger.warning("Code-index file update skipped due to project configuration error (%s)", cfg_exc)
                    break
                except Exception as index_exc:
                    services_module.logger.warning("Code-index file update failed (%s)", type(index_exc).__name__)
                    failed_update = True
            if failed_update:
                if progressed:
                    with self._stats_lock:
                        self._stats["code_index_files"] += progressed
                self._record_progress(root, progressed)
                retry_at = services_module.time.time() + 60.0
                self._set_project(
                    root, phase="code_index", status="waiting",
                    last_error="code_index_file_update_failed",
                    retry_after=retry_at, next_check_at=retry_at,
                )
                return True
        with self._stats_lock:
            self._stats["code_index_files"] += progressed
        self._record_progress(root, progressed)
        if len(pending) < limit or files_processed == 0:
            self._set_project(root, phase="deterministic")
        return True
