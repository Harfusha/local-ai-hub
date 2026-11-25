from __future__ import annotations

from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import time
from typing import Any

from .rag_chunking import (
    _check_rag_publish_budget,
    _fragment_hash,
    _rag_source_still_current,
    _read_bounded_file,
    _serialize_embedding,
)
from .rag_constants import (
    ProjectPolicySyncError,
    RAG_CHUNKER_VERSION,
    _INDEX_EMBED_BATCH_SIZE,
    _RAGSourceChangedBeforePublish,
)
from .scheduler import QueueFullError
from .sqlite_support import is_busy_error, retry_busy, write_transaction


RAGStore = None


class RAGMaintenanceMixin:
    def prune_missing(self, root: str, workspace: str, current_paths: list[str]) -> int:
        """Delete RAG rows for files no longer present without rescanning the filesystem."""
        current = set(current_paths)
        with self._get_workspace_lock(workspace,), closing(self._connect()) as con:
            policy_removed = 0
            if Path(root).is_dir():
                policy_context = self.project_context(root)
                policy_removed = self._sync_workspace_project_policy_identity(
                    root, workspace, policy_context
                )
            owner_root = str(Path(root).resolve())
            owned = {str(r[0]) for r in con.execute(
                "SELECT path FROM project_file_owners WHERE workspace=? AND root=?",
                (workspace, owner_root),
            ).fetchall()}
            deleted = owned - current
            for rel in deleted:
                con.execute(
                    "DELETE FROM project_file_owners WHERE workspace=? AND root=? AND path=?",
                    (workspace, owner_root, rel),
                )
                still_owned = con.execute(
                    "SELECT 1 FROM project_file_owners WHERE workspace=? AND path=? LIMIT 1",
                    (workspace, rel),
                ).fetchone()
                if still_owned is None:
                    self._delete_rag_path_rows(con, workspace, rel)
            if deleted:
                self._bump_workspace_index_generation(con, workspace)
            con.commit()
        return policy_removed + len(deleted)

    @staticmethod
    def _delete_rag_path_rows(con: sqlite3.Connection, workspace: str, path: str) -> None:
        con.execute("DELETE FROM chunks WHERE workspace=? AND path=?", (workspace, path))
        con.execute("DELETE FROM files WHERE workspace=? AND path=?", (workspace, path))
        try:
            con.execute("DELETE FROM chunk_fts WHERE workspace=? AND path=?", (workspace, path))
        except sqlite3.Error:
            pass

    def remove_project(
        self, root: str, *, workspace: str, preserve_paths: set[str] | None = None
    ) -> int:
        """Delete indexed paths only when this exact root owns their provenance."""
        owner_root = str(Path(root).resolve())
        preserve = {str(path).replace("\\", "/") for path in (preserve_paths or set())}
        with self._get_workspace_lock(workspace,), closing(self._connect()) as con:
            paths = [str(row[0]) for row in con.execute(
                "SELECT path FROM project_file_owners WHERE workspace=? AND root=?",
                (workspace, owner_root),
            ).fetchall()]
            removed = 0
            for path in paths:
                con.execute(
                    "DELETE FROM project_file_owners WHERE workspace=? AND root=? AND path=?",
                    (workspace, owner_root, path),
                )
                still_owned = con.execute(
                    "SELECT 1 FROM project_file_owners WHERE workspace=? AND path=? LIMIT 1",
                    (workspace, path),
                ).fetchone()
                if still_owned is None and path not in preserve:
                    before = con.total_changes
                    self._delete_rag_path_rows(con, workspace, path)
                    removed += int(con.total_changes > before)
            if removed:
                self._bump_workspace_index_generation(con, workspace)
            con.commit()
        return removed

    def remove_paths(self, *, workspace: str, paths: list[str]) -> int:
        """Remove explicitly known paths from a semantic workspace.

        Used when a newer deterministic analyzer proves that a declarative file no
        longer needs embeddings. This keeps rebuilt indexes free of stale semantic chunks.
        """
        unique = sorted({str(p).replace("\\", "/") for p in paths if str(p).strip()})
        if not unique:
            return 0
        removed = 0
        with self._get_workspace_lock(workspace,), closing(self._connect()) as con:
            changes_before = con.total_changes
            for rel in unique:
                row = con.execute(
                    "SELECT 1 FROM files WHERE workspace=? AND path=?",
                    (workspace, rel),
                ).fetchone()
                con.execute("DELETE FROM chunks WHERE workspace=? AND path=?", (workspace, rel))
                con.execute("DELETE FROM files WHERE workspace=? AND path=?", (workspace, rel))
                try:
                    con.execute("DELETE FROM chunk_fts WHERE workspace=? AND path=?", (workspace, rel))
                except Exception:
                    pass
                con.execute(
                    "DELETE FROM project_file_owners WHERE workspace=? AND path=?",
                    (workspace, rel),
                )
                removed += int(row is not None)
            if con.total_changes > changes_before:
                self._bump_workspace_index_generation(con, workspace)
            con.commit()
        return removed

    def index_paths_step(
        self,
        root: str,
        *,
        workspace: str,
        paths: list[str],
        should_yield: Any | None = None,
        content_overrides: dict[str, str] | None = None,
        deleted_paths: list[str] | None = None,
        _space_override: str | None = None, _identity_retry: bool = False,
    ) -> dict[str, Any]:
        """Index only explicitly dirty paths supplied by Local AI preprocessing.

        This avoids repeatedly walking a cold repository for each micro-step.
        """
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            return {"success": False, "error": f"root directory does not exist: {root_path}"}
        project_context = self.project_context(root_path)
        if not self._project_phase_allowed(project_context, "rag"):
            return {
                "success": True, "workspace": workspace, "skipped": True,
                "reason": "project phase disabled", "processed_paths": [],
                "embedded_chunks": 0, "reused_chunks": 0,
            }
        path_policy = None
        if project_context is not None:
            api = self.project_config_api()
            policy_factory = getattr(api, "ProjectPathPolicy", None)
            if callable(policy_factory):
                path_policy = policy_factory(root_path, project_context.settings)
        embedding_space = _space_override or self._embedding_space_id()
        processed_paths: list[str] = []
        embedded_chunks = 0
        reused_chunks = 0
        with self._get_workspace_lock(workspace):
            try:
                self._sync_workspace_project_policy_identity(
                    root_path, workspace, project_context
                )
            except ProjectPolicySyncError as exc:
                return {"success": False, "error": str(exc), "retryable": exc.retryable}
            with closing(self._connect()) as con:
                stored_chunker_version = self._stored_workspace_chunker_version(con, workspace)
                workspace_has_index = (
                    con.execute(
                        "SELECT 1 FROM files WHERE workspace=? LIMIT 1", (workspace,),
                    ).fetchone() is not None
                    or con.execute(
                        "SELECT 1 FROM chunks WHERE workspace=? LIMIT 1", (workspace,),
                    ).fetchone() is not None
                )
            chunker_reindex_required = (
                workspace_has_index and stored_chunker_version != RAG_CHUNKER_VERSION
            )
            initialize_chunker_version = not workspace_has_index
            with closing(self._connect()) as con:
                stored_space = self._stored_workspace_embedding_space(con, workspace)
                reindex_target = self._stored_workspace_reindex_target(con, workspace)
                legacy_rows = (
                    con.execute(
                        "SELECT DISTINCT COALESCE(TRIM(CAST(embedding_space AS TEXT)), '') "
                        "FROM chunks WHERE workspace=? AND embedding IS NOT NULL "
                        "AND length(embedding)>0 AND TRIM(CAST(embedding AS TEXT))<>'[]'",
                        (workspace,),
                    ).fetchall()
                    if stored_space is None else []
                )
            inferred_spaces: set[str] = set()
            unresolved_legacy_vectors = False
            for row in legacy_rows:
                row_space = str(row[0] or "").strip()
                if not row_space:
                    unresolved_legacy_vectors = True
                else:
                    inferred_spaces.add(row_space)
            if stored_space is None and not reindex_target and (unresolved_legacy_vectors or len(inferred_spaces) > 1):
                return {
                    "success": False, "workspace": workspace,
                    "error": "embedding_space_rebuild_required",
                    "rebuild_required": True, "retryable": False,
                }
            if stored_space is None and inferred_spaces:
                inferred_space = next(iter(inferred_spaces))
                recovery_conflict = {"value": False}

                def persist_recovered_space() -> None:
                    with closing(self._connect()) as con, write_transaction(
                        con, max_duration_seconds=5.0, rollback_label="RAG embedding space recovery"
                    ):
                        current_space = self._stored_workspace_embedding_space(con, workspace)
                        if current_space is not None and current_space != inferred_space:
                            recovery_conflict["value"] = True
                            return
                        if current_space is None:
                            self._store_workspace_embedding_space(con, workspace, inferred_space)
                            self._bump_workspace_index_generation(con, workspace)

                try:
                    retry_busy(
                        persist_recovered_space,
                        retries=self._sqlite_write_retries,
                        base_delay_seconds=min(0.25, max(0.01, self._sqlite_busy_seconds / 10.0)),
                    )
                except Exception as exc:
                    return {
                        "success": False, "workspace": workspace,
                        "error": "embedding_space_recovery_failed",
                        "retryable": is_busy_error(exc),
                    }
                if recovery_conflict["value"]:
                    return {
                        "success": False, "workspace": workspace,
                        "error": "embedding_space_rebuild_required",
                        "rebuild_required": True, "retryable": False,
                    }
                stored_space = inferred_space
                embedding_space = inferred_space
            elif stored_space is not None and not self._embedding_space_is_resolved():
                embedding_space = stored_space
            embedding_space_resolved = bool(stored_space or self._embedding_space_is_resolved())
            if reindex_target:
                embedding_space = reindex_target
                embedding_space_resolved = True
            # 1. Read files and chunk
            file_data: list[dict[str, Any]] = []
            policy_deleted: set[str] = set()
            read_uncertain_paths: set[str] = set()
            ignored_dirs = {
                str(name).lower() for name in self.config.get("rag", {}).get("ignore_dirs", [])
            }
            for rel in paths:
                if callable(should_yield) and should_yield():
                    self._publish_workspace_read_uncertainty(workspace, read_uncertain_paths)
                    return {
                        "success": True, "workspace": workspace, "preempted": True,
                        "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
                        "reused_chunks": reused_chunks,
                    }
                rel = str(rel).replace("\\", "/")
                # Preserve the caller's original path for no-follow I/O.
                # Resolving it here would hide an in-root symlink from the reader.
                path = root_path / rel
                try:
                    if ".." in path.relative_to(root_path).parts:
                        continue
                    relative_path = path.resolve(strict=False).relative_to(root_path)
                except (OSError, RuntimeError, ValueError):
                    # Absolute, escaped or invalid paths are not valid RAG
                    # inventory entries and must not reach a file reader.
                    continue
                ignored_parts = relative_path.parts[:-1]
                requested_path = Path(os.path.normpath(rel))
                if not requested_path.is_absolute():
                    ignored_parts = (*ignored_parts, *requested_path.parts[:-1])
                if any(part.lower() in ignored_dirs for part in ignored_parts):
                    policy_deleted.add(rel)
                    continue
                if not path.is_file():
                    continue
                try:
                    stat = path.stat()
                    cfg = self.config.get("rag", {})
                    extensions = {str(ext).lower() for ext in cfg.get("extensions", [])}
                    if extensions and path.suffix.lower() not in extensions:
                        api = self.project_config_api() if project_context is not None else None
                        if api is None or api.custom_extension_kind(path.name, project_context.settings) != "text":
                            policy_deleted.add(rel)
                            continue
                    max_bytes = max(0, int(cfg.get("max_file_bytes", 2_000_000)))
                    if project_context is not None and project_context.settings.max_file_size_bytes is not None:
                        max_bytes = min(max_bytes, int(project_context.settings.max_file_size_bytes))
                    if int(stat.st_size) > max_bytes:
                        policy_deleted.add(rel)
                        continue
                    allowed, kind = self._project_path_decision(
                        root_path, path, project_context, phase="rag", size_bytes=int(stat.st_size),
                        path_policy=path_policy,
                    )
                    if not allowed or kind == "binary":
                        policy_deleted.add(rel)
                        continue
                    override = (content_overrides or {}).get(rel)
                    if override is not None and len(str(override).encode("utf-8")) > max_bytes:
                        # An explicitly oversized override is a policy denial,
                        # even if the current file is small.
                        policy_deleted.add(rel)
                        continue
                    # A cached lexical snapshot cannot prove the file is still
                    # identical. Re-read the bounded live bytes at the final
                    # indexing boundary, even when an override was supplied.
                    raw = _read_bounded_file(path, max_bytes, root=root_path)
                    if raw is None:
                        read_uncertain_paths.add(rel)
                        continue
                    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
                    if override is not None:
                        cached_text = str(override).replace("\r\n", "\n")
                        if (
                            text != cached_text
                            and text != cached_text + "\n"
                            and cached_text != text + "\n"
                        ):
                            # Only a missing terminal LF is source-index normalization.
                            read_uncertain_paths.add(rel)
                            continue
                    file_hash = hashlib.sha1(raw, usedforsecurity=False).hexdigest()
                    chunks = list(self._chunks(text, path=rel))
                    file_data.append({"rel": rel, "stat": stat, "file_hash": file_hash, "chunks": chunks, "max_bytes": max_bytes})
                except Exception:
                    read_uncertain_paths.add(rel)
                    continue

            self._publish_workspace_read_uncertainty(workspace, read_uncertain_paths)

            deleted_unique = sorted(
                {str(p).replace("\\", "/") for p in (deleted_paths or []) if str(p).strip()}
                | policy_deleted
            )
            if not file_data and not deleted_unique:
                if read_uncertain_paths:
                    def publish_uncertain_only() -> None:
                        with closing(self._connect()) as con, write_transaction(
                            con, max_duration_seconds=5.0, rollback_label="RAG uncertainty publish"
                        ):
                            self._update_workspace_read_uncertainty(
                                con, workspace, uncertain_paths=read_uncertain_paths,
                            )

                    retry_busy(
                        publish_uncertain_only,
                        retries=self._sqlite_write_retries,
                        base_delay_seconds=min(0.25, max(0.01, self._sqlite_busy_seconds / 10.0)),
                    )
                return {
                    "success": True, "workspace": workspace, "preempted": False,
                    "embedding_space_id": stored_space or embedding_space,
                    "embedding_space_resolved": embedding_space_resolved,
                    "processed_paths": [], "embedded_chunks": 0, "reused_chunks": 0,
                    "read_uncertain_paths": sorted(read_uncertain_paths),
                }

            # 2. Bulk load existing chunks
            all_rels = sorted({f["rel"] for f in file_data} | set(deleted_unique))
            old_chunks: dict[tuple[str, int, str], str] = {}
            with closing(self._connect()) as con:
                # Load in chunks of 500
                for i in range(0, len(all_rels), 500):
                    batch_rels = all_rels[i:i+500]
                    placeholders = ",".join("?" for _ in batch_rels)
                    rows = con.execute(
                        f"SELECT path,chunk_no,content_hash,embedding,embedding_space FROM chunks WHERE workspace=? AND path IN ({placeholders})",
                        (workspace, *batch_rels),
                    ).fetchall()
                    for r in rows:
                        if embedding_space and str(r[4] or "").strip() == embedding_space:
                            old_chunks[(str(r[0]), int(r[1]), str(r[2]))] = r[3]

            # 3. Build records and identify missing embeddings
            all_missing_texts: list[str] = []
            missing_pointers: list[tuple[int, int]] = []  # (file_idx, record_idx)

            for f_idx, item in enumerate(file_data):
                rel = item["rel"]
                records: list[dict[str, Any]] = []
                for chunk_no, chunk in enumerate(item["chunks"]):
                    chash = _fragment_hash(chunk)
                    embedding = old_chunks.get((rel, chunk_no, chash))
                    records.append({
                        "chunk_no": chunk_no, "text": chunk, "hash": chash, "embedding": embedding,
                        "embedding_space": embedding_space if embedding is not None else "",
                    })
                    if embedding is None:
                        all_missing_texts.append(chunk)
                        missing_pointers.append((f_idx, len(records) - 1))
                    else:
                        reused_chunks += 1
                item["records"] = records

            # Reuse vectors for identical file content even after its source workspace is removed.
            if all_missing_texts:
                content_hashes = list(dict.fromkeys(file_data[f_idx]["file_hash"] for f_idx, _ in missing_pointers))
                cached_chunks: dict[tuple[str, int], tuple[str, Any]] = {}
                with closing(self._connect()) as con:
                    for i in range(0, len(content_hashes), 500):
                        batch_hashes = content_hashes[i:i + 500]
                        placeholders = ",".join("?" for _ in batch_hashes)
                        existing = {
                            str(row[0]) for row in con.execute(
                                f"SELECT content_hash FROM files WHERE workspace=? AND content_hash IN ({placeholders})",
                                (workspace, *batch_hashes),
                            ).fetchall()
                        }
                        batch_hashes = [content_hash for content_hash in batch_hashes if content_hash not in existing]
                        if not batch_hashes:
                            continue
                        placeholders = ",".join("?" for _ in batch_hashes)
                        rows = con.execute(
                            f"SELECT content_hash,chunk_index,chunk_text,embedding_blob "
                            f"FROM content_rag_chunks WHERE embedding_space=? AND content_hash IN ({placeholders})",
                            (embedding_space, *batch_hashes),
                        ).fetchall()
                        cached_chunks.update(
                            ((str(row[0]), int(row[1])), (str(row[2]), row[3])) for row in rows
                        )
                if cached_chunks:
                    still_missing_texts: list[str] = []
                    still_missing_pointers: list[tuple[int, int]] = []
                    for (f_idx, rec_idx), text in zip(missing_pointers, all_missing_texts):
                        item = file_data[f_idx]
                        record = item["records"][rec_idx]
                        cached = cached_chunks.get((item["file_hash"], record["chunk_no"]))
                        if cached and cached[0] == text and cached[1]:
                            record["embedding"] = cached[1]
                            record["embedding_space"] = embedding_space
                            reused_chunks += 1
                        else:
                            still_missing_texts.append(text)
                            still_missing_pointers.append((f_idx, rec_idx))
                    all_missing_texts = still_missing_texts
                    missing_pointers = still_missing_pointers

            # 4. Cross-workspace / cross-worktree instant chunk embedding reuse
            if all_missing_texts:
                missing_hashes = [file_data[f_idx]["records"][rec_idx]["hash"] for f_idx, rec_idx in missing_pointers]
                global_chunks: dict[str, Any] = {}
                with closing(self._connect()) as con:
                    for i in range(0, len(missing_hashes), 500):
                        batch_h = missing_hashes[i:i + 500]
                        placeholders = ",".join("?" for _ in batch_h)
                        rows = con.execute(
                            f"SELECT content_hash, embedding FROM chunks WHERE embedding_space=? AND embedding_space<>'' AND content_hash IN ({placeholders})",
                            (embedding_space, *batch_h),
                        ).fetchall()
                        for r in rows:
                            if r[0] and r[1] and str(r[0]) not in global_chunks:
                                global_chunks[str(r[0])] = r[1]

                if global_chunks:
                    still_missing_texts: list[str] = []
                    still_missing_pointers: list[tuple[int, int]] = []
                    for (f_idx, rec_idx), text in zip(missing_pointers, all_missing_texts):
                        chash = file_data[f_idx]["records"][rec_idx]["hash"]
                        if chash in global_chunks:
                            file_data[f_idx]["records"][rec_idx]["embedding"] = global_chunks[chash]
                            file_data[f_idx]["records"][rec_idx]["embedding_space"] = embedding_space
                            reused_chunks += 1
                        else:
                            still_missing_texts.append(text)
                            still_missing_pointers.append((f_idx, rec_idx))
                    all_missing_texts = still_missing_texts
                    missing_pointers = still_missing_pointers

            # 5. Embed bounded batches. Do not publish partial vector batches.
            if all_missing_texts:
                if callable(should_yield) and should_yield():
                    return {
                        "success": True, "workspace": workspace, "preempted": True,
                        "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
                        "reused_chunks": reused_chunks,
                    }
                batch_embedding_space = None
                for offset in range(0, len(all_missing_texts), _INDEX_EMBED_BATCH_SIZE):
                    if offset and callable(should_yield) and should_yield():
                        return {
                            "success": True, "workspace": workspace, "preempted": True,
                            "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
                            "reused_chunks": reused_chunks,
                        }
                    batch_texts = all_missing_texts[offset:offset + _INDEX_EMBED_BATCH_SIZE]
                    batch_pointers = missing_pointers[offset:offset + _INDEX_EMBED_BATCH_SIZE]
                    try:
                        vectors_result = self.services.embed(batch_texts, priority=0, query=False, background=True)
                    except (TimeoutError, QueueFullError) as exc:
                        return {
                            "success": True, "workspace": workspace, "preempted": True,
                            "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
                            "reused_chunks": reused_chunks, "note": f"embedder busy or timed out: {exc}",
                        }
                    if not isinstance(vectors_result, dict) or not vectors_result.get("success"):
                        return vectors_result if isinstance(vectors_result, dict) else {"success": False, "error": "embed failed"}
                    vectors = vectors_result.get("embeddings", [])
                    if len(vectors) != len(batch_pointers):
                        return {"success": False, "error": "embedding count mismatch during background RAG path step"}
                    current_space = self._embedding_space_id(vectors_result)
                    if batch_embedding_space is not None and current_space != batch_embedding_space:
                        return {"success": False, "error": "embedding identity changed during RAG path step", "retryable": True}
                    if batch_embedding_space is None:
                        batch_embedding_space = current_space
                        if current_space != embedding_space:
                            if _identity_retry and reused_chunks:
                                return {"success": False, "error": "embedding identity changed during RAG path retry", "retryable": True}
                            if reused_chunks:
                                return self.index_paths_step(
                                    str(root_path), workspace=workspace, paths=paths,
                                    should_yield=should_yield, content_overrides=content_overrides,
                                    deleted_paths=deleted_paths, _space_override=current_space,
                                    _identity_retry=True,
                                )
                            embedding_space = batch_embedding_space
                        embedding_space_resolved = True
                    for (f_idx, rec_idx), vector in zip(batch_pointers, vectors):
                        embedding = _serialize_embedding(vector)
                        if embedding is None:
                            return {"success": False, "error": "embedding backend returned an invalid vector"}
                        file_data[f_idx]["records"][rec_idx]["embedding"] = embedding
                        file_data[f_idx]["records"][rec_idx]["embedding_space"] = batch_embedding_space
                    embedded_chunks += len(batch_pointers)

            if callable(should_yield) and should_yield():
                return {
                    "success": True, "workspace": workspace, "preempted": True,
                    "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
                    "reused_chunks": reused_chunks,
                }


            # Re-validate after each SQLite busy/backoff, not merely after
            # embeddings: an editor may have changed the file during retry.
            def assert_current_sources() -> None:
                stale_sources = sorted(
                    item["rel"] for item in file_data
                    if not _rag_source_still_current(
                        root_path, item["rel"], expected_hash=item["file_hash"],
                        expected_size=int(item["stat"].st_size),
                        expected_mtime_ns=int(item["stat"].st_mtime_ns),
                        max_bytes=int(item["max_bytes"]),
                    )
                )
                if stale_sources:
                    raise _RAGSourceChangedBeforePublish(stale_sources)

            # 5. Bulk SQLite transaction
            chunks_to_insert: list[tuple[Any, ...]] = []
            files_to_insert: list[tuple[Any, ...]] = []
            for item in file_data:
                rel = item["rel"]
                stat = item["stat"]
                for r in item["records"]:
                    chunks_to_insert.append((workspace, rel, r["chunk_no"], r["hash"], r["text"], r["embedding"], r["embedding_space"]))
                files_to_insert.append((workspace, rel, int(stat.st_mtime_ns), int(stat.st_size), item["file_hash"]))
                processed_paths.append(rel)

            def publish() -> None:
                assert_current_sources()
                publish_budget_seconds = 120.0
                with closing(self._connect()) as con, write_transaction(
                    con, max_duration_seconds=publish_budget_seconds,
                    rollback_label="RAG batch index publish",
                ):
                    publish_started = time.monotonic()
                    fts_exists = con.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_fts'"
                    ).fetchone()
                    _check_rag_publish_budget(
                        started_at=publish_started, stage="inspect_fts",
                        budget_seconds=publish_budget_seconds,
                    )
                    for i in range(0, len(all_rels), 500):
                        batch_rels = all_rels[i:i+500]
                        placeholders = ",".join("?" for _ in batch_rels)
                        con.execute(f"DELETE FROM chunks WHERE workspace=? AND path IN ({placeholders})", (workspace, *batch_rels))
                        con.execute(f"DELETE FROM files WHERE workspace=? AND path IN ({placeholders})", (workspace, *batch_rels))
                    if fts_exists and all_rels:
                        con.execute("CREATE TEMP TABLE rag_publish_paths(path TEXT PRIMARY KEY)")
                        con.executemany(
                            "INSERT OR IGNORE INTO rag_publish_paths(path) VALUES(?)",
                            ((rel,) for rel in all_rels),
                        )
                        con.execute(
                            "DELETE FROM chunk_fts WHERE workspace=? AND path IN "
                            "(SELECT path FROM rag_publish_paths)",
                            (workspace,),
                        )
                    _check_rag_publish_budget(
                        started_at=publish_started, stage="delete_old_rows",
                        budget_seconds=publish_budget_seconds,
                    )
                    con.executemany(
                        "INSERT INTO chunks(workspace,path,chunk_no,content_hash,text,embedding,embedding_space) VALUES(?,?,?,?,?,?,?)",
                        chunks_to_insert,
                    )
                    _check_rag_publish_budget(
                        started_at=publish_started, stage="insert_chunks",
                        budget_seconds=publish_budget_seconds,
                    )
                    if fts_exists:
                        con.executemany(
                            "INSERT INTO chunk_fts(workspace,path,chunk_no,text) VALUES(?,?,?,?)",
                            [(c[0], c[1], c[2], c[4]) for c in chunks_to_insert],
                        )
                    _check_rag_publish_budget(
                        started_at=publish_started, stage="insert_fts",
                        budget_seconds=publish_budget_seconds,
                    )
                    con.executemany(
                        "INSERT INTO files(workspace,path,mtime_ns,size,content_hash) VALUES(?,?,?,?,?)",
                        files_to_insert,
                    )
                    _check_rag_publish_budget(
                        started_at=publish_started, stage="insert_files",
                        budget_seconds=publish_budget_seconds,
                    )
                    for i in range(0, len(all_rels), 500):
                        batch_rels = all_rels[i:i + 500]
                        placeholders = ",".join("?" for _ in batch_rels)
                        con.execute(
                            "INSERT OR REPLACE INTO content_rag_chunks "
                            "(content_hash,embedding_space,chunk_index,chunk_text,embedding_blob,created_at) "
                            "SELECT f.content_hash,c.embedding_space,c.chunk_no,c.text,c.embedding,? "
                            "FROM chunks c JOIN files f ON f.workspace=c.workspace AND f.path=c.path "
                            f"WHERE c.workspace=? AND c.path IN ({placeholders}) "
                            "AND c.embedding IS NOT NULL AND c.embedding_space<>''",
                            (time.time(), workspace, *batch_rels),
                        )
                        _check_rag_publish_budget(
                            started_at=publish_started, stage="insert_content_cas",
                            budget_seconds=publish_budget_seconds,
                        )
                    for rel in set(deleted_paths or []) | policy_deleted:
                        con.execute(
                            "DELETE FROM project_file_owners WHERE workspace=? AND root=? AND path=?",
                            (workspace, str(root_path), str(rel).replace("\\", "/")),
                        )
                    con.executemany(
                        "INSERT OR IGNORE INTO project_file_owners(workspace,root,path) VALUES(?,?,?)",
                        [(workspace, str(root_path), rel) for rel in processed_paths],
                    )
                    _check_rag_publish_budget(
                        started_at=publish_started, stage="update_project_file_owners",
                        budget_seconds=publish_budget_seconds,
                    )
                    stale_vectors = con.execute(
                        """SELECT 1 FROM chunks WHERE workspace=?
                           AND embedding IS NOT NULL AND length(embedding)>0
                           AND COALESCE(embedding_space,'')<>? LIMIT 1""",
                        (workspace, embedding_space),
                    ).fetchone() if embedding_space else None
                    if embedding_space and stale_vectors is None:
                        self._store_workspace_embedding_space(con, workspace, embedding_space)
                    if reindex_target:
                        target_key = self._workspace_reindex_target_key(workspace)
                        if reindex_target == embedding_space and stale_vectors is None:
                            con.execute(
                                "DELETE FROM rag_meta WHERE key=? AND value=?",
                                (target_key, reindex_target),
                            )
                        elif embedding_space and reindex_target != embedding_space:
                            con.execute(
                                "UPDATE rag_meta SET value=? WHERE key=? AND value=?",
                                (embedding_space, target_key, reindex_target),
                            )
                    if initialize_chunker_version:
                        self._store_workspace_chunker_version(con, workspace)
                    uncertainty_changed = self._update_workspace_read_uncertainty(
                        con, workspace,
                        uncertain_paths=read_uncertain_paths,
                        clear_paths=set(all_rels),
                        bump_generation=False,
                    )
                    if all_rels or uncertainty_changed:
                        self._bump_workspace_index_generation(con, workspace)
                    _check_rag_publish_budget(
                        started_at=publish_started, stage="update_workspace_metadata",
                        budget_seconds=publish_budget_seconds,
                    )

            try:
                retry_busy(
                    publish,
                    retries=self._sqlite_write_retries,
                    base_delay_seconds=min(0.25, max(0.01, self._sqlite_busy_seconds / 10.0)),
                )
            except _RAGSourceChangedBeforePublish as exc:
                stale = set(exc.paths)
                self._publish_workspace_read_uncertainty(workspace, stale)
                return {
                    "success": False, "retryable": True, "workspace": workspace,
                    "error": "source_changed_before_publish",
                    "stale_source_paths": exc.paths,
                    "read_uncertain_paths": sorted(read_uncertain_paths | stale),
                }
            except Exception as exc:
                result = {
                    "success": False, "workspace": workspace,
                    "error": "publish_failed", "retryable": is_busy_error(exc),
                }
                if isinstance(exc, TimeoutError):
                    result["error_detail"] = str(exc)
                return result

        return {
            "success": True, "workspace": workspace, "preempted": False,
            "embedding_space_id": embedding_space,
            "embedding_space_resolved": embedding_space_resolved,
            "processed_paths": processed_paths, "embedded_chunks": embedded_chunks,
            "reused_chunks": reused_chunks,
            "policy_deleted_paths": sorted(policy_deleted),
            "read_uncertain_paths": sorted(read_uncertain_paths),
            "reindex_required": chunker_reindex_required,
        }

