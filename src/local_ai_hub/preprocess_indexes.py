from __future__ import annotations

import sqlite3
from typing import Any, Sequence


class PreprocessIndexesMixin:
    def _requeue_available_external_indexes(self) -> None:
        """Wake completed projects whose cached optional index can now run."""
        from . import preprocess as services_module
        checker = getattr(self.external_tools, "backend_available", None)
        if not callable(checker):
            return
        try:
            with self._db_lock, services_module.closing(self._connect()) as con:
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
                now = services_module.time.time()
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

    def _link_cached_file_cards(self, con: sqlite3.Connection, root: str, paths: Sequence[str] | None = None) -> None:
        from . import preprocess as services_module
        scope = "root=? AND card_key IS NULL AND needs_hash=0 AND content_hash<>''"
        params: tuple[Any, ...] = (root,)
        if paths is not None:
            scope += " AND path IN (" + ",".join("?" for _ in paths) + ")"
            params += tuple(paths)
        model = self._configured_preprocessing_model()
        allowed_models = {model, *self._file_card_fallbacks(model)} if model else set()
        models = sorted(allowed_models | services_module._DETERMINISTIC_FILE_CARD_MODELS)
        placeholders = ",".join("?" for _ in models)
        candidates = con.execute(
            f"""SELECT content_hash,card_key,model,card_json FROM content_cards
                WHERE analyzer_version=? AND model IN ({placeholders})
                  AND content_hash IN (SELECT content_hash FROM file_refs WHERE {scope})
                ORDER BY content_hash,hits DESC,card_key""",
            (services_module.PREPROCESS_ANALYZER_VERSION, *models, *params),
        )
        selected: dict[str, tuple[str, bool]] = {}
        for card in candidates:
            digest = card["content_hash"]
            enriched = card["model"] in allowed_models
            prior = selected.get(digest)
            if (prior is None or (enriched and not prior[1])) and self._reusable_file_card(
                card, allowed_models, allow_deterministic=True,
            ):
                selected[digest] = (card["card_key"], enriched)
        con.executemany(
            f"UPDATE file_refs SET card_key = ? WHERE {scope} AND content_hash=?",
            [(key, *params, digest) for digest, (key, _) in selected.items()],
        )

    def _insert_fts_rows(self, con: sqlite3.Connection, rows: Sequence[tuple[str, str, str]]) -> None:
        from . import preprocess as services_module
        services_module.insert_fts_rows(con, services_module.writable_fts_layout(con), rows)

    def _link_missing_fts_rows(
        self, con: sqlite3.Connection, root: str, paths: Sequence[str] | None = None,
    ) -> None:
        from . import preprocess as services_module
        source_scope = ""
        fts_scope = ""
        params: tuple[str, ...] = (root,)
        if paths is not None:
            if not paths:
                return
            placeholders = ",".join("?" for _ in paths)
            source_scope = f" AND s.path IN ({placeholders})"
            fts_scope = f" AND f.path IN ({placeholders})"
            params = (root, *paths)
        layout = services_module.writable_fts_layout(con)
        published = services_module.SHARED_FTS_ROWS if layout == services_module.SHARED_FTS_ROWS else services_module.LEGACY_FTS
        select_missing = f"""SELECT s.root, s.path, s.path || char(10) || s.text
            FROM source_index s
            JOIN file_refs r ON r.root=s.root AND r.path=s.path AND r.content_hash=s.content_hash
            WHERE s.root=?{source_scope} AND r.needs_hash=0 AND r.content_hash<>'' AND s.path NOT IN (
                SELECT f.path FROM {published} f WHERE f.root=?{fts_scope} AND f.path IS NOT NULL
            )"""
        if layout == services_module.LEGACY_FTS:
            con.execute(f"INSERT INTO source_fts(root, path, content) {select_missing}", (*params, *params))
        else:
            services_module.insert_fts_rows(con, layout, con.execute(select_missing, (*params, *params)))

    def _link_cached_source_text(
        self, con: sqlite3.Connection, root: str, now: float, paths: Sequence[str] | None = None,
    ) -> None:
        scope = ""
        params: tuple[str, ...] = (root,)
        if paths is not None:
            if not paths:
                return
            scope = " AND file_refs.path IN (" + ",".join("?" for _ in paths) + ")"
            params = (root, *paths)
        con.execute(
            f"""INSERT OR IGNORE INTO source_index(root, path, content_hash, text, updated_at, text_origin)
                SELECT ?, file_refs.path, file_refs.content_hash, COALESCE(cas.text, other.text), ?, 'source'
                FROM file_refs
                LEFT JOIN content_lexical AS cas ON cas.content_hash = file_refs.content_hash
                LEFT JOIN source_index AS other ON cas.content_hash IS NULL AND other.rowid = (
                    SELECT cached.rowid FROM source_index AS cached
                    WHERE cached.content_hash = file_refs.content_hash AND cached.text_origin='source' LIMIT 1
                )
                WHERE file_refs.root = ?{scope} AND file_refs.needs_hash=0 AND file_refs.content_hash <> ''
                  AND (cas.content_hash IS NOT NULL OR other.rowid IS NOT NULL)
                  AND NOT EXISTS (SELECT 1 FROM source_index AS s WHERE s.root = ? AND s.path = file_refs.path)""",
            (root, now, *params, root),
        )

    def _link_content_reuse(self, root: str) -> None:
        """Link content-addressed cards and lexical text from other worktrees."""
        from . import preprocess as services_module
        now = services_module.time.time()
        with self._db_lock, services_module.closing(self._connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            self._link_cached_file_cards(con, root)
            self._link_cached_source_text(con, root, now)
            self._link_missing_fts_rows(con, root)
            con.commit()

    def _rag_reindex_paths(self, root: str, workspace: str, *, limit: int) -> list[str]:
        selector = getattr(self.rag, "paths_needing_reindex", None)
        if not callable(selector):
            return []
        paths = selector(root, workspace=workspace, limit=limit)
        if paths is None:
            return []
        if not isinstance(paths, list) or any(type(path) is not str or not path for path in paths):
            raise RuntimeError("RAG stale-embedding path check returned an invalid result")
        return paths

    def _reconcile_missing_reference_rows(
        self, *, root: str, missing: list[str], existence: dict[str, str],
        pending_hashes: dict[str, str],
    ) -> None:
        # One missing-file batch can span hundreds of paths; bound each FTS cleanup transaction.
        from . import preprocess as services_module
        for offset in range(0, len(missing), services_module._MISSING_REF_WRITE_BATCH_SIZE):
            batch = missing[offset:offset + services_module._MISSING_REF_WRITE_BATCH_SIZE]
            with self._db_lock, services_module.closing(self._connect()) as con:
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                has_fts = "source_fts" in tables
                has_index = "source_index" in tables
                with services_module.write_transaction(con, max_duration_seconds=5.0, rollback_label="preprocessor missing refs"):
                    fts_paths: list[str] = []
                    for rel in batch:
                        status = existence[rel]
                        if status in ("missing", "escaped", "directory"):
                            deleted = con.execute(
                                "DELETE FROM file_refs WHERE root=? AND path=? AND content_hash=? AND needs_hash=0",
                                (root, rel, pending_hashes[rel]),
                            ).rowcount
                            if deleted:
                                if has_index:
                                    con.execute("DELETE FROM source_index WHERE root=? AND path=?", (root, rel))
                                if has_fts:
                                    fts_paths.append(rel)
                            else:
                                con.execute(
                                    "UPDATE file_refs SET needs_hash=1,rag_hash=NULL WHERE root=? AND path=? AND content_hash=? AND needs_hash=0",
                                    (root, rel, pending_hashes[rel]),
                                )
                        else:
                            # Uncertain or reappeared paths must be hashed again.
                            con.execute("UPDATE file_refs SET needs_hash=1,rag_hash=NULL WHERE root=? AND path=?", (root, rel))
                    if fts_paths:
                        placeholders = ",".join("?" for _ in fts_paths)
                        self._delete_fts_rows(
                            con, f"root=? AND path IN ({placeholders})",
                            (root, *fts_paths),
                        )

    def _find_lexical_pending(self, root: str, limit: int) -> list[sqlite3.Row]:
        from . import preprocess as services_module
        with self._db_lock, services_module.closing(self._connect()) as con:
            return con.execute(
                """SELECT f.path,f.content_hash FROM file_refs f
                   LEFT JOIN source_index s ON s.root=f.root AND s.path=f.path AND s.content_hash=f.content_hash
                   WHERE f.root=? AND f.needs_hash=0 AND f.content_hash<>'' AND s.path IS NULL
                   ORDER BY f.path LIMIT ?""",
                (root, max(1, limit)),
            ).fetchall()

    def _prune_missing_file_refs(self, root: str) -> int:
        """Remove files deleted without a file-level watcher event."""
        from . import preprocess as services_module
        base = services_module.Path(root)
        with self._db_lock, services_module.closing(self._connect()) as con:
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

        pruned = 0
        for offset in range(0, len(missing), 128):
            batch = missing[offset:offset + 128]
            for index in (self.code_index, self.deterministic):
                if index is None:
                    continue
                try:
                    if index is self.code_index:
                        # The code-index owns its trigram rows and cache generation;
                        # direct table deletes leave both stale.
                        index._remove_indexed_paths(root, batch)
                        continue
                    with services_module.closing(index._connect()) as con:
                        for table in ("files", "facts"):
                            con.executemany(f"DELETE FROM {table} WHERE root=? AND path=?", [(root, path) for path in batch])
                        con.commit()
                except (services_module.sqlite3.Error, OSError) as exc:
                    services_module.logger.warning("Could not prune deleted-file derived index (%s)", type(exc).__name__)
                    # Keep this batch's file references so a later pass can retry cleanup.
                    raise
            still_missing = []
            for rel in batch:
                try:
                    (base / rel).stat()
                except (FileNotFoundError, NotADirectoryError):
                    still_missing.append(rel)
                except OSError:
                    continue
            if not still_missing:
                continue

            def remove_refs(con: sqlite3.Connection) -> None:
                paths = [(root, path) for path in still_missing]
                con.executemany("DELETE FROM file_refs WHERE root=? AND path=?", paths)
                con.executemany("DELETE FROM source_index WHERE root=? AND path=?", paths)
                placeholders = ",".join("?" for _ in still_missing)
                self._delete_fts_rows(
                    con, f"root=? AND path IN ({placeholders})",
                    (root, *still_missing),
                )
                con.execute("DELETE FROM module_cards WHERE root=?", (root,))
                con.execute("DELETE FROM project_cards WHERE root=?", (root,))
                con.execute("DELETE FROM hot_query_state WHERE root=?", (root,))
                con.execute("DELETE FROM task_capsules WHERE root=?", (root,))

            self._write_retry(remove_refs)
            pruned += len(still_missing)
            with self._stats_lock:
                self._stats["missing_files_pruned"] = self._stats.get("missing_files_pruned", 0) + len(still_missing)
        return pruned

    def _proactive_git_seeds(self, root: str, allowed: dict[str, str]) -> list[str]:
        """Discover proactive initial seeds: git status, branch changes, and entrypoints."""
        from . import preprocess as services_module
        proactive: list[str] = []
        try:
            status = getattr(self.repo_tools, "git_status", None)
            if callable(status):
                git_st = status(root)
                if isinstance(git_st, dict):
                    for p in git_st.get("modified", []) + git_st.get("staged", []) + git_st.get("untracked", []):
                        norm = str(p).replace("\\", "/")
                        if norm in allowed and norm not in proactive:
                            proactive.append(norm)
        except Exception:
            pass

        entrypoint_names = {
            "main.py", "app.py", "server.py", "index.ts", "index.js", "main.ts", "main.js",
            "main.go", "lib.rs", "main.rs", "program.cs", "main.java", "app.rb",
        }
        for path in allowed:
            pure = services_module.PurePosixPath(path)
            if pure.name.lower() in entrypoint_names or (len(pure.parts) <= 2 and pure.suffix in {".py", ".ts", ".js", ".go", ".rs"}):
                if path not in proactive:
                    proactive.append(path)
                    if len(proactive) >= 16:
                        break

        return proactive[:32]

    @staticmethod
    def _bound_generation_set(s: set[tuple[Any, ...]], max_size: int = 512) -> set[tuple[Any, ...]]:
        if len(s) > max_size:
            return set(sorted(s, key=lambda item: item[1])[-max_size // 2:])
        return s

    def _external_revision(self, root: str) -> str:
        from . import preprocess as services_module
        with self._db_lock, services_module.closing(self._connect()) as con:
            rows = con.execute(
                "SELECT path,content_hash FROM file_refs WHERE root=? AND needs_hash=0 AND content_hash<>'' ORDER BY path",
                (root,),
            ).fetchall()
        return services_module.stable_hash([(str(row[0]), str(row[1])) for row in rows])

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

    def _ranked_lexical_paths(self, con: sqlite3.Connection, root: str, expression: str, limit: int) -> list[str]:
        from . import preprocess as services_module
        published = services_module.SHARED_FTS_ROWS if services_module.fts_layout(con) == services_module.SHARED_FTS_ROWS else services_module.LEGACY_FTS
        bindings = f"CROSS JOIN {published} ON {published}.id=source_fts.rowid" if published == services_module.SHARED_FTS_ROWS else ""
        rows = con.execute(
            f"""SELECT {published}.path FROM source_fts {bindings}
               JOIN file_refs f ON f.root={published}.root AND f.path={published}.path
               JOIN source_index s ON s.root=f.root AND s.path=f.path AND s.content_hash=f.content_hash
               WHERE {published}.root=? AND source_fts MATCH ? AND f.needs_hash=0 AND f.content_hash<>''
               ORDER BY bm25(source_fts),source_fts.rowid LIMIT ?""",
            (root, expression, limit),
        )
        return [str(row[0]) for row in rows]
