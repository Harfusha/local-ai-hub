"""Shared external content for the preprocessor's native FTS5 index."""

from collections.abc import Iterable
from hashlib import sha256
import sqlite3
import time

from .sqlite_support import write_transaction


SHARED_FTS_ROWS = "source_fts_bindings"
LEGACY_FTS = "source_fts"
_COPY_FTS = "source_fts_next"
_RETIRED_FTS = "source_fts_retired"
_WRITE_BATCH_ROWS = 256
_WRITE_BATCH_BYTES = 8 * 1024 * 1024
_MIGRATION_BATCH_ROWS = 128

_SHARED_SCHEMA = (
    """CREATE TABLE source_fts_documents (
        id INTEGER PRIMARY KEY, digest BLOB NOT NULL UNIQUE, content TEXT
    )""",
    """CREATE TABLE source_fts_bindings (
        id INTEGER PRIMARY KEY, root TEXT, path TEXT,
        document_id INTEGER NOT NULL REFERENCES source_fts_documents(id)
    )""",
    "CREATE INDEX source_fts_binding_path ON source_fts_bindings(root,path)",
    "CREATE INDEX source_fts_binding_document ON source_fts_bindings(document_id)",
    """CREATE VIEW source_fts_contents AS
       SELECT b.id,b.root,b.path,d.content FROM source_fts_bindings b
       JOIN source_fts_documents d ON d.id=b.document_id""",
    """CREATE TRIGGER source_fts_document_gc AFTER DELETE ON source_fts_bindings BEGIN
        DELETE FROM source_fts_documents WHERE id=old.document_id
        AND NOT EXISTS (SELECT 1 FROM source_fts_bindings WHERE document_id=old.document_id);
    END""",
)


def _create_delete_trigger(con: sqlite3.Connection, index: str) -> None:
    con.execute(f"""CREATE TRIGGER source_fts_binding_delete BEFORE DELETE ON source_fts_bindings BEGIN
        INSERT INTO {index}({index},rowid,root,path,content)
        SELECT 'delete',old.id,old.root,old.path,content FROM source_fts_documents WHERE id=old.document_id;
    END""")


def _create_shared_schema(con: sqlite3.Connection, index: str) -> None:
    for ddl in _SHARED_SCHEMA:
        con.execute(ddl)
    con.execute(f"""CREATE VIRTUAL TABLE {index} USING fts5(root UNINDEXED,path UNINDEXED,content,
        content='source_fts_contents',content_rowid='id')""")
    _create_delete_trigger(con, index)


def fts_layout(con: sqlite3.Connection) -> str:
    return str(con.execute("""SELECT CASE
        WHEN EXISTS (SELECT 1 FROM sqlite_master WHERE name='source_fts_migration') THEN 'source_fts_next'
        WHEN EXISTS (SELECT 1 FROM sqlite_master WHERE name='source_fts_bindings') THEN 'source_fts_bindings'
        ELSE 'source_fts' END""").fetchone()[0])


def writable_fts_layout(con: sqlite3.Connection) -> str:
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")
    return fts_layout(con)


def has_retired_fts(con: sqlite3.Connection) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (_RETIRED_FTS,)).fetchone() is not None


