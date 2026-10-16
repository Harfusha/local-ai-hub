from __future__ import annotations

import importlib
import json
import math
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .cache import MemoryLRUCache, stable_hash
from .json_utils import dumps as json_dumps
from .normalizer import normalize_query
from .sqlite_support import connect_sqlite, initialize_wal, retry_busy

_NUMPY: Any = None
_NUMPY_CHECKED = False


def _load_numpy() -> Any | None:
    """Load the optional vector backend on first semantic comparison only."""
    global _NUMPY, _NUMPY_CHECKED
    if not _NUMPY_CHECKED:
        try:
            _NUMPY = importlib.import_module("numpy")
        except (ImportError, OSError):
            _NUMPY = None
        _NUMPY_CHECKED = True
    return _NUMPY


def _safe_int(val: Any, default: int, min_val: int | None = None, max_val: int | None = None) -> int:
    if isinstance(val, bool) or val is None:
        return default
    try:
        if isinstance(val, float) and not math.isfinite(val):
            return default
        res = int(val)
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and res < min_val:
        return min_val
    if max_val is not None and res > max_val:
        return max_val
    return res


def _safe_float(val: Any, default: float, min_val: float | None = None, max_val: float | None = None) -> float:
    if isinstance(val, bool) or val is None:
        return default
    try:
        res = float(val)
        if not math.isfinite(res):
            return default
    except (ValueError, TypeError, OverflowError):
        return default
    if min_val is not None and res < min_val:
        return min_val
    if max_val is not None and res > max_val:
        return max_val
    return res


