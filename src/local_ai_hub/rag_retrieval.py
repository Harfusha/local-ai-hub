from __future__ import annotations

from contextlib import closing
import heapq
import importlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from typing import Any

from .rag_centroids import (
    _decode_centroid_vector,
    _fine_cosine_scores,
)
from .rag_chunking import _reverse_text_order
from .rag_constants import (
    _CENTROID_COUNT,
    _CENTROID_ENTRY_MAX_BYTES,
    _CENTROID_FILTER_ENABLED,
    _CENTROID_ITERATIONS,
    _CENTROID_SAMPLE_SIZE,
    _MAX_RERANK_CANDIDATES,
)
from .rag_search_helpers import _search_limit_reached
from .search_modes import search_execution_stopped
from .sqlite_support import connect_sqlite, write_transaction


RAGStore = None


class RAGRetrievalMixin:
    def _build_centroid_index(
        self, workspace: str, embedding_space: str,
        dimension: int, generation: int, chunk_count: int,
    ) -> tuple[Any, dict[int, tuple[tuple[str, int], ...]], int] | None:
        try:
            np = importlib.import_module("numpy")
        except Exception:
            return None
        sample_count = min(_CENTROID_SAMPLE_SIZE, chunk_count)
        if sample_count < 2:
            return None
        positions = {
            round(index * (chunk_count - 1) / max(1, sample_count - 1))
            for index in range(sample_count)
        }
        query = (
            "SELECT path,chunk_no,embedding FROM chunks WHERE workspace=? "
            "AND embedding_space=? AND embedding_space<>'' ORDER BY path,chunk_no"
        )
        with closing(self._connect()) as con:
            con.execute("BEGIN")
            if self._workspace_index_generation(con, workspace) != generation:
                return None
            sample = []
            sample_path_bytes = 0
            cursor = con.execute(query, (workspace, embedding_space))
            position = 0
            try:
                while True:
                    batch = cursor.fetchmany(512)
                    if not batch:
                        break
                    for path, _, raw in batch:
                        if position in positions:
                            vector = _decode_centroid_vector(raw, dimension, np)
                            if vector is None:
                                return None
                            sample.append(vector)
                            sample_path_bytes += len(str(path).encode("utf-8"))
                        position += 1
            finally:
                cursor.close()
            if len(sample) < 2:
                return None
            training = np.stack(sample).astype(np.float32, copy=False)
            centers = [training[0].copy()]
            while len(centers) < min(_CENTROID_COUNT, len(training)):
                nearest = np.max(np.dot(training, np.stack(centers).T), axis=1)
                candidate = training[int(np.argmin(nearest))]
                if float(np.max(np.dot(np.stack(centers), candidate))) > 0.99999:
                    break
                centers.append(candidate.copy())
            centers_array = np.stack(centers).astype(np.float32, copy=False)
            for _ in range(_CENTROID_ITERATIONS):
                labels = np.argmax(np.dot(training, centers_array.T), axis=1)
                updated = []
                for cluster_id in range(len(centers_array)):
                    members = training[labels == cluster_id]
                    if len(members):
                        center = members.mean(axis=0)
                        norm = float(np.linalg.norm(center))
                        if norm > 1e-9:
                            updated.append(center / norm)
                if not updated:
                    return None
                centers_array = np.stack(updated).astype(np.float32, copy=False)

            estimated_entry_bytes = int(
                centers_array.nbytes
                + chunk_count * (sample_path_bytes // max(1, len(sample)) + 256)
            )
            if estimated_entry_bytes > _CENTROID_ENTRY_MAX_BYTES:
                return None

            buckets: dict[int, list[tuple[str, int]]] = {index: [] for index in range(len(centers_array))}
            retained_bytes = int(centers_array.nbytes)
            cursor = con.execute(query, (workspace, embedding_space))
            try:
                while True:
                    batch = cursor.fetchmany(256)
                    if not batch:
                        break
                    vectors = []
                    for _, _, raw in batch:
                        vector = _decode_centroid_vector(raw, dimension, np)
                        if vector is None:
                            return None
                        vectors.append(vector)
                    labels = np.argmax(np.dot(np.stack(vectors), centers_array.T), axis=1)
                    for (path, chunk_no, _), cluster_id in zip(batch, labels):
                        path = str(path)
                        retained_bytes += len(path.encode("utf-8")) + 256
                        if retained_bytes > _CENTROID_ENTRY_MAX_BYTES:
                            return None
                        buckets[int(cluster_id)].append((path, int(chunk_no)))
            finally:
                cursor.close()
            if self._workspace_index_generation(con, workspace) != generation:
                return None
        return centers_array, {key: tuple(value) for key, value in buckets.items()}, retained_bytes

    def _search_uncached(self, query: str, workspace: str, top_k: int = 8, use_reranker: bool = True, priority: int = 3, scope_path: str | None = None, deadline: float | None = None, cancel_event: Any | None = None, *, lexical_only: bool = False, semantic_only: bool = False, embedding_query: str | None = None, allow_cpu_fallback: bool = True) -> dict[str, Any]:
        with closing(self._connect()) as con:
            con.execute("BEGIN")
            uncertain_paths = self._workspace_read_uncertain_paths(con, workspace)
            has_chunks = con.execute(
                "SELECT 1 FROM chunks WHERE workspace=? LIMIT 1", (workspace,)
            ).fetchone() is not None
            # An explicit service space can bypass inference only when the index
            # also lacks vectors in that space. Older searches could leave a stale marker.
            active_space = getattr(self.services, "space_id", None)
            if semantic_only and isinstance(active_space, str) and active_space:
                stored_space = self._stored_workspace_embedding_space(con, workspace)
                if (stored_space and stored_space != active_space
                        and not self._workspace_has_vectors_in_space(con, workspace, active_space)):
                    return {
                        "success": True, "workspace": workspace, "results": [],
                        "degraded": True, "fallback": "embedding_space_mismatch",
                        "reason": "indexed vectors do not match the active query embedding space",
                        "reindex_required": True, "embedding_space_id": active_space,
                    }

        if semantic_only and not has_chunks:
            if uncertain_paths:
                return {
                    "success": True, "workspace": workspace, "results": [],
                    "degraded": True, "fallback": "source_read_uncertain",
                    "index_state": "stale", "reindex_required": True,
                }
            return {
                "success": True, "workspace": workspace, "results": [],
                "degraded": True, "fallback": "empty_index", "index_state": "empty",
            }

        def visible(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [item for item in candidates if "*" not in uncertain_paths and str(item.get("path", "")) not in uncertain_paths]

        def deadline_result(fallbacks: list[str] | None = None) -> dict[str, Any]:
            return {
                "success": True, "workspace": workspace, "results": [],
                "degraded": True, "fallback": "deadline_exceeded",
                "fallbacks": fallbacks or ["deadline_exceeded"], "reason": "search deadline was exceeded",
            }

        remaining = deadline - time.perf_counter() if deadline is not None else None
        if (remaining is not None and remaining <= 0) or (cancel_event is not None and cancel_event.is_set()):
            return deadline_result()

        if lexical_only:
            query_result = {"success": False, "error": "embedding_disabled"}
        else:
            try:
                embed_options: dict[str, Any] = {}
                if remaining is not None:
                    embed_options["wait_timeout"] = remaining
                if cancel_event is not None:
                    embed_options["cancel_event"] = cancel_event
                query_result = self.services.embed(
                    [embedding_query if embedding_query is not None else query],
                    priority=priority, query=True, **embed_options,
                )
            except Exception as exc:
                query_result = {"success": False, "error": str(exc)}
            if search_execution_stopped(query_result):
                return {**query_result, "success": False, "workspace": workspace, "results": []}
            if _search_limit_reached(deadline, cancel_event):
                return deadline_result()
        if query_result.get("success"):
            embeddings = query_result.get("embeddings")
            try:
                if not isinstance(embeddings, (list, tuple)) or not embeddings:
                    raise TypeError("embedding result has no query vector")
                query_vector = [float(value) for value in embeddings[0]]
                valid_query_vector = (
                    bool(query_vector)
                    and all(math.isfinite(value) for value in query_vector)
                )
                if valid_query_vector:
                    query_norm = math.sqrt(sum(value * value for value in query_vector))
                    valid_query_vector = math.isfinite(query_norm) and query_norm > 1e-9
            except (IndexError, KeyError, TypeError, ValueError, OverflowError):
                valid_query_vector = False
            if not valid_query_vector:
                query_result = {**query_result, "success": False, "error": "invalid_query_embedding"}
        if not query_result.get("success"):
            if semantic_only:
                return {"success": True, "workspace": workspace, "results": [], "degraded": True,
                        "fallback": "embedding_backend", "reason": str(query_result.get("error", "embedder_unavailable"))}
            lexical_backend = "fts5"
            fts_raw = self._search_fts_candidates(
                query, workspace, max(16, top_k * 2), scope_path,
                excluded_paths=uncertain_paths,
            )
            if _search_limit_reached(deadline, cancel_event):
                return deadline_result()
            fts_result = (
                fts_raw if isinstance(fts_raw, dict)
                else {"status": "MATCHES_FOUND" if fts_raw else "MATCHES_EMPTY", "candidates": fts_raw}
            )
            candidates = visible(fts_result["candidates"])
            fallback_used = False
            if not candidates:
                lexical_backend = "token_overlap"
                try:
                    candidates = visible(self._search_token_overlap(
                        query, workspace, max(16, top_k * 2), scope_path,
                        excluded_paths=uncertain_paths, deadline=deadline, cancel_event=cancel_event,
                    ))
                except TimeoutError:
                    return deadline_result()
                fallback_used = True
            results = [
                {
                    "path": c["path"],
                    "chunk_no": c["chunk_no"],
                    "text": c.get("text", ""),
                    "content_hash": c.get("content_hash", ""),
                    "score": float(c.get("fts_score", 0.5)),
                }
                for c in candidates[:top_k]
            ]
            return {
                "success": True,
                "workspace": workspace,
                "results": results,
                "degraded": True,
                "fallback": "source_read_uncertain" if uncertain_paths else "bm25_fts",
                "retrieval_mode": "lexical_fallback",
                "lexical_backend": lexical_backend,
                "component_status": {
                    "fts": fts_result["status"],
                    "lexical_fallback": "FALLBACK_USED" if fallback_used else "not_used",
                },
                "fallback_used": fallback_used,
                "reason": str(query_result.get("error", "embedder_unavailable")),
            }
        query_vec = query_result["embeddings"][0]
        embedding_space = self._embedding_space_id(query_result)
        embedding_space_resolved = self._embedding_space_is_resolved(query_result)
        stored_embedding_space: str | None = None
        stored_embedding_space_read = False
        fallbacks: list[str] = []
        if uncertain_paths:
            fallbacks.append("source_read_uncertain")
        if query_result.get("degraded"):
            fallbacks.append(str(query_result.get("fallback") or "embedding_backend"))

        rag_cfg = self.config.get("rag", {})
        candidate_limit = min(_MAX_RERANK_CANDIDATES, max(16, int(rag_cfg.get("rerank_candidates", 16))))
        query_dim = len(query_vec) if isinstance(query_vec, (list, tuple)) else int(getattr(query_vec, "size", 0))
        configured_batch = int(rag_cfg.get("search_batch_size", 512))
        batch_size = min(8192, max(32, configured_batch))
        if query_dim > 0:
            batch_size = min(batch_size, max(32, (1024 * 1024) // query_dim))
        best: list[tuple[float, tuple[int, ...], int, tuple[int, ...], dict[str, Any]]] = []
        rows_seen = 0
        try:
            import numpy as np
        except Exception:
            np = None

        centroid_index = None
        # Workspace-wide centroids cannot guarantee coverage after a path
        # scope or read-uncertainty exclusion is applied. Keep those queries
        # exact so the prefilter cannot hide their only matching chunks.
        if (
            _CENTROID_FILTER_ENABLED
            and np is not None
            and embedding_space_resolved
            and not scope_path
            and not uncertain_paths
        ):
            try:
                centroid_index = self._centroid_index_for_search(
                    workspace, embedding_space, query_vec
                )
            except Exception:
                centroid_index = None

        if np is not None:
            q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
            dimension = int(q.size)
            q_norm = float(np.linalg.norm(q))
            if q_norm > 1e-9:
                q = q / q_norm
            else:
                q = np.zeros(dimension, dtype=np.float32)

        def offer(row: Any, score: float) -> None:
            if "*" in uncertain_paths or str(row[0]) in uncertain_paths:
                return
            score = float(score)
            if not math.isfinite(score):
                score = 0.0
            item = {
                "path": row[0], "chunk_no": row[1], "content_hash": row[3],
                "embedding_score": score,
            }
            entry = (
                score,
                _reverse_text_order(str(row[0])),
                -int(row[1]),
                _reverse_text_order(str(row[3] or "")),
                item,
            )
            if len(best) < candidate_limit:
                heapq.heappush(best, entry)
            elif entry[:4] > best[0][:4]:
                heapq.heapreplace(best, entry)

        with closing(self._connect()) as con:
            # Keep one read snapshot across keyset batches, but close each SQL
            # cursor before vector parsing/scoring so the statement VM is idle.
            path_filter = self._search_path_exclusion(con, uncertain_paths, "path")
            con.execute("BEGIN")
            norm_scope = scope_path.replace("\\", "/").rstrip("/") if scope_path else None
            centroid_active = False
            if centroid_index is not None:
                centroid_generation, centroid_rows = centroid_index
                if self._workspace_index_generation(con, workspace) == centroid_generation:
                    con.execute(
                        "CREATE TEMP TABLE IF NOT EXISTS rag_centroid_candidates "
                        "(path TEXT NOT NULL, chunk_no INTEGER NOT NULL, PRIMARY KEY(path,chunk_no)) WITHOUT ROWID"
                    )
                    con.execute("DELETE FROM rag_centroid_candidates")
                    con.executemany(
                        "INSERT OR IGNORE INTO rag_centroid_candidates(path,chunk_no) VALUES(?,?)",
                        centroid_rows,
                    )
                    centroid_active = True
            last_path: str | None = None
            last_chunk_no: int | None = None
            while True:
                if _search_limit_reached(deadline, cancel_event):
                    fallbacks.append("deadline_exceeded")
                    break
                predicates = ["workspace=?", "embedding_space=?", "embedding_space<>''"]
                params: list[Any] = [workspace, embedding_space]
                if centroid_active:
                    predicates.append(
                        "EXISTS (SELECT 1 FROM rag_centroid_candidates cc "
                        "WHERE cc.path=chunks.path AND cc.chunk_no=chunks.chunk_no)"
                    )
                if path_filter:
                    predicates.append(path_filter.removeprefix(" AND "))
                if norm_scope is not None:
                    predicates.append("(path=? OR path LIKE ? || '/%')")
                    params.extend((norm_scope, norm_scope))
                if last_path is not None:
                    predicates.append("(path>? OR (path=? AND chunk_no>?))")
                    params.extend((last_path, last_path, last_chunk_no))
                cursor = con.execute(
                    "SELECT chunks.path, chunks.chunk_no, chunks.embedding, chunks.content_hash FROM chunks AS chunks WHERE "
                    + " AND ".join(predicates)
                    + " ORDER BY path, chunk_no LIMIT ?",
                    (*params, batch_size),
                )
                try:
                    batch = cursor.fetchmany(batch_size)
                finally:
                    cursor.close()
                if not batch:
                    break
                rows_seen += len(batch)
                last_path, last_chunk_no = str(batch[-1][0]), int(batch[-1][1])

                if np is not None:
                    if all(isinstance(row[2], (bytes, memoryview)) and len(row[2]) == dimension * 4 for row in batch):
                        packed = b"".join(bytes(row[2]) for row in batch)
                        matrix = np.frombuffer(packed, dtype=np.float32).reshape(len(batch), dimension)
                    else:
                        matrix = np.zeros((len(batch), dimension), dtype=np.float32)
                        for index, row in enumerate(batch):
                            raw = row[2]
                            try:
                                if isinstance(raw, (bytes, memoryview)):
                                    vector = np.frombuffer(raw, dtype=np.float32)
                                elif isinstance(raw, str):
                                    vector = np.asarray(json.loads(raw), dtype=np.float32).reshape(-1)
                                else:
                                    continue
                                if vector.size == dimension:
                                    matrix[index] = vector
                            except (TypeError, ValueError, OverflowError, json.JSONDecodeError):
                                continue
                    scores = _fine_cosine_scores(matrix, q)
                    local_count = min(candidate_limit, len(batch))
                    if local_count < len(batch):
                        kth = len(batch) - local_count
                        partition = np.argpartition(scores, kth)
                        cutoff = scores[partition[kth]]
                        above = np.flatnonzero(scores > cutoff)
                        tied = np.flatnonzero(scores == cutoff)
                        remaining = local_count - len(above)
                        if tied.size > remaining:
                            tie_paths = np.asarray([str(batch[int(index)][0]) for index in tied], dtype=np.str_)
                            tie_chunks = np.fromiter(
                                (int(batch[int(index)][1]) for index in tied), dtype=np.int64, count=len(tied)
                            )
                            tie_hashes = np.asarray(
                                [str(batch[int(index)][3] or "") for index in tied], dtype=np.str_
                            )
                            tie_order = np.lexsort((tie_hashes, tie_chunks, tie_paths))
                            tied = tied[tie_order[:remaining]]
                        candidate_indices = np.concatenate((above, tied))
                    else:
                        candidate_indices = np.arange(len(batch), dtype=np.intp)
                    for index in candidate_indices:
                        offer(batch[int(index)], float(scores[int(index)]))
                else:
                    import struct

                    for index, row in enumerate(batch):
                        raw = row[2]
                        try:
                            if isinstance(raw, (bytes, memoryview)) and len(raw) % 4 == 0:
                                vector = struct.unpack(f"{len(raw) // 4}f", raw)
                            elif isinstance(raw, str):
                                vector = [float(value) for value in json.loads(raw)]
                            else:
                                vector = []
                            score = self._cosine(query_vec, vector) if len(vector) == len(query_vec) else 0.0
                        except (TypeError, ValueError, OverflowError, struct.error, json.JSONDecodeError):
                            score = 0.0
                        offer(row, score)
            has_stale_embedding_rows = self._workspace_has_stale_vectors(con, workspace, embedding_space)
            can_repair_metadata = (
                embedding_space_resolved and rows_seen > 0 and not has_stale_embedding_rows
                and "deadline_exceeded" not in fallbacks
            )
            if can_repair_metadata:
                try:
                    stored_embedding_space = self._stored_workspace_embedding_space(con, workspace)
                    stored_embedding_space_read = True
                except sqlite3.Error:
                    pass

        if can_repair_metadata:
            try:
                if not stored_embedding_space_read or stored_embedding_space != embedding_space:
                    with closing(self._connect()) as con, write_transaction(
                        con, max_duration_seconds=5.0, rollback_label="RAG embedding metadata"
                    ):
                        if (self._stored_workspace_embedding_space(con, workspace) != embedding_space
                                and self._workspace_has_vectors_in_space(con, workspace, embedding_space)
                                and not self._workspace_has_stale_vectors(con, workspace, embedding_space)):
                            self._store_workspace_embedding_space(con, workspace, embedding_space)
            except sqlite3.Error:
                fallbacks.append("embedding_space_metadata")

        if has_stale_embedding_rows:
            fallbacks.append("embedding_space_rebuild_pending")

        if rows_seen == 0:
            if "deadline_exceeded" in fallbacks:
                return deadline_result(fallbacks)
            fallback_label = "source_read_uncertain" if uncertain_paths else ("embedding_space_mismatch" if has_stale_embedding_rows else None)
            if not semantic_only:
                lexical_backend = "fts5"
                fts_raw = self._search_fts_candidates(
                    query, workspace, max(16, top_k * 2), scope_path,
                    excluded_paths=uncertain_paths,
                )
                if _search_limit_reached(deadline, cancel_event):
                    return deadline_result()
                fts_result = (
                    fts_raw if isinstance(fts_raw, dict)
                    else {"status": "MATCHES_FOUND" if fts_raw else "MATCHES_EMPTY", "candidates": fts_raw}
                )
                candidates = visible(fts_result["candidates"])
                fallback_used = False
                if not candidates:
                    lexical_backend = "token_overlap"
                    try:
                        candidates = visible(self._search_token_overlap(
                            query, workspace, max(16, top_k * 2), scope_path,
                            excluded_paths=uncertain_paths, deadline=deadline, cancel_event=cancel_event,
                        ))
                    except TimeoutError:
                        return deadline_result()
                    fallback_used = True
                if candidates:
                    results = [
                        {
                            "path": c["path"],
                            "chunk_no": c["chunk_no"],
                            "text": c.get("text", ""),
                            "content_hash": c.get("content_hash", ""),
                            "score": float(c.get("fts_score", 0.5)),
                        }
                        for c in candidates[:top_k]
                    ]
                    resp = {
                        "success": True,
                        "workspace": workspace,
                        "results": results,
                        "degraded": True,
                        "fallback": fallback_label or "bm25_fts",
                        "retrieval_mode": "lexical_fallback",
                        "lexical_backend": lexical_backend,
                        "component_status": {
                            "fts": fts_result["status"],
                            "lexical_fallback": "FALLBACK_USED" if fallback_used else "not_used",
                        },
                        "fallback_used": fallback_used,
                    }
                    if has_stale_embedding_rows:
                        resp["reindex_required"] = True
                        if embedding_space_resolved:
                            resp["embedding_space_id"] = embedding_space
                    return resp
            if uncertain_paths:
                return {
                    "success": True, "workspace": workspace, "results": [],
                    "degraded": True, "fallback": "source_read_uncertain",
                    "reason": "source files could not be read during indexing",
                }
            if has_stale_embedding_rows:
                return {
                    "success": True, "workspace": workspace, "results": [], "degraded": True,
                    "fallback": "embedding_space_mismatch",
                    "reason": "indexed vectors do not match the query embedding space",
                    "reindex_required": True,
                    **({"embedding_space_id": embedding_space} if embedding_space_resolved else {}),
                }
            return {"success": True, "workspace": workspace, "results": [], "warning": "workspace has no matching indexed chunks"}

        candidates = [
            entry[4]
            for entry in sorted(
                best,
                key=lambda item: (
                    -item[0], str(item[4]["path"]), int(item[4]["chunk_no"]), str(item[4]["content_hash"] or "")
                ),
            )
        ]

        # Hybrid search: combine vector candidates with FTS5 keyword hits via Reciprocal Rank Fusion (RRF)
        fts_raw = (
            {"status": "NOT_REQUESTED", "candidates": []}
            if semantic_only
            else self._search_fts_candidates(query, workspace, 16, scope_path, embedding_space, uncertain_paths)
        )
        fts_result = (
            fts_raw if isinstance(fts_raw, dict)
            else {"status": "MATCHES_FOUND" if fts_raw else "MATCHES_EMPTY", "candidates": fts_raw}
        )
        fts_candidates = visible(fts_result["candidates"])
        fts_failed = fts_result["status"] not in {"NOT_REQUESTED", "MATCHES_FOUND", "MATCHES_EMPTY"}
        if fts_failed:
            fallbacks.append(f"fts_{fts_result['status'].lower().replace('/', '_')}")

        is_hybrid = bool(fts_candidates)
        if is_hybrid:
            k_rrf = 60.0
            combined: dict[tuple[str, int], dict[str, Any]] = {}
            for rank, c in enumerate(candidates):
                ckey = (c["path"], c["chunk_no"])
                item = dict(c)
                item["rrf_score"] = 1.0 / (k_rrf + rank + 1)
                combined[ckey] = item

            for rank, c in enumerate(fts_candidates):
                ckey = (c["path"], c["chunk_no"])
                rrf_delta = 1.0 / (k_rrf + rank + 1)
                if ckey in combined:
                    combined[ckey]["rrf_score"] += rrf_delta
                    combined[ckey]["fts_score"] = c.get("fts_score", 0.0)
                else:
                    item = dict(c)
                    item["rrf_score"] = rrf_delta
                    item["embedding_score"] = 0.0
                    combined[ckey] = item

            candidates = sorted(
                combined.values(),
                key=lambda item: (
                    -float(item.get("rrf_score", 0.0)), str(item.get("path", "")),
                    int(item.get("chunk_no", 0)), str(item.get("content_hash", "")),
                ),
            )
            candidates = candidates[:candidate_limit]

        # Hydrate text for winning candidates from DB
        needed_map: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for c in candidates:
            if "text" not in c or not c.get("text"):
                needed_map.setdefault((c["path"], c["chunk_no"]), []).append(c)
        if needed_map:
            with closing(self._connect()) as con:
                for (chunk_path, chunk_no), target_candidates in needed_map.items():
                    txt_row = con.execute(
                        "SELECT text FROM chunks WHERE workspace=? AND path=? AND chunk_no=?",
                        (workspace, chunk_path, chunk_no),
                    ).fetchone()
                    chunk_text = str(txt_row[0]) if txt_row else ""
                    for c in target_candidates:
                        c["text"] = chunk_text

        reranked = False
        reranker_failed = False
        heuristic_fallback = False
        if use_reranker and candidates:
            if _search_limit_reached(deadline, cancel_event):
                fallbacks.append("reranker_deadline_skipped")
            elif self.config.get("features", {}).get("reranker", True) and hasattr(self, "reranker") and self.reranker:
                reranker_device = str(
                    getattr(self.reranker, "active_device", None)
                    or getattr(self.reranker, "device", None)
                    or ""
                ).strip().lower()
                if reranker_device and reranker_device not in {"unknown", "none"}:
                    try:
                        rr = self.reranker.rerank(
                            query,
                            [c["text"] for c in candidates],
                            top_k=top_k,
                            priority=priority,
                            allow_cpu_fallback=allow_cpu_fallback,
                        )
                        if rr.get("success"):
                            ordered: list[dict[str, Any]] = []
                            for item in rr["results"]:
                                base = dict(candidates[item["index"]])
                                base["rerank_score"] = item["score"]
                                ordered.append(base)
                            candidates = ordered
                            reranked = True
                        else:
                            reranker_failed = True
                    except Exception:
                        reranker_failed = True

            if not reranked:
                q_terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 1]
                if q_terms:
                    for c in candidates:
                        h_score = float(c.get("rrf_score", c.get("embedding_score", 0.5)))
                        txt = str(c.get("text", "")).lower()
                        p_low = str(c.get("path", "")).lower()
                        if any(t in p_low for t in q_terms):
                            h_score *= 1.35
                        for t in q_terms:
                            if f"def {t}" in txt or f"class {t}" in txt or f"interface {t}" in txt:
                                h_score *= 1.5
                        if len(q_terms) >= 2 and all(t in txt for t in q_terms[:2]):
                            h_score *= 1.2
                        c["heuristic_rerank_score"] = round(h_score, 4)
                candidates = sorted(candidates, key=lambda x: x.get("heuristic_rerank_score", 0.0), reverse=True)
                heuristic_fallback = True

        if heuristic_fallback:
            fallbacks.append("heuristic_rerank")
        if reranker_failed:
            fallbacks.append("reranker")

        graphrag_enriched = False
        try:
            repository_id = self._get_workspace_repository_id(workspace)
            state_dir = Path(self.config.get("server", {}).get("state_dir", "state")).resolve()
            state_db = state_dir / "agent_state.sqlite"
            if repository_id and state_db.is_file():
                con_state = connect_sqlite(state_db)
                try:
                    cur_rel = con_state.cursor()
                    for c in candidates[:top_k]:
                        c_text = c.get("text", "")
                        words = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b", c_text[:1000]))
                        if not words:
                            continue
                        matched_rels: list[dict[str, Any]] = []
                        for w in list(words)[:15]:
                            rows_rel = cur_rel.execute(
                                """
                                SELECT source_entity, relation, target_entity, weight
                                FROM agent_entity_relations
                                WHERE (source_entity = ? OR target_entity = ?)
                                  AND CASE WHEN json_valid(metadata) THEN
                                    CASE
                                      WHEN json_type(metadata, '$.tenant') IS NOT NULL
                                        OR json_type(metadata, '$.tenant_key') IS NOT NULL
                                        OR json_type(metadata, '$.provenance.tenant') IS NOT NULL
                                        OR json_type(metadata, '$.provenance.tenant_key') IS NOT NULL
                                      THEN 0
                                      WHEN json_extract(metadata, '$.scope') = 'global' THEN 1
                                      WHEN json_extract(metadata, '$.scope') = 'repository'
                                        AND json_extract(metadata, '$.provenance.repository_id') = ?
                                      THEN 1
                                      ELSE 0
                                    END
                                  ELSE 0 END = 1
                                LIMIT 5
                                """,
                                (w, w, repository_id),
                            ).fetchall()
                            for r_row in rows_rel:
                                matched_rels.append({
                                    "source": r_row[0], "relation": r_row[1], "target": r_row[2], "weight": float(r_row[3]),
                                })
                        if matched_rels:
                            c["graph_relations"] = matched_rels[:5]
                            graphrag_enriched = True
                finally:
                    con_state.close()
        except Exception:
            pass

        return {
            "success": True,
            "workspace": workspace,
            "reranked": reranked,
            "degraded": bool(fallbacks),
            "fallback": fallbacks[0] if fallbacks else None,
            "fallbacks": fallbacks,
            "component_status": {
                "fts": fts_result["status"],
                "lexical_fallback": "FALLBACK_USED" if fts_failed else "not_used",
            },
            "fallback_used": fts_failed,
            "reindex_required": has_stale_embedding_rows,
            **({"embedding_space_id": embedding_space} if has_stale_embedding_rows and embedding_space_resolved else {}),
            "hybrid": is_hybrid,
            "graphrag_enriched": graphrag_enriched,
            "results": candidates[:top_k],
        }

