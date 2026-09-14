from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from .cache import MemoryLRUCache, stable_hash
from .normalizer import normalize_query
from .sqlite_support import connect_sqlite, initialize_wal, retry_busy


class SemanticGenerationCache:
    """Conservative semantic reuse for rephrased requests over identical context.

    Reuse is scoped by model/system/options/context fingerprint. It intentionally
    does not cross different code/context snapshots.
    """

    def __init__(self, config: dict[str, Any], embeddings: Any):
        cfg = config.get("semantic_cache", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.threshold = float(cfg.get("threshold", 0.935))
        self.ttl_seconds = int(cfg.get("ttl_seconds", 7 * 86400))
        self.max_entries = int(cfg.get("max_entries", 10000))
        self.max_candidates = int(cfg.get("max_candidates", 128))
        self.min_query_chars = int(cfg.get("min_query_chars", 8))
        self.embeddings = embeddings
        self.path = Path(config["server"]["state_dir"]) / "semantic-cache.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._recent = MemoryLRUCache(int(cfg.get("l1_entries", 512)), int(cfg.get("l1_ttl_seconds", 1800)))
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
            con.execute(
                """CREATE TABLE IF NOT EXISTS semantic_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope_key TEXT NOT NULL,
                    query_hash TEXT NOT NULL,
                    query_text TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    accessed_at REAL NOT NULL,
                    hits INTEGER NOT NULL DEFAULT 0
                )"""
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_sem_scope_access ON semantic_entries(scope_key, accessed_at DESC)")
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sem_scope_query ON semantic_entries(scope_key, query_hash)")
            con.commit()

    @staticmethod
    def _cos(a: list[float], b: list[float]) -> float:
        if not a or len(a) != len(b):
            return -1.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        denom = na * nb
        return dot / denom if denom > 1e-12 else -1.0

    @staticmethod
    def _decode_vector(raw: Any) -> list[float]:
        if isinstance(raw, memoryview):
            raw = raw.tobytes()
        if isinstance(raw, (bytes, bytearray)):
            import struct
            data = bytes(raw)
            if len(data) % 4:
                raise ValueError("invalid float32 vector blob length")
            return list(struct.unpack(f"<{len(data) // 4}f", data))
        if isinstance(raw, str):
            value = json.loads(raw)
            if not isinstance(value, list):
                raise ValueError("vector JSON must be an array")
            return [float(v) for v in value]
        if isinstance(raw, list):
            return [float(v) for v in raw]
        raise ValueError("unsupported vector encoding")

    def _vector(self, text: str) -> list[float] | None:
        result = self.embeddings.encode([text], query=True)
        if not result.get("success"):
            return None
        vectors = result.get("embeddings", [])
        if not vectors:
            return None
        return [float(v) for v in vectors[0]]

    def get(self, scope: str, query_text: str) -> tuple[dict[str, Any] | None, float]:
        query_text = normalize_query(query_text)
        if not self.enabled or len(query_text) < self.min_query_chars:
            return None, 0.0
        exact_recent = self._recent.get(stable_hash({"s": scope, "q": query_text}))
        if isinstance(exact_recent, dict):
            self.hits += 1
            return exact_recent, 1.0
        vector = self._vector(query_text)
        if vector is None:
            self.misses += 1
            return None, 0.0
        cutoff = time.time() - self.ttl_seconds if self.ttl_seconds else 0
        with self._lock, closing(self._connect()) as con:
            rows = con.execute(
                "SELECT id,vector_json,value_json,created_at FROM semantic_entries WHERE scope_key=? AND created_at>=? ORDER BY accessed_at DESC LIMIT ?",
                (scope, cutoff, self.max_candidates),
            ).fetchall()
            if not rows:
                self.misses += 1
                return None, 0.0

            best: tuple[int, dict[str, Any], float] | None = None
            try:
                import numpy as np
                q = np.array(vector, dtype=np.float32)
                q_norm = float(np.linalg.norm(q))
                if q_norm > 1e-9:
                    q = q / q_norm
                
                vec_list = []
                for r in rows:
                    try:
                        candidate = self._decode_vector(r[1])
                        vec_list.append(np.array(candidate, dtype=np.float32) if len(candidate) == len(vector) else np.zeros(len(vector), dtype=np.float32))
                    except Exception:
                        vec_list.append(np.zeros(len(vector), dtype=np.float32))

                mat = np.vstack(vec_list)
                norms = np.linalg.norm(mat, axis=1, keepdims=True)
                norms[norms < 1e-9] = 1.0
                normed_mat = mat / norms
                scores = np.dot(normed_mat, q)
                self.comparisons += len(rows)

                max_idx = int(np.argmax(scores))
                max_score = float(scores[max_idx])
                if max_score >= self.threshold:
                    val = rows[max_idx][2]
                    value_dict = json.loads(val) if isinstance(val, str) else val
                    if isinstance(value_dict, dict):
                        best = (int(rows[max_idx][0]), value_dict, max_score)
            except Exception:
                for row in rows:
                    try:
                        candidate = self._decode_vector(row[1])
                        score = self._cos(vector, candidate)
                        self.comparisons += 1
                        if score >= self.threshold and (best is None or score > best[2]):
                            value = json.loads(row[2])
                            if isinstance(value, dict):
                                best = (int(row[0]), value, score)
                    except Exception:
                        continue

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
        query_text = normalize_query(query_text)
        if not self.enabled or len(query_text) < self.min_query_chars:
            return
        vector = self._vector(query_text)
        if vector is None:
            return
        now = time.time()
        qhash = stable_hash(query_text)
        try:
            import numpy as np
            vec_blob = sqlite3.Binary(np.array(vector, dtype=np.float32).tobytes())
        except Exception:
            vec_blob = json.dumps(vector, separators=(",", ":"))
        with self._lock, closing(self._connect()) as con:
            def write() -> None:
                con.execute(
                    """INSERT INTO semantic_entries(scope_key,query_hash,query_text,vector_json,value_json,created_at,accessed_at,hits)
                       VALUES(?,?,?,?,?,?,?,0)
                       ON CONFLICT(scope_key,query_hash) DO UPDATE SET
                         vector_json=excluded.vector_json,value_json=excluded.value_json,created_at=excluded.created_at,accessed_at=excluded.accessed_at""",
                    (scope, qhash, query_text, vec_blob, json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str), now, now),
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

    def stats(self) -> dict[str, Any]:
        with closing(self._connect()) as con:
            row = con.execute("SELECT COUNT(*), COALESCE(SUM(hits),0) FROM semantic_entries").fetchone()
        return {
            "enabled": self.enabled, "entries": int(row[0]), "persistent_hits": int(row[1]),
            "runtime_hits": self.hits, "runtime_misses": self.misses, "comparisons": self.comparisons,
            "busy_fallbacks": self.busy_fallbacks, "threshold": self.threshold, "l1": self._recent.stats(),
        }
