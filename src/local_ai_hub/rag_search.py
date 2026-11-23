from __future__ import annotations

from contextlib import closing
import heapq
import importlib
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any, Callable

from .cache import stable_hash
from .normalizer import normalize_query
from .rag_centroids import (
    _CENTROID_BUILD_LOCK,
    _centroid_cache_get,
    _centroid_cache_put,
    _centroid_threshold_reached,
)
from .rag_chunking import _fragment_hash
from .rag_constants import (
    ProjectPolicySyncError,
    RAG_CHUNKER_VERSION,
    _CENTROID_PROBES,
)
from .rag_search_helpers import _search_limit_reached, _semantic_embedding_query
from .search_modes import search_execution_stopped
from .sqlite_support import sqlite_batches


RAGStore = None


class RAGSearchMixin:
    def index_step(
        self,
        root: str,
        *,
        workspace: str | None = None,
        max_files: int = 2,
        should_yield: Any | None = None,
        dirty_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Index only a few changed files so idle preprocessing stays preemptible.

        Each call commits independently. Repeated calls converge to the same state as
        :meth:`index`, while foreground work can take over between calls.
        """
        root_path = Path(root).resolve()
        if not root_path.exists() or not root_path.is_dir():
            return {"success": False, "error": f"root directory does not exist: {root_path}"}
        project_context = self.project_context(root_path)
        if not self._project_phase_allowed(project_context, "rag"):
            target_ws = workspace or self.workspace_id(str(root_path))
            removed = self.prune_missing(root, target_ws, [])
            return {
                "success": True, "workspace": target_ws,
                "skipped": True, "reason": "project phase disabled", "done": True,
                "removed_paths": removed,
                "processed_files": 0,
            }
        workspace = workspace or self.workspace_id(str(root_path))
        with self._get_workspace_lock(workspace):
            try:
                self._sync_workspace_project_policy_identity(
                    root_path, workspace, project_context
                )
            except ProjectPolicySyncError as exc:
                return {"success": False, "error": str(exc), "retryable": exc.retryable}
            embedding_space = self._embedding_space_id()
            if callable(should_yield) and should_yield():
                return {"success": True, "workspace": workspace, "preempted": True, "done": False, "processed_files": 0}

            with closing(self._connect()) as con:
                old_rows = con.execute(
                    "SELECT path,mtime_ns,size,content_hash FROM files WHERE workspace=?",
                    (workspace,),
                ).fetchall()
                old_chunk_rows = con.execute(
                    "SELECT path,chunk_no,content_hash,embedding,embedding_space FROM chunks WHERE workspace=?",
                    (workspace,),
                ).fetchall()
                uncertain_retry_paths = self._workspace_read_uncertain_paths(con, workspace)
                stale_embedding_paths = {
                    str(row[0]).replace("\\", "/")
                    for row in old_chunk_rows
                    if str(row[4] or "") != embedding_space
                }
            old_files = {r[0]: {"mtime_ns": int(r[1]), "size": int(r[2]), "content_hash": r[3]} for r in old_rows}

            current_meta: dict[str, tuple[Path, int, int]] = {}
            for path in self._iter_files(root_path, project_context):
                try:
                    st = path.stat()
                    rel = str(path.relative_to(root_path)).replace("\\", "/")
                    current_meta[rel] = (path, int(st.st_mtime_ns), int(st.st_size))
                except OSError:
                    continue
            deleted = sorted(set(old_files) - set(current_meta))
            changed_all = [
                rel for rel, (_p, mt, sz) in current_meta.items()
                if rel not in old_files or old_files[rel]["mtime_ns"] != mt or old_files[rel]["size"] != sz
                or rel in stale_embedding_paths
                or rel in uncertain_retry_paths
            ]
            if dirty_paths:
                norm_dirty = set()
                for dp in dirty_paths:
                    try:
                        p_obj = Path(dp)
                        if p_obj.is_absolute():
                            norm_dirty.add(str(p_obj.relative_to(root_path)).replace("\\", "/"))
                        else:
                            norm_dirty.add(str(dp).replace("\\", "/"))
                    except Exception:
                        norm_dirty.add(str(dp).replace("\\", "/"))
                changed_all = sorted(set(changed_all) | (norm_dirty & set(current_meta)))
                changed_all.sort(key=lambda rel: (rel not in norm_dirty, rel))
            else:
                changed_all.sort()

            pending = sorted(set(changed_all) | set(deleted))
            selected = pending[: max(1, int(max_files))]
            selected_changed = [rel for rel in selected if rel in current_meta]
            selected_deleted = [rel for rel in selected if rel in deleted]
            staged = self.index_paths_step(
                str(root_path), workspace=workspace, paths=selected_changed,
                should_yield=should_yield, deleted_paths=selected_deleted,
            )
            if not staged.get("success"):
                return staged
            completed_paths = {
                str(path).replace("\\\\", "/") for path in staged.get("processed_paths", [])
            }
            completed_paths.update(
                str(path).replace("\\\\", "/") for path in staged.get("deleted_paths", [])
            )
            remaining_paths = set(pending) - completed_paths
            remaining = len(remaining_paths)
            return {
                "success": True, "workspace": workspace,
                "preempted": bool(staged.get("preempted", False)),
                "done": remaining == 0 and not staged.get("preempted", False),
                "processed_files": len(staged.get("processed_paths", [])) + len(selected_deleted),
                "remaining_changed_files": remaining,
                "deleted_files": len(selected_deleted),
                "embedded_chunks": staged.get("embedded_chunks", 0),
                "reused_chunks": staged.get("reused_chunks", 0),
            }

    @staticmethod
    def _dot(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            return 0.0
        if not all(math.isfinite(value) for value in (*a, *b)):
            return 0.0
        dot = RAGStore._dot(a, b)
        na = math.sqrt(RAGStore._dot(a, a))
        nb = math.sqrt(RAGStore._dot(b, b))
        score = dot / (na * nb) if na and nb else 0.0
        return score if math.isfinite(score) else 0.0

    def _revision_from_connection(
        self, con: sqlite3.Connection, workspace: str, generation: int, now: float,
        publication: str | None,
    ) -> str:
        if publication is not None:
            return stable_hash({
                "index": self.index_fingerprint, "workspace": workspace,
                "generation": generation, "publication": publication,
            })
        if not hasattr(self, "_rev_cache"):
            self._rev_cache: dict[str, tuple[float, str, int]] = {}
            self._rev_lock = threading.Lock()
        with self._rev_lock:
            cached = self._rev_cache.get(workspace)
            if cached and now - cached[0] < 3.0 and cached[2] == generation:
                return cached[1]
        rows = con.execute(
            "SELECT path,content_hash,mtime_ns,size FROM files WHERE workspace=? ORDER BY path",
            (workspace,),
        ).fetchall()
        rev = stable_hash({"index": self.index_fingerprint, "generation": generation, "files": rows})
        with self._rev_lock:
            if len(self._rev_cache) > 256:
                oldest_keys = sorted(self._rev_cache.keys(), key=lambda k: self._rev_cache[k][0])[:128]
                for k in oldest_keys:
                    self._rev_cache.pop(k, None)
            self._rev_cache[workspace] = (now, rev, generation)
        return rev

    def revision(self, *, workspace: str) -> str:
        now = time.monotonic()
        with closing(self._connect()) as con:
            con.execute("BEGIN")
            generation = self._workspace_index_generation(con, workspace)
            publication = self._workspace_publication(con, workspace, generation)
            return self._revision_from_connection(con, workspace, generation, now, publication)

    @staticmethod
    def _postprocess_search_payload(payload: dict[str, Any], top_k: int) -> dict[str, Any]:
        """Remove duplicate evidence after ranking without altering source text."""
        result = dict(payload)
        removed = 0
        limit = max(1, int(top_k))
        for list_key in ("results", "matches", "chunks", "evidence"):
            candidates = result.get(list_key)
            if not isinstance(candidates, list):
                continue
            seen: set[str] = set()
            unique: list[Any] = []
            for position, item in enumerate(candidates):
                if isinstance(item, dict):
                    identity = str(item.get("content_hash") or "")
                    if not identity:
                        text = item.get("text") or item.get("content") or item.get("excerpt")
                        identity = _fragment_hash(str(text)) if text else stable_hash(item)
                else:
                    identity = _fragment_hash(str(item))
                if identity in seen:
                    removed += 1
                    continue
                seen.add(identity)
                unique.append(item)
                if len(unique) >= limit:
                    removed += len(candidates) - position - 1
                    break
            result[list_key] = unique
        if removed:
            result["deterministic_postprocess"] = {"deduplicated": removed}
        return result

    def search(self, query: str, *, workspace: str, top_k: int = 8, use_reranker: bool = True, priority: int = 3, scope_path: str | None = None, deadline: float | None = None, cancel_event: Any | None = None, semantic_only: bool = False) -> dict[str, Any]:
        clean_query = normalize_query(query)
        embedding_query = _semantic_embedding_query(clean_query) if semantic_only else clean_query
        semantic_search_options = (
            {"semantic_only": True, "embedding_query": embedding_query}
            if semantic_only else {}
        )
        cache_identity_known = self._embedding_space_cache_identity_known()
        query_space = self._embedding_space_id()
        with closing(self._connect()) as con:
            con.execute("BEGIN")
            generation = self._workspace_index_generation(con, workspace)
            publication = self._workspace_publication(con, workspace, generation)
            stored_chunker_version = self._stored_workspace_chunker_version(con, workspace)
            revision = self._revision_from_connection(
                con, workspace, generation, time.monotonic(), publication,
            )
        cache_dimension = self._embedding_dimension_cache_identity()

        def cache_key(space: str | None, dimension: dict[str, Any], index_generation: int) -> str:
            return stable_hash({
                "workspace": workspace, "revision": revision, "generation": index_generation,
                "query": clean_query, "top_k": top_k, "reranker": use_reranker, "semantic_only": semantic_only,
                "semantic_query": embedding_query,
                "scope_path": scope_path,
                "chunker_version": RAG_CHUNKER_VERSION,
                "stored_chunker_version": stored_chunker_version,
                "embedding_space": space if cache_identity_known else None,
                "embedding_dimension": dimension,
            })

        key = cache_key(query_space, cache_dimension, generation)
        observed_identity: dict[str, Any] = {}

        def is_transient_fallback(result: Any) -> bool:
            return isinstance(result, dict) and (
                result.get("retrieval_mode") == "lexical_fallback"
                or result.get("fallback") == "embedding_backend"
            )

        def compute_search() -> dict[str, Any]:
            if deadline is not None or cancel_event is not None:
                raw_result = self._search_uncached(
                    clean_query, workspace, top_k, use_reranker, priority, scope_path,
                    deadline=deadline, cancel_event=cancel_event,
                    allow_cpu_fallback=False, **semantic_search_options,
                )
            else:
                raw_result = self._search_uncached(
                    clean_query, workspace, top_k, use_reranker, priority, scope_path,
                    allow_cpu_fallback=False, **semantic_search_options,
                )
            if search_execution_stopped(raw_result):
                return {**raw_result, "success": False, "_cacheable": False}
            if is_transient_fallback(raw_result):
                return {**raw_result, "_cacheable": False}
            deadline_fallbacks = ("deadline_exceeded", "reranker_deadline_skipped")
            if isinstance(raw_result, dict) and raw_result.get("success") is True and (
                _search_limit_reached(deadline, cancel_event)
                or raw_result.get("fallback") in deadline_fallbacks
                or any(flag in (raw_result.get("fallbacks") or ()) for flag in deadline_fallbacks)
            ):
                # A partial result must not be published under either embedding identity.
                return {**raw_result, "_cacheable": False}
            observed_identity["space"] = self._embedding_space_id()
            observed_identity["dimension"] = self._embedding_dimension_cache_identity()
            return raw_result

        def get_cached_search(search_key: str, compute: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], bool, bool]:
            wait_options: dict[str, Any] = {}
            if deadline is not None:
                wait_options["wait_timeout_seconds"] = max(0.01, deadline - time.perf_counter())
            if cancel_event is not None:
                wait_options["cancel_event"] = cancel_event
            return self.search_flight.get_or_compute(search_key, compute, **wait_options)

        if cache_identity_known:
            raw, hit, coalesced = get_cached_search(key, compute_search)
            actual_space = observed_identity.get("space")
            actual_dimension = observed_identity.get("dimension")
            if (
                actual_dimension is not None
                and (actual_space != query_space or actual_dimension != cache_dimension)
            ):
                self.search_flight.cache.delete(key)
                key = cache_key(str(actual_space) if actual_space else None, actual_dimension, generation)
                computed_raw = raw
                raw, hit, coalesced = get_cached_search(key, lambda: computed_raw)
            if hit and is_transient_fallback(raw):
                self.search_flight.cache.delete(key)
        else:
            if deadline is not None or cancel_event is not None:
                raw = self._search_uncached(
                    clean_query, workspace, top_k, use_reranker, priority, scope_path,
                    deadline=deadline, cancel_event=cancel_event,
                    allow_cpu_fallback=False, **semantic_search_options,
                )
            else:
                raw = self._search_uncached(
                    clean_query, workspace, top_k, use_reranker, priority, scope_path,
                    deadline=deadline, cancel_event=cancel_event,
                    allow_cpu_fallback=False, **semantic_search_options,
                )
            hit, coalesced = False, False
        if search_execution_stopped(raw):
            result = {**raw, "index_revision": revision,
                      "search_cache": {"hit": hit, "coalesced": coalesced, "revision": revision}}
            result.pop("_cacheable", None)
            return result
        with closing(self._connect()) as con:
            con.execute("BEGIN")
            latest_generation = self._workspace_index_generation(con, workspace)
            latest_publication = self._workspace_publication(con, workspace, latest_generation)
            index_changed = latest_generation != generation or latest_publication != publication
            if index_changed:
                revision = self._revision_from_connection(
                    con, workspace, latest_generation, time.monotonic(), latest_publication,
                )
            latest_chunker_index_current = self._workspace_chunker_index_is_current(con, workspace)
        if index_changed:
            raw = self._search_uncached(
                clean_query, workspace, top_k, use_reranker, priority, scope_path,
                deadline=deadline, cancel_event=cancel_event,
                allow_cpu_fallback=False, **semantic_search_options,
            )
            hit, coalesced = False, False
        result = dict(raw) if isinstance(raw, dict) else {"success": False, "error": "search failed"}
        if result.get("reindex_required") is True and (
            result.get("fallback") == "embedding_space_mismatch"
            or "embedding_space_rebuild_pending" in (result.get("fallbacks") or ())
        ):
            target_space = result.get("embedding_space_id")
            if isinstance(target_space, str) and target_space:
                try:
                    self._request_workspace_reindex(workspace, target_space)
                    result["reindex_scheduled"] = True
                except Exception as exc:
                    result["reindex_scheduled"] = False
                    result["reindex_schedule_error"] = str(exc)
            else:
                result["reindex_scheduled"] = False
        result["index_revision"] = revision
        result["search_cache"] = {"hit": hit, "coalesced": coalesced, "revision": revision}
        if not latest_chunker_index_current:
            result["degraded"] = True
            result["reindex_required"] = True
            result["index_state"] = "stale"
            result["stale_reason"] = "chunker_version_mismatch"
        return self._postprocess_search_payload(result, top_k) if isinstance(result, dict) else result

    @staticmethod
    def _search_path_exclusion(
        con: sqlite3.Connection, excluded_paths: set[str] | None, column: str
    ) -> str:
        paths = excluded_paths or set()
        if "*" in paths:
            return " AND 0"
        if not paths:
            return ""
        con.execute("CREATE TEMP TABLE rag_uncertain_paths(path TEXT PRIMARY KEY)")
        con.executemany(
            "INSERT OR IGNORE INTO rag_uncertain_paths(path) VALUES(?)",
            [(path,) for path in sorted(paths)],
        )
        con.commit()
        return f" AND {column} NOT IN (SELECT path FROM rag_uncertain_paths)"

    @staticmethod
    def _fts_error_status(error: sqlite3.Error) -> str:
        message = str(error).lower()
        if any(token in message for token in ("database is locked", "database is busy", "locked", "busy", "timeout")):
            return "FTS_TIMEOUT/LOCKED"
        if "malformed" in message or "corrupt" in message:
            return "FTS_INDEX_CORRUPT"
        if any(token in message for token in ("syntax error", "unterminated", "no such column")):
            return "FTS_QUERY_INVALID"
        if any(token in message for token in ("no such table", "no such module", "fts5 is not available")):
            return "FTS_UNAVAILABLE"
        return "FTS_UNAVAILABLE"

    def _search_fts_candidates(
        self, query: str, workspace: str, limit: int = 16,
        scope_path: str | None = None, embedding_space: str | None = None,
        excluded_paths: set[str] | None = None,
    ) -> dict[str, Any]:
        try:
            tokens = [re.sub(r"[^\w_]", "", t) for t in query.split()]
            tokens = [t for t in tokens if len(t) > 1]
            if not tokens:
                return {"status": "MATCHES_EMPTY", "candidates": []}
            fts_expr = " OR ".join(f'"{t}"' for t in tokens[:8])
            space_filter = " AND c.embedding_space=?" if embedding_space is not None else ""
            space_params = (embedding_space,) if embedding_space is not None else ()
            with closing(self._connect()) as con:
                path_filter = self._search_path_exclusion(con, excluded_paths, "c.path")
                if scope_path:
                    norm_scope = scope_path.replace("\\", "/").rstrip("/")
                    fts_rows = con.execute(
                        f"""SELECT c.path, c.chunk_no, c.text, c.content_hash, bm25(chunk_fts)
                           FROM chunk_fts
                           JOIN chunks c ON c.workspace=chunk_fts.workspace AND c.path=chunk_fts.path AND c.chunk_no=chunk_fts.chunk_no
                           WHERE chunk_fts.workspace=? AND (chunk_fts.path=? OR chunk_fts.path LIKE ? || '/%'){space_filter}{path_filter} AND chunk_fts MATCH ?
                           ORDER BY bm25(chunk_fts) LIMIT ?""",
                        (workspace, norm_scope, norm_scope, *space_params, fts_expr, limit),
                    ).fetchall()
                else:
                    fts_rows = con.execute(
                        f"""SELECT c.path, c.chunk_no, c.text, c.content_hash, bm25(chunk_fts)
                           FROM chunk_fts
                           JOIN chunks c ON c.workspace=chunk_fts.workspace AND c.path=chunk_fts.path AND c.chunk_no=chunk_fts.chunk_no
                           WHERE chunk_fts.workspace=?{space_filter}{path_filter} AND chunk_fts MATCH ?
                           ORDER BY bm25(chunk_fts) LIMIT ?""",
                        (workspace, *space_params, fts_expr, limit),
                    ).fetchall()
                candidates = [
                    {
                        "path": r[0], "chunk_no": r[1], "text": r[2], "content_hash": r[3],
                        "fts_score": float(r[4]),
                    }
                    for r in fts_rows
                ]
                return {"status": "MATCHES_FOUND" if candidates else "MATCHES_EMPTY", "candidates": candidates}
        except sqlite3.Error as exc:
            return {"status": self._fts_error_status(exc), "candidates": []}

    def _search_token_overlap(
        self, query: str, workspace: str, limit: int = 16,
        scope_path: str | None = None, embedding_space: str | None = None,
        excluded_paths: set[str] | None = None,
        *, deadline: float | None = None, cancel_event: Any | None = None,
    ) -> list[dict[str, Any]]:
        terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 1]
        if not terms or limit <= 0:
            return []

        def token_hits(text: str) -> int:
            lowered = str(text).lower()
            hits = 0
            for term in terms:
                hits += term in lowered
            return hits

        scope_filter = ""
        scope_params: tuple[str, ...] = ()
        if scope_path:
            norm_scope = scope_path.replace("\\", "/").rstrip("/")
            scope_filter = " AND (path=? OR path LIKE ? || '/%')"
            scope_params = (norm_scope, norm_scope)
        space_filter = " AND embedding_space=?" if embedding_space is not None else ""
        space_params = (embedding_space,) if embedding_space is not None else ()
        best: list[tuple[int, int, int]] = []
        bounded = deadline is not None or cancel_event is not None
        budget_error = "RAG token overlap search exceeded its budget"
        if _search_limit_reached(deadline, cancel_event):
            raise TimeoutError(budget_error)

        with closing(self._connect()) as con:
            if bounded:
                con.set_progress_handler(lambda: int(_search_limit_reached(deadline, cancel_event)), 1000)
            try:
                path_filter = self._search_path_exclusion(con, excluded_paths, "path")
                con.execute("BEGIN")
                con.create_function("rag_token_hits", 1, token_hits)
                # The subquery boundary keeps one score evaluation per scanned row.
                ranked = con.execute(
                    f"""SELECT rowid, hits FROM (
                            SELECT rowid, rag_token_hits(text) AS hits FROM chunks
                            WHERE workspace=?{scope_filter}{space_filter}{path_filter}
                            LIMIT -1 OFFSET 0
                        ) WHERE hits>0""",
                    (workspace, *scope_params, *space_params),
                )
                with closing(ranked):
                    for seq, (row_id, hits) in enumerate(ranked):
                        if bounded and seq % 64 == 0 and _search_limit_reached(deadline, cancel_event):
                            raise TimeoutError(budget_error)
                        entry = (hits, -seq, row_id)
                        if len(best) < limit:
                            heapq.heappush(best, entry)
                        elif entry > best[0]:
                            heapq.heapreplace(best, entry)
                        # Later equal scores cannot outrank the retained perfect matches.
                        if len(best) == limit and best[0][0] == len(terms):
                            break

                chunks = {}
                for batch in sqlite_batches([entry[2] for entry in best]):
                    placeholders = ",".join("?" for _ in batch)
                    chunks.update(
                        (row[0], row[1:]) for row in con.execute(
                            f"SELECT rowid,path,chunk_no,text,content_hash FROM chunks WHERE rowid IN ({placeholders})",
                            batch,
                        )
                    )
            except sqlite3.OperationalError as exc:
                if bounded and getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_INTERRUPT:
                    raise TimeoutError(budget_error) from exc
                raise

        if _search_limit_reached(deadline, cancel_event):
            raise TimeoutError(budget_error)
        results = []
        for hits, _seq, row_id in sorted(best, reverse=True):
            path, chunk_no, text, content_hash = chunks[row_id]
            results.append({
                "path": path, "chunk_no": chunk_no, "text": text,
                "content_hash": content_hash, "fts_score": hits / len(terms),
            })
        return results

    def _centroid_index_for_search(
        self, workspace: str, embedding_space: str, query_vector: Any,
    ) -> tuple[int, tuple[tuple[str, int], ...]] | None:
        try:
            np = importlib.import_module("numpy")
        except Exception:
            return None
        dimension = int(getattr(query_vector, "size", len(query_vector) if isinstance(query_vector, (list, tuple)) else 0))
        if dimension <= 0 or dimension > 4096:
            return None
        with closing(self._connect()) as con:
            generation = self._workspace_index_generation(con, workspace)
            row = con.execute(
                "SELECT COUNT(*) FROM chunks WHERE workspace=? AND embedding_space=? AND embedding_space<>''",
                (workspace, embedding_space),
            ).fetchone()
            chunk_count = int(row[0]) if row else 0
        if not _centroid_threshold_reached(chunk_count):
            return None
        key = (str(self.db_path.resolve()), workspace, embedding_space, dimension, generation)
        cached = _centroid_cache_get(key)
        if cached is None:
            with _CENTROID_BUILD_LOCK:
                cached = _centroid_cache_get(key)
                if cached is None:
                    cached = self._build_centroid_index(
                        workspace, embedding_space, dimension, generation, chunk_count
                    )
                    if cached is not None and not _centroid_cache_put(key, cached):
                        return None
                    cached = _centroid_cache_get(key)
        if cached is None:
            return None
        centers, buckets, _ = cached
        query = np.asarray(query_vector, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(query))
        if query.size != dimension or not math.isfinite(norm) or norm <= 1e-9:
            return None
        similarities = np.dot(centers, query / norm)
        ordered = np.argsort(-similarities, kind="stable")
        selected: list[tuple[str, int]] = []
        for cluster_id in ordered[: min(_CENTROID_PROBES, len(centers))]:
            selected.extend(buckets.get(int(cluster_id), ()))
        return (generation, tuple(selected)) if selected else None

