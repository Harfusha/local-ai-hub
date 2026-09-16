from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from collections import OrderedDict
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .sqlite_support import connect_sqlite, initialize_wal, is_busy_error, retry_busy


_SQLITE_RECOVERY_LOCK = threading.RLock()
_SQLITE_INITIALIZED_PATHS: set[str] = set()


def stable_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class MemoryLRUCache:
    """Bounded in-process L1 cache with per-entry expiry and lock striping."""

    def __init__(self, max_entries: int = 256, ttl_seconds: float = 600, shards: int = 16):
        self.max_entries = max(1, int(max_entries))
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self.num_shards = max(1, int(shards))
        self._shard_max = max(1, self.max_entries // self.num_shards)
        self._locks = [threading.RLock() for _ in range(self.num_shards)]
        self._shards: list[OrderedDict[str, tuple[float, Any]]] = [OrderedDict() for _ in range(self.num_shards)]
        self._hits = [0] * self.num_shards
        self._misses = [0] * self.num_shards
        self._evictions = [0] * self.num_shards

    def _shard_idx(self, key: str) -> int:
        return (hash(key) & 0x7FFFFFFF) % self.num_shards

    @property
    def _lock(self) -> threading.RLock:
        return self._locks[0]

    @property
    def _items(self) -> OrderedDict[str, tuple[float, Any]]:
        combined: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        for idx in range(self.num_shards):
            with self._locks[idx]:
                combined.update(self._shards[idx])
        return combined

    @property
    def hits(self) -> int:
        return sum(self._hits)

    @hits.setter
    def hits(self, val: int) -> None:
        self._hits[0] = val

    @property
    def misses(self) -> int:
        return sum(self._misses)

    @misses.setter
    def misses(self, val: int) -> None:
        self._misses[0] = val

    @property
    def evictions(self) -> int:
        return sum(self._evictions)

    @evictions.setter
    def evictions(self, val: int) -> None:
        self._evictions[0] = val

    def get(self, key: str) -> Any | None:
        idx = self._shard_idx(key)
        now = time.monotonic()
        with self._locks[idx]:
            items = self._shards[idx]
            item = items.get(key)
            if item is None:
                self._misses[idx] += 1
                return None
            created_at, value = item
            if self.ttl_seconds and now - created_at > self.ttl_seconds:
                items.pop(key, None)
                self._misses[idx] += 1
                return None
            items.move_to_end(key)
            self._hits[idx] += 1
            return value

    def set(self, key: str, value: Any) -> None:
        idx = self._shard_idx(key)
        now = time.monotonic()
        with self._locks[idx]:
            items = self._shards[idx]
            items[key] = (now, value)
            items.move_to_end(key)
            while len(items) > self._shard_max:
                items.popitem(last=False)
                self._evictions[idx] += 1

    def delete(self, key: str) -> None:
        idx = self._shard_idx(key)
        with self._locks[idx]:
            self._shards[idx].pop(key, None)

    def clear(self) -> None:
        for idx in range(self.num_shards):
            with self._locks[idx]:
                self._shards[idx].clear()

    def stats(self) -> dict[str, Any]:
        total_entries = sum(len(s) for s in self._shards)
        return {
            "entries": total_entries,
            "max_entries": self.max_entries,
            "shards": self.num_shards,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
        }


class SingleFlightGroup:
    """Coalesces concurrent identical in-flight function calls into a single execution.
    
    Thread-safe, lock-striped request coalescer (Go singleflight pattern).
    If multiple threads invoke .do(key, fn) simultaneously with the same key,
    fn is run exactly once by the first caller, and all other concurrent callers
    block until the result is ready and share the exact return value.
    """

    def __init__(self, shards: int = 16, default_timeout_seconds: float = 60.0):
        self.num_shards = max(1, int(shards))
        self.default_timeout = max(0.01, float(default_timeout_seconds))
        self._locks = [threading.Lock() for _ in range(self.num_shards)]
        self._inflight: list[dict[str, tuple[threading.Event, list[Any], float]]] = [{} for _ in range(self.num_shards)]
        self._total_calls = [0] * self.num_shards
        self._coalesced_calls = [0] * self.num_shards
        self._timeouts = [0] * self.num_shards

    def _shard(self, key: str) -> int:
        return (hash(key) & 0x7FFFFFFF) % self.num_shards

    @property
    def total_calls(self) -> int:
        return sum(self._total_calls)

    @property
    def coalesced_calls(self) -> int:
        return sum(self._coalesced_calls)

    @property
    def timeouts(self) -> int:
        return sum(self._timeouts)

    def do(self, key: str, fn: Callable[[], Any], timeout_seconds: float | None = None) -> tuple[Any, bool]:
        """Execute fn or wait for active flight with the same key. Returns (result, coalesced: bool).

        Thread safety: holder list is written by the owner thread and read by waiters only
        after event.wait() returns (which happens-after event.set() in the owner's finally block).
        The GIL plus threading.Event guarantee the required memory visibility.
        """
        idx = self._shard(key)
        timeout = timeout_seconds if timeout_seconds is not None else self.default_timeout
        with self._locks[idx]:
            self._total_calls[idx] += 1
            flight = self._inflight[idx].get(key)
            if flight is None:
                event = threading.Event()
                holder: list[Any] = [None, None]  # [result, exception]
                self._inflight[idx][key] = (event, holder, time.monotonic())
                owner = True
            else:
                event, holder, _ = flight
                owner = False
                self._coalesced_calls[idx] += 1

        if not owner:
            if not event.wait(timeout):
                with self._locks[idx]:
                    self._timeouts[idx] += 1
                raise TimeoutError(f"singleflight wait timed out for key: {key[:64]}")
            exc = holder[1]
            if exc is not None:
                # Re-raise with chained context so the waiter's traceback is distinct
                # from the owner's traceback and does not confuse cross-thread diagnostics.
                raise RuntimeError(f"singleflight coalesced call failed: {type(exc).__name__}: {exc}") from exc
            return holder[0], True

        try:
            res = fn()
            holder[0] = res
            return res, False
        except BaseException as exc:
            holder[1] = exc
            raise
        finally:
            # event.set() is called under the shard lock after holder is fully written.
            # Waiters that return from event.wait() will always see a consistent holder.
            with self._locks[idx]:
                self._inflight[idx].pop(key, None)
                event.set()

    def stats(self) -> dict[str, Any]:
        inflight_count = sum(len(s) for s in self._inflight)
        return {
            "total_calls": self.total_calls,
            "coalesced_calls": self.coalesced_calls,
            "coalesced_rate": round(self.coalesced_calls / max(1, self.total_calls), 4),
            "timeouts": self.timeouts,
            "inflight": inflight_count,
            "shards": self.num_shards,
        }


class SQLiteCache:
    """Persistent JSON L2 cache shared by all tenants/processes.

    The database contains derived data only. A damaged DB is quarantined and
    recreated rather than taking foreground requests down with it.
    """

    def __init__(self, path: Path, namespace: str, ttl_seconds: int = 86400, max_entries: int = 5000, *, busy_timeout_seconds: float = 0.75, busy_retries: int = 3):
        self.path = path
        self.namespace = f"{__version__}:{namespace}"
        self.ttl_seconds = max(0, int(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._lock = threading.RLock()
        self.busy_timeout_seconds = max(0.01, float(busy_timeout_seconds))
        self.busy_retries = max(1, int(busy_retries))
        self.busy_fallbacks = 0
        self._touched_keys: set[str] = set()
        # Eviction is maintenance, not part of the foreground write path. Counting
        # the whole namespace on every insert made a cold embedding pass perform one
        # extra SQLite scan per vector. A bounded overshoot is harmless for derived
        # cache data; periodic pruning keeps the durable size limit effectively exact
        # without turning cache warming into a read-amplified workload.
        self._writes_since_prune = 0
        self._prune_every_writes = max(16, min(128, self.max_entries // 32 or 16))
        path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = connect_sqlite(self.path, timeout_seconds=self.busy_timeout_seconds)
        try:
            con.execute("PRAGMA cache_size=-65536")
            con.execute("PRAGMA mmap_size=536870912")
        except sqlite3.OperationalError:
            pass
        return con

    def _create_schema(self) -> None:
        with closing(self._connect()) as con:
            initialize_wal(con)
            con.execute(
                """CREATE TABLE IF NOT EXISTS cache_entries (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    accessed_at REAL NOT NULL,
                    hits INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(namespace, cache_key)
                )"""
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_cache_access ON cache_entries(namespace, accessed_at)")
            con.commit()

    def _recover(self) -> None:
        # LIMITATION: _SQLITE_RECOVERY_LOCK is process-local. If two hub processes
        # concurrently detect a corrupted DB, both may rename it and recreate the schema.
        # This is safe because SQLiteCache stores only derived, disposable data (command
        # results, query results) that can be rebuilt on the next cache miss. No
        # cross-process file lock is needed — worst case is two fresh empty caches.
        with _SQLITE_RECOVERY_LOCK:
            # Another cache instance may already have recovered the shared DB.
            try:
                if self.path.exists():
                    with closing(sqlite3.connect(self.path, timeout=1)) as con:
                        if con.execute("PRAGMA quick_check").fetchone()[0] == "ok":
                            self._create_schema()
                            return
            except (sqlite3.DatabaseError, OSError):
                pass

            stamp = f"{int(time.time())}-{threading.get_ident()}"
            try:
                if self.path.exists():
                    self.path.replace(self.path.with_name(self.path.name + f".corrupt-{stamp}"))
                for suffix in ("-wal", "-shm"):
                    side = Path(str(self.path) + suffix)
                    if side.exists():
                        side.unlink()
            except OSError:
                # Best effort: if rename/delete races, schema creation below is
                # still attempted. Foreground callers will degrade to a miss.
                pass
            self._create_schema()

    def _init_db(self) -> None:
        # Several cache namespaces share one derived-data database. Schema creation +
        # quick_check once per SQLite path is sufficient for this process and avoids
        # repeating synchronous integrity work during hub construction. The lock also
        # keeps concurrent constructors from racing the one-time initialization.
        identity = str(self.path.resolve(strict=False))
        with _SQLITE_RECOVERY_LOCK:
            if identity in _SQLITE_INITIALIZED_PATHS:
                return
            try:
                self._create_schema()
                with closing(self._connect()) as con:
                    row = con.execute("PRAGMA quick_check").fetchone()
                    if not row or row[0] != "ok":
                        raise sqlite3.DatabaseError("quick_check failed")
            except sqlite3.DatabaseError as exc:
                if is_busy_error(exc):
                    return
                self._recover()
            _SQLITE_INITIALIZED_PATHS.add(identity)

    def _safe(self, operation: Callable[[], Any], fallback: Any) -> Any:
        try:
            return retry_busy(operation, retries=self.busy_retries)
        except sqlite3.DatabaseError as exc:
            # A busy WAL writer is not corruption. Degrade to a cache miss/write drop
            # instead of quarantining a healthy shared database.
            if is_busy_error(exc):
                self.busy_fallbacks += 1
                return fallback
            try:
                self._recover()
            except Exception:
                pass
            return fallback

    def get(self, key: str) -> Any | None:
        def op() -> Any | None:
            now = time.time()
            with self._lock, closing(self._connect()) as con:
                row = con.execute(
                    "SELECT value_json, created_at FROM cache_entries WHERE namespace=? AND cache_key=?",
                    (self.namespace, key),
                ).fetchone()
                if not row:
                    return None
                if self.ttl_seconds and now - float(row[1]) > self.ttl_seconds:
                    con.execute("DELETE FROM cache_entries WHERE namespace=? AND cache_key=?", (self.namespace, key))
                    con.commit()
                    return None
                try:
                    value = json.loads(row[0])
                except json.JSONDecodeError:
                    # Corrupt derived entries are self-healing misses. Remove them so
                    # every later request does not pay the same decode failure.
                    con.execute("DELETE FROM cache_entries WHERE namespace=? AND cache_key=?", (self.namespace, key))
                    con.commit()
                    return None
                # Persist recency at most once per key per process. TieredCache promotes
                # an L2 hit to L1 immediately, so writing on every direct L2 read only
                # creates WAL contention without improving eviction quality.
                if key not in self._touched_keys:
                    con.execute(
                        "UPDATE cache_entries SET accessed_at=?, hits=hits+1 WHERE namespace=? AND cache_key=?",
                        (now, self.namespace, key),
                    )
                    con.commit()
                    self._touched_keys.add(key)
                    if len(self._touched_keys) > min(self.max_entries, 8192):
                        self._touched_keys.clear()
                        self._touched_keys.add(key)
                return value
        return self._safe(op, None)

    def set(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)

        def op() -> None:
            now = time.time()
            with self._lock, closing(self._connect()) as con:
                con.execute(
                    """INSERT INTO cache_entries(namespace, cache_key, value_json, created_at, accessed_at, hits)
                       VALUES(?,?,?,?,?,0)
                       ON CONFLICT(namespace, cache_key) DO UPDATE SET
                         value_json=excluded.value_json,
                         created_at=excluded.created_at,
                         accessed_at=excluded.accessed_at""",
                    (self.namespace, key, payload, now, now),
                )
                self._writes_since_prune += 1
                if self._writes_since_prune >= self._prune_every_writes:
                    count = con.execute("SELECT COUNT(*) FROM cache_entries WHERE namespace=?", (self.namespace,)).fetchone()[0]
                    extra = int(count) - self.max_entries
                    if extra > 0:
                        con.execute(
                            "DELETE FROM cache_entries WHERE rowid IN (SELECT rowid FROM cache_entries WHERE namespace=? ORDER BY accessed_at ASC LIMIT ?)",
                            (self.namespace, extra + 32),
                        )
                    self._writes_since_prune = 0
                con.commit()
        self._safe(op, None)

    def delete(self, key: str) -> None:
        def op() -> None:
            with self._lock, closing(self._connect()) as con:
                con.execute("DELETE FROM cache_entries WHERE namespace=? AND cache_key=?", (self.namespace, key))
                con.commit()
        self._safe(op, None)

    def clear(self) -> int:
        def op() -> int:
            with self._lock, closing(self._connect()) as con:
                cur = con.execute("DELETE FROM cache_entries WHERE namespace=?", (self.namespace,))
                con.commit()
                return int(cur.rowcount or 0)
        return int(self._safe(op, 0))

    def prune(self) -> int:
        if not self.ttl_seconds:
            return 0
        cutoff = time.time() - self.ttl_seconds

        def op() -> int:
            with self._lock, closing(self._connect()) as con:
                cur = con.execute("DELETE FROM cache_entries WHERE namespace=? AND created_at<?", (self.namespace, cutoff))
                con.commit()
                return int(cur.rowcount or 0)
        return int(self._safe(op, 0))

    def stats(self) -> dict[str, Any]:
        def op() -> dict[str, Any]:
            with self._lock, closing(self._connect()) as con:
                row = con.execute(
                    "SELECT COUNT(*), COALESCE(SUM(hits),0), COALESCE(MIN(created_at),0), COALESCE(MAX(accessed_at),0) FROM cache_entries WHERE namespace=?",
                    (self.namespace,),
                ).fetchone()
            return {
                "namespace": self.namespace,
                "entries": int(row[0]),
                "hits": int(row[1]),
                "oldest_created_at": float(row[2]),
                "latest_accessed_at": float(row[3]),
                "busy_fallbacks": self.busy_fallbacks,
            }
        return self._safe(op, {"namespace": self.namespace, "entries": 0, "hits": 0, "busy_fallbacks": self.busy_fallbacks, "degraded": True})


class TieredCache:
    """Fast L1 RAM cache backed by persistent SQLite L2.

    Counter fields (l1_hits, l2_hits, misses) are best-effort metrics.
    On CPython the GIL makes plain int += atomic; on other implementations
    they may be approximate. Use them for monitoring only, not for correctness.
    """

    def __init__(self, l2: SQLiteCache, l1_entries: int = 256, l1_ttl_seconds: int = 900):
        self.l2 = l2
        self.l1 = MemoryLRUCache(l1_entries, l1_ttl_seconds)
        self.l1_hits = 0
        self.l2_hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        value = self.l1.get(key)
        if value is not None:
            self.l1_hits += 1
            return value
        value = self.l2.get(key)
        if value is not None:
            self.l2_hits += 1
            self.l1.set(key, value)
            return value
        self.misses += 1
        return None

    def set(self, key: str, value: Any) -> None:
        self.l2.set(key, value)
        self.l1.set(key, value)

    def delete(self, key: str) -> None:
        self.l1.delete(key)
        self.l2.delete(key)

    def clear(self) -> int:
        self.l1.clear()
        return self.l2.clear()

    def stats(self) -> dict[str, Any]:
        return {
            "l1_hits": self.l1_hits,
            "l2_hits": self.l2_hits,
            "misses": self.misses,
            "l1": self.l1.stats(),
            "l2": self.l2.stats(),
        }


class SingleFlightCache:
    """Exact cache plus striped in-process coalescing of identical concurrent requests."""

    def __init__(self, cache: Any, enabled: bool = True, wait_timeout_seconds: float = 45.0, shards: int = 16):
        self.cache = cache
        self.enabled = enabled
        self.wait_timeout_seconds = max(0.01, float(wait_timeout_seconds))
        self.num_shards = max(1, int(shards))
        self._locks = [threading.Lock() for _ in range(self.num_shards)]
        self._inflight_shards: list[dict[str, threading.Event]] = [{} for _ in range(self.num_shards)]
        self._inflight_started_shards: list[dict[str, float]] = [{} for _ in range(self.num_shards)]
        self._errors_shards: list[dict[str, tuple[float, str]]] = [{} for _ in range(self.num_shards)]
        self._ephemeral_shards: list[dict[str, tuple[float, dict[str, Any]]]] = [{} for _ in range(self.num_shards)]
        self._hits = [0] * self.num_shards
        self._misses = [0] * self.num_shards
        self._coalesced_waiters = [0] * self.num_shards
        self._coalesced_timeouts = [0] * self.num_shards

    def _shard(self, key: str) -> int:
        return (hash(key) & 0x7FFFFFFF) % self.num_shards

    @property
    def _lock(self) -> threading.Lock:
        return self._locks[0]

    @property
    def _inflight(self) -> dict[str, threading.Event]:
        out: dict[str, threading.Event] = {}
        for idx in range(self.num_shards):
            with self._locks[idx]:
                out.update(self._inflight_shards[idx])
        return out

    @property
    def _inflight_started(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for idx in range(self.num_shards):
            with self._locks[idx]:
                out.update(self._inflight_started_shards[idx])
        return out

    @property
    def _errors(self) -> dict[str, tuple[float, str]]:
        out: dict[str, tuple[float, str]] = {}
        for idx in range(self.num_shards):
            with self._locks[idx]:
                out.update(self._errors_shards[idx])
        return out

    @property
    def _ephemeral(self) -> dict[str, tuple[float, dict[str, Any]]]:
        out: dict[str, tuple[float, dict[str, Any]]] = {}
        for idx in range(self.num_shards):
            with self._locks[idx]:
                out.update(self._ephemeral_shards[idx])
        return out

    @property
    def hits(self) -> int:
        return sum(self._hits)

    @hits.setter
    def hits(self, v: int) -> None:
        self._hits[0] = v

    @property
    def misses(self) -> int:
        return sum(self._misses)

    @misses.setter
    def misses(self, v: int) -> None:
        self._misses[0] = v

    @property
    def coalesced_waiters(self) -> int:
        return sum(self._coalesced_waiters)

    @coalesced_waiters.setter
    def coalesced_waiters(self, v: int) -> None:
        self._coalesced_waiters[0] = v

    @property
    def coalesced_timeouts(self) -> int:
        return sum(self._coalesced_timeouts)

    @coalesced_timeouts.setter
    def coalesced_timeouts(self, v: int) -> None:
        self._coalesced_timeouts[0] = v

    def get_or_compute(self, key: str, compute: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], bool, bool]:
        if not self.enabled:
            self._misses[0] += 1
            try:
                return compute(), False, False
            except Exception as exc:
                return {"success": False, "error": str(exc), "error_type": type(exc).__name__}, False, False

        cached = self.cache.get(key)
        if isinstance(cached, dict):
            idx = self._shard(key)
            self._hits[idx] += 1
            return cached, True, False

        idx = self._shard(key)
        lock = self._locks[idx]
        inflight = self._inflight_shards[idx]
        inflight_started = self._inflight_started_shards[idx]
        errors = self._errors_shards[idx]
        ephemeral = self._ephemeral_shards[idx]

        with lock:
            event = inflight.get(key)
            if event is None:
                event = threading.Event()
                inflight[key] = event
                inflight_started[key] = time.monotonic()
                owner = True
            else:
                owner = False
                self._coalesced_waiters[idx] += 1

        if not owner:
            if not event.wait(self.wait_timeout_seconds):
                with lock:
                    self._coalesced_timeouts[idx] += 1
                    started = inflight_started.get(key, time.monotonic())
                return {
                    "success": False,
                    "in_progress": True,
                    "retryable": True,
                    "retry_after_seconds": 1,
                    "owner_age_seconds": round(max(0.0, time.monotonic() - started), 3),
                    "error": "identical work is still running; do not start a duplicate",
                }, False, True
            cached = self.cache.get(key)
            if isinstance(cached, dict):
                self._hits[idx] += 1
                return cached, True, True
            with lock:
                eph = ephemeral.get(key)
                if eph and time.monotonic() - eph[0] <= 10.0:
                    return eph[1], False, True
                err_entry = errors.get(key)
                err = err_entry[1] if err_entry else None
            return {"success": False, "error": err or "coalesced request failed"}, False, True

        self._misses[idx] += 1
        try:
            result = compute()
            if isinstance(result, dict) and result.get("success", "error" not in result):
                cacheable = bool(result.get("_cacheable", True))
                clean_result = dict(result)
                clean_result.pop("_cacheable", None)
                if cacheable:
                    self.cache.set(key, clean_result)
                else:
                    with lock:
                        ephemeral[key] = (time.monotonic(), clean_result)
                result = clean_result
                with lock:
                    errors.pop(key, None)
                    now = time.monotonic()
                    for k in [k for k, v in ephemeral.items() if now - v[0] > 10.0]:
                        ephemeral.pop(k, None)
                    for k in [k for k, v in errors.items() if isinstance(v, tuple) and now - v[0] > 60.0]:
                        errors.pop(k, None)
            else:
                with lock:
                    now = time.monotonic()
                    err_msg = str(result.get("error", "request failed")) if isinstance(result, dict) else "request failed"
                    errors[key] = (now, err_msg)
                    for k in [k for k, v in errors.items() if isinstance(v, tuple) and now - v[0] > 60.0]:
                        errors.pop(k, None)
            return result, False, False
        except Exception as exc:
            with lock:
                now = time.monotonic()
                errors[key] = (now, str(exc))
                for k in [k for k, v in errors.items() if isinstance(v, tuple) and now - v[0] > 60.0]:
                    errors.pop(k, None)
            return {"success": False, "error": str(exc), "error_type": type(exc).__name__}, False, False
        finally:
            with lock:
                inflight.pop(key, None)
                inflight_started.pop(key, None)
                event.set()

    def stats(self) -> dict[str, Any]:
        inflight_total = sum(len(s) for s in self._inflight_shards)
        return {
            "enabled": self.enabled,
            "hits": self.hits,
            "misses": self.misses,
            "coalesced_waiters": self.coalesced_waiters,
            "coalesced_timeouts": self.coalesced_timeouts,
            "shards": self.num_shards,
            "inflight": inflight_total,
            "persistent": self.cache.stats(),
        }
