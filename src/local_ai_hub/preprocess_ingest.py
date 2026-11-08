"""Single-pass file ingest and AST buffer across preprocessing phases."""

from __future__ import annotations

import ast
import hashlib
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


@dataclass(slots=True)
class IngestedFile:
    path: str
    content_hash: str
    size_bytes: int
    text: str
    lines: tuple[str, ...]
    ast_tree: Any | None
    timestamp: float


class SinglePassIngestCache:
    """Thread-safe, memory-bounded single-pass ingest cache across preprocessing phases."""

    def __init__(self, max_entries: int = 500, max_bytes: int = 64 * 1024 * 1024) -> None:
        self.max_entries = max(1, int(max_entries))
        self.max_bytes = max(1, int(max_bytes))
        self._cache: dict[str, IngestedFile] = {}
        self._total_bytes: int = 0
        self._lock = threading.RLock()
        self._in_flight: dict[str, threading.Event] = {}

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    @staticmethod
    def _key(rel_path: str, root: str | None = None) -> str:
        norm = rel_path.replace("\\", "/").lstrip("/")
        if root:
            norm_root = str(Path(root).resolve()).replace("\\", "/").rstrip("/")
            return f"{norm_root}:{norm}"
        return norm

    def has(self, rel_path: str, root: str | None = None) -> bool:
        norm = rel_path.replace("\\", "/").lstrip("/")
        with self._lock:
            if root is not None:
                return self._key(norm, root) in self._cache
            return any(k == norm or k.endswith(f":{norm}") for k in self._cache)

    def get(self, rel_path: str, root: str | None = None) -> IngestedFile | None:
        norm = rel_path.replace("\\", "/").lstrip("/")
        with self._lock:
            if root is not None:
                k = self._key(norm, root)
                item = self._cache.get(k)
                if item is not None:
                    self._cache.pop(k, None)
                    self._cache[k] = item
                return item
            matches = [k for k in self._cache if k == norm or k.endswith(f":{norm}")]
            if len(matches) == 1:
                k = matches[0]
                item = self._cache.pop(k)
                self._cache[k] = item
                return item
            return None

    def invalidate(self, rel_path: str | None = None, root: str | None = None) -> None:
        with self._lock:
            if rel_path is None and root is None:
                self._cache.clear()
                self._total_bytes = 0
                return
            if rel_path is None and root is not None:
                norm_root = str(Path(root).resolve()).replace("\\", "/").rstrip("/")
                prefix = f"{norm_root}:"
                keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
                for k in keys_to_remove:
                    evicted = self._cache.pop(k, None)
                    if evicted is not None:
                        self._total_bytes = max(0, self._total_bytes - evicted.size_bytes)
                return
            if rel_path is not None and root is not None:
                k = self._key(rel_path, root)
                evicted = self._cache.pop(k, None)
                if evicted is not None:
                    self._total_bytes = max(0, self._total_bytes - evicted.size_bytes)
                return
            if rel_path is not None and root is None:
                norm = rel_path.replace("\\", "/").lstrip("/")
                keys_to_remove = [k for k in self._cache if k == norm or k.endswith(f":{norm}")]
                for k in keys_to_remove:
                    evicted = self._cache.pop(k, None)
                    if evicted is not None:
                        self._total_bytes = max(0, self._total_bytes - evicted.size_bytes)

    def put(self, ingested: IngestedFile | str, text: str | None = None, content_hash: str | None = None, root: str | None = None) -> None:
        if isinstance(ingested, str):
            rel = ingested
            text_val = text or ""
            chash = content_hash or hashlib.sha256(text_val.encode("utf-8", errors="replace")).hexdigest()
            tree = None
            if rel.endswith(".py"):
                try:
                    tree = ast.parse(text_val)
                except Exception:
                    tree = None
            size_b = len(text_val.encode("utf-8", errors="replace"))
            if size_b > self.max_bytes:
                return
            item = IngestedFile(
                path=rel,
                content_hash=chash,
                size_bytes=size_b,
                text=text_val,
                lines=tuple(text_val.splitlines()),
                ast_tree=tree,
                timestamp=time.time(),
            )
        else:
            item = ingested
            if item.size_bytes > self.max_bytes:
                return
        with self._lock:
            k = self._key(item.path, root)
            existing = self._cache.pop(k, None)
            if existing is not None:
                self._total_bytes = max(0, self._total_bytes - existing.size_bytes)
            self._cache[k] = item
            self._total_bytes += item.size_bytes
            self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        while self._cache and (len(self._cache) > self.max_entries or self._total_bytes > self.max_bytes):
            oldest_key = next(iter(self._cache))
            evicted = self._cache.pop(oldest_key)
            self._total_bytes = max(0, self._total_bytes - evicted.size_bytes)

    def get_or_ingest(self, base: Path, rel_path: str, repo_tools: Any) -> IngestedFile:
        root_str = str(base)
        normalized = rel_path.replace("\\", "/").lstrip("/")
        cached = self.get(normalized, root=root_str)
        if cached is not None:
            return cached

        event_key = self._key(normalized, root_str)
        with self._lock:
            cached = self.get(normalized, root=root_str)
            if cached is not None:
                return cached
            event = self._in_flight.get(event_key)
            if event is None:
                event = threading.Event()
                self._in_flight[event_key] = event
                is_leader = True
            else:
                is_leader = False

        if not is_leader:
            event.wait(timeout=30.0)
            cached = self.get(normalized, root=root_str)
            if cached is not None:
                return cached

        try:
            target = base / Path(normalized)
            c_hash, lines = repo_tools._read_snapshot(target)
            source = "\n".join(lines)
            if not c_hash:
                c_hash = hashlib.sha256(source.encode("utf-8", errors="replace")).hexdigest()
            size = len(source.encode("utf-8", errors="replace"))

            tree = None
            if PurePosixPath(normalized).suffix.lower() == ".py":
                try:
                    tree = ast.parse(source)
                except Exception:
                    tree = None

            ingested = IngestedFile(
                path=normalized,
                content_hash=str(c_hash),
                size_bytes=size,
                text=source,
                lines=tuple(lines),
                ast_tree=tree,
                timestamp=time.time(),
            )
            self.put(ingested, root=root_str)
            return ingested
        finally:
            if is_leader:
                with self._lock:
                    self._in_flight.pop(event_key, None)
                event.set()
