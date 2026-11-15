"""Single-pass file ingest and AST buffer across preprocessing phases."""

from __future__ import annotations

import ast
import hashlib
import stat
import threading
import time
from dataclasses import dataclass, field
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
    ast_attempted: bool = True
    # Opportunistic local-file freshness hint, never used in place of an explicit expected_hash.
    source_signature: tuple[int, int, int, int, int] | None = None
    _ast_lock: Any = field(default_factory=threading.Lock, repr=False, compare=False)


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
    def _key(rel_path: str, root: str | None = None, content_hash: str | None = None) -> str:
        norm = rel_path.replace("\\", "/").lstrip("/")
        if root:
            norm_root = str(Path(root).resolve()).replace("\\", "/").rstrip("/")
            if content_hash:
                return f"{norm_root}:{norm}:{content_hash}"
            return f"{norm_root}:{norm}"
        if content_hash:
            return f"{norm}:{content_hash}"
        return norm

    @staticmethod
    def _source_signature(base: Path, rel_path: str) -> tuple[int, int, int, int, int] | None:
        """Conservatively identify stable regular files for repeat ingest reads.

        A missing, non-regular or symlinked source is never trusted from metadata
        alone; the repository reader remains authoritative for source bytes.
        """
        try:
            candidate = base
            for part in PurePosixPath(rel_path).parts:
                candidate = candidate / part
                if candidate.is_symlink():
                    return None
            info = candidate.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                return None
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        except (OSError, ValueError):
            return None

    def has(self, rel_path: str, root: str | None = None, content_hash: str | None = None) -> bool:
        norm = rel_path.replace("\\", "/").lstrip("/")
        with self._lock:
            if content_hash is not None:
                if root is not None:
                    return self._key(norm, root, content_hash) in self._cache
                target = f"{norm}:{content_hash}"
                return any(k == target or k.endswith(f":{target}") for k in self._cache)
            if root is not None:
                norm_root = str(Path(root).resolve()).replace("\\", "/").rstrip("/")
                prefix = f"{norm_root}:{norm}:"
                exact = f"{norm_root}:{norm}"
                return any(k == exact or k.startswith(prefix) for k in self._cache)
            return any(k == norm or k.endswith(f":{norm}") or f":{norm}:" in k for k in self._cache)

    def get(self, rel_path: str, root: str | None = None, content_hash: str | None = None) -> IngestedFile | None:
        norm = rel_path.replace("\\", "/").lstrip("/")
        with self._lock:
            if content_hash is not None:
                if root is not None:
                    k = self._key(norm, root, content_hash)
                    item = self._cache.get(k)
                    if item is not None:
                        self._cache.pop(k, None)
                        self._cache[k] = item
                    return item
                target = f"{norm}:{content_hash}"
                matches = [k for k in self._cache if k == target or k.endswith(f":{target}")]
                if len(matches) == 1:
                    k = matches[0]
                    item = self._cache.pop(k)
                    self._cache[k] = item
                    return item
                return None
            if root is not None:
                norm_root = str(Path(root).resolve()).replace("\\", "/").rstrip("/")
                prefix = f"{norm_root}:{norm}:"
                exact = f"{norm_root}:{norm}"
                matches = [k for k in self._cache if k == exact or k.startswith(prefix)]
                if matches:
                    k = matches[-1]
                    item = self._cache.pop(k)
                    self._cache[k] = item
                    return item
                return None
            matches = [k for k in self._cache if k == norm or k.endswith(f":{norm}") or f":{norm}:" in k]
            if len(matches) == 1:
                k = matches[0]
                item = self._cache.pop(k)
                self._cache[k] = item
                return item
            return None

    def invalidate(self, rel_path: str | None = None, root: str | None = None, content_hash: str | None = None) -> None:
        if rel_path is not None and not root:
            raise ValueError("root is required when invalidating a relative path")
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
                norm = rel_path.replace("\\", "/").lstrip("/")
                norm_root = str(Path(root).resolve()).replace("\\", "/").rstrip("/")
                if content_hash is not None:
                    k = self._key(norm, root, content_hash)
                    evicted = self._cache.pop(k, None)
                    if evicted is not None:
                        self._total_bytes = max(0, self._total_bytes - evicted.size_bytes)
                    return
                prefix = f"{norm_root}:{norm}:"
                exact = f"{norm_root}:{norm}"
                keys_to_remove = [k for k in self._cache if k == exact or k.startswith(prefix)]
                for k in keys_to_remove:
                    evicted = self._cache.pop(k, None)
                    if evicted is not None:
                        self._total_bytes = max(0, self._total_bytes - evicted.size_bytes)
                return
            if rel_path is not None and root is None:
                norm = rel_path.replace("\\", "/").lstrip("/")
                keys_to_remove = [k for k in self._cache if k == norm or k.endswith(f":{norm}") or f":{norm}:" in k]
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
            norm = item.path.replace("\\", "/").lstrip("/")
            if root:
                norm_root = str(Path(root).resolve()).replace("\\", "/").rstrip("/")
                prefix = f"{norm_root}:{norm}:"
                exact = f"{norm_root}:{norm}"
                stale_keys = [k for k in self._cache if k == exact or k.startswith(prefix)]
                for sk in stale_keys:
                    old_item = self._cache.pop(sk, None)
                    if old_item is not None:
                        self._total_bytes = max(0, self._total_bytes - old_item.size_bytes)
            k = self._key(item.path, root, item.content_hash)
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

    def _ensure_ast(self, item: IngestedFile, parse_ast: bool) -> IngestedFile:
        if not parse_ast or item.ast_attempted:
            return item
        acquired = item._ast_lock.acquire(timeout=30.0)
        try:
            if item.ast_attempted:
                return item
            try:
                tree = ast.parse(item.text)
            except Exception:
                tree = None
            with self._lock:
                if not item.ast_attempted:
                    item.ast_tree = tree
                    item.ast_attempted = True
            return item
        finally:
            if acquired:
                item._ast_lock.release()

    def get_with_ast(self, rel_path: str, root: str | None = None, content_hash: str | None = None) -> IngestedFile | None:
        item = self.get(rel_path, root=root, content_hash=content_hash)
        if item is None:
            return None
        self._ensure_ast(item, True)
        # An invalidation or replacement during parsing makes this snapshot stale.
        return item if self.get(rel_path, root=root, content_hash=content_hash) is item else None

    def get_or_ingest(
        self,
        base: Path,
        rel_path: str,
        repo_tools: Any,
        *,
        parse_ast: bool = True,
        expected_hash: str | None = None,
    ) -> IngestedFile:
        root_str = str(base)
        normalized = rel_path.replace("\\", "/").lstrip("/")

        def ensure_current(item: IngestedFile | None) -> IngestedFile | None:
            if not parse_ast:
                return item
            for _ in range(3):
                if item is None:
                    return None
                self._ensure_ast(item, True)
                current = self.get(normalized, root=root_str, content_hash=expected_hash)
                if current is item:
                    return item
                item = current
            return None

        cached = self.get(normalized, root=root_str, content_hash=expected_hash)
        if cached is not None:
            if expected_hash is not None and cached.content_hash == expected_hash:
                cached = ensure_current(cached)
                if cached is not None:
                    return cached
            elif expected_hash is None:
                # The common case must not reread the entire file in every
                # parallel caller after the first single-flight ingest finishes.
                current_signature = self._source_signature(base, normalized)
                if current_signature is not None and current_signature == cached.source_signature:
                    cached = ensure_current(cached)
                    if cached is not None:
                        return cached
                else:
                    # Unknown/changed metadata cannot prove source freshness.
                    # Fall back to the exact source digest instead of assuming.
                    current_hash, _current_lines = repo_tools._read_snapshot(base / Path(normalized))
                    if current_hash == cached.content_hash:
                        cached = ensure_current(cached)
                        if cached is not None:
                            return cached
            self.invalidate(normalized, root=root_str)

        event_key = self._key(normalized, root_str, expected_hash)
        with self._lock:
            cached = self.get(normalized, root=root_str, content_hash=expected_hash)
            if cached is None:
                event = self._in_flight.get(event_key)
                if event is None:
                    event = threading.Event()
                    self._in_flight[event_key] = event
                    is_leader = True
                else:
                    is_leader = False
        if cached is not None:
            cached = ensure_current(cached)
            if cached is not None:
                return cached
            # The item was invalidated while parsing; join or start a fresh read.
            with self._lock:
                event = self._in_flight.get(event_key)
                if event is None:
                    event = threading.Event()
                    self._in_flight[event_key] = event
                    is_leader = True
                else:
                    is_leader = False

        if not is_leader:
            event.wait(timeout=30.0)
            cached = self.get(normalized, root=root_str, content_hash=expected_hash)
            if cached is not None:
                cached = ensure_current(cached)
                if cached is not None:
                    return cached

        try:
            target = base / Path(normalized)
            signature_before = self._source_signature(base, normalized)
            c_hash, lines = repo_tools._read_snapshot(target)
            signature_after = self._source_signature(base, normalized)
            source_signature = (
                signature_after if signature_before is not None and signature_before == signature_after else None
            )
            source = "\n".join(lines)
            if not c_hash:
                c_hash = hashlib.sha256(source.encode("utf-8", errors="replace")).hexdigest()
            size = len(source.encode("utf-8", errors="replace"))

            tree = None
            is_python = PurePosixPath(normalized).suffix.lower() == ".py"
            if is_python and parse_ast:
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
                ast_attempted=parse_ast or not is_python,
                source_signature=source_signature,
            )
            self.put(ingested, root=root_str)
            return ingested
        finally:
            if is_leader:
                with self._lock:
                    self._in_flight.pop(event_key, None)
                event.set()
