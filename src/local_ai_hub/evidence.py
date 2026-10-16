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
        start = _safe_positive_int(item.get("start_line", 1), 1, minimum=1)
        end = _safe_positive_int(item.get("end_line", start), start, minimum=start)
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

    def get(self, evidence_id: str, *, verify: bool = True) -> dict[str, Any]:
        eid = _clean_text(evidence_id).strip()
        if not eid:
            return {"success": False, "error": "evidence not found"}
        try:
            with self._lock, closing(self._connect()) as con:
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
                    stale = hashlib.sha256(path.read_bytes()).hexdigest() != str(row["file_hash"])
                else:
                    stale = True
            except Exception:
                stale = True
        return {"success": True, "evidence_id": eid, "root": row["root"], "path": row["path"], "file_sha256": row["file_hash"], "start_line": row["start_line"], "end_line": row["end_line"], "text": row["text"], "stale": stale}

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
