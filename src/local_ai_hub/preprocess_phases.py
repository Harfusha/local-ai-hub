from __future__ import annotations

import hashlib
import sqlite3
from typing import Any


class PreprocessPhaseMixin:
    def _step_hash(self, row: dict[str, Any]) -> bool:
        from . import preprocess as services_module
        root = str(row["root"])
        limit = max(1, int(self.cfg.get("hash_files_per_step", 256)))
        hash_key = (root, int(row.get("generation", 0) or 0))
        with self._db_lock, services_module.closing(self._connect()) as con:
            pending = con.execute(
                "SELECT path,content_hash,rag_hash FROM file_refs WHERE root=? AND needs_hash=1 ORDER BY path LIMIT ?",
                (root, limit),
            ).fetchall()
        if not pending:
            with self._hash_git_maps_lock:
                self._hash_git_maps.pop(hash_key, None)
            self._set_project(root, phase="code_index")
            return True
        base = services_module.Path(root)
        def _hash_one(item: sqlite3.Row) -> tuple[str, str, bool]:
            rel = str(item["path"])
            path = (base / rel).resolve(strict=False)
            unstable = False
            try:
                path.relative_to(base)
                for attempt in range(2):
                    before = path.stat()
                    invalidate = getattr(self.repo_tools, "invalidate_snapshot", None)
                    if callable(invalidate):
                        invalidate(path)
                    digest = self.repo_tools._hash_file_only(path)
                    after = path.stat()
                    if (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns):
                        break
                    if attempt == 1:
                        unstable = True
            except Exception:
                digest = ""
            if unstable:
                raise RuntimeError(f"source kept changing during preprocessing hash: {rel}")
            old_hash = str(item["content_hash"] or "")
            same = bool(digest and digest == old_hash)
            return rel, digest, same

        hashed_results = list(self._hash_pool().map(_hash_one, pending))
        if hasattr(self, "ingest_cache") and self.ingest_cache is not None:
            for rel, digest, same in hashed_results:
                if not same:
                    self.ingest_cache.invalidate(rel, root=root)
                    inv = getattr(self.repo_tools, "invalidate_snapshot", None)
                    if callable(inv):
                        inv((base / rel).resolve(strict=False))

        now = services_module.time.time()
        with self._db_lock, services_module.closing(self._connect()) as con:
            con.executemany(
                "UPDATE file_refs SET content_hash=?,needs_hash=0,card_key=CASE WHEN ? THEN card_key ELSE NULL END,updated_at=? WHERE root=? AND path=?",
                [(digest, int(same), now, root, rel) for rel, digest, same in hashed_results],
            )
            batch_paths = [rel for rel, digest, _ in hashed_results if digest]
            if batch_paths:
                for batch in services_module.sqlite_batches(batch_paths):
                    placeholders = ",".join("?" for _ in batch)
                    # Check the indexed paths before scanning the FTS table.
                    stale = con.execute(
                        f"""SELECT s.path FROM source_index s JOIN file_refs f
                              ON f.root=s.root AND f.path=s.path
                            WHERE s.root=? AND s.path IN ({placeholders})
                              AND s.content_hash<>f.content_hash""",
                        (root, *batch),
                    ).fetchall()
                    if stale:
                        stale_placeholders = ",".join("?" for _ in stale)
                        stale_params = (root, *(row["path"] for row in stale))
                        self._delete_fts_rows(
                            con, f"root=? AND path IN ({stale_placeholders})",
                            stale_params,
                        )
                        con.execute(
                            f"DELETE FROM source_index WHERE root=? AND path IN ({stale_placeholders})",
                            stale_params,
                        )
                    self._link_cached_file_cards(con, root, batch)
                    self._link_cached_source_text(con, root, now, batch)
                    self._link_missing_fts_rows(con, root, batch)
            # Do not mark RAG complete from another worktree. Each worktree has a
            # separate path namespace, so it still needs its own chunk rows. The
            # RAG step reuses global content-hash embeddings without re-embedding.
            con.commit()
        with self._stats_lock:
            self._stats["hashed_files"] = self._stats.get("hashed_files", 0) + len(hashed_results)
        self._record_progress(root, len(hashed_results))
        return True

    def _step_lexical(self, row: dict[str, Any]) -> bool:
        from . import preprocess as services_module
        root = str(row["root"])
        limit = max(1, int(self.cfg.get("lexical_files_per_step", 128)))
        pending = self._find_lexical_pending(root, limit)
        if not pending:
            # Defensive recovery for interrupted state: lexical indexing
            # must never spin on files whose content hash has not been reconciled.
            # Return to the checkpointed hash phase instead of indexing uncertain
            # bytes or advancing to semantic cards with an empty/stale hash.
            with self._db_lock, services_module.closing(self._connect()) as con:
                unhashed = int(con.execute(
                    "SELECT COUNT(*) FROM file_refs WHERE root=? AND (needs_hash=1 OR content_hash='')",
                    (root,),
                ).fetchone()[0])
            if unhashed:
                self._set_project(root, phase="hash")
                return True
            self._set_project(root, phase="rag")
            return True
        base = services_module.Path(root)
        def _lex_one(item: services_module.sqlite3.Row) -> tuple[str, str, str, str, str] | None:
            rel = str(item["path"])
            path = (base / rel).resolve(strict=False)
            path.relative_to(base)
            try:
                if hasattr(self, "ingest_cache") and self.ingest_cache is not None:
                    ingested = self.ingest_cache.get_or_ingest(
                        base, rel, self.repo_tools, parse_ast=False, expected_hash=str(item["content_hash"])
                    )
                    file_hash, text = ingested.content_hash, ingested.text
                else:
                    reader = getattr(getattr(self, "repo_tools", None), "_read_snapshot", None)
                    if callable(reader):
                        file_hash, lines = reader(path)
                        text = "\n".join(lines)
                    else:
                        raw = path.read_bytes()
                        file_hash = hashlib.sha256(raw).hexdigest()
                        text = raw.decode("utf-8", errors="replace")
            except FileNotFoundError:
                # The file may disappear after inventory or the earlier stale-ref
                # cleanup. Drop that ref and let the rest of this batch proceed.
                return None
            text_origin = "source"
            if self.deterministic is not None and bool(self.cfg.get("compact_lexical_for_deterministic_declarative", True)):
                try:
                    compact = self.deterministic.lexical_projection(
                        root, rel, int(self.cfg.get("deterministic_lexical_max_chars", 12000))
                    )
                    if compact is not None:
                        text = compact
                        text_origin = "projection"
                except FileNotFoundError:
                    return None
                except services_module.sqlite3.Error as exc:
                    services_module.logger.warning("Deterministic lexical projection unavailable (%s)", type(exc).__name__)
            return rel, str(item["content_hash"]), str(file_hash), text, text_origin

        batch_results = list(self._cpu_pool.map(_lex_one, pending))
        if any(result is None for result in batch_results):
            self._prune_missing_file_refs(root)
        lex_results = [result for result in batch_results if result is not None]
        if not lex_results:
            return True

        now = services_module.time.time()
        indexed_count = 0
        def _write_lexical_batch(batch):
            try:
                with self._db_lock, services_module.closing(self._connect()) as con:
                    with services_module.write_transaction(con, max_duration_seconds=5.0, rollback_label="preprocessor lexical index"):
                        placeholders = ",".join("?" for _ in batch)
                        current = {str(item["path"]): (str(item["content_hash"]), int(item["needs_hash"]))
                                   for item in con.execute(
                                       f"SELECT path,content_hash,needs_hash FROM file_refs WHERE root=? AND path IN ({placeholders})",
                                       (root, *(item[0] for item in batch)),
                                   )}
                        # Recheck each bounded batch because the watcher may have
                        # changed file identity while the CPU pool read its bytes.
                        accepted = []
                        for rel, expected_hash, file_hash, text, text_origin in batch:
                            if current.get(rel) != (expected_hash, 0):
                                continue
                            if file_hash != expected_hash:
                                if hasattr(self, "ingest_cache") and self.ingest_cache is not None:
                                    self.ingest_cache.invalidate(rel, root=root)
                                inv = getattr(self.repo_tools, "invalidate_snapshot", None)
                                if callable(inv):
                                    inv((base / rel).resolve(strict=False))
                                con.execute("UPDATE file_refs SET needs_hash=1 WHERE root=? AND path=? AND content_hash=? AND needs_hash=0",
                                            (root, rel, expected_hash))
                                continue
                            accepted.append((rel, expected_hash, text, text_origin))
                        if accepted:
                            accepted_paths = [rel for rel, _, _, _ in accepted]
                            accepted_placeholders = ",".join("?" for _ in accepted_paths)
                            # Project-specific projections cannot seed content shared by other roots.
                            con.executemany(
                                "INSERT OR IGNORE INTO content_lexical(content_hash,text,updated_at) VALUES(?,?,?)",
                                [(chash, text, now) for _, chash, text, origin in accepted if origin == "source"],
                            )
                            con.executemany(
                                """INSERT OR REPLACE INTO source_index(root,path,content_hash,text,updated_at,text_origin)
                                   VALUES(?,?,?,?,?,?)""",
                                [(root, rel, chash, text, now, origin) for rel, chash, text, origin in accepted],
                            )
                            self._delete_fts_rows(
                                con, f"root=? AND path IN ({accepted_placeholders})",
                                (root, *accepted_paths),
                            )
                            # Include paths so filename and module searches narrow candidates.
                            self._insert_fts_rows(
                                con,
                                [(root, rel, rel + "\n" + text) for rel, _, text, _ in accepted],
                            )
                return len(accepted)
            except TimeoutError as exc:
                if not str(exc).startswith("SQLite write transaction exceeded its duration budget ") or len(batch) < 2:
                    raise
                midpoint = len(batch) // 2
                return _write_lexical_batch(batch[:midpoint]) + _write_lexical_batch(batch[midpoint:])

        for offset in range(0, len(lex_results), services_module._LEXICAL_WRITE_BATCH_SIZE):
            batch = lex_results[offset:offset + services_module._LEXICAL_WRITE_BATCH_SIZE]
            indexed_count += _write_lexical_batch(batch)
        with self._stats_lock:
            self._stats["lexical_files"] = self._stats.get("lexical_files", 0) + indexed_count
        self._record_progress(root, indexed_count)
        return True

    def _step_deterministic(self, row: dict[str, Any]) -> bool:
        from . import preprocess as services_module
        root = str(row["root"])
        if self.deterministic is None:
            self._set_project(root, phase="lexical")
            return True
        limit = max(1, int(self.cfg.get("deterministic_files_per_step", 256)))
        generation_key = (root, int(row.get("generation", 0) or 0))
        if generation_key not in self._missing_refs_checked_generations:
            self._prune_missing_file_refs(root)
            self._missing_refs_checked_generations.add(generation_key)
            self._missing_refs_checked_generations = self._bound_generation_set(self._missing_refs_checked_generations)
        with self._db_lock, services_module.closing(self._connect()) as con:
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
            with services_module.closing(self.deterministic._connect()) as det_con:
                existing = dict(det_con.execute("SELECT path, content_hash FROM files WHERE root=?", (root,)).fetchall())
        except Exception:
            existing = {}
        pending = [(p, h) for p, h in refs if existing.get(p) != h][:limit]
        if not pending:
            try:
                self.deterministic.refresh_manifests(root)
            except Exception as index_exc:
                services_module.logger.warning("Deterministic manifest refresh failed (%s)", type(index_exc).__name__)
            try:
                self.deterministic.precompute_test_mappings(root)
            except Exception as index_exc:
                services_module.logger.warning("Deterministic test-map refresh failed (%s)", type(index_exc).__name__)
            try:
                self.deterministic.find_hotspots(root, days=30, limit=20)
            except Exception as index_exc:
                services_module.logger.warning("Deterministic hotspot refresh failed (%s)", type(index_exc).__name__)
            if hasattr(self.deterministic, "get_centrality_ranks"):
                try:
                    ranks = self.deterministic.get_centrality_ranks(root)
                    if ranks:
                        with self._db_lock, services_module.closing(self._connect()) as con:
                            con.executemany(
                                "UPDATE file_refs SET centrality_score=? WHERE root=? AND path=?",
                                [(score, root, p) for p, score in ranks.items()],
                            )
                            con.commit()
                except Exception as exc:
                    services_module.logger.debug("Centrality calculation failed: %s", exc)
            if hasattr(self.deterministic, "precompute_dead_code"):
                try:
                    self.deterministic.precompute_dead_code(root)
                except Exception as exc:
                    services_module.logger.debug("Dead code precompute failed: %s", exc)
            self._set_project(root, phase="lexical")
            return True

        update_batch = getattr(self.deterministic, "update_files_batch", None)
        if callable(update_batch):
            progressed = 0
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
                        progressed += int(result.get("updated", 0)) + int(result.get("cached", 0))
            except Exception as batch_exc:
                services_module.logger.warning("Deterministic batch update failed (%s)", type(batch_exc).__name__)
                if progressed:
                    with self._stats_lock:
                        self._stats["deterministic_files"] += progressed
                    self._record_progress(root, progressed)
                retry_at = services_module.time.time() + 60.0
                self._set_project(
                    root, phase="deterministic", status="waiting",
                    last_error=f"deterministic_batch_failed:{type(batch_exc).__name__}",
                    retry_after=retry_at, next_check_at=retry_at,
                )
                return True
        else:
            progressed = 0
            failed_update = False
            for p, digest in pending:
                try:
                    updated = bool(self.deterministic.update_file(root, p, digest).get("success"))
                    progressed += int(updated)
                    failed_update |= not updated
                except Exception as index_exc:
                    services_module.logger.warning("Deterministic file update failed (%s)", type(index_exc).__name__)
                    failed_update = True
            if failed_update:
                if progressed:
                    with self._stats_lock:
                        self._stats["deterministic_files"] += progressed
                self._record_progress(root, progressed)
                retry_at = services_module.time.time() + 60.0
                self._set_project(
                    root, phase="deterministic", status="waiting",
                    last_error="deterministic_file_update_failed",
                    retry_after=retry_at, next_check_at=retry_at,
                )
                return True
        with self._stats_lock:
            self._stats["deterministic_files"] += progressed
        self._record_progress(root, progressed)
        return True

    def _step_external_index(self, row: dict[str, Any], backend: str, next_phase: str) -> bool:
        from . import preprocess as services_module
        root = str(row["root"])
        intelligence_cfg = self.config.get("code_intelligence", {})
        enabled = bool(intelligence_cfg.get(f"preprocess_{backend}", True)) and bool(intelligence_cfg.get(f"{backend}_enabled", True))
        if self.external_tools is None or not enabled:
            self._set_project(root, phase=next_phase)
            return True
        # External language-server/graph indexing can be CPU/RAM intensive. Never
        # start it while foreground inference is active; this is a background phase.
        if not self._scheduler_background_allowed() or self.scheduler.foreground_busy():
            return False
        revision = self._external_revision(root)
        force_refresh = bool(row.get("force_refresh"))
        retry_count = 0
        with self._db_lock, services_module.closing(self._connect()) as con:
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
                        with self._db_lock, services_module.closing(self._connect()) as con:
                            con.execute(
                                "UPDATE external_index_state SET status='unavailable' WHERE root=? AND backend=? AND revision_hash=?",
                                (root, backend, revision),
                            )
                            con.commit()
                    self._set_project(root, phase=next_phase)
                    return True
            if prior_status in {"degraded", "unavailable"} and retry_count > 0:
                elapsed = max(0.0, services_module.time.time() - float(state[4] or 0.0))
                if elapsed < self._external_retry_delay(retry_count):
                    # External indexes are optional; advance preprocessing while
                    # this revision's bounded transient retry is cooling down.
                    self._set_project(root, phase=next_phase)
                    self._record_progress(root, 1)
                    return True
        if not services_module.Path(root).is_dir():
            result = {"success": False, "skipped": True, "error": "project root is missing"}
        else:
            # Publish the active state before the potentially long subprocess so
            # the dashboard cannot display a stale prior failure as RUNNING.
            with self._db_lock, services_module.closing(self._connect()) as con:
                con.execute(
                    "INSERT OR REPLACE INTO external_index_state(root,backend,revision_hash,status,updated_at,error,retry_count) VALUES(?,?,?,?,?,?,?)",
                    (root, backend, revision, "running", services_module.time.time(), "", retry_count),
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
        with self._db_lock, services_module.closing(self._connect()) as con:
            con.execute(
                "INSERT OR REPLACE INTO external_index_state(root,backend,revision_hash,status,updated_at,error,retry_count) VALUES(?,?,?,?,?,?,?)",
                (root, backend, revision, status, services_module.time.time(), error, retry_count + 1),
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
