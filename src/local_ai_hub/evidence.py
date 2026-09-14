from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .sqlite_support import connect_sqlite, initialize_wal, is_busy_error


class EvidenceStore:
    """Content-addressed exact evidence slices shared by every local/cloud agent.

    Evidence is immutable: an id is derived from root/path/file hash/line range/text.
    Consumers can pass ids between stages without duplicating source text. A later fetch
    optionally verifies the current file hash so stale evidence is explicit.
    """

    def __init__(self, state_dir: Path, max_entries: int = 100_000):
        self.db_path = state_dir / "evidence.sqlite3"
        self.max_entries = max(1000, int(max_entries))
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
                """)

    @staticmethod
    def _id(root: str, path: str, file_hash: str, start: int, end: int, text: str) -> str:
        raw = f"{root}\0{path}\0{file_hash}\0{start}\0{end}\0{text}".encode("utf-8", errors="replace")
        return "E" + hashlib.sha256(raw).hexdigest()[:20]

    def put(self, root: str, item: dict[str, Any]) -> str | None:
        path = str(item.get("path", ""))
        text = str(item.get("text", ""))
        file_hash = str(item.get("file_sha256") or item.get("content_hash") or "")
        if not path or not text or not file_hash:
            return None
        start = int(item.get("start_line", 1) or 1)
        end = int(item.get("end_line", start) or start)
        eid = self._id(root, path, file_hash, start, end, text)
        now = time.time()
        try:
            with self._lock, closing(self._connect()) as con:
                con.execute("INSERT OR IGNORE INTO evidence(id,root,path,file_hash,start_line,end_line,text,created_at,accessed_at,hits) VALUES(?,?,?,?,?,?,?,?,?,0)", (eid, root, path, file_hash, start, end, text, now, now))
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
        if not items:
            return []
        now = time.time()
        inserts = []
        updates = []
        out: list[dict[str, Any]] = []
        for item in items:
            clone = dict(item)
            path = str(item.get("path", ""))
            text = str(item.get("text", ""))
            file_hash = str(item.get("file_sha256") or item.get("content_hash") or "")
            if not path or not text or not file_hash:
                out.append(clone)
                continue
            start = int(item.get("start_line", 1) or 1)
            end = int(item.get("end_line", start) or start)
            eid = self._id(root, path, file_hash, start, end, text)
            clone["evidence_id"] = eid
            inserts.append((eid, root, path, file_hash, start, end, text, now, now))
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
            except sqlite3.DatabaseError:
                pass
        return out

    def get(self, evidence_id: str, *, verify: bool = True) -> dict[str, Any]:
        try:
            with self._lock, closing(self._connect()) as con:
                row = con.execute("SELECT * FROM evidence WHERE id=?", (evidence_id,)).fetchone()
                if not row:
                    return {"success": False, "error": "evidence not found"}
                # A fetched evidence item is normally reused repeatedly within one
                # agent turn. Persist recency only once per process/id to avoid a WAL
                # write for every verification fetch.
                if evidence_id not in self._touched_ids:
                    con.execute("UPDATE evidence SET accessed_at=?,hits=hits+1 WHERE id=?", (time.time(), evidence_id))
                    con.commit()
                    self._touched_ids.add(evidence_id)
                    if len(self._touched_ids) > 8192:
                        self._touched_ids.clear(); self._touched_ids.add(evidence_id)
        except sqlite3.DatabaseError as exc:
            return {"success": False, "error": f"evidence store unavailable: {exc}"}
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
        return {"success": True, "evidence_id": evidence_id, "root": row["root"], "path": row["path"], "file_sha256": row["file_hash"], "start_line": row["start_line"], "end_line": row["end_line"], "text": row["text"], "stale": stale}

    def stats(self) -> dict[str, Any]:
        try:
            with self._lock, closing(self._connect()) as con:
                row = con.execute("SELECT COUNT(*),COALESCE(SUM(hits),0) FROM evidence").fetchone()
            return {"entries": int(row[0]), "hits": int(row[1]), "healthy": True}
        except sqlite3.DatabaseError:
            return {"entries": 0, "hits": 0, "healthy": False}
