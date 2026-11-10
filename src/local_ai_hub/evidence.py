from __future__ import annotations

from collections.abc import Mapping
from contextlib import closing
import hashlib
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal, is_busy_error

logger = logging.getLogger(__name__)


def _clean_text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    raw = str(value).replace("\x00", "")
    return raw.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def _safe_positive_int(value: Any, default: int, *, minimum: int = 1) -> int:
    if value is None or isinstance(value, bool):
        return max(minimum, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return max(minimum, default)
    return max(minimum, parsed)


def is_evidence_id(value: Any) -> bool:
    """Check the syntactic shape of a content-addressed evidence reference."""
    if isinstance(value, bool) or value is None:
        return False
    text = str(value)
    return len(text) == 21 and text.startswith("E") and all(
        char in "0123456789abcdefABCDEF" for char in text[1:]
    )


def is_current_evidence_id(value: Any, evidence_store: Any) -> bool:
    """Accept an evidence reference only when its store proves current provenance."""
    if not is_evidence_id(value) or evidence_store is None:
        return False
    validator = getattr(evidence_store, "validate_current", None)
    if not callable(validator):
        return False
    try:
        return validator(str(value)) is True
    except Exception:
        return False


class EvidenceStore:
    """Content-addressed exact evidence slices shared by every local/cloud agent.

    Evidence is immutable: an id is derived from root/path/file hash/line range/text.
    Consumers can pass ids between stages without duplicating source text. A later fetch
    optionally verifies the current file hash so stale evidence is explicit.
    """

    def __init__(self, state_dir: Path, max_entries: int = 100_000):
        self.db_path = state_dir / "evidence.sqlite3"
        self.max_entries = _safe_positive_int(max_entries, 100_000, minimum=1000)
        self._lock = threading.RLock()
        self._touched_ids: set[str] = set()
        state_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.db_path, timeout_seconds=0.75, row_factory=sqlite3.Row)

    @staticmethod
    def _hash_source_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(65536):
                digest.update(chunk)
        return digest.hexdigest()

    def _init_db(self) -> None:
        try:
            with self._lock, closing(self._connect()) as con:
                initialize_wal(con)
                con.executescript("""
                CREATE TABLE IF NOT EXISTS evidence(
                    id TEXT PRIMARY KEY, root TEXT NOT NULL, path TEXT NOT NULL,
                    file_hash TEXT NOT NULL, start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
                    text TEXT NOT NULL, created_at REAL NOT NULL, accessed_at REAL NOT NULL, hits INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_evidence_root_path ON evidence(root,path);
                CREATE INDEX IF NOT EXISTS idx_evidence_hits ON evidence(hits);
                """)
                con.commit()
        except sqlite3.DatabaseError as exc:
            if is_busy_error(exc):
                return
            # Derived data is rebuildable. Preserve the broken file for diagnostics.
            broken = self.db_path.with_suffix(f".corrupt-{int(time.time())}.sqlite3")
            try:
                self.db_path.replace(broken)
            except OSError:
                pass
            with self._lock, closing(self._connect()) as con:
                initialize_wal(con)
                con.executescript("""
                CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,root TEXT NOT NULL,path TEXT NOT NULL,file_hash TEXT NOT NULL,start_line INTEGER NOT NULL,end_line INTEGER NOT NULL,text TEXT NOT NULL,created_at REAL NOT NULL,accessed_at REAL NOT NULL,hits INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS idx_evidence_root_path ON evidence(root,path);
                CREATE INDEX IF NOT EXISTS idx_evidence_hits ON evidence(hits);
                """)

    @staticmethod
    def _id(root: str, path: str, file_hash: str, start: int, end: int, text: str) -> str:
        raw = f"{root}\0{path}\0{file_hash}\0{start}\0{end}\0{text}".encode("utf-8", errors="replace")
        return "E" + hashlib.sha256(raw).hexdigest()[:20]

    def put(self, root: str, item: dict[str, Any]) -> str | None:
        if not isinstance(item, Mapping):
            return None
        clean_root = _clean_text(root)
        path = _clean_text(item.get("path", ""))
        text = _clean_text(item.get("text") or item.get("raw") or item.get("content") or "")
        file_hash = _clean_text(item.get("file_sha256") or item.get("content_hash") or "")
        if not path or not text or not file_hash:
            return None
        if clean_root:
            try:
                cand = (Path(clean_root) / path).resolve()
                cand.relative_to(Path(clean_root).resolve())
            except Exception:
                return None
        start = _safe_positive_int(item.get("start_line", 1), 1, minimum=1)
        end = _safe_positive_int(item.get("end_line", start), start, minimum=start)
        text = self._strip_display_line_numbers(text, start, end)
        eid = self._id(clean_root, path, file_hash, start, end, text)
        now = time.time()
        try:
            with self._lock, closing(self._connect()) as con:
                con.execute("INSERT OR IGNORE INTO evidence(id,root,path,file_hash,start_line,end_line,text,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,?,?,0)", (eid, clean_root, path, file_hash, start, end, text, now, now))
                con.execute("UPDATE evidence SET accessed_at=?,hits=hits+1 WHERE id=?", (now, eid))
                # Probabilistic count check (1 in 32 inserts) to prevent table scan on every write
                if int(now * 1000) % 32 == 0:
                    count = int(con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0])
                    if count > self.max_entries:
                        con.execute("DELETE FROM evidence WHERE id IN (SELECT id FROM evidence ORDER BY accessed_at ASC LIMIT ?)", (count - self.max_entries + 32,))
                con.commit()
        except sqlite3.DatabaseError:
            return None
        return eid

    def recent_paths(self, root: str, *, limit: int = 128) -> list[dict[str, Any]]:
        """Return bounded, root-scoped usage metadata without source text."""
        if not isinstance(root, str) or not root or root != root.strip():
            raise ValueError("root must be a non-empty canonical string")
        if type(limit) is not int or not 1 <= limit <= 256:
            raise ValueError("limit must be an integer between 1 and 256")
        with self._lock, closing(self._connect()) as con:
            rows = con.execute(
                "SELECT path, SUM(hits) AS uses, MAX(accessed_at) AS last_used "
                "FROM evidence WHERE root=? GROUP BY path "
                "ORDER BY last_used DESC, uses DESC, path ASC LIMIT ?",
                (root, limit),
            ).fetchall()
        return [{"path": str(row["path"]), "uses": int(row["uses"]),
                 "last_used": float(row["last_used"])} for row in rows]

    def put_many(self, root: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items or not isinstance(items, (list, tuple)):
            return []
        clean_root = _clean_text(root)
        now = time.time()
        inserts = []
        updates = []
        out: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            clone = dict(item)
            path = _clean_text(item.get("path", ""))
            text = _clean_text(item.get("text") or item.get("raw") or item.get("content") or "")
            file_hash = _clean_text(item.get("file_sha256") or item.get("content_hash") or "")
            if not path or not text or not file_hash:
                out.append(clone)
                continue
            start = _safe_positive_int(item.get("start_line", 1), 1, minimum=1)
            end = _safe_positive_int(item.get("end_line", start), start, minimum=start)
            text = self._strip_display_line_numbers(text, start, end)
            eid = self._id(clean_root, path, file_hash, start, end, text)
            clone["evidence_id"] = eid
            inserts.append((eid, clean_root, path, file_hash, start, end, text, now, now))
            updates.append((now, eid))
            out.append(clone)

        if inserts:
            try:
                with self._lock, closing(self._connect()) as con:
                    con.executemany("INSERT OR IGNORE INTO evidence(id,root,path,file_hash,start_line,end_line,text,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,?,?,0)", inserts)
                    con.executemany("UPDATE evidence SET accessed_at=?,hits=hits+1 WHERE id=?", updates)
                    count = int(con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0])
                    if count > self.max_entries:
                        con.execute("DELETE FROM evidence WHERE id IN (SELECT id FROM evidence ORDER BY accessed_at ASC LIMIT ?)", (count - self.max_entries + 32,))
                    con.commit()
            except sqlite3.DatabaseError as store_exc:
                logger.debug(
                    "Evidence batch persistence skipped (%s)",
                    type(store_exc).__name__,
                )
                unpersisted_ids = {str(row[0]) for row in inserts}
                for item in out:
                    if str(item.get("evidence_id") or "") in unpersisted_ids:
                        item.pop("evidence_id", None)
        return out

    @staticmethod
    def _strip_display_line_numbers(text: str, start: int, end: int) -> str:
        lines = text.splitlines()
        if len(lines) != end - start + 1:
            return text
        source_lines: list[str] = []
        for line_number, line in enumerate(lines, start=start):
            prefix = f"{line_number}: "
            if not line.startswith(prefix):
                return text
            source_lines.append(line[len(prefix):])
        return "\n".join(source_lines)

    def get(self, evidence_id: str, *, verify: bool = True, root: str | None = None) -> dict[str, Any]:
        eid = _clean_text(evidence_id).strip()
        if not eid:
            return {"success": False, "error": "evidence not found"}
        try:
            with self._lock, closing(self._connect()) as con:
                if root is not None:
                    if not isinstance(root, str) or not root:
                        return {"success": False, "error": "evidence not found"}
                    row = con.execute("SELECT * FROM evidence WHERE id=? AND root=?", (eid, root)).fetchone()
                else:
                    row = con.execute("SELECT * FROM evidence WHERE id=?", (eid,)).fetchone()
                if not row:
                    return {"success": False, "error": "evidence not found"}
                # A fetched evidence item is normally reused repeatedly within one
                # agent turn. Persist recency only once per process/id to avoid a WAL
                # write for every verification fetch.
                if eid not in self._touched_ids:
                    con.execute("UPDATE evidence SET accessed_at=?,hits=hits+1 WHERE id=?", (time.time(), eid))
                    con.commit()
                    self._touched_ids.add(eid)
                    if len(self._touched_ids) > 8192:
                        self._touched_ids.clear(); self._touched_ids.add(eid)
        except sqlite3.DatabaseError:
            return {"success": False, "error": "evidence store unavailable"}
        stale = False
        if verify:
            try:
                path = (Path(str(row["root"])) / str(row["path"])).resolve(strict=False)
                if path.is_file():
                    h = hashlib.sha256()
                    with path.open("rb") as f:
                        while chunk := f.read(65536):
                            h.update(chunk)
                    if h.hexdigest() != str(row["file_hash"]):
                        stale = True
                    else:
                        try:
                            with path.open("r", encoding="utf-8", errors="replace") as f:
                                s_line = int(row["start_line"])
                                e_line = int(row["end_line"])
                                selected: list[str] = []
                                line_count = 0
                                for line_count, line in enumerate(f, start=1):
                                    if s_line <= line_count <= e_line:
                                        selected.append(line)
                                    if line_count >= e_line:
                                        break
                            if s_line < 1 or line_count < e_line or len(selected) != e_line - s_line + 1:
                                stale = True
                            else:
                                expected_snippet = "".join(selected).rstrip("\r\n")
                                actual_snippet = str(row["text"]).rstrip("\r\n")
                                if expected_snippet != actual_snippet:
                                    stale = True
                        except Exception:
                            stale = True
                else:
                    stale = True
            except Exception:
                stale = True
        return {"success": True, "evidence_id": eid, "root": row["root"], "path": row["path"], "file_sha256": row["file_hash"], "start_line": row["start_line"], "end_line": row["end_line"], "text": row["text"], "stale": stale}

    def get_many(self, evidence_ids: list[str], *, verify: bool = True, root: str | None = None) -> list[dict[str, Any]]:
        """Fetch bounded evidence batches, sharing database and source verification work."""
        if not isinstance(evidence_ids, (list, tuple)) or not evidence_ids:
            return []
        if root is not None and (not isinstance(root, str) or not root):
            return [{"success": False, "error": "evidence not found"} for _ in evidence_ids]
        ids = [_clean_text(value).strip() for value in evidence_ids]
        unique_ids = list(dict.fromkeys(value for value in ids if value))
        rows_by_id: dict[str, sqlite3.Row] = {}
        try:
            with self._lock, closing(self._connect()) as con:
                for offset in range(0, len(unique_ids), 400):
                    batch = unique_ids[offset:offset + 400]
                    placeholders = ",".join("?" for _ in batch)
                    sql = f"SELECT * FROM evidence WHERE id IN ({placeholders})"
                    params: tuple[Any, ...] = tuple(batch)
                    if root is not None:
                        sql = f"SELECT * FROM evidence WHERE root=? AND id IN ({placeholders})"
                        params = (root, *batch)
                    rows_by_id.update({str(row["id"]): row for row in con.execute(sql, params).fetchall()})
                now = time.time()
                untouched = [eid for eid in unique_ids if eid in rows_by_id and eid not in self._touched_ids]
                if untouched:
                    con.executemany("UPDATE evidence SET accessed_at=?,hits=hits+1 WHERE id=?", [(now, eid) for eid in untouched])
                    con.commit()
                    for eid in untouched:
                        self._touched_ids.add(eid)
                        if len(self._touched_ids) > 8192:
                            self._touched_ids.clear()
                            self._touched_ids.add(eid)
        except sqlite3.DatabaseError:
            return [{"success": False, "error": "evidence store unavailable"} for _ in ids]

        stale_by_id: dict[str, bool] = {}
        if verify:
            rows_by_path: dict[str, list[sqlite3.Row]] = {}
            for row in rows_by_id.values():
                try:
                    path = str((Path(str(row["root"])) / str(row["path"])).resolve(strict=False))
                except Exception:
                    stale_by_id[str(row["id"])] = True
                    continue
                rows_by_path.setdefault(path, []).append(row)
            for raw_path, rows in rows_by_path.items():
                path = Path(raw_path)
                stale_ids = {str(row["id"]) for row in rows}
                try:
                    if not path.is_file():
                        stale_by_id.update({eid: True for eid in stale_ids})
                        continue
                    actual_hash = self._hash_source_file(path)
                    hash_matches = {str(row["id"]): actual_hash == str(row["file_hash"]) for row in rows}
                    readable = [row for row in rows if hash_matches[str(row["id"])] ]
                    if readable:
                        starts: dict[int, list[sqlite3.Row]] = {}
                        ends: dict[int, list[sqlite3.Row]] = {}
                        for row in readable:
                            starts.setdefault(int(row["start_line"]), []).append(row)
                            ends.setdefault(int(row["end_line"]), []).append(row)
                        selected: dict[str, list[str]] = {str(row["id"]): [] for row in readable}
                        active: dict[str, sqlite3.Row] = {}
                        line_count = 0
                        with path.open("r", encoding="utf-8", errors="replace") as source:
                            for line_count, line in enumerate(source, start=1):
                                for row in starts.get(line_count, ()):
                                    active[str(row["id"])] = row
                                for eid in active:
                                    selected[eid].append(line)
                                for row in ends.get(line_count, ()):
                                    active.pop(str(row["id"]), None)
                                if line_count >= max(ends):
                                    break
                        for row in readable:
                            eid = str(row["id"])
                            start_line = int(row["start_line"])
                            end_line = int(row["end_line"])
                            actual_lines = selected[eid]
                            expected = "".join(actual_lines).rstrip("\r\n")
                            recorded = str(row["text"]).rstrip("\r\n")
                            stale_by_id[eid] = (start_line < 1 or line_count < end_line
                                                or len(actual_lines) != end_line - start_line + 1
                                                or expected != recorded)
                    for eid, matches in hash_matches.items():
                        stale_by_id.setdefault(eid, not matches)
                except Exception:
                    stale_by_id.update({eid: True for eid in stale_ids})

        results: list[dict[str, Any]] = []
        for eid in ids:
            row = rows_by_id.get(eid)
            if not eid or row is None:
                results.append({"success": False, "error": "evidence not found"})
                continue
            results.append({"success": True, "evidence_id": eid, "root": row["root"], "path": row["path"],
                            "file_sha256": row["file_hash"], "start_line": row["start_line"],
                            "end_line": row["end_line"], "text": row["text"],
                            "stale": stale_by_id.get(eid, False)})
        return results

    def validate_current(self, evidence_id: str) -> bool:
        """Prove an evidence ID still matches its stored row and current source."""
        if not is_evidence_id(evidence_id):
            return False
        try:
            item = self.get(evidence_id, verify=True)
            if (
                not item.get("success")
                or item.get("stale") is not False
                or item.get("evidence_id") != evidence_id
            ):
                return False
            expected = self._id(
                str(item["root"]),
                str(item["path"]),
                str(item["file_sha256"]),
                int(item["start_line"]),
                int(item["end_line"]),
                str(item["text"]),
            )
        except Exception:
            return False
        return expected == evidence_id

    def validate_current_many(self, evidence_ids: Any) -> bool:
        """Prove a bounded evidence batch is current, hashing each source once."""
        if type(evidence_ids) not in (list, tuple) or not evidence_ids or len(evidence_ids) > 64:
            return False
        if any(not isinstance(value, str) or not is_evidence_id(value) for value in evidence_ids):
            return False
        ids = list(dict.fromkeys(evidence_ids))
        placeholders = ",".join("?" for _ in ids)
        try:
            with self._lock, closing(self._connect()) as con:
                rows = con.execute(
                    "SELECT id,root,path,file_hash,start_line,end_line,text FROM evidence "
                    f"WHERE id IN ({placeholders})",
                    tuple(ids),
                ).fetchall()
            by_id = {str(row["id"]): row for row in rows}
            if len(by_id) != len(ids):
                return False

            file_hashes: dict[Path, str] = {}
            for evidence_id in ids:
                row = by_id[evidence_id]
                expected = self._id(
                    str(row["root"]),
                    str(row["path"]),
                    str(row["file_hash"]),
                    int(row["start_line"]),
                    int(row["end_line"]),
                    str(row["text"]),
                )
                if expected != evidence_id:
                    return False

                path = (Path(str(row["root"])) / str(row["path"])).resolve(strict=False)
                actual_hash = file_hashes.get(path)
                if actual_hash is None:
                    if not path.is_file():
                        return False
                    actual_hash = self._hash_source_file(path)
                    file_hashes[path] = actual_hash
                if actual_hash != str(row["file_hash"]):
                    return False

                start_line = int(row["start_line"])
                end_line = int(row["end_line"])
                selected: list[str] = []
                line_count = 0
                with path.open("r", encoding="utf-8", errors="replace") as source:
                    for line_count, line in enumerate(source, start=1):
                        if start_line <= line_count <= end_line:
                            selected.append(line)
                        if line_count >= end_line:
                            break
                if (
                    start_line < 1
                    or line_count < end_line
                    or len(selected) != end_line - start_line + 1
                ):
                    return False
                if "".join(selected).rstrip("\r\n") != str(row["text"]).rstrip("\r\n"):
                    return False
        except Exception:
            return False
        return True

    def count(self) -> int:
        return int(self.stats().get("entries", 0))

    def has(self, evidence_id: str) -> bool:
        eid = _clean_text(evidence_id).strip()
        if not is_evidence_id(eid):
            return False
        try:
            with self._lock, closing(self._connect()) as con:
                row = con.execute("SELECT 1 FROM evidence WHERE id=? LIMIT 1", (eid,)).fetchone()
                return row is not None
        except sqlite3.DatabaseError:
            return False

    def clear(self) -> None:
        try:
            with self._lock, closing(self._connect()) as con:
                con.execute("DELETE FROM evidence")
                con.commit()
                self._touched_ids.clear()
        except sqlite3.DatabaseError:
            pass

    def stats(self) -> dict[str, Any]:
        try:
            with closing(self._connect()) as con:
                row = con.execute("SELECT COUNT(*),COALESCE(SUM(hits),0) FROM evidence").fetchone()
            return {"entries": int(row[0]), "hits": int(row[1]), "healthy": True}
        except sqlite3.DatabaseError:
            return {"entries": 0, "hits": 0, "healthy": False}