class SemanticGenerationCache:
    """Conservative semantic reuse for rephrased requests over identical context.

    Reuse is scoped by model/system/options/context fingerprint. It intentionally
    does not cross different code/context snapshots.
    """

    def __init__(self, config: dict[str, Any], embeddings: Any):
        if not isinstance(config, dict):
            raise TypeError("config must be a dictionary")
        cfg = config.get("semantic_cache", {}) if isinstance(config.get("semantic_cache"), dict) else {}
        self.enabled = bool(cfg.get("enabled", True))
        self.threshold = _safe_float(cfg.get("threshold"), 0.935, min_val=0.0, max_val=1.0)
        self.ttl_seconds = _safe_int(cfg.get("ttl_seconds"), 7 * 86400, min_val=0)
        self.max_entries = _safe_int(cfg.get("max_entries"), 10000, min_val=1)
        self.max_candidates = _safe_int(cfg.get("max_candidates"), 128, min_val=1)
        self.min_query_chars = _safe_int(cfg.get("min_query_chars"), 8, min_val=1)
        self.embeddings = embeddings
        server_cfg = config.get("server")
        if not isinstance(server_cfg, dict):
            raise TypeError("config.server must be a dictionary")
        state_dir = server_cfg.get("state_dir")
        if not isinstance(state_dir, (str, Path)):
            raise TypeError("server.state_dir must be a path string or Path")
        if not str(state_dir).strip() or "\x00" in str(state_dir):
            raise ValueError("server.state_dir must be nonempty and contain no NUL")
        self.path = Path(state_dir) / "semantic-cache.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        l1_entries = _safe_int(cfg.get("l1_entries"), 512, min_val=1)
        l1_ttl = _safe_int(cfg.get("l1_ttl_seconds"), 1800, min_val=0)
        self._recent = MemoryLRUCache(l1_entries, l1_ttl)
        self.hits = 0
        self.misses = 0
        self.comparisons = 0
        self.busy_fallbacks = 0
        self._touched_ids: set[int] = set()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path, timeout_seconds=0.75)

    def _init_db(self) -> None:
        with closing(self._connect()) as con:
            initialize_wal(con)
            columns = {
                row[1]
                for row in con.execute("PRAGMA table_info(semantic_entries)").fetchall()
            }
            if columns and "vector_blob" not in columns:
                # Semantic cache is disposable derived state; discard stale encodings.
                con.execute("DROP TABLE semantic_entries")
            con.execute(
                """CREATE TABLE IF NOT EXISTS semantic_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope_key TEXT NOT NULL,
                    query_hash TEXT NOT NULL,
                    query_text TEXT NOT NULL,
                    vector_blob BLOB NOT NULL,
                    value_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    accessed_at REAL NOT NULL,
                    hits INTEGER NOT NULL DEFAULT 0
                )"""
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_sem_scope_access ON semantic_entries(scope_key, accessed_at DESC)")
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sem_scope_query ON semantic_entries(scope_key, query_hash)")
            con.commit()

    def _vector(self, text: str) -> list[float] | None:
        try:
            result = self.embeddings.encode([text], query=True)
            if not result.get("success"):
                return None
            vectors = result.get("embeddings", [])
            if not vectors:
                return None
            values = vectors[0]
            if not isinstance(values, (list, tuple)) or not values:
                return None
            vector = []
            for value in values:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return None
                number = float(value)
                if not math.isfinite(number) or abs(number) > 3.4028234663852886e38:
                    return None
                vector.append(number)
            return vector
        except Exception:
            return None

    def get(self, scope: str, query_text: str) -> tuple[dict[str, Any] | None, float]:
        if not isinstance(scope, str) or "\x00" in scope:
            return None, 0.0
        query_text = normalize_query(query_text)
        if not self.enabled or len(query_text) < self.min_query_chars:
            return None, 0.0
        exact_recent = self._recent.get(stable_hash({"s": scope, "q": query_text}))
        if isinstance(exact_recent, dict):
            self.hits += 1
            return exact_recent, 1.0
        cutoff = time.time() - self.ttl_seconds if self.ttl_seconds else 0
        query_hash = stable_hash(query_text)
        with self._lock, closing(self._connect()) as con:
            exact_row = con.execute(
                "SELECT id,value_json FROM semantic_entries WHERE scope_key=? AND query_hash=? AND created_at>=? LIMIT 1",
                (scope, query_hash, cutoff),
            ).fetchone()
            if exact_row:
                value_dict = json.loads(exact_row[1]) if isinstance(exact_row[1], str) else exact_row[1]
                if isinstance(value_dict, dict):
                    entry_id = int(exact_row[0])
                    if entry_id not in self._touched_ids:
                        try:
                            retry_busy(
                                lambda: (
                                    con.execute(
                                        "UPDATE semantic_entries SET accessed_at=?, hits=hits+1 WHERE id=?",
                                        (time.time(), entry_id),
                                    ),
                                    con.commit(),
                                ),
                                retries=2,
                            )
                            self._touched_ids.add(entry_id)
                        except sqlite3.OperationalError:
                            self.busy_fallbacks += 1
                            try:
                                con.rollback()
                            except sqlite3.Error:
                                pass
                    self._recent.set(stable_hash({"s": scope, "q": query_text}), value_dict)
                    self.hits += 1
                    return value_dict, 1.0

        numpy = _load_numpy()
        if numpy is None:
            self.misses += 1
            return None, 0.0
        vector = self._vector(query_text)
        if vector is None:
            self.misses += 1
            return None, 0.0
        with self._lock, closing(self._connect()) as con:
            rows = con.execute(
                "SELECT id,vector_blob,value_json,created_at FROM semantic_entries WHERE scope_key=? AND created_at>=? ORDER BY accessed_at DESC LIMIT ?",
                (scope, cutoff, self.max_candidates),
            ).fetchall()
            if not rows:
                self.misses += 1
                return None, 0.0

            best: tuple[int, dict[str, Any], float] | None = None
            query_vector = numpy.asarray(vector, dtype=numpy.float32)
            query_norm = float(numpy.linalg.norm(query_vector))
            if not math.isfinite(query_norm) or query_norm <= 1e-9:
                self.misses += 1
                return None, 0.0
            query_vector = query_vector / query_norm

            vector_rows: list[Any] = []
            for row in rows:
                raw_vector = row[1]
                if isinstance(raw_vector, memoryview):
                    raw_vector = raw_vector.tobytes()
                try:
                    candidate = numpy.frombuffer(raw_vector, dtype=numpy.float32)
                    if candidate.shape[0] != len(vector):
                        candidate = numpy.zeros(len(vector), dtype=numpy.float32)
                except (TypeError, ValueError):
                    candidate = numpy.zeros(len(vector), dtype=numpy.float32)
                vector_rows.append(candidate)

            matrix = numpy.vstack(vector_rows)
            norms = numpy.linalg.norm(matrix, axis=1, keepdims=True)
            valid_rows = numpy.isfinite(matrix).all(axis=1) & numpy.isfinite(norms[:, 0]) & (norms[:, 0] > 1e-9)
            norms[~valid_rows] = 1.0
            scores = numpy.dot(matrix / norms, query_vector)
            scores[~valid_rows] = -numpy.inf
            self.comparisons += len(rows)

            best_index = int(numpy.argmax(scores))
            best_score = float(scores[best_index])
            if best_score >= self.threshold:
                value = rows[best_index][2]
                value_dict = json.loads(value) if isinstance(value, str) else value
                if isinstance(value_dict, dict):
                    best = (int(rows[best_index][0]), value_dict, best_score)

            if best is None:
                self.misses += 1
                return None, 0.0
            # Persistent hit telemetry is intentionally sampled once per entry/process.
            # Semantic hits are promoted to L1, so writing SQLite on every hit only adds
            # lock contention without improving reuse quality.
            if best[0] not in self._touched_ids:
                try:
                    retry_busy(
                        lambda: (
                            con.execute("UPDATE semantic_entries SET accessed_at=?, hits=hits+1 WHERE id=?", (time.time(), best[0])),
                            con.commit(),
                        ),
                        retries=2,
                    )
                    self._touched_ids.add(best[0])
                except sqlite3.OperationalError:
                    self.busy_fallbacks += 1
                    try:
                        con.rollback()
                    except sqlite3.Error:
                        pass
            self._recent.set(stable_hash({"s": scope, "q": query_text}), best[1])
            self.hits += 1
            return best[1], best[2]

    def set(self, scope: str, query_text: str, value: dict[str, Any]) -> None:
        if not isinstance(scope, str) or "\x00" in scope or not isinstance(value, dict):
            return
        query_text = normalize_query(query_text)
        if not self.enabled or len(query_text) < self.min_query_chars:
            return
        numpy = _load_numpy()
        vector = self._vector(query_text) if numpy is not None else None
        if numpy is not None and vector is None:
            return
        now = time.time()
        qhash = stable_hash(query_text)
        vec_blob = sqlite3.Binary(
            numpy.asarray(vector, dtype=numpy.float32).tobytes() if numpy is not None else b""
        )
        with self._lock, closing(self._connect()) as con:
            def write() -> None:
                con.execute(
                    """INSERT INTO semantic_entries(scope_key,query_hash,query_text,vector_blob,value_json,created_at,accessed_at,hits)
                       VALUES(?,?,?,?,?,?,?,0)
                       ON CONFLICT(scope_key,query_hash) DO UPDATE SET
                         vector_blob=excluded.vector_blob,value_json=excluded.value_json,created_at=excluded.created_at,accessed_at=excluded.accessed_at""",
                    (scope, qhash, query_text, vec_blob, json_dumps(value, ensure_ascii=False, separators=(",", ":"), default=str), now, now),
                )
                count = int(con.execute("SELECT COUNT(*) FROM semantic_entries WHERE scope_key=?", (scope,)).fetchone()[0])
                if count > self.max_entries:
                    con.execute("DELETE FROM semantic_entries WHERE id IN (SELECT id FROM semantic_entries WHERE scope_key=? ORDER BY accessed_at ASC LIMIT ?)", (scope, count - self.max_entries + 32))
                if self.ttl_seconds > 0:
                    con.execute("DELETE FROM semantic_entries WHERE created_at < ?", (now - self.ttl_seconds,))
                con.commit()
            try:
                retry_busy(write, retries=3)
            except sqlite3.OperationalError:
                self.busy_fallbacks += 1
                try:
                    con.rollback()
                except sqlite3.Error:
                    pass
                return
        self._recent.set(stable_hash({"s": scope, "q": query_text}), value)

    def is_enabled(self) -> bool:
        return bool(self.enabled)

    def entry_count(self) -> int:
        with closing(self._connect()) as con:
            row = con.execute("SELECT COUNT(*) FROM semantic_entries").fetchone()
            return int(row[0]) if row else 0

    def clear(self, scope: str | None = None) -> int:
        if scope is not None and (not isinstance(scope, str) or "\x00" in scope):
            raise ValueError("scope must be a string without NUL or None")
        with self._lock, closing(self._connect()) as con:
            if scope is not None:
                count = con.execute("DELETE FROM semantic_entries WHERE scope_key=?", (scope,)).rowcount
            else:
                count = con.execute("DELETE FROM semantic_entries").rowcount
            con.commit()
        self._recent = MemoryLRUCache(self._recent.max_entries, self._recent.ttl_seconds)
        self._touched_ids.clear()
        return max(0, count)

    def stats(self) -> dict[str, Any]:
        with closing(self._connect()) as con:
            row = con.execute("SELECT COUNT(*), COALESCE(SUM(hits),0) FROM semantic_entries").fetchone()
        return {
            "enabled": self.enabled, "entries": int(row[0]), "persistent_hits": int(row[1]),
            "runtime_hits": self.hits, "runtime_misses": self.misses, "comparisons": self.comparisons,
            "busy_fallbacks": self.busy_fallbacks, "threshold": self.threshold, "l1": self._recent.stats(),
        }
