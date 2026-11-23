from __future__ import annotations

from dataclasses import dataclass
import heapq
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping


class FileTooLargeError(OSError):
    """Raised when a bounded snapshot exceeds its configured byte limit."""


class GitFileInventory(list[Path]):
    """Bounded Git path inventory with an explicit completeness marker."""

    def __init__(self, paths: Iterable[Path], *, complete: bool):
        super().__init__(paths)
        self.complete = complete


class _ReversePath:
    __slots__ = ("value",)

    def __init__(self, value: str):
        self.value = value

    def __lt__(self, other: _ReversePath) -> bool:
        return self.value > other.value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _ReversePath) and self.value == other.value


class _BoundedSortedPaths:
    """Keep the lexically first unique paths with O(limit) retained entries."""

    def __init__(self, limit: int):
        self._limit = max(0, limit)
        self._heap: list[tuple[_ReversePath, str]] = []
        self._retained: set[str] = set()
        self._complete = True

    def add(self, path: str) -> None:
        if path in self._retained:
            return
        if self._limit == 0:
            self._complete = False
            return
        if len(self._heap) < self._limit:
            heapq.heappush(self._heap, (_ReversePath(path), path))
            self._retained.add(path)
            return
        self._complete = False
        largest = self._heap[0][1]
        if path < largest:
            heapq.heapreplace(self._heap, (_ReversePath(path), path))
            self._retained.remove(largest)
            self._retained.add(path)

    def finish(self) -> tuple[list[str], bool]:
        return sorted(self._retained), self._complete


class _IncompleteGitInventory(RuntimeError):
    pass


@dataclass(frozen=True)
class GitBlobRecord:
    state: str
    oid: str | None = None
    identity: str | None = None


@dataclass(frozen=True)
class GitSnapshot:
    common_dir: str | None
    worktree_root: str
    git_dir: str | None
    index_path: str | None
    index_signature: tuple[int, int, int, int, int, str] | None
    head_oid: str | None
    tree_oid: str | None
    status: Mapping[str, str]
    blobs: Mapping[str, GitBlobRecord]
    deleted: tuple[str, ...]
    renames: Mapping[str, str]
    degraded: bool = False
    error: str | None = None
    status_identity: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", MappingProxyType(dict(self.status)))
        object.__setattr__(self, "blobs", MappingProxyType(dict(self.blobs)))
        object.__setattr__(self, "renames", MappingProxyType(dict(self.renames)))

    @property
    def revision(self) -> str:
        """Stable repository revision for bounded guard provenance."""
        return self.head_oid or self.status_identity or ""

    @property
    def repository_revision(self) -> str:
        return self.revision

    @property
    def changed_paths(self) -> tuple[str, ...]:
        paths = {path for path, state in self.status.items() if state != "clean"}
        paths.update(self.deleted)
        paths.update(self.renames)
        paths.update(self.renames.values())
        return tuple(sorted(path for path in paths if path))
