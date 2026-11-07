"""Single-pass file ingest and AST buffer across preprocessing phases."""

from __future__ import annotations

import ast
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

    def put(self, ingested: IngestedFile) -> None:
        with self._lock:
            norm = ingested.path.replace("\\", "/")
            existing = self._cache.pop(norm, None)
            if existing is not None:
                self._total_bytes = max(0, self._total_bytes - existing.size_bytes)
            self._cache[norm] = ingested
            self._total_bytes += ingested.size_bytes
            self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        while len(self._cache) > self.max_entries or (self._total_bytes > self.max_bytes and len(self._cache) > 1):
            oldest_key = next(iter(self._cache))
            evicted = self._cache.pop(oldest_key)
            self._total_bytes = max(0, self._total_bytes - evicted.size_bytes)

    def get_or_ingest(self, base: Path, rel_path: str, repo_tools: Any) -> IngestedFile:
        norm = rel_path.replace("\\", "/")
        with self._lock:
            cached = self.get(norm)
            if cached is not None:
                return cached

        target = base / Path(rel_path)
        file_hash, lines = repo_tools._read_snapshot(target)
        text = "\n".join(lines)
        size_bytes = len(text.encode("utf-8", errors="ignore"))
        ast_tree = None

        if PurePosixPath(norm).suffix.lower() == ".py":
            try:
                ast_tree = ast.parse(text)
            except (SyntaxError, ValueError, RecursionError):
                ast_tree = None

        ingested = IngestedFile(
            path=norm,
            content_hash=str(file_hash),
            size_bytes=size_bytes,
            text=text,
            lines=tuple(lines),
            ast_tree=ast_tree,
            timestamp=time.monotonic(),
        )

        self.put(ingested)
        return ingested