def has_canonical_shared_fts(con: sqlite3.Connection) -> bool:
    """Return whether every shared-index object needed by current runtime exists."""
    if fts_layout(con) != SHARED_FTS_ROWS or has_retired_fts(con):
        return False
    columns = {
        "source_fts_documents": ("id", "digest", "content"),
        "source_fts_bindings": ("id", "root", "path", "document_id"),
        "source_fts": ("root", "path", "content"),
    }
    for table, expected in columns.items():
        actual = tuple(str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")'))
        if actual != expected:
            return False
    objects = {
        (str(kind), str(name))
        for kind, name in con.execute(
            "SELECT type,name FROM sqlite_master WHERE name IN "
            "('source_fts_contents','source_fts_document_gc','source_fts_binding_delete',"
            "'source_fts_binding_path','source_fts_binding_document')"
        )
    }
    expected_objects = {
        ("view", "source_fts_contents"),
        ("trigger", "source_fts_document_gc"),
        ("trigger", "source_fts_binding_delete"),
        ("index", "source_fts_binding_path"),
        ("index", "source_fts_binding_document"),
    }
    if not expected_objects.issubset(objects):
        return False
    sql_row = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='source_fts'").fetchone()
    sql = " ".join(str(sql_row[0] or "").lower().split()) if sql_row else ""
    return "using fts5" in sql and "content='source_fts_contents'" in sql and "content_rowid='id'" in sql


def initialize_fts_rows(con: sqlite3.Connection) -> str:
    with write_transaction(con, rollback_label="lexical index schema"):
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='source_fts'").fetchone() is None:
            _create_shared_schema(con, LEGACY_FTS)
        layout = fts_layout(con)
        if layout != SHARED_FTS_ROWS or not has_canonical_shared_fts(con):
            raise sqlite3.DatabaseError("preprocess state requires the update-time lexical-index migration")
        return layout


_LegacyRow = tuple[int | None, str | None, str | None, str | None]
_PendingRow = tuple[int | None, str | None, str | None, bytes, str | None]


def _write_shared_batch(con: sqlite3.Connection, index: str, batch: list[_PendingRow]) -> None:
    con.execute("""CREATE TEMP TABLE IF NOT EXISTS source_fts_pending (
        seq INTEGER PRIMARY KEY, legacy_id INTEGER, root TEXT, path TEXT, digest BLOB NOT NULL, content TEXT
    )""")
    con.executemany("INSERT INTO source_fts_pending(legacy_id,root,path,digest,content) VALUES(?,?,?,?,?)", batch)
    con.execute("""INSERT INTO source_fts_documents(digest,content)
        SELECT digest,content FROM source_fts_pending WHERE 1 ON CONFLICT(digest) DO NOTHING""")
    if con.execute("""SELECT 1 FROM source_fts_pending p
        JOIN source_fts_documents d ON d.digest=p.digest WHERE d.content IS NOT p.content LIMIT 1""").fetchone():
        raise sqlite3.IntegrityError("Lexical payload digest collision")

    # Allocate shared row IDs under the same write lock as the FTS posting insert.
    last_id = con.execute("SELECT COALESCE(MAX(id),0) FROM source_fts_bindings").fetchone()[0]
    con.execute("""INSERT INTO source_fts_bindings(id,root,path,document_id)
        SELECT COALESCE(p.legacy_id,?+p.seq),p.root,p.path,d.id FROM source_fts_pending p
        JOIN source_fts_documents d ON d.digest=p.digest""", (last_id,))
    con.execute(f"""INSERT INTO {index}(rowid,root,path,content)
        SELECT COALESCE(legacy_id,?+seq),root,path,content FROM source_fts_pending""", (last_id,))
    con.execute("DELETE FROM source_fts_pending")


def _insert_shared_rows(con: sqlite3.Connection, index: str, rows: Iterable[_LegacyRow]) -> None:
    batch: list[_PendingRow] = []
    batch_bytes = 0
    for rowid, root, path, content in rows:
        encoded = content.encode("utf-8") if content is not None else b""
        row_bytes = len(encoded)
        if batch and (len(batch) == _WRITE_BATCH_ROWS or batch_bytes + row_bytes > _WRITE_BATCH_BYTES):
            _write_shared_batch(con, index, batch)
            batch.clear()
            batch_bytes = 0
        batch.append((rowid, root, path, sha256(encoded).digest() if content is not None else b"", content))
        batch_bytes += row_bytes
    if batch:
        _write_shared_batch(con, index, batch)


def insert_fts_rows(con: sqlite3.Connection, layout: str, rows: Iterable[tuple[str, str, str]]) -> None:
    insert_legacy = "INSERT INTO source_fts(root,path,content) VALUES(?,?,?)"
    if layout == LEGACY_FTS:
        con.executemany(insert_legacy, rows)
    elif layout == SHARED_FTS_ROWS:
        _insert_shared_rows(con, LEGACY_FTS, ((None, *row) for row in rows))
    else:
        _insert_shared_rows(con, _COPY_FTS, ((con.execute(insert_legacy, row).lastrowid, *row) for row in rows))


def delete_fts_rows(con: sqlite3.Connection, where: str, params: tuple) -> None:
    layout = writable_fts_layout(con)
    active_rows = SHARED_FTS_ROWS if layout == SHARED_FTS_ROWS else LEGACY_FTS
    con.execute(f"DELETE FROM {active_rows} AS published WHERE {where}", params)
    if layout == _COPY_FTS:
        con.execute(f"DELETE FROM {SHARED_FTS_ROWS} AS published WHERE {where}", params)


def _verify_next_range(con: sqlite3.Connection, last_id: int | None, end_id: int | None) -> int | None:
    if end_id is None:
        return None
    edges = []
    for table in (LEGACY_FTS, SHARED_FTS_ROWS):
        sql = f"SELECT rowid FROM {table} WHERE rowid<=?"
        params = (end_id,)
        if last_id is not None:
            sql += " AND rowid>?"
            params += (last_id,)
        ids = con.execute(sql + " ORDER BY rowid LIMIT ?", (*params, _MIGRATION_BATCH_ROWS)).fetchall()
        if ids:
            edges.append((ids[-1][0], len(ids) == _MIGRATION_BATCH_ROWS))
    if not edges:
        return None

    full = [edge for edge, has_full_batch in edges if has_full_batch]
    upper = min(full) if full else max(edge for edge, _ in edges)
    legacy_range = "f.rowid<=?"
    shared_range = "b.id<=?"
    params = (upper,)
    if last_id is not None:
        legacy_range += " AND f.rowid>?"
        shared_range += " AND b.id>?"
        params += (last_id,)
    if con.execute(f"""SELECT EXISTS (
        SELECT 1 FROM source_fts f LEFT JOIN source_fts_bindings c ON c.id=f.rowid
        LEFT JOIN source_fts_documents d ON d.id=c.document_id
        WHERE {legacy_range} AND (
            d.id IS NULL OR f.root IS NOT c.root OR f.path IS NOT c.path OR f.content IS NOT d.content
        )
    ) OR EXISTS (
        SELECT 1 FROM source_fts_bindings b WHERE {shared_range}
        AND NOT EXISTS (SELECT 1 FROM source_fts f WHERE f.rowid=b.id)
    )""", (*params, *params)).fetchone()[0]:
        raise sqlite3.IntegrityError("Shared lexical index does not match the legacy index")
    return upper


def advance_fts_migration(con: sqlite3.Connection) -> bool:
    """Copy one bounded batch or atomically adopt the completed external index."""
    with write_transaction(con, rollback_label="lexical index migration"):
        layout = fts_layout(con)
        if layout == SHARED_FTS_ROWS:
            if has_retired_fts(con):
                deadline = time.monotonic() + 4.0
                con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
                try:
                    con.execute("DROP TABLE source_fts_retired")
                finally:
                    con.set_progress_handler(None, 0)
            return False
        if layout == LEGACY_FTS:
            _create_shared_schema(con, _COPY_FTS)
            con.execute("CREATE TABLE source_fts_migration (last_id INTEGER, end_id INTEGER, verifying INTEGER NOT NULL)")
            con.execute("INSERT INTO source_fts_migration SELECT NULL,MAX(rowid),0 FROM source_fts")

        last_id, end_id, verifying = con.execute("SELECT last_id,end_id,verifying FROM source_fts_migration").fetchone()
        if verifying:
            deadline = time.monotonic() + 3.0
            con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            try:
                verified_id = _verify_next_range(con, last_id, end_id)
                if verified_id is not None:
                    con.execute("UPDATE source_fts_migration SET last_id=?", (verified_id,))
                    return True
                con.execute("DROP TRIGGER source_fts_binding_delete")
                con.execute("ALTER TABLE source_fts RENAME TO source_fts_retired")
                con.execute("ALTER TABLE source_fts_next RENAME TO source_fts")
                _create_delete_trigger(con, LEGACY_FTS)
                con.execute("DROP TABLE source_fts_migration")
            finally:
                con.set_progress_handler(None, 0)
            return True

        source_sql = """SELECT f.rowid,f.root,f.path,f.content FROM source_fts f
            WHERE f.rowid<=? AND NOT EXISTS (SELECT 1 FROM source_fts_bindings b WHERE b.id=f.rowid)"""
        params = (end_id,)
        if last_id is not None:
            source_sql += " AND f.rowid>?"
            params += (last_id,)
        source_sql += " ORDER BY f.rowid LIMIT ?"
        copied_id = None
        copied_bytes = 0

        def pending_rows():
            nonlocal copied_id, copied_bytes
            for row in con.execute(source_sql, (*params, _MIGRATION_BATCH_ROWS)):
                size = len(row[3].encode("utf-8")) if row[3] is not None else 0
                if copied_id is not None and copied_bytes + size > _WRITE_BATCH_BYTES:
                    break
                copied_bytes += size
                copied_id = row[0]
                yield tuple(row)

        _insert_shared_rows(con, _COPY_FTS, pending_rows())
        if copied_id is not None:
            con.execute("UPDATE source_fts_migration SET last_id=?", (copied_id,))
        else:
            # Later inserts use the dual writer and do not extend the verification frontier.
            con.execute("""UPDATE source_fts_migration SET last_id=NULL,verifying=1,end_id=(
                SELECT MAX(rowid) FROM (
                    SELECT MAX(rowid) AS rowid FROM source_fts
                    UNION ALL SELECT MAX(id) FROM source_fts_bindings
                )
            )""")
        return True
