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
        self.max_bytes = max(1024, int(max_bytes))
        self._cache: dict[str, IngestedFile] = {}
        self._total_bytes: int = 0
        self._lock = threading.RLock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def has(self, rel_path: str) -> bool:
        normalized = rel_path.replace("\\", "/")
        with self._lock:
            return normalized in self._cache

    def get(self, rel_path: str) -> IngestedFile | None:
        normalized = rel_path.replace("\\", "/")
        with self._lock:
            item = self._cache.get(normalized)
            if item is not None:
                # Refresh LRU position
                self._cache.pop(normalized, None)
                self._cache[normalized] = item
            return item

    def invalidate(self, rel_path: str | None = None) -> None:
        with self._lock:
            if rel_path is None:
                self._cache.clear()
                self._total_bytes = 0
                return
            normalized = rel_path.replace("\\", "/")
            item = self._cache.pop(normalized, None)
            if item is not None:
                self._total_bytes = max(0, self._total_bytes - item.size_bytes)

    def put(self, ingested: IngestedFile | str, text: str | None = None, content_hash: str | None = None) -> None:
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
            item = IngestedFile(
                path=rel,
                content_hash=chash,
                size_bytes=len(text_val.encode("utf-8", errors="replace")),
                text=text_val,
                lines=tuple(text_val.splitlines()),
                ast_tree=tree,
                timestamp=time.time(),
            )
        else:
            item = ingested
        with self._lock:
            norm = item.path.replace("\\", "/")
            existing = self._cache.pop(norm, None)
            if existing is not None:
                self._total_bytes = max(0, self._total_bytes - existing.size_bytes)
            self._cache[norm] = item
            self._total_bytes += item.size_bytes
            self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        while len(self._cache) > self.max_entries or (self._total_bytes > self.max_bytes and len(self._cache) > 1):
            oldest_key = next(iter(self._cache))
            evicted = self._cache.pop(oldest_key)
            self._total_bytes = max(0, self._total_bytes - evicted.size_bytes)

    def get_or_ingest(self, base: Path, rel_path: str, repo_tools: Any) -> IngestedFile:
        normalized = rel_path.replace("\\", "/")
        cached = self.get(normalized)
        if cached is not None:
            return cached

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
        self.put(ingested)
        return ingested
