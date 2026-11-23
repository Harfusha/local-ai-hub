from __future__ import annotations

from contextlib import closing, nullcontext
import math
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterable

from .process_utils import canonical_root
from .sqlite_support import incremental_vacuum, is_busy_error, write_transaction


CodeIndex = None


class CodeIndexMaintenanceMixin:
    def record_usage(self, root: str, paths: list[dict[str, Any]]) -> int:
        """Reconcile bounded usage evidence, keeping missing timestamps cold."""
        resolved_root = canonical_root(root)
        rows: list[tuple[str, str, int, float]] = []
        for item in paths[:256]:
            if not isinstance(item, dict):
                continue
            path = self._norm_rel(str(item.get("path") or ""))
            if not path:
                continue
            try:
                uses = max(1, min(int(item.get("uses", 1)), 2_147_483_647))
            except (TypeError, ValueError, OverflowError):
                uses = 1
            try:
                last_used_at = float(item.get("last_used_at", item.get("last_used", 0.0)))
            except (TypeError, ValueError, OverflowError):
                last_used_at = 0.0
            if not math.isfinite(last_used_at) or last_used_at <= 0:
                last_used_at = 0.0
            rows.append((resolved_root, path, uses, last_used_at))
        if not rows:
            return 0
        with self._write_lock, self._lock:
            unique_paths = sorted({row[1] for row in rows})
            with closing(self._connect()) as con:
                placeholders = ",".join("?" for _ in unique_paths)
                existing = {
                    str(row[0]) for row in con.execute(
                        f"SELECT path FROM file_usage WHERE root=? AND path IN ({placeholders})",
                        (resolved_root, *unique_paths),
                    ).fetchall()
                }
            missing_count = len(unique_paths) - len(existing)
            if missing_count:
                # Reserve conservative page and index headroom before metadata
                # writes too; otherwise usage-only paths can bypass the cap.
                budget = self._reserve_write_budget(resolved_root, missing_count * 1024)
                if not budget["success"]:
                    return 0
            with closing(self._connect()) as con:
                with write_transaction(
                    con, max_duration_seconds=5.0, rollback_label="code index usage"
                ):
                    placeholders = ",".join("?" for _ in unique_paths)
                    con.execute(
                        "UPDATE file_usage SET last_used_at=0 WHERE root=? "
                        f"AND last_used_at<>0 AND path NOT IN ({placeholders})",
                        (resolved_root, *unique_paths),
                    )
                    con.executemany(
                        "INSERT INTO file_usage(root,path,use_count,last_used_at) VALUES(?,?,?,?) "
                        "ON CONFLICT(root,path) DO UPDATE SET "
                        "use_count=MAX(file_usage.use_count,excluded.use_count), "
                        "last_used_at=excluded.last_used_at "
                        "WHERE excluded.use_count>file_usage.use_count "
                        "OR excluded.last_used_at<>file_usage.last_used_at",
                        rows,
                    )
        return len(rows)

    def measure_storage(self) -> dict[str, int]:
        """Measure SQLite allocation, free pages, and current on-disk sidecars."""
        with self._lock, closing(self._connect()) as con:
            page_count = int(con.execute("PRAGMA page_count").fetchone()[0])
            page_size = int(con.execute("PRAGMA page_size").fetchone()[0])
            freelist_count = int(con.execute("PRAGMA freelist_count").fetchone()[0])
            physical_bytes = sum(
                path.stat().st_size for path in (
                    self.db_path, Path(str(self.db_path) + "-wal"), Path(str(self.db_path) + "-shm"),
                ) if path.exists()
            )
        return {
            "page_count": page_count,
            "page_size": page_size,
            "freelist_count": freelist_count,
            "allocated_bytes": page_count * page_size,
            "reusable_bytes": freelist_count * page_size,
            "physical_bytes": physical_bytes,
        }

    def prune_unreferenced_parse_blobs(
        self,
        *,
        dry_run: bool = True,
        max_blobs: int = 2048,
        target_bytes: int | None = None,
    ) -> dict[str, Any]:
        """Evict a bounded oldest-first batch of parse blobs unused by any indexed file."""
        if type(dry_run) is not bool:
            return {"success": False, "error": "dry_run must be a boolean"}
        if self._read_only and not dry_run:
            return {"success": False, "dry_run": False, "error": "read_only_index"}
        if type(max_blobs) is not int or not 1 <= max_blobs <= 8192:
            return {"success": False, "error": "max_blobs must be between 1 and 8192"}
        if target_bytes is not None and (type(target_bytes) is not int or target_bytes < 0):
            return {"success": False, "error": "target_bytes must be a nonnegative integer"}

        before = self.measure_storage()
        deleted_count = 0
        deleted_payload_bytes = 0
        try:
            with self._lock, closing(self._connect()) as con, (
                write_transaction(
                    con, max_duration_seconds=5.0, rollback_label="code index parse blob prune"
                ) if not dry_run else nullcontext(con)
            ):
                totals = con.execute(
                    "SELECT COUNT(*) AS blob_count, "
                    "COALESCE(SUM(length(p.payload_json)),0) AS payload_bytes "
                    "FROM parse_blobs p WHERE NOT EXISTS ("
                    "SELECT 1 FROM files f WHERE f.content_hash=p.content_hash "
                    "AND f.analyzer_version=p.analyzer_version AND f.language=p.language)"
                ).fetchone()
                candidates = con.execute(
                    "SELECT p.rowid,length(p.payload_json) AS payload_bytes "
                    "FROM parse_blobs p WHERE NOT EXISTS ("
                    "SELECT 1 FROM files f WHERE f.content_hash=p.content_hash "
                    "AND f.analyzer_version=p.analyzer_version AND f.language=p.language) "
                    "ORDER BY p.updated_at ASC,p.rowid ASC LIMIT ?",
                    (max_blobs,),
                ).fetchall()
                selected: list[tuple[int, int]] = []
                selected_payload_bytes = 0
                for row in candidates:
                    if target_bytes == 0 or (
                        target_bytes is not None and selected_payload_bytes >= target_bytes
                    ):
                        break
                    selected.append((int(row[0]), max(0, int(row[1] or 0))))
                    selected_payload_bytes += selected[-1][1]
                if not dry_run and selected:
                    before_changes = con.total_changes
                    con.executemany(
                        "DELETE FROM parse_blobs WHERE rowid=? AND NOT EXISTS ("
                        "SELECT 1 FROM files f WHERE f.content_hash=parse_blobs.content_hash "
                        "AND f.analyzer_version=parse_blobs.analyzer_version "
                        "AND f.language=parse_blobs.language)",
                        [(rowid,) for rowid, _ in selected],
                    )
                    deleted_count = con.total_changes - before_changes
                    deleted_payload_bytes = sum(payload_bytes for _, payload_bytes in selected[:deleted_count])
        except sqlite3.DatabaseError as exc:
            return {
                "success": False,
                "dry_run": dry_run,
                "error": type(exc).__name__,
                "before": before,
                "after": self.measure_storage(),
            }

        candidate_count = int(totals["blob_count"])
        candidate_payload_bytes = int(totals["payload_bytes"])
        removed_count = deleted_count if not dry_run else len(selected)
        removed_payload_bytes = deleted_payload_bytes if not dry_run else selected_payload_bytes
        remaining_count = max(0, candidate_count - removed_count)
        remaining_payload_bytes = max(0, candidate_payload_bytes - removed_payload_bytes)
        after = self.measure_storage()
        return {
            "success": True,
            "dry_run": dry_run,
            "max_blobs": max_blobs,
            "candidate_blob_count": candidate_count,
            "candidate_payload_bytes": candidate_payload_bytes,
            "selected_blob_count": len(selected),
            "selected_payload_bytes": selected_payload_bytes,
            "deleted_blob_count": deleted_count,
            "logical_bytes_released": deleted_payload_bytes,
            "remaining_unreferenced_blob_count": remaining_count,
            "remaining_unreferenced_payload_bytes": remaining_payload_bytes,
            "before": before,
            "after": after,
            "physical_bytes_released": max(0, before["physical_bytes"] - after["physical_bytes"]),
        }

    def enforce_size_limit(
        self, *, max_bytes: int | None = None, dry_run: bool = False, max_files: int = 128,
        protected_roots: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Evict cold derived rows and reclaim SQLite pages in a bounded pass."""
        limit = self.max_index_bytes if max_bytes is None else max_bytes
        if type(limit) is not int or limit < 1:
            return {"success": False, "error": "max_bytes must be a positive integer"}
        if type(max_files) is not int or not 1 <= max_files <= 512:
            return {"success": False, "error": "max_files must be between 1 and 512"}
        if isinstance(protected_roots, (str, bytes)):
            return {"success": False, "error": "protected_roots must be an iterable of absolute paths"}
        try:
            raw_protected_roots = tuple(protected_roots)
        except TypeError:
            return {"success": False, "error": "protected_roots must be an iterable of absolute paths"}
        if len(raw_protected_roots) > 8192 or any(
            type(root) is not str or not root.strip() or not Path(root).is_absolute()
            for root in raw_protected_roots
        ):
            return {"success": False, "error": "protected_roots must contain at most 8192 absolute paths"}
        try:
            normalized_protected_roots = tuple(dict.fromkeys(
                canonical_root(root) for root in raw_protected_roots
            ))
        except (OSError, RuntimeError, ValueError) as exc:
            return {"success": False, "error": f"invalid protected root: {type(exc).__name__}"}
        before = self.measure_storage()
        if before["physical_bytes"] <= limit:
            return {
                "success": True, "dry_run": dry_run, "within_budget": True,
                "max_bytes": limit, "before": before, "after": before,
                "evicted_paths": [], "estimated_reclaimable_bytes": 0,
                "protected_root_count": len(normalized_protected_roots),
            }

        live_physical_before = max(0, before["physical_bytes"] - before["reusable_bytes"])
        cache_need = max(0, live_physical_before - limit)
        cache_cleanup = {
            "success": True,
            "dry_run": dry_run,
            "selected_blob_count": 0,
            "selected_payload_bytes": 0,
            "deleted_blob_count": 0,
            "logical_bytes_released": 0,
        }
        if cache_need:
            cache_cleanup = self.prune_unreferenced_parse_blobs(
                dry_run=dry_run, max_blobs=8192, target_bytes=cache_need,
            )
        cache_estimated = int(
            cache_cleanup.get(
                "selected_payload_bytes" if dry_run else "logical_bytes_released", 0
            ) or 0
        )
        if dry_run:
            live_physical_bytes = max(0, live_physical_before - cache_estimated)
        else:
            cache_after = cache_cleanup.get("after", before)
            live_physical_bytes = max(
                0, int(cache_after["physical_bytes"]) - int(cache_after["reusable_bytes"])
            )
        need = max(0, live_physical_bytes - limit)
        selected: list[tuple[str, str]] = []
        estimated = 0
        with self._lock, closing(self._connect()) as con, (
            write_transaction(
                con, max_duration_seconds=5.0, rollback_label="code index size enforcement"
            ) if not dry_run and need else nullcontext(con)
        ):
            if normalized_protected_roots:
                con.execute(
                    "CREATE TEMP TABLE protected_code_index_roots (root TEXT PRIMARY KEY) WITHOUT ROWID"
                )
                con.executemany(
                    "INSERT INTO protected_code_index_roots(root) VALUES (?)",
                    ((root,) for root in normalized_protected_roots),
                )
                candidate_filter = (
                    "WHERE NOT EXISTS (SELECT 1 FROM protected_code_index_roots p "
                    "WHERE p.root=f.root) "
                )
            else:
                candidate_filter = ""
            candidates = con.execute(
                "SELECT f.root,f.path,COALESCE(u.use_count,0) AS use_count, "
                "COALESCE(u.last_used_at,f.updated_at,0) AS last_used_at "
                "FROM files f LEFT JOIN file_usage u ON u.root=f.root AND u.path=f.path "
                + candidate_filter
                + "ORDER BY use_count ASC,last_used_at ASC,f.updated_at ASC,f.root ASC,f.path ASC "
                "LIMIT ?",
                (max_files,),
            ).fetchall()
            for row in candidates:
                if len(selected) >= max_files or estimated >= need:
                    break
                root_path = str(row["root"])
                file_path = str(row["path"])
                counts = {
                    table: int(con.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE root=? AND path=?",
                        (root_path, file_path),
                    ).fetchone()[0])
                    for table in ("symbols", "refs", "edges", "symbol_trigrams")
                }
                selected.append((root_path, file_path))
                # Source size_bytes is metadata only; source content is not stored here.
                estimated += (
                    counts["symbols"] * 1024
                    + counts["refs"] * 384
                    + counts["edges"] * 384
                    + counts["symbol_trigrams"] * 192
                    + 65536
                )
            if not dry_run and selected:
                for table in ("symbol_trigrams", "symbols", "refs", "edges", "file_usage", "files"):
                    con.executemany(f"DELETE FROM {table} WHERE root=? AND path=?", selected)

        if dry_run:
            predicted_physical = max(0, live_physical_bytes - estimated)
            return {
                "success": True, "dry_run": dry_run,
                "within_budget": predicted_physical <= limit, "max_bytes": limit,
                "before": before, "after": before,
                "evicted_paths": selected,
                "estimated_reclaimable_bytes": before["reusable_bytes"] + cache_estimated + estimated,
                "predicted_physical_bytes": predicted_physical,
                "parse_cache_cleanup": cache_cleanup,
                "protected_root_count": len(normalized_protected_roots),
            }

        if selected:
            self._advance_query_cache_generation()
        try:
            with closing(self._connect()) as con:
                auto_vacuum = int(con.execute("PRAGMA auto_vacuum").fetchone()[0])
        except sqlite3.DatabaseError as exc:
            auto_vacuum = 0
            compact_error = type(exc).__name__
        else:
            compact_error = None

        # Prefer bounded incremental reclamation. A full VACUUM is allowed only
        # for databases no larger than the configured index budget; larger legacy
        # databases would monopolize the writer lock and need explicit maintenance.
        if before["physical_bytes"] <= self.max_index_bytes:
            compact_deadline = time.monotonic() + 5.0
            try:
                with closing(self._connect()) as con:
                    con.set_progress_handler(lambda: int(time.monotonic() >= compact_deadline), 2000)
                    con.execute("VACUUM")
                vacuum = {"success": True, "method": "bounded_vacuum"}
            except sqlite3.DatabaseError as exc:
                vacuum = {"success": False, "method": "bounded_vacuum", "error": type(exc).__name__}
        elif auto_vacuum == 2:
            vacuum = incremental_vacuum(
                self.db_path, pages=65536, freelist_threshold=1, timeout_seconds=5.0,
            )
            vacuum["method"] = "incremental_vacuum"
        else:
            vacuum = {
                "success": False,
                "method": "skipped",
                "reason": "large_legacy_database_requires_scheduled_compaction",
            }
        if compact_error:
            vacuum["compaction_error"] = compact_error
        try:
            with closing(self._connect()) as con:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.DatabaseError:
            pass
        after = self.measure_storage()
        return {
            "success": bool(vacuum.get("success")),
            "dry_run": False,
            "within_budget": after["physical_bytes"] <= limit,
            "max_bytes": limit,
            "before": before,
            "after": after,
            "evicted_paths": selected,
            "estimated_reclaimable_bytes": before["reusable_bytes"] + cache_estimated + estimated,
            "physical_bytes_released": max(0, before["physical_bytes"] - after["physical_bytes"]),
            "parse_cache_cleanup": cache_cleanup,
            "vacuum": vacuum,
            "protected_root_count": len(normalized_protected_roots),
        }

    def prune_orphaned_trigrams(
        self,
        *,
        dry_run: bool = True,
        max_rows: int = 100000,
        max_roots: int = 64,
    ) -> dict[str, Any]:
        """Remove a bounded batch of trigram rows with no owning symbol.

        A fresh active-root snapshot is required for both dry-run and mutation.
        Active preprocessing roots and Git roots are protected. Source files,
        symbols, parse blobs, and other roots are never changed.
        """
        if type(dry_run) is not bool:
            return {"success": False, "error": "dry_run must be a boolean"}
        if self._read_only and not dry_run:
            return {"success": False, "dry_run": False, "error": "read_only_index"}
        if type(max_rows) is not int or not 1 <= max_rows <= 100000:
            return {"success": False, "error": "max_rows must be between 1 and 100000"}
        if type(max_roots) is not int or not 1 <= max_roots <= 128:
            return {"success": False, "error": "max_roots must be between 1 and 128"}

        provider = self._active_roots_provider
        if not callable(provider):
            return {"success": False, "error": "active_roots_unavailable"}
        try:
            active_values = provider()
            if isinstance(active_values, (str, bytes)) or active_values is None:
                return {"success": False, "error": "active_roots_unavailable"}
            active_roots = set()
            for value in active_values:
                if not isinstance(value, str) or not value.strip() or not Path(value).is_absolute():
                    return {"success": False, "error": "active_roots_unavailable"}
                active_roots.add(canonical_root(value))
        except Exception:
            return {"success": False, "error": "active_roots_unavailable"}

        before = self.measure_storage()
        try:
            with self._lock, closing(self._connect()) as con:
                if self._read_only:
                    con.execute("BEGIN")
                orphaned_total = int(con.execute(
                    "SELECT COUNT(*) FROM symbol_trigrams t WHERE NOT EXISTS ("
                    "SELECT 1 FROM symbols s WHERE s.rowid=t.symbol_rowid "
                    "AND s.root=t.root AND s.path=t.path)"
                ).fetchone()[0])
                root_rows = con.execute(
                    "SELECT t.root,COUNT(*) AS orphan_count FROM symbol_trigrams t "
                    "WHERE NOT EXISTS (SELECT 1 FROM symbols s WHERE s.rowid=t.symbol_rowid "
                    "AND s.root=t.root AND s.path=t.path) "
                    "GROUP BY t.root ORDER BY t.root LIMIT ?",
                    (max_roots + 1,),
                ).fetchall()
                has_more_roots = len(root_rows) > max_roots
                root_rows = root_rows[:max_roots]
                eligible_roots: list[str] = []
                skipped_roots: list[dict[str, Any]] = []
                eligible_total = 0
                for row in root_rows:
                    root = str(row["root"])
                    try:
                        base = Path(root).expanduser()
                        if not base.is_absolute() or "\x00" in root or base.is_symlink():
                            raise ValueError("unsafe_root_path")
                        base = base.resolve(strict=False)
                    except (OSError, RuntimeError, ValueError):
                        skipped_roots.append({"root": root, "reason": "unsafe_root_path"})
                        continue
                    if root in active_roots:
                        skipped_roots.append({"root": root, "reason": "active_preprocessing_root"})
                        continue
                    if any((ancestor / ".git").exists() for ancestor in (base, *base.parents)):
                        skipped_roots.append({"root": root, "reason": "active_git_root"})
                        continue
                    eligible_roots.append(root)
                    eligible_total += int(row["orphan_count"])

                placeholders = ",".join("?" for _ in eligible_roots)
                candidates = []
                if eligible_roots:
                    candidates = con.execute(
                        "SELECT t.root,t.path,t.symbol_rowid,t.field,t.gram "
                        "FROM symbol_trigrams t WHERE t.root IN (" + placeholders + ") "
                        "AND NOT EXISTS (SELECT 1 FROM symbols s WHERE s.rowid=t.symbol_rowid "
                        "AND s.root=t.root AND s.path=t.path) "
                        "ORDER BY t.root,t.path,t.symbol_rowid,t.field,t.gram LIMIT ?",
                        (*eligible_roots, max_rows),
                    ).fetchall()
                if not dry_run and candidates:
                    with write_transaction(
                        con, max_duration_seconds=5.0, rollback_label="code index orphan trigram prune"
                    ):
                        con.executemany(
                            "DELETE FROM symbol_trigrams WHERE root=? AND path=? AND symbol_rowid=? "
                            "AND field=? AND gram=? AND NOT EXISTS ("
                            "SELECT 1 FROM symbols s WHERE s.rowid=symbol_trigrams.symbol_rowid "
                            "AND s.root=symbol_trigrams.root AND s.path=symbol_trigrams.path)",
                            [tuple(row) for row in candidates],
                        )
                rows_pruned = 0 if dry_run else int(con.total_changes)
                after = self.measure_storage() if not dry_run else before
        except sqlite3.DatabaseError as exc:
            return {
                "success": False, "dry_run": dry_run, "error": str(exc),
                "busy": is_busy_error(exc), "storage_before": before,
                "storage_after": self.measure_storage(), "interrupted_safe_to_repeat": True,
            }

        if rows_pruned:
            self._advance_query_cache_generation()
        remaining_eligible = max(0, eligible_total - rows_pruned)
        return {
            "success": True, "dry_run": dry_run,
            "orphan_trigrams_available": orphaned_total,
            "eligible_trigrams": eligible_total,
            "rows_pruned": rows_pruned,
            "max_rows": max_rows,
            "has_more": remaining_eligible > 0 or has_more_roots,
            "roots_scanned": len(root_rows), "has_more_roots": has_more_roots,
            "skipped_roots": skipped_roots,
            "storage_before": before, "storage_after": after,
            "physical_bytes_released": max(0, before["physical_bytes"] - after["physical_bytes"]),
            "freelist_bytes_released": max(0, before["reusable_bytes"] - after["reusable_bytes"]),
            "interrupted_safe_to_repeat": True,
        }

    def cleanup_stale_files(
        self,
        *,
        dry_run: bool = True,
        max_roots: int = 64,
        max_paths_per_root: int = 20000,
        compact: bool = False,
        after_root: str | None = None,
    ) -> dict[str, Any]:
        """Prune derived rows for missing source paths and empty inactive roots.

        Active Git roots are skipped as a whole. For other roots, a source path
        must still resolve to a file inside its owning root to remain indexed.
        Shared parse blobs are never removed. Each root is committed separately,
        making interrupted runs safe to repeat.
        """
        if type(dry_run) is not bool or type(compact) is not bool:
            return {"success": False, "error": "dry_run and compact must be booleans"}
        if self._read_only and not dry_run:
            return {"success": False, "dry_run": False, "error": "read_only_index"}
        if after_root is not None and (
            not isinstance(after_root, str) or not after_root or "\x00" in after_root
            or len(after_root) > 32768 or not Path(after_root).is_absolute()
        ):
            return {"success": False, "error": "after_root must be an absolute path"}
        if type(max_roots) is not int or not 1 <= max_roots <= 128:
            return {"success": False, "error": "max_roots must be between 1 and 128"}
        if type(max_paths_per_root) is not int or not 1 <= max_paths_per_root <= 100000:
            return {"success": False, "error": "max_paths_per_root must be between 1 and 100000"}

        before = self.measure_storage()
        with self._lock, closing(self._connect()) as con:
            query = "SELECT root,COUNT(*) AS file_count FROM files"
            params: tuple[Any, ...] = ()
            if after_root is not None:
                query += " WHERE root > ?"
                params = (after_root,)
            query += " GROUP BY root ORDER BY root LIMIT ?"
            root_rows = con.execute(query, (*params, max_roots + 1)).fetchall()
        has_more_roots = len(root_rows) > max_roots
        root_rows = root_rows[:max_roots]
        next_root = str(root_rows[-1]["root"]) if has_more_roots and root_rows else None
        plans: list[dict[str, Any]] = []
        for root_row in root_rows:
            root = str(root_row["root"])
            base = Path(root).expanduser()
            if not base.is_absolute() or "\x00" in root or base.is_symlink():
                plans.append({"root": root, "skipped": True, "reason": "unsafe_root_path"})
                continue
            try:
                base = base.resolve(strict=False)
            except (OSError, RuntimeError, ValueError):
                plans.append({"root": root, "skipped": True, "reason": "root_resolution_failed"})
                continue
            if any((ancestor / ".git").exists() for ancestor in (base, *base.parents)):
                plans.append({"root": root, "skipped": True, "reason": "active_git_root"})
                continue
            with self._lock, closing(self._connect()) as con:
                total = int(con.execute("SELECT COUNT(*) FROM files WHERE root=?", (root,)).fetchone()[0])
                if total > max_paths_per_root:
                    plans.append({
                        "root": root, "skipped": True, "reason": "root_scan_limit",
                        "file_count": total, "max_paths_per_root": max_paths_per_root,
                    })
                    continue
                rows = con.execute(
                    "SELECT path,size_bytes FROM files WHERE root=? ORDER BY path",
                    (root,),
                ).fetchall()
            current_paths: list[str] = []
            stale_paths: list[str] = []
            logical_source_bytes = 0
            for row in rows:
                rel = str(row["path"] or "").replace("\\", "/")
                rel_path = Path(rel)
                if not rel or rel_path.is_absolute() or ".." in rel_path.parts or "\x00" in rel:
                    stale_paths.append(rel)
                    logical_source_bytes += max(0, int(row["size_bytes"] or 0))
                    continue
                target = base / rel_path
                try:
                    resolved_target = target.resolve(strict=True)
                    resolved_target.relative_to(base)
                    if not resolved_target.is_file() or target.is_symlink():
                        raise ValueError("source path is not a confined regular file")
                except (OSError, RuntimeError, ValueError):
                    stale_paths.append(rel)
                    logical_source_bytes += max(0, int(row["size_bytes"] or 0))
                    continue
                current_paths.append(rel)
            plans.append({
                "root": root, "skipped": False, "file_count": total,
                "stale_file_count": len(stale_paths),
                "logical_source_bytes": logical_source_bytes,
                "current_file_count": len(current_paths),
                "stale_paths": stale_paths,
                "current_paths": current_paths,
            })

        target_plans = [item for item in plans if not item.get("skipped") and item.get("stale_file_count", 0)]
        if dry_run:
            return {
                "success": True, "dry_run": True, "roots_scanned": len(root_rows),
                "has_more_roots": has_more_roots, "next_root": next_root, "roots": [
                    {key: value for key, value in item.items() if key not in {"current_paths", "stale_paths"}}
                    | {"stale_path_preview": item.get("stale_paths", [])[:20]}
                    for item in plans
                ],
                "stale_root_count": len(target_plans),
                "stale_file_count": sum(item["stale_file_count"] for item in target_plans),
                "logical_source_bytes": sum(item["logical_source_bytes"] for item in target_plans),
                "storage_before": before, "storage_after": before,
                "currently_reusable_bytes": before["reusable_bytes"],
                "parse_blobs_preserved": True,
            }

        pruned_roots: list[dict[str, Any]] = []
        for item in target_plans:
            result = self.prune(
                str(item["root"]), list(item["current_paths"]),
                stale_paths=list(item["stale_paths"]),
            )
            if not isinstance(result, dict) or result.get("success") is not True:
                return {
                    "success": False, "dry_run": False, "roots": pruned_roots,
                    "failed_root": item["root"], "error": result.get("error", "root_prune_failed") if isinstance(result, dict) else "root_prune_failed",
                    "storage_before": before, "storage_after": self.measure_storage(),
                    "interrupted_safe_to_repeat": True,
                }
            pruned_roots.append({"root": item["root"], "pruned": int(result.get("pruned", 0))})

        compaction: dict[str, Any] = {"success": True, "method": "not_requested"}
        if compact and any(int(item["pruned"]) > 0 for item in pruned_roots):
            compaction = incremental_vacuum(
                self.db_path, pages=65536, freelist_threshold=1, timeout_seconds=5.0,
            )
            try:
                with closing(self._connect()) as con:
                    con.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except sqlite3.DatabaseError as exc:
                compaction["checkpoint_error"] = type(exc).__name__
        after = self.measure_storage()
        return {
            "success": all(bool(item.get("success")) for item in (compaction,)),
            "dry_run": False, "roots_scanned": len(root_rows),
            "has_more_roots": has_more_roots, "next_root": next_root, "roots_pruned": pruned_roots,
            "files_pruned": sum(int(item["pruned"]) for item in pruned_roots),
            "logical_source_bytes": sum(item["logical_source_bytes"] for item in target_plans),
            "storage_before": before, "storage_after": after,
            "physical_bytes_released": max(0, before["physical_bytes"] - after["physical_bytes"]),
            "freelist_bytes_released": max(0, before["reusable_bytes"] - after["reusable_bytes"]),
            "compaction": compaction, "parse_blobs_preserved": True,
            "interrupted_safe_to_repeat": True,
        }

