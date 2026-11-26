from __future__ import annotations

from typing import Any


class PreprocessRAGMixin:
    def _audit_rag_sync_batch(self, root: str, workspace: str, limit: int = 128) -> None:
        from . import preprocess as services_module
        with self._db_lock:
            cursors = getattr(self, "_rag_sync_audit_cursors", None)
            if cursors is None:
                cursors = self._rag_sync_audit_cursors = {}
            cursor = str(cursors.get(root, ""))
            with services_module.closing(self._connect()) as con:
                rows = con.execute(
                    """SELECT path,content_hash FROM file_refs
                       WHERE root=? AND needs_hash=0 AND content_hash<>''
                         AND rag_hash=content_hash AND path>?
                       ORDER BY path LIMIT ?""",
                    (root, cursor, limit),
                ).fetchall()
                if not rows and cursor:
                    cursor = ""
                    rows = con.execute(
                        """SELECT path,content_hash FROM file_refs
                           WHERE root=? AND needs_hash=0 AND content_hash<>''
                             AND rag_hash=content_hash
                           ORDER BY path LIMIT ?""",
                        (root, limit),
                    ).fetchall()
            if rows:
                cursors[root] = str(rows[-1]["path"])
            else:
                cursors.pop(root, None)
        if not rows:
            return

        semantic_paths = [str(item["path"]) for item in rows]
        if self.deterministic is not None and bool(self.cfg.get("skip_rag_for_deterministic_declarative", True)):
            semantic_paths = [
                path for path in semantic_paths if self.deterministic.semantic_needed(root, path)
            ]
        if not semantic_paths:
            return
        indexed_paths = self.rag.indexed_paths(workspace=workspace, paths=semantic_paths)
        if not isinstance(indexed_paths, set):
            raise RuntimeError("RAG indexed-path check returned an invalid result")
        missing = [
            str(item["path"]) for item in rows
            if str(item["path"]) in semantic_paths and str(item["path"]) not in indexed_paths
        ]
        if not missing:
            return
        now = services_module.time.time()
        with self._db_lock, services_module.closing(self._connect()) as con:
            con.executemany(
                """UPDATE file_refs SET rag_hash=NULL,updated_at=?
                   WHERE root=? AND path=? AND content_hash=? AND rag_hash=? AND needs_hash=0""",
                [(now, root, str(item["path"]), str(item["content_hash"]), str(item["content_hash"]))
                 for item in rows if str(item["path"]) in missing],
            )
            con.commit()

    def _step_rag(self, row: dict[str, Any]) -> bool:
        from . import preprocess as services_module
        root = str(row["root"])
        if self._yield():
            with self._db_lock:
                getattr(self, "_rag_batch_successes", {}).pop(root, None)
            return False
        workspace = str(row["workspace"])
        configured_limit = max(1, int(self.cfg.get("rag_files_per_step", 128)))
        # A preempted RAG step publishes no partial vector batch. Shrink the
        # next step for this root so recurring foreground work cannot repeatedly
        # discard an entire large batch. Recover after sustained progress and
        # reset once the root is caught up.
        with self._db_lock:
            batch_limits = getattr(self, "_rag_batch_limits", None)
            if batch_limits is None:
                batch_limits = self._rag_batch_limits = {}
            batch_successes = getattr(self, "_rag_batch_successes", None)
            if batch_successes is None:
                batch_successes = self._rag_batch_successes = {}
            limit = min(configured_limit, batch_limits.get(root, configured_limit))
        priority_paths = self._learned_priority_paths(root) if limit > 1 else ()
        with self._db_lock, services_module.closing(self._connect()) as con:
            selection = """SELECT path,content_hash FROM file_refs
                   WHERE root=? AND needs_hash=0 AND content_hash<>''
                     AND COALESCE(rag_hash,'')<>content_hash"""
            order = """ ORDER BY
                     (COALESCE(last_accessed_at, 0) > 0) DESC,
                     COALESCE(centrality_score, 0.0) DESC,
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
                   LIMIT ?"""
            pending = con.execute(selection + order, (root, limit)).fetchall()
            if pending and priority_paths:
                placeholders = ",".join("?" for _ in priority_paths)
                quota = min(limit - 1, max(1, limit // 4))
                preferred = con.execute(
                    selection + f" AND path IN ({placeholders})" + order,
                    (root, *priority_paths, quota),
                ).fetchall()
                seen = {str(item["path"]) for item in preferred}
                pending = (list(preferred) + [item for item in pending if str(item["path"]) not in seen])[:limit]
        if pending:
            self._audit_rag_sync_batch(root, workspace)
        reindex_paths = self._rag_reindex_paths(root, workspace, limit=128)
        if reindex_paths:
            already_pending = {str(item["path"]) for item in pending}
            reindex_paths = [path for path in reindex_paths if path not in already_pending][:limit]
            if reindex_paths:
                placeholders = ",".join("?" for _ in reindex_paths)
                with self._db_lock, services_module.closing(self._connect()) as con:
                    rows = con.execute(
                        f"SELECT path,content_hash FROM file_refs WHERE root=? AND needs_hash=0 "
                        f"AND content_hash<>'' AND path IN ({placeholders})",
                        (root, *reindex_paths),
                    ).fetchall()
                rows_by_path = {str(item["path"]): item for item in rows}
                reindex_pending = [rows_by_path[path] for path in reindex_paths if path in rows_by_path]
                pending = (reindex_pending + list(pending))[:limit]
        if not pending:
            force = bool(row.get("force_refresh"))
            # Older test/migrating databases may not yet contain the
            # inventory revision table. Fall back to a full audit rather
            # than crashing or assuming a completed RAG inventory.
            with self._db_lock, services_module.closing(self._connect()) as con:
                has_revision_table = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='file_refs_revision'"
                ).fetchone() is not None
                rev_row = (
                    con.execute("SELECT revision FROM file_refs_revision WHERE root=?", (root,)).fetchone()
                    if has_revision_table else None
                )
                curr_rev = int(rev_row[0]) if rev_row is not None else 0
                count_row = con.execute("SELECT count(*) FROM file_refs WHERE root=?", (root,)).fetchone()
                curr_count = int(count_row[0]) if count_row is not None else 0
                rag_snapshot: tuple[int, int, int, int] | None = None
                stats_provider = getattr(self.rag, "workspace_stats", None)
                if callable(stats_provider):
                    try:
                        workspace_counts = stats_provider([workspace])
                        counts = workspace_counts.get(workspace, {}) if isinstance(workspace_counts, dict) else None
                        if isinstance(counts, dict):
                            rag_snapshot = (
                                int(counts.get("files", 0)),
                                int(counts.get("chunks", 0)),
                                int(counts.get("chunked_files", 0)),
                                int(counts.get("index_generation", 0)),
                            )
                    except (OSError, ValueError, TypeError, services_module.sqlite3.Error):
                        rag_snapshot = None
                inventory_digest = (curr_rev, curr_count, rag_snapshot)
                cadence = float(self.cfg.get("rag_idle_audit_cadence_seconds", 300.0))
                now = services_module.time.time()
                cached_digest, last_audit = getattr(self, "_rag_inventory_digests", {}).get(root, (None, 0.0))
                if has_revision_table and not force and cached_digest == inventory_digest and (now - last_audit) < cadence:
                    all_paths = None
                else:
                    all_paths = [str(r[0]) for r in con.execute("SELECT path FROM file_refs WHERE root=? ORDER BY path", (root,)).fetchall()]
        if not pending:
            if all_paths is None:
                with self._db_lock:
                    batch_limits.pop(root, None)
                    batch_successes.pop(root, None)
                self._set_project(root, phase="files")
                return True
            with self._db_lock, services_module.closing(self._connect()) as con:
                semantic_rows = con.execute(
                    """SELECT f.path,f.content_hash
                       FROM file_refs f
                       WHERE f.root=? AND f.needs_hash=0 AND f.content_hash<>''
                       ORDER BY f.path""",
                    (root,),
                ).fetchall()
            skip_declarative = (
                self.deterministic is not None
                and bool(self.cfg.get("skip_rag_for_deterministic_declarative", True))
            )
            semantic_paths = [
                str(item["path"] if isinstance(item, services_module.sqlite3.Row) else item[0])
                for item in semantic_rows
                if not skip_declarative or self.deterministic.semantic_needed(root, str(item["path"] if isinstance(item, services_module.sqlite3.Row) else item[0]))
            ]
            if semantic_paths:
                indexed_paths = self.rag.indexed_paths(workspace=workspace, paths=semantic_paths)
                if not isinstance(indexed_paths, set):
                    raise RuntimeError("RAG indexed-path check returned an invalid result")
                missing_paths = [path for path in semantic_paths if path not in indexed_paths]
                if missing_paths:
                    hashes = {
                        str(item["path"] if isinstance(item, services_module.sqlite3.Row) else item[0]): str(item["content_hash"] if isinstance(item, services_module.sqlite3.Row) else item[1])
                        for item in semantic_rows
                    }
                    now = services_module.time.time()
                    with self._db_lock, services_module.closing(self._connect()) as con:
                        con.executemany(
                            """UPDATE file_refs SET rag_hash=NULL,updated_at=?
                               WHERE root=? AND path=? AND content_hash=? AND needs_hash=0""",
                            [(now, root, path, hashes[path]) for path in missing_paths],
                        )
                        con.commit()
                    getattr(self, "_rag_inventory_digests", {}).pop(root, None)
                    return True
            with self._db_lock:
                batch_limits.pop(root, None)
                batch_successes.pop(root, None)
            deleted = self.rag.prune_missing(root, workspace, all_paths)
            if deleted:
                with self._stats_lock:
                    self._stats["rag_deleted_files"] = self._stats.get("rag_deleted_files", 0) + deleted
            if not hasattr(self, "_rag_inventory_digests"):
                self._rag_inventory_digests = {}
            self._rag_inventory_digests[root] = (inventory_digest, services_module.time.time())
            self._set_project(root, phase="files")
            return True
        pending_hashes = {str(item["path"]): str(item["content_hash"]) for item in pending}
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
            if callable(getattr(self.rag, "remove_paths", None)):
                self.rag.remove_paths(workspace=workspace, paths=skipped)
            now = services_module.time.time()
            with self._db_lock, services_module.closing(self._connect()) as con:
                con.executemany(
                    "UPDATE file_refs SET rag_hash=?,updated_at=? WHERE root=? AND path=? AND content_hash=? AND needs_hash=0",
                    [(pending_hashes[rel], now, root, rel, pending_hashes[rel]) for rel in skipped],
                )
                con.commit()
            with self._stats_lock:
                self._stats["rag_skipped_files"] = self._stats.get("rag_skipped_files", 0) + len(skipped)

        skipped_paths = set(skipped)
        needed_items = [p for p in pending if str(p["path"]) not in skipped_paths]
        if not needed_items:
            return True

        paths = [str(p["path"]) for p in needed_items]
        base = services_module.Path(root)
        stale_paths: list[str] = []
        for rel in paths:
            # Never inspect an outside symlink target during stale detection.
            if services_module.checked_relative_source(root, rel) != "inside_regular_file":
                continue
            fpath = (base / rel).resolve(strict=False)
            try:
                if not fpath.is_file():
                    continue
                expected_h = pending_hashes.get(rel) or ""
                reader = getattr(getattr(self, "repo_tools", None), "_read_snapshot", None)
                if callable(reader):
                    disk_hash, _ = reader(fpath)
                else:
                    disk_hash = services_module.hashlib.sha256(fpath.read_bytes()).hexdigest()
                is_sha256 = len(expected_h) == 64 and all(c in "0123456789abcdefABCDEF" for c in expected_h)
                if not is_sha256:
                    # Legacy opaque hashes cannot be compared to SHA-256 bytes.
                    # Do not invalidate their DB row using an incomparable
                    # digest. The RAG index step verifies live bytes against
                    # any cached content override before publication.
                    continue
                if disk_hash != expected_h:
                    stale_paths.append(rel)
            except Exception:
                continue

        if stale_paths:
            write_batch_size = services_module._MISSING_REF_WRITE_BATCH_SIZE
            for offset in range(0, len(stale_paths), write_batch_size):
                stale_batch = stale_paths[offset:offset + write_batch_size]
                with self._db_lock, services_module.closing(self._connect()) as con:
                    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                    has_fts = "source_fts" in tables
                    has_index = "source_index" in tables
                    with services_module.write_transaction(con, max_duration_seconds=5.0, rollback_label="preprocessor stale unwatched refs"):
                        stale_fts_paths: list[str] = []
                        for rel in stale_batch:
                            expected_hash = pending_hashes[rel]
                            changed = con.execute(
                                "UPDATE file_refs SET needs_hash=1, rag_hash=NULL "
                                "WHERE root=? AND path=? AND content_hash=? AND needs_hash=0",
                                (root, rel, expected_hash),
                            ).rowcount
                            # A newer source generation is never invalidated by an
                            # older RAG batch, including the FTS view of that path.
                            if changed:
                                if has_index:
                                    con.execute(
                                        "DELETE FROM source_index WHERE root=? AND path=? AND content_hash=?",
                                        (root, rel, expected_hash),
                                    )
                                if has_fts:
                                    stale_fts_paths.append(rel)
                        if stale_fts_paths:
                            placeholders = ",".join("?" for _ in stale_fts_paths)
                            delete_filter = f"root=? AND path IN ({placeholders})"
                            if has_index:
                                delete_filter += (
                                    " AND NOT EXISTS (SELECT 1 FROM source_index s "
                                    "WHERE s.root=published.root AND s.path=published.path)"
                                )
                            self._delete_fts_rows(con, delete_filter, (root, *stale_fts_paths))
            stale_set = set(stale_paths)
            paths = [p for p in paths if p not in stale_set]
            if not paths:
                return True
        content_overrides: dict[str, str] = {}
        placeholders = ",".join("?" for _ in paths)
        with self._db_lock, services_module.closing(self._connect()) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "source_index" in tables:
                rows = con.execute(
                    f"SELECT path,content_hash,text FROM source_index WHERE root=? AND path IN ({placeholders})",
                    (root, *paths),
                ).fetchall()
                content_overrides.update({str(item["path"]): str(item["text"]) for item in rows
                                          if str(item["path"]) not in content_overrides
                                          and str(item["content_hash"]) == pending_hashes.get(str(item["path"]))})
        missing_hashes = list(dict.fromkeys(h for p, h in pending_hashes.items() if p not in content_overrides and h))
        if missing_hashes and "source_index" in tables:
            cas_map = {}
            with self._db_lock, services_module.closing(self._connect()) as con:
                for batch in services_module.sqlite_batches(missing_hashes):
                    values = ",".join("(?)" for _ in batch)
                    cas_map.update(con.execute(
                        f"""WITH requested(content_hash) AS (VALUES {values})
                            SELECT requested.content_hash, source_index.text FROM requested
                            JOIN source_index ON source_index.rowid = (
                                SELECT cached.rowid FROM source_index AS cached
                                WHERE cached.content_hash = requested.content_hash AND cached.text_origin='source' LIMIT 1
                            )""",
                        batch,
                    ))
            for p, h in pending_hashes.items():
                if p not in content_overrides and h in cas_map:
                    content_overrides[p] = cas_map[h]
        if hasattr(self, "ingest_cache") and self.ingest_cache is not None:
            for p in paths:
                expected_h = pending_hashes.get(p)
                if p not in content_overrides and expected_h and self.ingest_cache.has(p, root=root, content_hash=expected_h):
                    item = self.ingest_cache.get(p, root=root, content_hash=expected_h)
                    if item is not None and item.content_hash == expected_h:
                        content_overrides[p] = item.text
        result = self.rag.index_paths_step(
            root, workspace=workspace, paths=paths,
            should_yield=self._yield,
            content_overrides=content_overrides or None,
        )
        with self._stats_lock:
            self._stats["rag_steps"] += 1
        if result.get("preempted"):
            with self._db_lock:
                batch_limits[root] = min(batch_limits.get(root, configured_limit), max(1, limit // 2))
                batch_successes.pop(root, None)
            return False
        if not result.get("success"):
            message = str(result.get("error", "RAG preprocessing failed"))
            error_code = result.get("error_code")
            error_code = error_code if isinstance(error_code, str) else ""
            # NEW-001: Graceful auto-recovery for embedding_space_rebuild_required
            if result.get("rebuild_required") is True or message == "embedding_space_rebuild_required":
                reindex_fn = getattr(self.rag, "_request_workspace_reindex", None)
                target_space = getattr(self.rag, "_embedding_space_id", lambda: None)()
                if callable(reindex_fn) and target_space:
                    reindex_fn(workspace, target_space)
                    if hasattr(self.rag, "_connect"):
                        try:
                            with services_module.closing(self.rag._connect()) as rag_con:
                                with services_module.write_transaction(
                                    rag_con, max_duration_seconds=5.0, rollback_label="clear legacy vectors for rebuild"
                                ):
                                    rag_con.execute(
                                        "UPDATE chunks SET embedding='[]', embedding_space='' WHERE workspace=? AND (embedding<>'[]' OR embedding_space<>?)",
                                        (workspace, target_space),
                                    )
                        except Exception as rag_exc:
                            services_module.logger.debug("RAG legacy vector reset yielded: %s", rag_exc)
                    with self._db_lock, services_module.closing(self._connect()) as con:
                        con.execute("UPDATE file_refs SET rag_hash=NULL WHERE root=?", (root,))
                        con.commit()
                    services_module.logger.info("Automatically scheduled RAG embedding space rebuild for workspace %s into %s", workspace, target_space)
                    return False
            if result.get("retryable") is True:
                retry_after = result.get("retry_after_seconds", 60.0)
                try:
                    retry_after = float(retry_after)
                except (TypeError, ValueError):
                    retry_after = 60.0
                raise services_module._RetryablePreprocessingError(
                    message, retry_after, error_code=error_code,
                )
            if result.get("retryable") is False:
                raise services_module._NonRetryablePreprocessingError(
                    message, error_code=error_code,
                )
            error = RuntimeError(message)
            error.error_code = error_code
            raise error
        if result.get("skipped") is True and result.get("reason") == "project phase disabled":
            self._set_project(root, phase="files")
            return True
        processed = set(str(x) for x in result.get("processed_paths", []))
        policy_deleted_paths = result.get("policy_deleted_paths", [])
        if (
            not isinstance(policy_deleted_paths, list)
            or any(type(path) is not str or path not in pending_hashes for path in policy_deleted_paths)
        ):
            raise RuntimeError("RAG policy-deleted path result returned an invalid result")
        processed.update(policy_deleted_paths)
        # A watcher event can leave a deleted file_ref behind after the file has
        # disappeared. RAG intentionally ignores missing paths, so without this
        # cleanup the same pending path is selected forever and the phase spins.
        missing = []
        uncertain = []
        for rel in paths:
            classification = services_module.checked_relative_source(root, rel)
            if classification in ("missing", "escaped", "directory"):
                missing.append(rel)
            elif classification == "inaccessible":
                uncertain.append(rel)
        if uncertain:
            with self._db_lock, services_module.closing(self._connect()) as con:
                con.executemany(
                    "UPDATE file_refs SET needs_hash=1,rag_hash=NULL WHERE root=? AND path=? AND content_hash=?",
                    [(root, rel, pending_hashes[rel]) for rel in uncertain],
                )
                con.commit()
        if missing:
            if callable(getattr(self.rag, "remove_paths", None)):
                self.rag.remove_paths(workspace=workspace, paths=missing)
            existence = {}
            for rel in missing:
                existence[rel] = services_module.checked_relative_source(root, rel)
            self._reconcile_missing_reference_rows(
                root=root, missing=missing, existence=existence, pending_hashes=pending_hashes,
            )
        if processed:
            now = services_module.time.time()
            with self._db_lock, services_module.closing(self._connect()) as con:
                con.executemany(
                    "UPDATE file_refs SET rag_hash=?,updated_at=? WHERE root=? AND path=? AND content_hash=? AND needs_hash=0",
                    [(pending_hashes[rel], now, root, rel, pending_hashes[rel]) for rel in processed if rel in pending_hashes],
                )
                con.commit()
            self._record_progress(root, len(processed))
            # Recover gradually after contention subsides, while keeping each
            # step preemptible and avoiding oscillation on a single success.
            with self._db_lock:
                if root in batch_limits and batch_limits[root] < configured_limit:
                    successes = batch_successes.get(root, 0) + 1
                    if successes >= 4:
                        batch_limits[root] = min(configured_limit, batch_limits[root] * 2)
                        batch_successes.pop(root, None)
                    else:
                        batch_successes[root] = successes
        return True

