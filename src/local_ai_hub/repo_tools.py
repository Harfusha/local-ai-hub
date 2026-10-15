from __future__ import annotations

import hashlib
import fnmatch
import heapq
import json
import math
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from collections import Counter, OrderedDict
from functools import lru_cache
from queue import Empty, Queue
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from .budget import chars_for_tokens, estimate_tokens
from .normalizer import tokenize_query_terms
from .process_utils import canonical_root, hidden_run_kwargs, popen_managed, terminate_tree
from .search_pagination import MAX_PAGE_SIZE, MAX_PAGE_WINDOW, pagination_bounds_error


_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_./:-]{1,80}")
MAX_EXACT_SEARCH_FILES = 8000


class GitFileInventory(list[Path]):
    """Bounded Git path inventory with an explicit completeness marker."""

    def __init__(self, paths: Iterable[Path], *, complete: bool):
        super().__init__(paths)
        self.complete = complete


class _IncompleteGitInventory(RuntimeError):
    pass


def is_root_archive_path(relative: str | Path) -> bool:
    """Return whether a repository-relative path belongs to a root audit overlay."""
    parts = tuple(
        part.casefold()
        for part in str(relative).replace("\\", "/").strip("/").split("/")
        if part not in {"", "."}
    )
    if not parts:
        return False
    if parts[0] in {"handoff", ".handoff", ".merge-checks", ".sync-checks", ".system_generated"}:
        return True
    if len(parts) > 1 and parts[:2] == ("artifacts", "handoff"):
        return True
    if len(parts) > 1 and parts[0] == "artifacts" and "-overlay-" in parts[1]:
        return True
    if len(parts) > 1 and parts[0] == "artifacts":
        artifact_name = parts[1]
        if re.fullmatch(r"t\d+-.+", artifact_name) and (
            parts[2:4] == ("src", "local_ai_hub")
            or parts[2:3] in {("tests",), ("tools",)}
        ):
            return True
        if re.match(r"t\d+-ast-check-", artifact_name):
            return True
        if re.fullmatch(
            r"t\d+-root-current-.+(?:-preimage(?:\.[^/]*)?|-replay\.py|-memory-transition\.py)",
            artifact_name,
        ):
            return True
    if (
        len(parts) >= 6
        and parts[0] == ".validation"
        and re.fullmatch(r"t\d+-.+", parts[1]) is not None
        and parts[2] == "package-pytest"
        and parts[3].startswith("test_")
        and "generated" in parts[4:]
    ):
        return True
    root_name = parts[0].lstrip(".")
    return (
        "-root-overlay-" in parts[0]
        or "-root-current-check-" in parts[0]
        or "-root-current-overlay" in parts[0]
        or re.match(r"t\d+-review-artifacts-", root_name) is not None
        or re.match(r"t\d+-(?:sync-checks|main-preflight-overlay)(?:-|$)", root_name) is not None
    )
_MAX_DIRECTORY_HINT_FILES = 64
_MAX_PATH_CONTROLS = 64
_HARD_SEARCH_DIRS = frozenset({".git", ".local-ai-hub", ".serena", ".codegraphcontext"})
_UNSET_GIT_INVENTORY = object()
_SYMBOL_PATTERNS = [
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)"),
    re.compile(r"^\s*class\s+([A-Za-z_]\w*)"),
    re.compile(r"^\s*(?:public|private|protected|internal|static|final|virtual|override|abstract|sealed|partial|async|export|default|const|let|var|function|func|fn|type|interface|enum|struct|record|trait|impl|namespace|module)\s+(?:[\w<>,?\[\].]+\s+)*([A-Za-z_]\w*)"),
]


@lru_cache(maxsize=1)
def _windows_file_api():
    import ctypes
    from ctypes import wintypes

    class _FileBasicInfo(ctypes.Structure):
        _fields_ = [
            ("CreationTime", ctypes.c_longlong),
            ("LastAccessTime", ctypes.c_longlong),
            ("LastWriteTime", ctypes.c_longlong),
            ("ChangeTime", ctypes.c_longlong),
            ("FileAttributes", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    get_info = kernel32.GetFileInformationByHandleEx
    get_info.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    return _FileBasicInfo, kernel32, create_file, get_info, close_handle, ctypes.c_void_p(-1).value


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


class FileTooLargeError(OSError):
    """Raised when a bounded snapshot exceeds its configured byte limit."""


class RepositoryTools:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        rag = config.get("rag", {})
        search = config.get("search", {})
        self.extensions = {str(x).lower() for x in rag.get("extensions", [])}
        self.special_filenames = {str(x).lower() for x in search.get("special_filenames", [
            "dockerfile", "containerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
            "makefile", "gnumakefile", "justfile", "gemfile", "pipfile", ".env", ".env.example", ".env.sample",
            ".gitlab-ci.yml", ".gitlab-ci.yaml", "azure-pipelines.yml", "azure-pipelines.yaml",
            "pytest.ini", "tox.ini", "phpunit.xml", "phpunit.xml.dist", "phpstan.neon", "phpstan.neon.dist",
        ])}
        default_ignore_dirs = {
            ".git", ".svn", ".hg", ".idea", ".vscode", ".venv", "venv", "node_modules",
            "vendor", "dist", "build", "bin", "obj", "coverage", ".next", ".cache",
            "library", "temp", "logs", "usersettings", "packagestore", "memorycaptures", "builds",
            ".serena", ".local-ai-hub", ".codegraphcontext", ".handoff",
            ".t03-main-preflight-overlay", ".system_generated", "artifacts", ".validation",
            ".pytest_cache", ".mypy_cache", ".ruff_cache",
        }
        self.ignore_dirs = {str(name).lower() for name in rag.get("ignore_dirs", [])} | default_ignore_dirs
        self.ignore_extensions = {str(x).lower() for x in rag.get("ignore_extensions", [
            ".meta", ".asset", ".prefab", ".mat", ".unity", ".anim", ".controller",
            ".overridecontroller", ".physicmaterial", ".physicsmaterial2d", ".guiskin",
            ".mask", ".cubemap", ".flare", ".fontsettings", ".terrainlayer",
            ".mesh", ".fbx", ".obj", ".blend", ".tga", ".psd", ".png", ".jpg", ".jpeg",
            ".wav", ".mp3", ".ogg", ".shadergraph", ".shadersubgraph"
        ])}
        self.max_file_bytes = int(rag.get("max_file_bytes", 2_000_000))
        self.max_files = int(search.get("max_files", 8000))
        self.python_fallback_max_files = max(
            1, min(max(1, self.max_files), int(search.get("python_fallback_max_files", self.max_files)))
        )
        self.max_hits = int(search.get("max_hits", 80))
        self.max_search_terms = max(4, int(search.get("max_terms", 12)))
        self.snippet_lines = int(search.get("snippet_lines", 5))
        self.max_snippets_per_file = int(search.get("max_snippets_per_file", 3))
        self.prefer_git = bool(search.get("prefer_git_files", True))
        self.use_ripgrep = bool(search.get("use_ripgrep_if_available", True))
        self.ripgrep_timeout = max(0.5, float(search.get("ripgrep_timeout_seconds", 15.0)))
        self.ripgrep_slow_cooldown = max(1.0, float(search.get("ripgrep_slow_cooldown_seconds", 15.0)))
        self.git_grep_timeout = max(0.5, float(search.get("git_grep_timeout_seconds", min(10.0, self.ripgrep_timeout))))
        self.git_files_timeout = max(0.5, float(search.get("git_files_timeout_seconds", 5.0)))
        self.git_files_cache_ttl = max(0.0, float(search.get("git_files_cache_ttl_seconds", 3.0)))
        self.git_files_slow_cooldown = max(1.0, float(search.get("git_files_slow_cooldown_seconds", 15.0)))
        self.use_git_grep = bool(search.get("use_git_grep_fallback", True))
        self._rg = shutil.which("rg") if self.use_ripgrep else None
        self._git_files_lock = threading.RLock()
        self._git_files_cache: dict[str, tuple[float, tuple[str, ...]]] = {}
        self._git_blob_cache: dict[str, tuple[float, dict[str, str]]] = {}
        self._git_snapshot_cache: dict[str, tuple[float, GitSnapshot]] = {}
        self._git_snapshot_slow_until: dict[str, float] = {}
        self._git_files_slow_until: dict[str, float] = {}
        self._git_files_flights: dict[str, threading.Lock] = {}
        self._git_grep_slow_until: dict[str, float] = {}
        self._ripgrep_slow_until: dict[str, float] = {}
        self._git_stats = {"file_list_hits": 0, "file_list_misses": 0, "file_list_timeouts": 0, "file_list_coalesced": 0, "grep_timeouts": 0, "grep_cooldown_skips": 0, "ripgrep_timeouts": 0, "ripgrep_cooldown_skips": 0, "python_search_fallbacks": 0, "snapshot_hits": 0, "snapshot_misses": 0, "snapshot_degraded": 0}
        snap = config.get("snapshot_cache", {})
        self.snapshot_max_entries = max(64, int(snap.get("max_entries", max(4096, self.max_files))))
        self.snapshot_max_bytes = max(8_000_000, int(snap.get("max_bytes", 256_000_000)))
        self._snapshot_lock = threading.RLock()
        self._snapshots: OrderedDict[str, tuple[int, int, int, int, str, list[str], int]] = OrderedDict()
        self._hash_only_cache: OrderedDict[str, tuple[int, int, int, int, str, bool]] = OrderedDict()
        self._hash_only_max_entries = 8192
        self._snapshot_bytes = 0
        self.snapshot_hits = 0
        self.snapshot_misses = 0
        self.snapshot_verified_rehashes = 0

    @staticmethod
    def _root(root: str) -> Path:
        canon = canonical_root(root)
        path = Path(canon)
        if not path.is_dir():
            raise ValueError(f"root directory does not exist: {path}")
        return path

    def _git_files(self, root: Path, *, max_files: int | None = None) -> GitFileInventory | None:
        """Stream a bounded tracked + untracked Git inventory.

        At most ``max_files`` paths are retained (the default hard bound is
        ``self.max_files``); ``complete=False`` marks a further eligible path.
        The NUL-delimited subprocess output is consumed in fixed-size chunks.
        """
        if not self.prefer_git or not (root / ".git").exists():
            return None
        limit = self.max_files if max_files is None else max(0, int(max_files))
        key = str(root)
        now = time.monotonic()
        with self._git_files_lock:
            cached = self._git_files_cache.get(key)
            if cached and (self.git_files_cache_ttl <= 0 or now - cached[0] <= self.git_files_cache_ttl):
                self._git_stats["file_list_hits"] += 1
                return GitFileInventory(
                    [(root / rel).resolve(strict=False) for rel in cached[1][:limit]],
                    complete=len(cached[1]) <= limit,
                )
            if now < self._git_files_slow_until.get(key, 0.0):
                return None
            flight = self._git_files_flights.setdefault(key, threading.Lock())

        if not flight.acquire(timeout=self.git_files_timeout + 0.25):
            with self._git_files_lock:
                self._git_stats["file_list_coalesced"] += 1
            return None
        process = None
        timer = None
        timed_out = threading.Event()
        try:
            now = time.monotonic()
            with self._git_files_lock:
                cached = self._git_files_cache.get(key)
                if cached and (self.git_files_cache_ttl <= 0 or now - cached[0] <= self.git_files_cache_ttl):
                    self._git_stats["file_list_hits"] += 1
                    self._git_stats["file_list_coalesced"] += 1
                    return GitFileInventory(
                        [(root / rel).resolve(strict=False) for rel in cached[1][:limit]],
                        complete=len(cached[1]) <= limit,
                    )
                if now < self._git_files_slow_until.get(key, 0.0):
                    return None
                self._git_stats["file_list_misses"] += 1
            process = popen_managed(
                ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                **hidden_run_kwargs(text=False),
            )

            def kill_on_timeout() -> None:
                if process is not None and process.poll() is None:
                    timed_out.set()
                    try:
                        terminate_tree(process.pid, grace_seconds=0.1, process_handle=process)
                    except (OSError, ValueError):
                        pass

            timer = threading.Timer(self.git_files_timeout, kill_on_timeout)
            timer.daemon = True
            timer.start()
            rels: list[str] = []
            pending = bytearray()
            truncated = False

            def consider(raw: bytes) -> bool:
                nonlocal truncated
                if not raw:
                    return True
                rel = raw.decode("utf-8", errors="surrogateescape").replace("\\", "/")
                candidate = (root / rel).resolve(strict=False)
                try:
                    candidate.relative_to(root)
                except ValueError:
                    return True
                if max_files is not None:
                    relative = Path(rel)
                    if any(part.lower() in self.ignore_dirs for part in relative.parts[:-1]):
                        return True
                    if candidate.suffix.lower() in self.ignore_extensions:
                        return True
                    if self.extensions and candidate.suffix.lower() not in self.extensions and candidate.name.lower() not in self.special_filenames:
                        return True
                    try:
                        if candidate.stat().st_size > self.max_file_bytes:
                            return True
                    except OSError:
                        return True
                if len(rels) >= limit:
                    truncated = True
                    return False
                rels.append(rel)
                return True

            assert process.stdout is not None
            while True:
                chunk = process.stdout.read(64 * 1024)
                if not chunk:
                    break
                pending.extend(chunk)
                while True:
                    separator = pending.find(0)
                    if separator < 0:
                        if len(pending) > 64 * 1024:
                            raise OSError("Git path exceeded bounded inventory buffer")
                        break
                    raw = bytes(pending[:separator])
                    del pending[:separator + 1]
                    if not consider(raw):
                        break
                if truncated:
                    break
            if pending and not truncated:
                consider(bytes(pending))
            if truncated:
                terminate_tree(process.pid, grace_seconds=0.1, process_handle=process)
            return_code = process.wait()
            if timed_out.is_set() or (return_code != 0 and not truncated):
                if timed_out.is_set():
                    with self._git_files_lock:
                        self._git_stats["file_list_timeouts"] += 1
                        self._git_files_slow_until[key] = time.monotonic() + self.git_files_slow_cooldown
                return None
            complete = not truncated
            inventory = GitFileInventory(
                [(root / rel).resolve(strict=False) for rel in rels], complete=complete,
            )
            with self._git_files_lock:
                if max_files is None and complete:
                    self._git_files_cache[key] = (time.monotonic(), tuple(rels))
                    if len(self._git_files_cache) > 64:
                        for cache_key in list(self._git_files_cache.keys())[:-32]:
                            self._git_files_cache.pop(cache_key, None)
                self._git_files_slow_until.pop(key, None)
            return inventory
        except OSError:
            with self._git_files_lock:
                self._git_files_slow_until[key] = time.monotonic() + self.git_files_slow_cooldown
            return None
        finally:
            if timer is not None:
                timer.cancel()
            if process is not None and process.poll() is None:
                try:
                    terminate_tree(process.pid, grace_seconds=0.1, process_handle=process)
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if process is not None and process.stdout is not None:
                try:
                    process.stdout.close()
                except OSError:
                    pass
            flight.release()

    def iter_files(
        self, root: str, max_depth: int = 25, *, project_settings: Any | None = None,
        max_files: int | None = None,
    ) -> Iterable[Path]:
        for path, _stat in self._iter_files_with_stat(
            root, max_depth=max_depth, project_settings=project_settings, max_files=max_files,
        ):
            yield path

    def _is_ignored_relative_path(self, relative: Path) -> bool:
        if is_root_archive_path(relative):
            return True
        if any(part.lower() in self.ignore_dirs for part in relative.parts[:-1]):
            return True
        if relative.suffix.lower() in self.ignore_extensions:
            return True
        return bool(
            self.extensions
            and relative.suffix.lower() not in self.extensions
            and relative.name.lower() not in self.special_filenames
        )

    def _iter_files_with_stat(
        self, root: str, max_depth: int = 25, *, project_settings: Any | None = None,
        max_files: int | None = None,
    ) -> Iterable[tuple[Path, os.stat_result]]:
        base = self._root(root)
        limit = self.max_files if max_files is None else max(0, int(max_files))
        if project_settings is not None:
            yielded = 0
            for path in self._iter_project_search_files(base, project_settings, max_depth):
                if yielded >= limit:
                    break
                yielded += 1
                try:
                    stat = path.stat()
                except OSError:
                    continue
                yield path, stat
            return
        git_files = self._git_files(base, max_files=limit) if max_files is not None else self._git_files(base)
        if git_files is not None:
            candidates = git_files
        else:
            candidates = []
            visited_realpaths: set[str] = set()
            try:
                visited_realpaths.add(os.path.realpath(base))
            except Exception:
                pass
            for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
                try:
                    relative_dir = Path(dirpath).relative_to(base)
                except ValueError:
                    relative_dir = Path()
                dirnames[:] = [
                    d for d in dirnames
                    if d.lower() not in self.ignore_dirs
                    and not is_root_archive_path(relative_dir / d)
                ]
                try:
                    rel_parts = Path(dirpath).relative_to(base).parts
                    if len(rel_parts) >= max_depth:
                        dirnames.clear()
                        continue
                except ValueError:
                    pass

                kept_dirnames: list[str] = []
                for d in dirnames:
                    subdir = os.path.join(dirpath, d)
                    try:
                        rpath = os.path.realpath(subdir)
                        if rpath in visited_realpaths:
                            continue
                        visited_realpaths.add(rpath)
                        kept_dirnames.append(d)
                    except Exception:
                        kept_dirnames.append(d)
                dirnames[:] = kept_dirnames

                for name in filenames:
                    p = Path(dirpath) / name
                    if p.suffix.lower() in self.ignore_extensions:
                        continue
                    if self.extensions and p.suffix.lower() not in self.extensions and p.name.lower() not in self.special_filenames:
                        continue
                    if max_files is not None:
                        try:
                            if p.stat().st_size > self.max_file_bytes:
                                continue
                        except OSError:
                            continue
                    candidates.append(p)
                    if len(candidates) >= limit:
                        break
                if len(candidates) >= limit:
                    break
        count = 0
        for path in candidates:
            if count >= limit:
                break
            try:
                relative = path.relative_to(base)
            except ValueError:
                continue
            # `git ls-files -co --exclude-standard` can return ignored paths from
            # other worktrees; configured exclusions apply to every inventory path.
            if self._is_ignored_relative_path(relative):
                continue
            try:
                stat = path.stat()
                if stat.st_size > self.max_file_bytes:
                    continue
            except OSError:
                continue
            count += 1
            yield path, stat

    def _read_snapshot(
        self,
        path: Path,
        *,
        stat: os.stat_result | None = None,
        force: bool = False,
        max_bytes: int | None = None,
    ) -> tuple[str, list[str]]:
        """Cache decoded file content/hash by stat identity across different repo queries."""
        if max_bytes is not None:
            # Re-stat even when the caller supplied a snapshot. The bounded read
            # below also catches growth after this check without allocating it all.
            stat = path.stat()
            if stat.st_size > max_bytes:
                raise FileTooLargeError(f"{path} exceeds {max_bytes} bytes")
            force = True
        stat_was_supplied = stat is not None
        if stat is None:
            stat = path.stat()
        key = str(path)
        identity, verify_content = self._cache_identity(path, stat)
        allow_cached_lookup = True
        if stat_was_supplied and os.name != "nt":
            with self._snapshot_lock:
                allow_cached_lookup = key in self._snapshots
            if allow_cached_lookup:
                # POSIX identity uses the supplied stat, which can predate this read.
                stat = path.stat()
                identity, verify_content = self._cache_identity(path, stat)
        cached = None
        with self._snapshot_lock:
            item = self._snapshots.get(key) if allow_cached_lookup else None
            if item is not None and item[:4] == identity:
                self._snapshots.move_to_end(key)
                if not verify_content and not force:
                    self.snapshot_hits += 1
                    return item[4], item[5]
                cached = item
        if max_bytes is None:
            raw = path.read_bytes()
        else:
            with path.open("rb") as source:
                raw = source.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise FileTooLargeError(f"{path} exceeds {max_bytes} bytes")
        digest = hashlib.sha256(raw).hexdigest()
        if cached is not None and cached[4] == digest:
            with self._snapshot_lock:
                self.snapshot_verified_rehashes += 1
                current = self._snapshots.get(key)
                if current is not None and current[4] == digest:
                    self._snapshots.move_to_end(key)
                self._hash_only_cache[key] = (*identity, digest, False)
                self._hash_only_cache.move_to_end(key)
                while len(self._hash_only_cache) > self._hash_only_max_entries:
                    self._hash_only_cache.popitem(last=False)
            return cached[4], cached[5]
        lines = raw.decode("utf-8", errors="replace").splitlines()
        size = len(raw)
        with self._snapshot_lock:
            if cached is not None:
                self.snapshot_verified_rehashes += 1
            old = self._snapshots.pop(key, None)
            if old:
                self._snapshot_bytes -= old[6]
            self._snapshots[key] = (*identity, digest, lines, size)
            self._snapshot_bytes += size
            self._hash_only_cache[key] = (*identity, digest, False)
            self._hash_only_cache.move_to_end(key)
            if len(self._hash_only_cache) > self._hash_only_max_entries:
                self._hash_only_cache.popitem(last=False)
            self.snapshot_misses += 1
            while self._snapshots and (len(self._snapshots) > self.snapshot_max_entries or self._snapshot_bytes > self.snapshot_max_bytes):
                _k, evicted = self._snapshots.popitem(last=False)
                self._snapshot_bytes -= evicted[6]
        return digest, lines

    @staticmethod
    def _windows_change_time(path: Path) -> int | None:
        """Return NTFS change time, which remains distinct when mtime is restored."""
        if os.name != "nt":
            return None
        handle = None
        close_handle = None
        invalid_handle = -1
        try:
            import ctypes
            _FileBasicInfo, _kernel32, create_file, get_info, close_handle, invalid_handle = _windows_file_api()
            native_path = os.path.abspath(os.fspath(path))
            if native_path.startswith("\\\\"):
                native_path = "\\\\?\\UNC\\" + native_path[2:]
            elif not native_path.startswith("\\\\?\\"):
                native_path = "\\\\?\\" + native_path
            handle = create_file(native_path, 0x80, 0x7, None, 3, 0x80, None)
            if handle == ctypes.c_void_p(-1).value:
                return None
            info = _FileBasicInfo()
            if not get_info(handle, 0, ctypes.byref(info), ctypes.sizeof(info)):
                return None
            return int(info.ChangeTime)
        except Exception:
            return None
        finally:
            if close_handle is not None and handle is not None and handle != invalid_handle:
                try:
                    close_handle(handle)
                except Exception:
                    pass

    def _cache_identity(self, path: Path, stat: os.stat_result) -> tuple[tuple[int, int, int, int], bool]:
        change_time = self._windows_change_time(path)
        if os.name == "nt" and change_time is None:
            # Windows st_ctime_ns is creation time; hash when native change time is unavailable.
            return (
                int(stat.st_mtime_ns), int(stat.st_size),
                int(getattr(stat, "st_ctime_ns", 0)), int(getattr(stat, "st_ino", 0)),
            ), True
        return (
            int(stat.st_mtime_ns), int(stat.st_size),
            int(change_time if change_time is not None else getattr(stat, "st_ctime_ns", 0)),
            int(getattr(stat, "st_ino", 0)),
        ), False

    @staticmethod
    def _stat_cache_identity(stat: os.stat_result) -> tuple[int, int, int, int]:
        return (
            int(stat.st_mtime_ns), int(stat.st_size),
            int(getattr(stat, "st_ctime_ns", 0)), int(getattr(stat, "st_ino", 0)),
        )

    def _hash_file_only(self, path: Path) -> str:
        """Return SHA-256 without decoding source text or populating the decoded snapshot LRU.

        Preprocessing uses this when it only needs content identity. Interactive reads
        continue to use ``_read_snapshot`` so decoded text is cached on demand.
        """
        stat = path.stat()
        key = str(path)
        with self._snapshot_lock:
            snapshot = self._snapshots.get(key)
            h_item = self._hash_only_cache.get(key)
        identity_unverified = os.name == "nt" and snapshot is None and h_item is None
        if identity_unverified:
            # Cold reads already hash every byte. Defer the extra Windows handle
            # query until next access, then verify bytes before trusting this identity.
            identity = self._stat_cache_identity(stat)
            verify_content = True
        else:
            identity, verify_content = self._cache_identity(path, stat)
        cached_digest = None
        with self._snapshot_lock:
            item = self._snapshots.get(key)
            if item is not None and item[:4] == identity:
                self._snapshots.move_to_end(key)
                if verify_content:
                    cached_digest = item[4]
                else:
                    self.snapshot_hits += 1
                    return item[4]
            h_item = self._hash_only_cache.get(key)
            if h_item is not None and h_item[:4] == identity:
                self._hash_only_cache.move_to_end(key)
                if verify_content or h_item[5]:
                    cached_digest = cached_digest or h_item[4]
                else:
                    self.snapshot_hits += 1
                    return h_item[4]
            elif h_item is not None and h_item[5] and h_item[:4] == self._stat_cache_identity(stat):
                self._hash_only_cache.move_to_end(key)
                cached_digest = cached_digest or h_item[4]
                verify_content = True
        h = hashlib.sha256()
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        digest = h.hexdigest()
        with self._snapshot_lock:
            snapshot = self._snapshots.get(key)
            snapshot_identity_matches = snapshot is not None and snapshot[:4] == identity
            if snapshot_identity_matches and snapshot[4] != digest:
                self._snapshots.pop(key, None)
                self._snapshot_bytes -= snapshot[6]
            elif snapshot_identity_matches:
                self._snapshots.move_to_end(key)
            if cached_digest is not None:
                self.snapshot_verified_rehashes += 1
            self._hash_only_cache[key] = (
                identity[0], identity[1], identity[2], identity[3], digest,
                identity_unverified and cached_digest is None,
            )
            self._hash_only_cache.move_to_end(key)
            if len(self._hash_only_cache) > self._hash_only_max_entries:
                self._hash_only_cache.popitem(last=False)
        return digest

    def invalidate_snapshot(self, path: Path) -> None:
        """Drop cached identities when a caller has independent change evidence."""
        key = str(path)
        with self._snapshot_lock:
            item = self._snapshots.pop(key, None)
            if item is not None:
                self._snapshot_bytes -= item[6]
            self._hash_only_cache.pop(key, None)

    @staticmethod
    def _git_empty_snapshot(root: str, error: str) -> GitSnapshot:
        return GitSnapshot(
            common_dir=None,
            worktree_root=root,
            git_dir=None,
            index_path=None,
            index_signature=None,
            head_oid=None,
            tree_oid=None,
            status=MappingProxyType({}),
            blobs=MappingProxyType({}),
            deleted=(),
            renames=MappingProxyType({}),
            degraded=True,
            error=error,
        )

    def _git_snapshot_run(self, base: Path, *args: str) -> bytes:
        completed = subprocess.run(
            ["git", "-C", str(base), *args],
            capture_output=True,
            timeout=self.git_files_timeout,
            check=False,
            **hidden_run_kwargs(),
        )
        if not isinstance(completed.stdout, (bytes, bytearray)):
            raise ValueError("git command failed")
        if completed.returncode != 0:
            # ``HEAD`` is legitimately unresolved before the first commit. Git
            # still returns complete repository/index metadata in this case.
            unborn_head = (
                args[-1:] == ("HEAD",)
                and bytes(completed.stdout).splitlines()[-1:] == [b"HEAD"]
                and isinstance(completed.stderr, (bytes, bytearray))
                and b"ambiguous argument 'HEAD'" in bytes(completed.stderr)
            )
            if not unborn_head:
                raise ValueError("git command failed")
        return bytes(completed.stdout)

    @staticmethod
    def _git_oid(raw: bytes) -> str:
        try:
            oid = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("invalid git object id") from exc
        if len(oid) not in {40, 64} or re.fullmatch(r"[0-9a-fA-F]+", oid) is None:
            raise ValueError("invalid git object id")
        return oid.lower()

    @staticmethod
    def _git_path(root: Path, raw: bytes) -> str:
        path = raw.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        if not path:
            raise ValueError("empty git path")
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = root / candidate
        return str(candidate.resolve(strict=False))

    @staticmethod
    def _git_relpath(raw: bytes) -> str:
        path = raw.decode("utf-8", errors="surrogateescape").replace("\\", "/")
        parts = path.split("/")
        if not path or path.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("invalid git relative path")
        return path

    @staticmethod
    def _git_nul_records(raw: bytes) -> list[bytes]:
        if not isinstance(raw, bytes):
            raise ValueError("git output is not bytes")
        if not raw:
            return []
        if not raw.endswith(b"\0"):
            raise ValueError("unterminated git output")
        return [record for record in raw.split(b"\0")[:-1]]

    @classmethod
    def _git_parse_index(cls, raw: bytes) -> dict[str, str | None]:
        entries: dict[str, list[tuple[int, str]]] = {}
        for record in cls._git_nul_records(raw):
            if b"\t" not in record:
                raise ValueError("malformed git index record")
            metadata, raw_path = record.split(b"\t", 1)
            fields = metadata.split(b" ")
            if len(fields) != 3 or re.fullmatch(rb"[0-7]{6}", fields[0]) is None:
                raise ValueError("malformed git index metadata")
            try:
                stage = int(fields[2])
            except ValueError as exc:
                raise ValueError("malformed git index stage") from exc
            if stage not in {0, 1, 2, 3}:
                raise ValueError("malformed git index stage")
            path = cls._git_relpath(raw_path)
            entries.setdefault(path, []).append((stage, cls._git_oid(fields[1])))
        result: dict[str, str | None] = {}
        for path, values in entries.items():
            stage_zero = [oid for stage, oid in values if stage == 0]
            result[path] = stage_zero[0] if len(values) == 1 and len(stage_zero) == 1 else None
        return result

    @classmethod
    def _git_parse_status(cls, raw: bytes) -> list[tuple[str, str, str, str, str | None]]:
        records = cls._git_nul_records(raw)
        parsed: list[tuple[str, str, str, str, str | None]] = []
        index = 0
        while index < len(records):
            record = records[index]
            if record.startswith(b"1 "):
                fields = record.split(b" ", 8)
                if len(fields) != 9 or len(fields[1]) != 2:
                    raise ValueError("malformed porcelain-v2 ordinary record")
                path = cls._git_relpath(fields[8])
                x, y = chr(fields[1][0]), chr(fields[1][1])
                parsed.append((path, x, y, cls._git_status_state(x, y), None))
            elif record.startswith(b"2 "):
                fields = record.split(b" ", 9)
                if len(fields) != 10 or len(fields[1]) != 2 or index + 1 >= len(records):
                    raise ValueError("malformed porcelain-v2 rename record")
                path = cls._git_relpath(fields[9])
                original = cls._git_relpath(records[index + 1])
                if fields[8][:1] not in {b"R", b"C"} or not fields[8][1:].isdigit():
                    raise ValueError("malformed porcelain-v2 rename score")
                x, y = chr(fields[1][0]), chr(fields[1][1])
                parsed.append((path, x, y, cls._git_status_state(x, y), original))
                index += 1
            elif record.startswith(b"u "):
                fields = record.split(b" ", 10)
                if len(fields) != 11 or len(fields[1]) != 2:
                    raise ValueError("malformed porcelain-v2 unmerged record")
                path = cls._git_relpath(fields[10])
                parsed.append((path, chr(fields[1][0]), chr(fields[1][1]), "unmerged", None))
            elif record.startswith(b"? "):
                parsed.append((cls._git_relpath(record[2:]), ".", ".", "untracked", None))
            elif record.startswith(b"! "):
                cls._git_relpath(record[2:])
            else:
                raise ValueError("malformed porcelain-v2 status record")
            index += 1
        return parsed

    @staticmethod
    def _git_status_state(x: str, y: str) -> str:
        if "U" in {x, y}:
            return "unmerged"
        if "D" in {x, y}:
            return "deleted"
        staged = x != "."
        modified = y != "."
        if staged and modified:
            return "staged_and_worktree_modified"
        if staged:
            return "staged"
        if modified:
            return "modified"
        return "clean"

    def _git_index_signature(self, base: Path, index_path: str) -> tuple[int, int, int, int, int, str] | None:
        try:
            stat = Path(index_path).stat()
        except OSError:
            return None

        completed = subprocess.run(
            ["git", "-C", str(base), "hash-object", "--", index_path],
            capture_output=True,
            timeout=self.git_files_timeout,
            check=False,
            **hidden_run_kwargs(),
        )
        if completed.returncode != 0 or not isinstance(completed.stdout, (bytes, bytearray)):
            raise ValueError("git index digest failed")
        digest = self._git_oid(bytes(completed.stdout).strip())
        return (
            int(stat.st_mtime_ns),
            int(stat.st_size),
            int(getattr(stat, "st_ctime_ns", 0)),
            int(getattr(stat, "st_dev", 0)),
            int(getattr(stat, "st_ino", 0)),
            digest,
        )

    @staticmethod
    def _git_index_cache_identity(signature: tuple[int, int, int, int, int, str] | None) -> tuple[int, str] | None:
        if signature is None:
            return None
        # `git status` may atomically replace the index file while preserving its
        # logical contents. Size + content digest stay stable across that rewrite.
        return (signature[1], signature[5])

    def git_snapshot(self, root: str) -> GitSnapshot:
        try:
            base = self._root(root)
        except ValueError:
            return self._git_empty_snapshot(str(root), "invalid repository root")
        worktree_root = str(base)
        key = worktree_root
        if shutil.which("git") is None:
            return self._git_empty_snapshot(worktree_root, "git unavailable")
        now = time.monotonic()
        with self._git_files_lock:
            if now < self._git_snapshot_slow_until.get(key, 0.0):
                self._git_stats["snapshot_degraded"] += 1
                return self._git_empty_snapshot(worktree_root, "git snapshot cooldown")
            cached_entry = self._git_snapshot_cache.get(key)
        try:
            identity_output = self._git_snapshot_run(base, "rev-parse", "--git-common-dir", "--git-dir", "--git-path", "index", "HEAD")
            identity_lines = identity_output.splitlines()
            if len(identity_lines) != 4 or any(not line for line in identity_lines[:3]):
                raise ValueError("malformed git identity output")
            common_dir = self._git_path(base, identity_lines[0])
            git_dir = self._git_path(base, identity_lines[1])
            index_path = self._git_path(base, identity_lines[2])
            unborn_head = identity_lines[3] == b"HEAD"
            head_oid = None if unborn_head else self._git_oid(identity_lines[3])

            status_output = self._git_snapshot_run(base, "status", "--porcelain=v2", "--untracked-files=all", "-z")
            status_entries = self._git_parse_status(status_output)
            staged_output = self._git_snapshot_run(base, "diff", "--cached", "--raw", "-z")
            status_identity = hashlib.sha256(status_output + b"\0" + staged_output).hexdigest()
            index_signature = self._git_index_signature(base, index_path)
            if cached_entry is not None:
                cached_at, cached = cached_entry
                same_identity = (
                    cached.common_dir == common_dir
                    and cached.worktree_root == worktree_root
                    and cached.git_dir == git_dir
                    and cached.index_path == index_path
                    and self._git_index_cache_identity(cached.index_signature) == self._git_index_cache_identity(index_signature)
                    and cached.head_oid == head_oid
                    and cached.status_identity == status_identity
                )
                if same_identity and (self.git_files_cache_ttl <= 0 or now - cached_at <= self.git_files_cache_ttl):
                    with self._git_files_lock:
                        self._git_stats["snapshot_hits"] += 1
                    return cached

            if unborn_head:
                tree_oid = None
            else:
                tree_output = self._git_snapshot_run(base, "rev-parse", "HEAD^{tree}")
                tree_lines = tree_output.splitlines()
                if len(tree_lines) != 1:
                    raise ValueError("malformed git tree output")
                tree_oid = self._git_oid(tree_lines[0])
            index_entries = self._git_parse_index(self._git_snapshot_run(base, "ls-files", "--stage", "-z"))
            status: dict[str, str] = {path: "clean" for path in index_entries}
            renames: dict[str, str] = {}
            deleted: set[str] = set()
            for path, _x, _y, state, original in status_entries:
                status[path] = state
                if state == "deleted":
                    deleted.add(path)
                if original is not None:
                    renames[path] = original
            blobs: dict[str, GitBlobRecord] = {}
            for path, oid in index_entries.items():
                state = status.get(path, "clean")
                identity = f"git:{oid}" if (state == "clean" or (unborn_head and state == "staged")) and oid is not None else None
                blobs[path] = GitBlobRecord(state=state, oid=oid, identity=identity)
            for path, state in status.items():
                if path not in blobs:
                    blobs[path] = GitBlobRecord(state=state)
            snapshot = GitSnapshot(
                common_dir=common_dir,
                worktree_root=worktree_root,
                git_dir=git_dir,
                index_path=index_path,
                index_signature=index_signature,
                head_oid=head_oid,
                tree_oid=tree_oid,
                status=MappingProxyType(dict(status)),
                blobs=MappingProxyType(dict(blobs)),
                deleted=tuple(sorted(deleted)),
                renames=MappingProxyType(dict(renames)),
                status_identity=status_identity,
            )
            with self._git_files_lock:
                self._git_snapshot_cache[key] = (now, snapshot)
                self._git_snapshot_slow_until.pop(key, None)
                self._git_stats["snapshot_misses"] += 1
                if len(self._git_snapshot_cache) > 64:
                    for old_key in list(self._git_snapshot_cache)[:-32]:
                        self._git_snapshot_cache.pop(old_key, None)
            return snapshot
        except (OSError, subprocess.TimeoutExpired, ValueError):
            with self._git_files_lock:
                self._git_stats["snapshot_degraded"] += 1
                self._git_snapshot_slow_until[key] = time.monotonic() + self.git_files_slow_cooldown
            return self._git_empty_snapshot(worktree_root, "bounded git snapshot failed")

    def git_blob_map(self, root: str) -> dict[str, str]:
        """Return ``git:<blob_oid>`` identities for clean tracked paths."""
        snapshot = self.git_snapshot(root)
        if snapshot.degraded:
            return {}
        return {
            path: record.identity
            for path, record in snapshot.blobs.items()
            if (record.state == "clean" or (snapshot.head_oid is None and record.state == "staged")) and record.identity is not None
        }

    def git_blob_hashes(self, root: str, paths: list[str]) -> dict[str, str]:
        """Return clean tracked Git blob IDs for selected paths."""
        normalized = [str(Path(path).as_posix()).lstrip("./") for path in paths]
        if not normalized:
            return {}
        result = self.git_blob_map(root)
        return {path: result[path] for path in normalized if path in result}

    def snapshot_stats(self) -> dict[str, Any]:
        with self._snapshot_lock:
            snapshot = {
                "entries": len(self._snapshots),
                "bytes": self._snapshot_bytes,
                "hits": self.snapshot_hits,
                "misses": self.snapshot_misses,
                "verified_rehashes": self.snapshot_verified_rehashes,
            }
        with self._git_files_lock:
            now = time.monotonic()
            snapshot["git_files"] = {
                **self._git_stats,
                "cached_roots": len(self._git_files_cache),
                "cooldown_roots": sum(1 for until in self._git_files_slow_until.values() if until > now),
                "grep_cooldown_roots": sum(1 for until in self._git_grep_slow_until.values() if until > now),
                "ripgrep_cooldown_roots": sum(1 for until in self._ripgrep_slow_until.values() if until > now),
                "snapshot_cached_roots": len(self._git_snapshot_cache),
                "snapshot_cooldown_roots": sum(1 for until in self._git_snapshot_slow_until.values() if until > now),
            }
        return snapshot

    _GENERIC_SEARCH_WORDS = frozenset({
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is", "it",
        "of", "on", "or", "the", "to", "with", "implement", "implementation", "implementing", "missing",
        "change", "changes", "fix", "fixing", "add", "added", "update", "updated", "make", "ensure", "support",
    })

    def search_terms(self, query: str) -> list[str]:
        """Return high-signal lexical anchors without flattening compounds."""
        raw = tokenize_query_terms(query, min_len=2, max_terms=32)
        compounds = [term.lower() for term in raw if any(char in term for char in ("-", ":", "/", ".", "_"))]
        compound_parts = {
            part
            for compound in compounds
            for part in re.split(r"[-:/. _]+", compound)
            if len(part) >= 3
        }
        terms: list[str] = []
        seen: set[str] = set()
        for term in raw:
            lowered = term.lower()
            if lowered in self._GENERIC_SEARCH_WORDS:
                continue
            if lowered in compound_parts and lowered not in compounds:
                continue
            if len(lowered) < 3 or lowered in seen:
                continue
            seen.add(lowered)
            terms.append(lowered)
            if len(terms) >= self.max_search_terms:
                break
        return terms

    def _terms(self, query: str) -> list[str]:
        return self.search_terms(query)

    def _git_grep_pathspecs(self) -> list[str]:
        includes = [f"*{extension}" for extension in sorted(self.extensions) if extension.startswith(".")]
        if not includes:
            includes = [":(top)**"]
        else:
            includes.extend(name for name in sorted(self.special_filenames) if "/" not in name and "\\" not in name)
        excludes = [f":(exclude){name}/**" for name in sorted(self.ignore_dirs) if name]
        return [*includes, *excludes]

    def _git_grep_command(self, base: Path, terms: list[str], max_matches: int) -> list[str]:
        cmd = [
            "git", "-C", str(base), "grep", "-n", "-I", "-i", "--no-color", "--full-name", "--untracked",
            "-m", str(max(1, min(8, self.max_snippets_per_file * 2))),
        ]
        for term in terms[: self.max_search_terms]:
            cmd.extend(["-e", term])
        cmd.extend(["--", *self._git_grep_pathspecs()])
        return cmd

    def _ripgrep_candidates(
        self, base: Path, terms: list[str], max_matches: int,
        *, candidate_paths: list[Path] | None = None,
    ) -> tuple[list[tuple[str, int]] | None, bool]:
        if not self._rg or not terms:
            return None, False
        cooldown_key = str(base)
        with self._git_files_lock:
            if time.monotonic() < self._ripgrep_slow_until.get(cooldown_key, 0.0):
                self._git_stats["ripgrep_cooldown_skips"] += 1
                return None, True
        out: list[tuple[str, int]] = []
        seen: set[tuple[str, int]] = set()
        batches: list[list[str] | None]
        if candidate_paths is None:
            batches = [None]
        else:
            if not candidate_paths:
                return [], False
            batches = []
            current: list[str] = []
            current_chars = 0
            fixed_chars = sum(len(term) + 4 for term in terms[:12]) + 256
            for path in candidate_paths:
                try:
                    relative = path.resolve(strict=False).relative_to(base).as_posix()
                except (OSError, RuntimeError, ValueError):
                    continue
                added_chars = len(relative) + 4
                if added_chars + fixed_chars > 20_000:
                    return None, True
                if current and (len(current) >= 192 or current_chars + added_chars + fixed_chars > 20_000):
                    batches.append(current)
                    current = []
                    current_chars = 0
                current.append(relative)
                current_chars += added_chars
            if current:
                batches.append(current)
            if not batches:
                return [], False

        deadline = time.monotonic() + self.ripgrep_timeout
        for batch in batches:
            cmd = [self._rg, "--json", "--ignore-case", "--max-count", str(max(2, self.max_snippets_per_file * 3))]
            for term in terms[:12]:
                cmd.extend(["-e", term])
            if batch is None:
                cmd.append(str(base))
            else:
                cmd.extend(["--", *batch])
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._git_files_lock:
                    self._git_stats["ripgrep_timeouts"] = min(1_000_000, self._git_stats["ripgrep_timeouts"] + 1)
                    self._ripgrep_slow_until[cooldown_key] = time.monotonic() + self.ripgrep_slow_cooldown
                return None, True
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=remaining, check=False,
                    encoding="utf-8", errors="replace",
                    cwd=str(base) if batch is not None else None, **hidden_run_kwargs(),
                )
            except subprocess.TimeoutExpired:
                with self._git_files_lock:
                    self._git_stats["ripgrep_timeouts"] = min(1_000_000, self._git_stats["ripgrep_timeouts"] + 1)
                    self._ripgrep_slow_until[cooldown_key] = time.monotonic() + self.ripgrep_slow_cooldown
                return None, True
            except Exception:
                return None, True
            # rg returns 1 when there are no matches; both 0/1 are successful searches.
            if proc.returncode not in {0, 1}:
                return None, True
            with self._git_files_lock:
                self._ripgrep_slow_until.pop(cooldown_key, None)
            for raw in proc.stdout.splitlines():
                try:
                    event = json.loads(raw)
                except Exception:
                    continue
                if event.get("type") != "match":
                    continue
                data = event.get("data", {})
                path_data = data.get("path", {}) if isinstance(data, dict) else {}
                path_text = path_data.get("text") if isinstance(path_data, dict) else None
                line_no = int(data.get("line_number", 0) or 0) if isinstance(data, dict) else 0
                if not path_text or line_no <= 0:
                    continue
                try:
                    raw_path = Path(str(path_text))
                    path = (base / raw_path).resolve(strict=False) if not raw_path.is_absolute() else raw_path.resolve(strict=False)
                    rel = str(path.relative_to(base)).replace("\\", "/")
                except Exception:
                    continue
                match_key = (rel, line_no)
                if match_key in seen:
                    continue
                seen.add(match_key)
                out.append(match_key)
                if len(out) >= max(1, int(max_matches)):
                    return out, False
        return out, False

    def _git_grep_candidates(self, base: Path, terms: list[str], max_matches: int) -> tuple[list[tuple[str, int]] | None, bool]:
        """Fast portable fallback when ripgrep is unavailable.

        `git grep` covers tracked files and is used only as a bounded accelerator. A
        successful zero-result probe is final for this accelerator path; preprocessed
        candidates and the normal file inventory cover untracked-file discovery.
        """
        if not self.use_git_grep or not terms or not (base / ".git").exists():
            return None, False
        key = str(base)
        with self._git_files_lock:
            if time.monotonic() < self._git_grep_slow_until.get(key, 0.0):
                self._git_stats["grep_cooldown_skips"] += 1
                return None, False
        cmd = self._git_grep_command(base, terms, max_matches)
        try:
            proc = popen_managed(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                **hidden_run_kwargs(text=True),
            )
        except OSError:
            return None, True

        def terminate_and_reap() -> None:
            terminate_tree(proc.pid, grace_seconds=1.0, process_handle=proc)
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass

        lines: Queue[tuple[str, str | None]] = Queue()

        def drain_stdout() -> None:
            try:
                if proc.stdout is not None:
                    for line in proc.stdout:
                        lines.put(("line", line))
            finally:
                lines.put(("eof", None))

        reader = threading.Thread(target=drain_stdout, name="git-grep-reader", daemon=True)
        reader.start()
        with self._git_files_lock:
            self._git_grep_slow_until.pop(key, None)
        out: list[tuple[str, int]] = []
        seen: set[tuple[str, int]] = set()
        capped = False
        deadline = time.monotonic() + self.git_grep_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                with self._git_files_lock:
                    self._git_stats["grep_timeouts"] += 1
                    self._git_grep_slow_until[key] = time.monotonic() + self.git_files_slow_cooldown
                terminate_and_reap()
                reader.join(timeout=1.0)
                if proc.stdout is not None:
                    proc.stdout.close()
                return None, True
            try:
                kind, raw = lines.get(timeout=min(0.2, remaining))
            except Empty:
                continue
            if kind == "eof":
                break
            if raw is None:
                continue
            parts = raw.split(":", 2)
            if len(parts) < 2:
                continue
            rel = parts[0].replace("\\", "/")
            try:
                line_no = int(parts[1])
                target = (base / rel).resolve(strict=False)
                target.relative_to(base)
            except Exception:
                continue
            match_key = (rel, line_no)
            if match_key in seen:
                continue
            seen.add(match_key); out.append(match_key)
            if len(out) >= max_matches:
                capped = True
                terminate_and_reap()
                break
        if proc.poll() is None:
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                terminate_and_reap()
        reader.join(timeout=1.0)
        if proc.stdout is not None:
            proc.stdout.close()
        if not capped and proc.returncode not in {0, 1}:
            return None, True
        return out, False

    @staticmethod
    def _project_settings_values(project_settings: Any | None) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], int | None]:
        if project_settings is None:
            return (), (), (), None
        text_extensions = tuple(
            str(value).casefold() for value in getattr(project_settings, "text_extensions", ())
            if isinstance(value, str)
        )
        binary_extensions = tuple(
            str(value).casefold() for value in getattr(project_settings, "binary_extensions", ())
            if isinstance(value, str)
        )
        forced = [
            str(value) for value in getattr(project_settings, "force_include_paths", ())
            if isinstance(value, str)
        ]
        overrides = getattr(project_settings, "path_overrides", {})
        if isinstance(overrides, Mapping):
            forced.extend(str(path) for path, action in tuple(overrides.items()) if action == "include")
        maximum = getattr(project_settings, "max_file_size_bytes", None)
        if isinstance(maximum, bool) or (maximum is not None and not isinstance(maximum, int)):
            maximum = 0
        return text_extensions, binary_extensions, tuple(forced), maximum

    @staticmethod
    def _project_path_matches(relative: str, patterns: tuple[str, ...]) -> bool:
        from .project_config import path_matches_pattern

        return any(path_matches_pattern(relative, pattern) for pattern in patterns)

    def _project_file_allowed(
        self, base: Path, path: Path, project_settings: Any, *, force_include: bool = False,
    ) -> bool:
        try:
            if path.is_symlink():
                return False
            lexical_relative = Path(os.path.abspath(path)).relative_to(base)
            current = base
            for part in lexical_relative.parts:
                current = current / part
                if current.is_symlink():
                    return False
            resolved = path.resolve(strict=True)
            resolved.relative_to(base)
            relative_path = resolved.relative_to(base)
            relative = relative_path.as_posix()
            if any(part.casefold() in _HARD_SEARCH_DIRS for part in relative_path.parts[:-1]):
                return False
            if is_root_archive_path(relative_path):
                return False
            if resolved.name in {".local-ai.toml", ".local-ai.worktree.toml"}:
                return False
            size_bytes = resolved.stat().st_size
            if size_bytes > self.max_file_bytes:
                return False
            _text, _binary, forced_patterns, _maximum = self._project_settings_values(project_settings)
            force_include = force_include or self._project_path_matches(relative, forced_patterns)
            soft_ignored = any(part.casefold() in self.ignore_dirs for part in relative_path.parts[:-1])
            if soft_ignored and not force_include:
                return False
            from .project_config import path_is_allowed

            if not path_is_allowed(
                base, resolved, project_settings, phase="search",
                soft_ignored=soft_ignored and not force_include, size_bytes=size_bytes,
            ):
                return False
            return self._path_extension_is_searchable(resolved, project_settings=project_settings)
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            return False

    def _expand_project_force_paths(
        self, base: Path, project_settings: Any, limit: int,
    ) -> list[Path]:
        _text, _binary, patterns, _maximum = self._project_settings_values(project_settings)
        found: dict[str, Path] = {}
        entry_budget = max(256, min(65_536, max(1, limit) * 32))
        deadline = time.monotonic() + min(2.0, self.git_files_timeout)
        entries_seen = 0
        for raw_pattern in patterns[:_MAX_PATH_CONTROLS]:
            pattern = raw_pattern.replace("\\", "/").strip()
            pure = PureWindowsPath(pattern)
            parts = tuple(part for part in pattern.split("/") if part not in {"", "."})
            if not parts or pure.is_absolute() or pure.drive or any(part == ".." for part in parts):
                continue
            stack: list[tuple[Path, int]] = [(base, 0)]
            visited: set[tuple[str, int]] = set()
            while stack and len(found) < limit and entries_seen < entry_budget and time.monotonic() < deadline:
                directory, index = stack.pop()
                try:
                    directory.resolve(strict=True).relative_to(base)
                    key = (str(directory), index)
                    if key in visited:
                        continue
                    visited.add(key)
                    if index >= len(parts):
                        if directory.is_file():
                            found[str(directory)] = directory
                        continue
                    segment = parts[index]
                    with os.scandir(directory) as scanner:
                        for entry in scanner:
                            entries_seen += 1
                            if entries_seen > entry_budget or time.monotonic() >= deadline:
                                break
                            if entry.is_symlink():
                                continue
                            child = Path(entry.path)
                            relative_parts = child.relative_to(base).parts
                            denied_parts = relative_parts if entry.is_dir(follow_symlinks=False) else relative_parts[:-1]
                            if any(part.casefold() in _HARD_SEARCH_DIRS for part in denied_parts):
                                continue
                            if entry.is_dir(follow_symlinks=False) and is_root_archive_path(child.relative_to(base)):
                                continue
                            if segment == "**":
                                stack.append((directory, index + 1))
                                if entry.is_dir(follow_symlinks=False):
                                    stack.append((child, index))
                                elif index == len(parts) - 1 and entry.is_file(follow_symlinks=False):
                                    found[str(child)] = child
                            elif fnmatch.fnmatchcase(entry.name, segment):
                                if index == len(parts) - 1 and entry.is_file(follow_symlinks=False):
                                    found[str(child)] = child
                                elif entry.is_dir(follow_symlinks=False):
                                    stack.append((child, index + 1))
                except (OSError, RuntimeError, ValueError):
                    continue
        return list(found.values())[:limit]

    def _iter_project_search_files(
        self, base: Path, project_settings: Any, max_depth: int,
        *, git_inventory: Any = _UNSET_GIT_INVENTORY,
    ) -> Iterable[Path]:
        limit = max(1, min(int(self.max_files), 100_000))
        _text, _binary, _forced, maximum = self._project_settings_values(project_settings)
        forced_paths = self._expand_project_force_paths(base, project_settings, limit)
        seen: set[str] = set()
        yielded = 0
        for path in forced_paths:
            key = str(path.resolve(strict=False))
            if key in seen or not self._project_file_allowed(base, path, project_settings, force_include=True):
                continue
            seen.add(key)
            yielded += 1
            yield path
            if yielded >= limit:
                return

        git_files = (
            self._git_files(base)
            if git_inventory is _UNSET_GIT_INVENTORY
            else git_inventory
        )
        if git_files is not None:
            candidates = git_files
        else:
            candidates = []
            entry_budget = max(256, min(65_536, limit * 16))
            entries_seen = 0
            try:
                for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
                    relative_dir = Path(dirpath).relative_to(base)
                    depth = len(relative_dir.parts)
                    dirnames[:] = [
                        name for name in dirnames
                        if name.casefold() not in _HARD_SEARCH_DIRS
                        and name.casefold() not in self.ignore_dirs
                        and depth < max_depth
                    ]
                    for name in filenames:
                        entries_seen += 1
                        if entries_seen > entry_budget:
                            break
                        candidates.append(Path(dirpath) / name)
                    if entries_seen > entry_budget:
                        break
            except (OSError, RuntimeError, ValueError):
                pass

        for path in candidates:
            if yielded >= limit:
                break
            try:
                relative_path = path.relative_to(base)
                _ = relative_path.as_posix()
            except ValueError:
                continue
            key = str(path.resolve(strict=False))
            if key in seen or any(part.casefold() in _HARD_SEARCH_DIRS for part in relative_path.parts[:-1]):
                continue
            if any(part.casefold() in self.ignore_dirs for part in relative_path.parts[:-1]):
                continue
            if not self._project_file_allowed(base, path, project_settings):
                continue
            seen.add(key)
            yielded += 1
            yield path

    def _read_search_snapshots(
        self, jobs: list[tuple[Any, Path]],
    ):
        """Read search files in order with bounded workers and queued snapshots."""
        if not jobs:
            return

        worker_count = min(4, len(jobs))
        pending_limit = min(8, worker_count * 2)

        def read(path: Path) -> tuple[str | None, list[str] | None, OSError | None]:
            try:
                stat = path.stat()
                if stat.st_size > self.max_file_bytes:
                    raise FileTooLargeError(f"{path} exceeds {self.max_file_bytes} bytes")
                file_hash, lines = self._read_snapshot(path, stat=stat)
                return file_hash, lines, None
            except OSError as exc:
                return None, None, exc

        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="repo-search-read") as pool:
            for offset in range(0, len(jobs), pending_limit):
                batch = jobs[offset:offset + pending_limit]
                for (metadata, _path), (file_hash, lines, error) in zip(
                    batch, pool.map(read, (path for _metadata, path in batch)),
                ):
                    yield metadata, file_hash, lines, error

    def _exact_search_page(
        self, base: Path, query: str, limit: int, offset: int,
        context_lines: int | None, project_settings: Any | None,
        git_inventory: Any, force_include_paths: list[str] | tuple[str, ...],
        path_priority: Callable[[str], tuple[int, int, int]] | None,
    ) -> dict[str, Any]:
        """Count every eligible result while retaining only the requested prefix."""
        terms = self._terms(query)
        phrase = query.strip().lower()
        if not terms and not phrase:
            return {
                "success": True, "root": str(base), "results": [], "terms": [],
                "matches_count": 0, "total_matches": 0, "has_more": False,
                "limit": limit, "offset": offset, "truncated": False,
                "count_exact": True, "engine": "python_exact",
            }

        snippet_lines = max(1, min(int(context_lines), 40)) if context_lines is not None else self.snippet_lines
        retain_count = offset + limit
        file_cap = max(1, min(int(self.max_files), MAX_EXACT_SEARCH_FILES))
        deadline = time.monotonic() + 60.0
        extension_check = getattr(self, "_path_extension_is_searchable", None)
        force_patterns = tuple(force_include_paths or ())

        def candidates() -> Iterable[Path]:
            if git_inventory is not _UNSET_GIT_INVENTORY and getattr(git_inventory, "complete", True) is False:
                raise _IncompleteGitInventory(
                    f"Git inventory is truncated at the {file_cap}-file exact-search bound"
                )

            if self.prefer_git and (base / ".git").exists():
                process = popen_managed(
                    ["git", "-C", str(base), "ls-files", "-co", "--exclude-standard", "-z"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    **hidden_run_kwargs(text=False),
                )
                timed_out = threading.Event()

                def stop_git() -> None:
                    if process.poll() is None:
                        timed_out.set()
                        try:
                            terminate_tree(process.pid, grace_seconds=0.1, process_handle=process)
                        except (OSError, ValueError):
                            pass

                timer = threading.Timer(self.git_files_timeout, stop_git)
                timer.daemon = True
                timer.start()
                pending = bytearray()
                previous_key: str | None = None
                try:
                    assert process.stdout is not None
                    while True:
                        chunk = process.stdout.read(64 * 1024)
                        if not chunk:
                            break
                        pending.extend(chunk)
                        while True:
                            separator = pending.find(0)
                            if separator < 0:
                                if len(pending) > 64 * 1024:
                                    raise OSError("Git path exceeded bounded stream buffer")
                                break
                            raw = bytes(pending[:separator])
                            del pending[:separator + 1]
                            if not raw:
                                continue
                            relative = raw.decode("utf-8", errors="surrogateescape").replace("\\", "/")
                            key = Path(relative).as_posix()
                            if key == previous_key:
                                continue
                            if previous_key is not None and key < previous_key:
                                raise _IncompleteGitInventory("Git emitted an unsorted exact-search inventory")
                            previous_key = key
                            yield base / relative
                    if pending:
                        relative = pending.decode("utf-8", errors="surrogateescape").replace("\\", "/")
                        key = Path(relative).as_posix()
                        if key != previous_key:
                            if previous_key is not None and key < previous_key:
                                raise _IncompleteGitInventory("Git emitted an unsorted exact-search inventory")
                            yield base / relative
                    return_code = process.wait()
                    if timed_out.is_set():
                        raise TimeoutError("exact Git inventory exceeded its configured time bound")
                    if return_code != 0:
                        raise OSError("Git exact-search inventory failed")
                finally:
                    timer.cancel()
                    if process.poll() is None:
                        terminate_tree(process.pid, grace_seconds=0.1, process_handle=process)
                        process.wait()
                return

            # Exact mode never consumes a materialized cache inventory: it can be
            # repository-sized even when the result page is small. Use the direct
            # Git stream above or a streaming filesystem walk below.
            def raise_walk_error(error: OSError) -> None:
                raise error

            for directory, dirnames, filenames in os.walk(
                base, followlinks=False, onerror=raise_walk_error,
            ):
                dirnames[:] = [
                    name for name in dirnames
                    if name.casefold() not in _HARD_SEARCH_DIRS
                ]
                for filename in filenames:
                    yield Path(directory) / filename

        class _WorstFirst:
            __slots__ = ("rank", "item")

            def __init__(self, item: dict[str, Any]) -> None:
                self.item = item
                priority = path_priority(str(item["path"])) if path_priority else (0, 0, 0)
                self.rank = (
                    *priority, -float(item["score"]),
                    str(item["path"]), int(item["start_line"]),
                )

            def __lt__(self, other: Any) -> bool:
                return self.rank > other.rank

        def retain(heap: list[Any], item: dict[str, Any], maximum: int) -> None:
            entry = _WorstFirst(item)
            if len(heap) < maximum:
                heapq.heappush(heap, entry)
            elif entry.rank < heap[0].rank:
                heapq.heapreplace(heap, entry)

        global_best: list[Any] = []
        total_matches = 0
        scanned = 0
        previous_relative_path: str | None = None
        try:
            for path in candidates():
                if time.monotonic() >= deadline:
                    raise TimeoutError("exact repository search exceeded 60 seconds")
                try:
                    if path.is_symlink():
                        continue
                    path = path.resolve(strict=True)
                    path.relative_to(base)
                    relative = path.relative_to(base)
                    rel = relative.as_posix()
                    forced = any(self._path_control_matches(rel, (pattern,)) for pattern in force_patterns)
                    if project_settings is None:
                        if self._is_ignored_relative_path(relative):
                            continue
                    elif not self._project_file_allowed(
                        base, path, project_settings,
                        force_include=forced,
                    ):
                        continue
                    if callable(extension_check) and not extension_check(
                        path, project_settings=project_settings,
                    ):
                        continue
                    # Built-in enumerators yield unique paths. Explicit sorted
                    # inventories can contain adjacent duplicates; collapse them
                    # with one path of state rather than a repository-sized set.
                    if rel == previous_relative_path:
                        continue
                    if not path.is_file():
                        continue
                    if path.stat().st_size > self.max_file_bytes:
                        continue
                    if scanned >= file_cap:
                        return {
                            "success": False, "root": str(base), "results": [],
                            "error": f"exact repository search exceeds the {file_cap}-file scan bound",
                            "status_code": 503, "terminal": True, "retryable": False,
                        }
                    scanned += 1
                    previous_relative_path = rel
                    file_hash, lines = self._read_snapshot(
                        path, max_bytes=self.max_file_bytes,
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    return {
                        "success": False, "root": str(base), "results": [],
                        "error": f"exact repository search could not enumerate/read an eligible file ({type(exc).__name__})",
                        "status_code": 503, "terminal": True, "retryable": False,
                    }

                path_lower = rel.lower()
                file_best: list[Any] = []
                current_bucket: int | None = None
                bucket_best: dict[str, Any] | None = None

                def finish_bucket() -> None:
                    nonlocal bucket_best
                    if bucket_best is not None:
                        retain(file_best, bucket_best, max(1, self.max_snippets_per_file))
                        bucket_best = None

                for idx, line in enumerate(lines):
                    if idx % 1024 == 0 and time.monotonic() >= deadline:
                        raise TimeoutError("exact repository search exceeded 60 seconds")
                    low = line.lower()
                    matched = [term for term in terms if term in low]
                    if not matched:
                        continue
                    score = float(
                        len(matched) * 3
                        + sum(1 for term in terms if term in path_lower) * 2
                        + sum(min(low.count(term), 3) * 0.5 for term in matched)
                    )
                    if phrase and len(phrase) <= 120 and phrase in low:
                        score += 8
                    start = max(0, idx - snippet_lines)
                    end = min(len(lines), idx + snippet_lines + 1)
                    hit = {
                        "path": rel, "start_line": start + 1, "end_line": end,
                        "score": round(score, 3),
                        "text": "\n".join(f"{n + 1}: {lines[n]}" for n in range(start, end)),
                        "file_sha256": file_hash,
                    }
                    bucket = hit["start_line"] // snippet_lines
                    if current_bucket is not None and bucket != current_bucket:
                        finish_bucket()
                    current_bucket = bucket
                    if bucket_best is None or _WorstFirst(hit).rank < _WorstFirst(bucket_best).rank:
                        bucket_best = hit
                finish_bucket()
                total_matches += len(file_best)
                for entry in file_best:
                    hit = entry.item
                    retain(global_best, {
                        key: hit[key]
                        for key in ("path", "start_line", "end_line", "score", "file_sha256")
                    }, retain_count)
        except TimeoutError as exc:
            return {
                "success": False, "root": str(base), "results": [],
                "error": str(exc), "status_code": 503,
                "terminal": True, "retryable": False,
            }
        except _IncompleteGitInventory as exc:
            return {
                "success": False, "root": str(base), "results": [],
                "error": str(exc), "status_code": 503,
                "terminal": True, "retryable": False,
            }
        except OSError as exc:
            return {
                "success": False, "root": str(base), "results": [],
                "error": f"exact repository search could not enumerate files ({type(exc).__name__})",
                "status_code": 503, "terminal": True, "retryable": False,
            }

        ranked = [entry.item for entry in sorted(global_best, key=lambda entry: entry.rank)]
        page_refs = ranked[offset:offset + limit]
        page_by_path: dict[str, list[dict[str, Any]]] = {}
        for reference in page_refs:
            page_by_path.setdefault(str(reference["path"]), []).append(reference)
        materialized: dict[tuple[str, int], dict[str, Any]] = {}
        for relative_path, references in page_by_path.items():
            target = base / relative_path
            try:
                target = target.resolve(strict=True)
                target.relative_to(base)
                digest, lines = self._read_snapshot(target, max_bytes=self.max_file_bytes)
            except (OSError, RuntimeError, ValueError) as exc:
                return {
                    "success": False, "root": str(base), "results": [],
                    "error": f"exact repository search could not materialize a page file ({type(exc).__name__})",
                    "status_code": 503, "terminal": True, "retryable": False,
                }
            if any(reference["file_sha256"] != digest for reference in references):
                return {
                    "success": False, "root": str(base), "results": [],
                    "error": "repository changed while exact search was materializing its page",
                    "status_code": 503, "terminal": True, "retryable": False,
                }
            for reference in references:
                start = max(0, int(reference["start_line"]) - 1)
                end = min(len(lines), int(reference["end_line"]))
                materialized[(relative_path, int(reference["start_line"]))] = {
                    **reference,
                    "text": "\n".join(f"{index + 1}: {lines[index]}" for index in range(start, end)),
                }
        page = [
            materialized[(str(reference["path"]), int(reference["start_line"]))]
            for reference in page_refs
        ]
        return {
            "success": True, "root": str(base), "scanned_files": scanned,
            "terms": terms, "results": page, "matches_count": total_matches,
            "total_matches": total_matches,
            "has_more": offset + len(page) < total_matches,
            "limit": limit, "offset": offset, "truncated": False,
            "count_exact": True, "engine": "python_exact",
        }

    def search(
        self, root: str, query: str, top_k: int = 12, context_lines: int | None = None,
        *, project_settings: Any | None = None,
        git_inventory: Any = _UNSET_GIT_INVENTORY,
        limit: int | None = None,
        offset: int = 0,
        exact_count: bool = False,
        force_include_paths: list[str] | tuple[str, ...] = (),
        path_priority: Callable[[str], tuple[int, int, int]] | None = None,
    ) -> dict[str, Any]:
        base = self._root(root)
        if exact_count:
            exact_limit = limit if limit is not None else top_k
            bounds_error = pagination_bounds_error(exact_limit, offset)
            if bounds_error:
                return {
                    "success": False, "root": str(base), "results": [],
                    "error": bounds_error, "status_code": 400,
                    "limit": exact_limit if isinstance(exact_limit, int) and not isinstance(exact_limit, bool) and 1 <= exact_limit <= MAX_PAGE_SIZE else None,
                    "offset": offset if isinstance(offset, int) and not isinstance(offset, bool) and 0 <= offset < MAX_PAGE_WINDOW else None,
                    "total_matches": 0, "has_more": False,
                }
            return self._exact_search_page(
                base, query, exact_limit, offset, context_lines,
                project_settings, git_inventory, force_include_paths,
                path_priority,
            )
        terms = self._terms(query)
        phrase = query.strip().lower()
        if not terms and not phrase:
            empty_limit = max(1, int(limit if limit is not None else top_k))
            return {
                "success": True, "root": str(base), "results": [],
                "matches_count": 0, "total_matches": 0, "has_more": False,
                "limit": empty_limit, "offset": max(0, int(offset)),
                "truncated": False, "count_exact": True,
            }
        result_limit = max(1, int(limit if limit is not None else top_k))
        offset = max(0, int(offset))
        effective_snippet_lines = max(1, min(int(context_lines), 40)) if context_lines is not None else self.snippet_lines
        hits: list[dict[str, Any]] = []
        scanned = 0
        python_fallback_scanned: int | None = None
        read_errors = 0
        truncation_reasons: list[str] = []
        # Keep enough globally ranked candidates for the requested page. The
        # multiplier remains the minimum working set for legacy top_k callers.
        candidate_limit = max(1, self.max_hits * 4, offset + result_limit)
        candidate_engine = "python"
        project_candidates = None
        if project_settings is not None:
            project_candidates = []
            for path in self._iter_project_search_files(
                base, project_settings, 25, git_inventory=git_inventory,
            ):
                if len(project_candidates) >= candidate_limit + 1:
                    break
                project_candidates.append(path)
        if project_candidates is None:
            candidates, accelerator_failed = self._ripgrep_candidates(
                base, terms, candidate_limit + 1,
            )
        else:
            candidates, accelerator_failed = self._ripgrep_candidates(
                base, terms, candidate_limit + 1, candidate_paths=project_candidates,
            )
        accelerated = candidates is not None
        if accelerated:
            candidate_engine = "ripgrep"
        else:
            git_grep_failed = False
            if project_settings is None:
                candidates, git_grep_failed = self._git_grep_candidates(base, terms, candidate_limit + 1)
            accelerator_failed = accelerator_failed or git_grep_failed
            accelerated = candidates is not None
            if accelerated:
                candidate_engine = "git-grep"
        if candidates is not None and len(candidates) > candidate_limit:
            truncation_reasons.append("result_limit")
            candidates = candidates[:candidate_limit]
        if candidates:
            per_path_lines: dict[str, list[int]] = {}
            for rel, line_no in candidates:
                per_path_lines.setdefault(rel, []).append(line_no)
            read_jobs: list[tuple[Any, Path]] = []
            for rel, line_numbers in per_path_lines.items():
                path = (base / rel).resolve(strict=False)
                try:
                    relative = path.relative_to(base)
                except ValueError:
                    continue
                if project_settings is None and self._is_ignored_relative_path(relative):
                    continue
                if project_settings is not None and not self._project_file_allowed(base, path, project_settings):
                    continue
                read_jobs.append(((rel, line_numbers), path))
            for (rel, line_numbers), file_hash, lines, error in self._read_search_snapshots(read_jobs):
                if error is not None:
                    read_errors += 1
                    continue
                scanned += 1
                path_lower = rel.lower()
                for line_no in line_numbers:
                    idx = line_no - 1
                    if idx < 0 or idx >= len(lines): continue
                    low = lines[idx].lower()
                    matched = [t for t in terms if t in low]
                    path_matches = sum(1 for t in terms if t in path_lower)
                    score = float(len(matched) * 3 + path_matches * 2 + sum(min(low.count(t), 3) * 0.5 for t in matched))
                    if phrase and len(phrase) <= 120 and phrase in low: score += 8
                    start = max(0, idx - effective_snippet_lines); end = min(len(lines), idx + effective_snippet_lines + 1)
                    snippet = "\n".join(f"{n + 1}: {lines[n]}" for n in range(start, end))
                    hits.append({"path": rel, "start_line": start + 1, "end_line": end, "score": round(score, 3), "text": snippet, "file_sha256": file_hash})
        # A timeout/error from both bounded accelerators must not trigger an
        # unbounded O(repository) Python scan. A valid accelerated zero result is
        # still final; Python remains the fallback only when no accelerator exists.
        if not accelerated and accelerator_failed:
            return {
                "success": False,
                "root": str(base),
                "terms": terms,
                "results": [],
                "engine": "bounded-accelerator-failure",
                "error": "bounded search accelerators timed out or failed",
                "retryable": True,
            }
        if not hits and not accelerated:
            python_fallback_scanned = 0
            with self._git_files_lock:
                self._git_stats["python_search_fallbacks"] = min(
                    1_000_000, self._git_stats["python_search_fallbacks"] + 1
                )
            fallback_paths = (
                project_candidates
                if project_candidates is not None
                else self.iter_files(str(base), max_files=self.python_fallback_max_files + 1)
            )
            fallback_jobs: list[tuple[str, Path]] = []
            for path in fallback_paths:
                if python_fallback_scanned >= self.python_fallback_max_files:
                    truncation_reasons.append("file_limit")
                    break
                scanned += 1
                python_fallback_scanned += 1
                rel = str(path.relative_to(base)).replace("\\", "/")
                fallback_jobs.append((rel, path))
            for rel, file_hash, lines, error in self._read_search_snapshots(fallback_jobs):
                path_lower = rel.lower()
                if error is not None:
                    read_errors += 1
                    continue
                for idx, line in enumerate(lines):
                    low = line.lower()
                    matched = [t for t in terms if t in low]
                    path_matches = sum(1 for t in terms if t in path_lower)
                    if not matched and not path_matches:
                        continue
                    score = float(len(matched) * 3 + path_matches * 2)
                    if phrase and len(phrase) <= 120 and phrase in low:
                        score += 8
                    score += sum(min(low.count(t), 3) * 0.5 for t in matched)
                    start = max(0, idx - self.snippet_lines)
                    end = min(len(lines), idx + self.snippet_lines + 1)
                    snippet = "\n".join(f"{n + 1}: {lines[n]}" for n in range(start, end))
                    hits.append({
                        "path": rel, "start_line": start + 1, "end_line": end,
                        "score": round(score, 3), "text": snippet, "file_sha256": file_hash,
                    })
                    if len(hits) > candidate_limit:
                        hits.pop()
                        if "result_limit" not in truncation_reasons:
                            truncation_reasons.append("result_limit")
                        break
                if "result_limit" in truncation_reasons:
                    break
        hits.sort(key=lambda x: (-x["score"], x["path"], x["start_line"]))
        dedup: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        per_file: Counter[str] = Counter()
        for hit in hits:
            key = (hit["path"], hit["start_line"] // max(1, self.snippet_lines))
            if key in seen or per_file[hit["path"]] >= self.max_snippets_per_file:
                continue
            seen.add(key)
            per_file[hit["path"]] += 1
            dedup.append(hit)
        total_matches = len(dedup)
        page_results = dedup[offset : offset + result_limit]
        has_more = offset + len(page_results) < total_matches
        if has_more and "result_limit" not in truncation_reasons:
            truncation_reasons.append("result_limit")
        candidate_pool = hits[: max(len(page_results), result_limit * 4)]
        candidate_tokens = sum(estimate_tokens(str(item.get("text", ""))) for item in candidate_pool)
        if read_errors:
            truncation_reasons.append("read_errors")
        result = {
            "success": True,
            "root": str(base),
            "scanned_files": scanned,
            "terms": terms,
            "results": page_results,
            "matches_count": total_matches,
            "total_matches": total_matches,
            "has_more": has_more,
            "engine": candidate_engine,
            "truncated": bool(truncation_reasons or read_errors or has_more),
            "truncation_reasons": truncation_reasons,
            "read_errors": read_errors,
        }
        if python_fallback_scanned is not None:
            result["python_fallback_files_scanned"] = python_fallback_scanned
            result["python_fallback_scanned_files"] = python_fallback_scanned
            result["python_fallback_file_limit"] = self.python_fallback_max_files
            result["python_fallback_limit"] = self.python_fallback_max_files
            result["python_fallback_truncated"] = "file_limit" in truncation_reasons
        if candidate_tokens:
            # Diagnostic only. Local RG-like filtering is not proof that a cloud
            # agent would otherwise have paid for the candidate snippets.
            result["candidate_context_tokens_est"] = candidate_tokens
        return result

    def repo_map(self, root: str, max_symbols: int = 120, paths: Iterable[str] | None = None) -> dict[str, Any]:
        base = self._root(root)
        extensions: Counter[str] = Counter()
        top_dirs: Counter[str] = Counter()
        symbols: list[dict[str, Any]] = []
        files = 0
        if paths is None:
            candidates: Iterable[Path] = self.iter_files(str(base))
        else:
            bounded: list[Path] = []
            for raw in paths:
                candidate = (base / str(raw)).resolve(strict=False)
                try:
                    candidate.relative_to(base)
                except ValueError:
                    continue
                bounded.append(candidate)
            candidates = bounded
        for path in candidates:
            if not path.is_file():
                continue
            if self.extensions and path.suffix.lower() not in self.extensions and path.name.lower() not in self.special_filenames:
                continue
            try:
                if path.stat().st_size > self.max_file_bytes:
                    continue
            except OSError:
                continue
            files += 1
            rel = str(path.relative_to(base)).replace("\\", "/")
            extensions[path.suffix.lower() or "<none>"] += 1
            top_dirs[rel.split("/", 1)[0]] += 1
            if len(symbols) >= max_symbols:
                continue
            try:
                _hash, lines = self._read_snapshot(path)
            except Exception:
                continue
            for line_no, line in enumerate(lines, 1):
                for pattern in _SYMBOL_PATTERNS:
                    match = pattern.match(line)
                    if match:
                        symbols.append({"name": match.group(1), "path": rel, "line": line_no})
                        break
                if len(symbols) >= max_symbols:
                    break
        return {
            "success": True, "root": str(base), "files": files,
            "extensions": extensions.most_common(20), "top_paths": top_dirs.most_common(30),
            "symbols_sample": symbols,
        }

    def project_profile(self, root: str) -> dict[str, Any]:
        """Detect project languages, manifests and likely validation commands without an LLM.

        Only small manifest/config files are read. Validation commands are suggestions;
        this method never executes project code.
        """
        base = self._root(root)
        language_by_ext = {
            ".py": "Python", ".php": "PHP", ".js": "JavaScript", ".jsx": "JavaScript",
            ".ts": "TypeScript", ".tsx": "TypeScript", ".cs": "C#", ".java": "Java",
            ".go": "Go", ".rs": "Rust", ".cpp": "C++", ".cc": "C++", ".cxx": "C++",
            ".c": "C", ".rb": "Ruby", ".kt": "Kotlin", ".swift": "Swift", ".scala": "Scala",
            ".dart": "Dart", ".ex": "Elixir", ".exs": "Elixir",
        }
        manifest_names = {
            "package.json", "pyproject.toml", "requirements.txt", "pipfile", "pipfile.lock", "poetry.lock", "uv.lock",
            "composer.json", "composer.lock", "cargo.toml", "cargo.lock", "go.mod", "go.sum",
            "pom.xml", "build.gradle", "build.gradle.kts", "gradlew", "gradlew.bat", "makefile",
            "cmakelists.txt", "gemfile", "gemfile.lock", "mix.exs", "pubspec.yaml", "deno.json", "deno.jsonc",
            "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb",
        }
        project_suffixes = {".sln", ".csproj", ".fsproj", ".vbproj"}
        raw_files = self._git_files(base)
        if raw_files is None:
            raw_files = []
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if d.lower() not in self.ignore_dirs]
                for name in filenames:
                    p = Path(dirpath) / name
                    ext = p.suffix.lower()
                    if ext not in language_by_ext and name.lower() not in manifest_names and ext not in project_suffixes:
                        continue
                    raw_files.append(p)
                    if len(raw_files) >= self.max_files:
                        break
                if len(raw_files) >= self.max_files:
                    break
        raw_files = raw_files[:self.max_files]
        languages: Counter[str] = Counter()
        manifests: list[str] = []
        by_name: dict[str, list[Path]] = {}
        basenames: set[str] = set()

        for path in raw_files:
            try:
                rel = str(path.resolve(strict=False).relative_to(base)).replace("\\", "/")
            except ValueError:
                continue
            ext = path.suffix.lower()
            language = language_by_ext.get(ext)
            if language:
                languages[language] += 1
            name = path.name.lower()
            basenames.add(name)
            by_name.setdefault(name, []).append(path)
            if name in manifest_names or ext in project_suffixes:
                manifests.append(rel)

        tools: set[str] = set()
        commands: list[dict[str, str]] = []

        def add_command(command: str, purpose: str, confidence: str = "high") -> None:
            if not any(x["command"] == command for x in commands):
                commands.append({"command": command, "purpose": purpose, "confidence": confidence})

        package_files = by_name.get("package.json", [])[:20]
        if package_files:
            tools.add("node")
            package_manager = "npm"
            if "pnpm-lock.yaml" in basenames:
                package_manager = "pnpm"
            elif "yarn.lock" in basenames:
                package_manager = "yarn"
            elif "bun.lock" in basenames or "bun.lockb" in basenames:
                package_manager = "bun"
            tools.add(package_manager)
            import json
            for package_file in package_files:
                try:
                    if package_file.stat().st_size > 1_000_000:
                        continue
                    data = json.loads(package_file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
                if isinstance(scripts, dict):
                    for script, purpose in [("test", "tests"), ("lint", "lint"), ("typecheck", "type-check"), ("check", "checks"), ("build", "build")]:
                        if script in scripts:
                            add_command(f"{package_manager} run {script}", purpose)
                deps: dict[str, Any] = {}
                for section in ("dependencies", "devDependencies"):
                    value = data.get(section, {}) if isinstance(data, dict) else {}
                    if isinstance(value, dict):
                        deps.update(value)
                for dep, label in [("typescript", "typescript"), ("eslint", "eslint"), ("vitest", "vitest"), ("jest", "jest"), ("next", "nextjs"), ("vite", "vite")]:
                    if dep in deps:
                        tools.add(label)

        pyproject_files = by_name.get("pyproject.toml", [])[:20]
        requirements_files = by_name.get("requirements.txt", [])[:20]
        if pyproject_files or requirements_files or languages.get("Python"):
            tools.add("python")
            all_py_parts: list[str] = []
            for file in [*pyproject_files, *requirements_files]:
                try:
                    if file.stat().st_size <= 1_000_000:
                        all_py_parts.append(file.read_text(encoding="utf-8", errors="replace").lower())
                except Exception:
                    pass
            all_py = "\n".join(all_py_parts)
            if "pytest" in all_py:
                tools.add("pytest"); add_command("python -m pytest", "tests")
            if "ruff" in all_py:
                tools.add("ruff"); add_command("ruff check .", "lint")
            if "mypy" in all_py:
                tools.add("mypy"); add_command("mypy .", "type-check", "medium")
            if "pyright" in all_py:
                tools.add("pyright"); add_command("pyright", "type-check", "medium")

        composer_files = by_name.get("composer.json", [])[:20]
        if composer_files or languages.get("PHP"):
            tools.add("php")
            import json
            for composer in composer_files:
                try:
                    if composer.stat().st_size > 1_000_000:
                        continue
                    data = json.loads(composer.read_text(encoding="utf-8"))
                except Exception:
                    continue
                scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
                if isinstance(scripts, dict):
                    for script, purpose in [("test", "tests"), ("phpunit", "tests"), ("phpstan", "static-analysis"), ("cs", "style/checks"), ("check", "checks")]:
                        if script in scripts:
                            add_command(f"composer {script}", purpose)
                reqs: dict[str, Any] = {}
                for section in ("require", "require-dev"):
                    value = data.get(section, {}) if isinstance(data, dict) else {}
                    if isinstance(value, dict):
                        reqs.update(value)
                for dep, label in [("phpunit/phpunit", "phpunit"), ("phpstan/phpstan", "phpstan"), ("cakephp/cakephp", "cakephp"), ("laravel/framework", "laravel"), ("symfony/framework-bundle", "symfony")]:
                    if dep in reqs:
                        tools.add(label)

        if "cargo.toml" in basenames or languages.get("Rust"):
            tools.update({"rust", "cargo"}); add_command("cargo test", "tests"); add_command("cargo check", "type/build-check")
        if "go.mod" in basenames or languages.get("Go"):
            tools.add("go"); add_command("go test ./...", "tests")
        if any(Path(x).suffix.lower() in project_suffixes for x in manifests) or languages.get("C#"):
            tools.add("dotnet"); add_command("dotnet test", "tests", "medium"); add_command("dotnet build --no-restore", "build", "medium")
        if "pom.xml" in basenames:
            tools.add("maven"); add_command("mvn test", "tests")
        if "build.gradle" in basenames or "build.gradle.kts" in basenames:
            tools.add("gradle")
            gradle_cmd = ".\\gradlew.bat test" if os.name == "nt" and "gradlew.bat" in basenames else "./gradlew test" if "gradlew" in basenames else "gradle test"
            add_command(gradle_cmd, "tests")
        if "makefile" in basenames:
            tools.add("make")

        ci: list[str] = []
        for candidate in [".github/workflows", ".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile"]:
            if (base / candidate).exists():
                ci.append(candidate)

        manifests = sorted(set(manifests), key=lambda x: (x.count("/"), x.lower()))[:80]
        return {
            "success": True,
            "root": str(base),
            "scanned_paths": len(raw_files),
            "languages": [{"name": name, "files": count} for name, count in languages.most_common(12)],
            "manifests": manifests,
            "tools": sorted(tools),
            "validation_commands": commands[:24],
            "ci": ci,
            "note": "Validation commands are detected/suggested only; Local AI Hub does not execute project code.",
        }


    def verify_evidence(self, root: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        base = self._root(root)
        checked: list[dict[str, Any]] = []
        stale = 0
        for item in evidence[:200]:
            rel = str(item.get("path", ""))
            expected = str(item.get("file_sha256", ""))
            candidate = (base / rel).resolve(strict=False)
            try:
                candidate.relative_to(base)
            except ValueError:
                checked.append({"path": rel, "status": "invalid-path"}); stale += 1; continue
            if not candidate.is_file():
                checked.append({"path": rel, "status": "missing"}); stale += 1; continue
            actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
            status = "current" if expected and actual == expected else "stale"
            if status != "current":
                stale += 1
            checked.append({"path": rel, "status": status, "expected_sha256": expected or None, "actual_sha256": actual})
        return {"success": True, "root": str(base), "stale": stale > 0, "stale_count": stale, "checked": checked}

    def git_diff(self, root: str, base: str = "HEAD", staged: bool = False, max_tokens: int = 10000) -> dict[str, Any]:
        repo = self._root(root)
        try:
            probe = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True,
                timeout=3, check=False, encoding="utf-8", errors="replace", **hidden_run_kwargs(),
            )
        except Exception as exc:
            return {"success": False, "error": str(exc), "terminal": True, "retryable": False}
        if probe.returncode != 0 or probe.stdout.strip().lower() != "true":
            return {"success": False, "error": "git diff requires a Git repository", "terminal": True, "retryable": False}
        cmd = ["git", "-C", str(repo), "diff", "--no-ext-diff", "--unified=3"]
        if staged:
            cmd.append("--cached")
        elif base:
            cmd.append(base)
        budget_chars = max(1, chars_for_tokens(max_tokens))
        def bounded_process(command: list[str], retain_limit: int, on_stdout_chunk: Any = None, digest_output: bool = False) -> dict[str, Any]:
            retained = bytearray()
            stderr_retained = bytearray()
            digest = hashlib.sha256() if digest_output else None
            total = 0
            stream_errors: list[str] = []

            def drain(stream: Any, output: bytearray, digest_value: Any = None, stream_name: str = "stdout") -> None:
                nonlocal total
                try:
                    while True:
                        chunk = stream.read(65536)
                        if not chunk:
                            return
                        if digest_value is not None:
                            digest_value.update(chunk)
                            total += len(chunk)
                        if on_stdout_chunk is not None and output is retained:
                            try:
                                on_stdout_chunk(chunk)
                            except Exception:
                                pass
                        remaining = max(0, retain_limit - len(output))
                        if remaining:
                            output.extend(chunk[:remaining])
                except Exception as exc:
                    if len(stream_errors) < 2:
                        detail = str(exc).replace("\r", " ").replace("\n", " ")[:200]
                        stream_errors.append(f"{stream_name}: {type(exc).__name__}: {detail}")
                    return

            process = None
            try:
                process = popen_managed(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **hidden_run_kwargs())
                stdout_thread = threading.Thread(target=drain, args=(process.stdout, retained, digest, "stdout"), daemon=True)
                stderr_thread = threading.Thread(target=drain, args=(process.stderr, stderr_retained, None, "stderr"), daemon=True)
                stdout_thread.start()
                stderr_thread.start()
                try:
                    returncode = process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    stdout_thread.join(timeout=5)
                    stderr_thread.join(timeout=5)
                    return {"returncode": None, "error": "git diff timed out", "retryable": True}
                stdout_thread.join(timeout=5)
                stderr_thread.join(timeout=5)
                if stdout_thread.is_alive() or stderr_thread.is_alive():
                    stream_errors.append("reader thread did not drain before timeout")
                if stream_errors:
                    return {
                        "returncode": None,
                        "error": "git diff stream read failed: " + "; ".join(stream_errors[:2]),
                        "retryable": True,
                    }
                return {
                    "returncode": returncode,
                    "stdout": bytes(retained),
                    "stderr": bytes(stderr_retained),
                    "total": total,
                    "sha256": digest.hexdigest() if digest is not None else "",
                }
            except Exception as exc:
                return {"returncode": None, "error": str(exc), "retryable": True}
            finally:
                if process is not None:
                    for stream in (process.stdout, process.stderr):
                        try:
                            stream.close()
                        except Exception:
                            pass

        content_result = bounded_process(cmd, budget_chars, digest_output=True)
        if content_result.get("returncode") is None:
            return {"success": False, "error": content_result.get("error", "git diff failed"), "retryable": content_result.get("retryable", False)}
        stderr_text = bytes(content_result.get("stderr", b"")).decode("utf-8", errors="replace").strip()
        if content_result["returncode"] != 0:
            return {"success": False, "error": stderr_text or "git diff failed"}
        stdout_retained = bytes(content_result.get("stdout", b""))
        stdout_total = int(content_result.get("total", len(stdout_retained)))
        text = stdout_retained.decode("utf-8", errors="replace")
        truncated = stdout_total > len(stdout_retained) or len(text) > budget_chars
        if len(text) > budget_chars:
            text = text[:budget_chars]
            truncated = True
        if truncated:
            text += "\n\n[... additional diff sections omitted to fit local review budget ...]\n"
        changed: list[str] = []
        retained_stdout = stdout_retained.decode("utf-8", errors="replace")
        for line in retained_stdout.splitlines():
            if not line.startswith("diff --git a/"):
                continue
            match = re.match(r"diff --git a/(.+?) b/(.+)$", line)
            if match:
                changed.append(match.group(2))
        path_names: list[str] = []
        path_pending = bytearray()
        path_capture_error = ""

        def collect_path_chunk(chunk: bytes) -> None:
            nonlocal path_capture_error
            if path_capture_error:
                return
            if len(path_names) >= 4096:
                path_capture_error = "path count cap reached"
                return
            data = bytes(path_pending) + chunk
            pieces = data.split(b"\0")
            tail = pieces.pop()
            if len(tail) > 4096:
                path_capture_error = "path byte cap reached"
                return
            path_pending.clear()
            path_pending.extend(tail)
            for piece in pieces:
                if not piece:
                    continue
                if len(piece) > 4096:
                    path_capture_error = "path byte cap reached"
                    return
                if len(path_names) >= 4096:
                    path_capture_error = "path count cap reached"
                    return
                path_names.append(piece.decode("utf-8", errors="replace"))

        path_cmd = ["git", "-C", str(repo), "diff", "--no-ext-diff", "--name-only", "-z"]
        if staged:
            path_cmd.append("--cached")
        elif base:
            path_cmd.append(base)
        path_result = bounded_process(path_cmd, 0, on_stdout_chunk=collect_path_chunk)
        if path_capture_error:
            return {
                "success": False,
                "error": f"git diff path capture failed: {path_capture_error}",
                "terminal": False,
                "retryable": True,
                "paths_complete": False,
            }
        if path_result.get("returncode") is None or path_result.get("returncode") != 0:
            path_error = bytes(path_result.get("stderr", b"")).decode("utf-8", errors="replace").strip()
            return {
                "success": False,
                "error": f"git diff path capture failed: {path_error or path_result.get('error', 'non-zero exit')}",
                "terminal": False,
                "retryable": bool(path_result.get("retryable", True)),
                "paths_complete": False,
            }
        if path_pending and len(path_names) < 4096:
            path_names.append(bytes(path_pending)[:4096].decode("utf-8", errors="replace"))
        snapshot = self.git_snapshot(str(repo))
        changed_files = list(dict.fromkeys(path_names + changed))
        changed_paths = list(dict.fromkeys(changed_files + list(snapshot.changed_paths)))
        return {
            "success": True, "root": str(repo), "diff": text, "changed_files": changed_files,
            "changed_paths": changed_paths, "revision": snapshot.revision,
            "repository_revision": snapshot.repository_revision,
            "estimated_tokens": estimate_tokens(text),
            "original_estimated_tokens": max(estimate_tokens(text), (stdout_total + 3) // 4),
            "truncated": truncated, "diff_sha256": content_result["sha256"],
            "paths_complete": True,
        }


    def impact_analysis(
        self,
        root: str,
        base: str = "HEAD",
        staged: bool = False,
        max_symbols: int = 48,
        max_dependents: int = 30,
    ) -> dict[str, Any]:
        """Cheap generic change-impact/test targeting without invoking an LLM.

        This is deliberately heuristic. Serena remains the preferred source
        for exact symbol relationships; this fallback is available everywhere and is
        useful before spending cloud context.
        """
        repo = self._root(root)
        diff = self.git_diff(str(repo), base=base, staged=staged, max_tokens=2500)
        if not diff.get("success"):
            return diff
        changed_files = [str(x) for x in diff.get("changed_files", [])]
        if not changed_files:
            return {
                "success": True, "root": str(repo), "changed_files": [],
                "changed_symbols": [], "likely_dependents": [], "suggested_tests": [],
                "risk": {"score": 0, "level": "low", "reasons": ["no changed files"]},
            }

        changed_symbols: list[dict[str, Any]] = []
        changed_set = set(changed_files)
        for rel in changed_files:
            path = (repo / rel).resolve(strict=False)
            try:
                path.relative_to(repo)
            except ValueError:
                continue
            if not path.is_file() or len(changed_symbols) >= max_symbols:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for line_no, line in enumerate(lines, 1):
                for pattern in _SYMBOL_PATTERNS:
                    match = pattern.match(line)
                    if match:
                        name = match.group(1)
                        if len(name) >= 3 and not any(x["name"] == name for x in changed_symbols):
                            changed_symbols.append({"name": name, "path": rel, "line": line_no})
                        break
                if len(changed_symbols) >= max_symbols:
                    break

        symbol_names = [x["name"] for x in changed_symbols]
        dependents: list[dict[str, Any]] = []
        test_candidates: list[dict[str, Any]] = []
        changed_stems = {Path(x).stem.lower().replace("test_", "").replace("_test", "") for x in changed_files}

        # Local AI deterministic fast path: let ripgrep reduce the dependent candidate
        # set before opening files. Exact counts are still verified against our own
        # decoded snapshots, so rg is only an accelerator and never a source of truth.
        dependent_candidates: set[str] | None = None
        if self._rg and symbol_names:
            cmd = [self._rg, "--files-with-matches", "--fixed-strings"]
            for name in symbol_names[:32]:
                cmd.extend(["-e", name])
            cmd.append(str(repo))
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.ripgrep_timeout, check=False, encoding="utf-8", errors="replace", **hidden_run_kwargs())
                if proc.returncode in {0, 1}:
                    dependent_candidates = set()
                    for raw in proc.stdout.splitlines():
                        try:
                            rel = str(Path(raw).resolve(strict=False).relative_to(repo)).replace("\\", "/")
                        except Exception:
                            continue
                        dependent_candidates.add(rel)
            except Exception:
                dependent_candidates = None

        for path in self.iter_files(str(repo)):
            rel = str(path.relative_to(repo)).replace("\\", "/")
            low_rel = rel.lower()
            is_test = (
                "/test" in f"/{low_rel}" or "/spec" in f"/{low_rel}"
                or Path(low_rel).name.startswith("test_")
                or any(marker in Path(low_rel).stem for marker in ("_test", ".test", "_spec", ".spec"))
            )
            stem = Path(low_rel).stem.lower().replace("test_", "").replace("_test", "").replace(".test", "").replace("_spec", "").replace(".spec", "")
            if is_test:
                score = sum(3 for changed in changed_stems if changed and (changed in stem or stem in changed))
                score += sum(1 for name in symbol_names[:20] if name.lower() in low_rel)
                if score:
                    test_candidates.append({"path": rel, "score": score})
            if rel in changed_set or not symbol_names:
                continue
            if dependent_candidates is not None and rel not in dependent_candidates:
                continue
            try:
                _digest, snapshot_lines = self._read_snapshot(path)
                text = "\n".join(snapshot_lines)
            except Exception:
                continue
            matched = []
            mentions = 0
            for name in symbol_names:
                count = text.count(name)
                if count:
                    matched.append(name)
                    mentions += min(count, 8)
            if matched:
                dependents.append({"path": rel, "symbols": matched[:8], "mentions": mentions})

        dependents.sort(key=lambda x: (-x["mentions"], x["path"]))
        test_candidates.sort(key=lambda x: (-x["score"], x["path"]))
        dependents = dependents[:max(1, int(max_dependents))]
        suggested_tests = test_candidates[:20]

        score = 0
        reasons: list[str] = []
        if len(changed_files) >= 6:
            score += 2; reasons.append("multi-file change")
        if len(changed_files) >= 15:
            score += 2; reasons.append("large change surface")
        risky_terms = {"auth", "security", "migration", "schema", "database", "transaction", "concurrency", "thread", "lock", "payment", "permission", "crypto"}
        if any(any(term in rel.lower() for term in risky_terms) for rel in changed_files):
            score += 2; reasons.append("sensitive subsystem path")
        if len(dependents) >= 10:
            score += 1; reasons.append("many likely dependents")
        if not suggested_tests and any(Path(x).suffix.lower() in self.extensions for x in changed_files):
            score += 1; reasons.append("no likely tests found")
        if diff.get("truncated"):
            score += 1; reasons.append("diff exceeded local impact budget")
        level = "high" if score >= 5 else "medium" if score >= 2 else "low"
        if not reasons:
            reasons.append("small localized change")

        return {
            "success": True, "root": str(repo), "changed_files": changed_files,
            "changed_symbols": changed_symbols, "likely_dependents": dependents,
            "suggested_tests": suggested_tests,
            "risk": {"score": score, "level": level, "reasons": reasons},
            "diff_sha256": diff.get("diff_sha256"),
            "note": "Heuristic fallback; use Serena for exact symbol relationships when available.",
        }



    @staticmethod
    def _path_control_matches(path: str, prefixes: tuple[str, ...]) -> bool:
        normalized = path.replace("\\", "/").strip("/").casefold()
        basename = normalized.rsplit("/", 1)[-1]
        for prefix in prefixes:
            pattern = prefix.replace("\\", "/").strip("/").casefold()
            if not pattern:
                continue
            if any(char in pattern for char in "*?["):
                if fnmatch.fnmatchcase(normalized, pattern) or fnmatch.fnmatchcase(basename, pattern):
                    return True
            elif normalized == pattern or normalized.startswith(pattern + "/"):
                return True
        return False

    def _validated_context_path(
        self, base: Path, value: Any, field: str, *, reject_symlink: bool = True
    ) -> tuple[str, Path]:
        if not isinstance(value, str):
            raise ValueError(f"{field} paths must be strings")
        raw = value.strip().replace("\\", "/")
        windows_path = PureWindowsPath(value.strip())
        project_rooted = raw.startswith("/") and not raw.startswith("//")
        if project_rooted:
            raw = raw[1:]
        if (
            not raw or len(raw) > 240 or not raw.isprintable() or raw.startswith("/")
            or (windows_path.is_absolute() and not project_rooted) or windows_path.drive
            or any(part == ".." for part in raw.split("/"))
        ):
            raise ValueError(f"{field} paths must be repository-relative")
        parts = [part for part in raw.split("/") if part not in {"", "."}]
        if not parts:
            raise ValueError(f"{field} paths must name a repository path")
        relative = "/".join(parts)
        candidate = base.joinpath(*parts)
        if reject_symlink:
            current = base
            for part in parts:
                current = current / part
                if current.is_symlink():
                    raise ValueError(f"{field} paths cannot traverse symlinks")
        try:
            candidate.resolve(strict=False).relative_to(base)
        except (OSError, ValueError) as exc:
            raise ValueError(f"{field} paths must remain inside the repository root") from exc
        return relative, candidate

    def _path_extension_is_searchable(
        self, path: str | os.PathLike[str], *, project_settings: Any | None = None,
    ) -> bool:
        candidate = Path(path)
        name = candidate.name.casefold()
        if name in {".local-ai.toml", ".local-ai.worktree.toml"}:
            return False
        suffix = candidate.suffix.casefold()
        text_extensions, binary_extensions, _forced, _maximum = self._project_settings_values(project_settings)
        if suffix in self.ignore_extensions or any(name.endswith(item) for item in binary_extensions):
            return False
        if any(name.endswith(item) for item in text_extensions):
            return True
        return not (
            self.extensions
            and suffix not in self.extensions
            and name not in self.special_filenames
        )

    def _searchable_context_file(
        self, base: Path, path: Path, *, force_include: bool = False,
        project_settings: Any | None = None,
    ) -> bool:
        try:
            relative = path.relative_to(base)
            parent_parts = tuple(part.casefold() for part in relative.parts[:-1])
            _text, _binary, forced_patterns, _maximum = self._project_settings_values(project_settings)
            policy_forced = self._project_path_matches(relative.as_posix(), forced_patterns)
            if path.is_symlink() or any(part in _HARD_SEARCH_DIRS for part in parent_parts) or (
                not (force_include or policy_forced)
                and any(part in self.ignore_dirs for part in parent_parts)
            ):
                return False
            if not self._path_extension_is_searchable(path, project_settings=project_settings):
                return False
            if not path.is_file():
                return False
            size_bytes = path.stat().st_size
            if size_bytes > self.max_file_bytes:
                return False
            if project_settings is not None and not self._project_file_allowed(
                base, path, project_settings, force_include=force_include,
            ):
                return False
            return True
        except (OSError, ValueError):
            return False

    def _expand_context_directory(
        self, base: Path, relative: str, directory: Path, limit: int,
        *, project_settings: Any | None = None,
    ) -> list[tuple[str, Path]]:
        """Enumerate only one explicitly hinted directory, with bounded Git ignores."""
        if limit <= 0:
            return []
        collected: list[tuple[str, Path]] = []
        try:
            completed = subprocess.run(
                ["git", "-C", str(base), "ls-files", "-co", "--exclude-standard", "-z", "--", relative],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=self.git_files_timeout,
                check=False, **hidden_run_kwargs(),
            )
            if completed.returncode == 0:
                listed = sorted({raw.decode("utf-8", errors="surrogateescape").replace("\\", "/")
                                 for raw in completed.stdout.split(b"\0") if raw})
                for item in listed:
                    if not (item == relative or item.startswith(relative.rstrip("/") + "/")):
                        continue
                    candidate = base.joinpath(*item.split("/"))
                    if self._searchable_context_file(
                        base, candidate, project_settings=project_settings,
                    ):
                        collected.append((item, candidate))
                        if len(collected) >= limit:
                            break
                return collected
        except (OSError, subprocess.TimeoutExpired):
            pass

        for dirpath, dirnames, filenames in os.walk(directory, followlinks=False):
            current = Path(dirpath)
            dirnames[:] = sorted(
                name for name in dirnames
                if name.lower() not in self.ignore_dirs and not (current / name).is_symlink()
            )
            if len(current.relative_to(directory).parts) >= 25:
                dirnames.clear()
            for name in sorted(filenames):
                candidate = current / name
                if not self._searchable_context_file(base, candidate, project_settings=project_settings):
                    continue
                try:
                    rel = candidate.relative_to(base).as_posix()
                except ValueError:
                    continue
                collected.append((rel, candidate))
                if len(collected) >= limit:
                    return collected
        return collected

    def search_paths(
        self, root: str, query: str, paths: list[str], top_k: int = 10,
        context_lines: int | None = None, *, directory_hints: list[str] | tuple[str, ...] = (),
        exclude_paths: list[str] | tuple[str, ...] = (),
        force_include_paths: list[str] | tuple[str, ...] = (),
        max_directory_files: int = _MAX_DIRECTORY_HINT_FILES,
        project_settings: Any | None = None,
        git_inventory: Any = _UNSET_GIT_INVENTORY,
    ) -> dict[str, Any]:
        """Search explicit files and bounded content below caller-supplied directories."""
        from .project_config import path_is_allowed, resolve_project_context
        from .state_paths import configured_state_dir

        base = self._root(root)
        try:
            project_context = resolve_project_context(base, configured_state_dir(self.config))
            if project_context.resolution.error_codes:
                raise ValueError("project_policy_unavailable")
            if project_settings is None:
                project_settings = project_context.settings
        except (OSError, RuntimeError, ValueError):
            return {
                "success": False, "root": str(base), "error": "project_policy_unavailable",
                "results": [], "scanned_files": 0, "targeted": True,
            }
        if git_inventory is _UNSET_GIT_INVENTORY:
            git_inventory = self._git_files(base)
        git_metadata = base / ".git"
        valid_git_metadata = (
            (git_metadata.is_dir() and (git_metadata / "HEAD").is_file())
            or git_metadata.is_file()
            or (base / ".gitignore").is_file()
        )
        if git_inventory is None and valid_git_metadata:
            return {
                "success": False, "root": str(base), "error": "git_inventory_unavailable",
                "results": [], "scanned_files": 0, "targeted": True,
            }
        git_paths = None
        if git_inventory is not None:
            git_paths = set()
            for candidate in git_inventory:
                try:
                    git_paths.add(candidate.resolve(strict=False).relative_to(base).as_posix())
                except (OSError, RuntimeError, ValueError):
                    continue
        if not isinstance(paths, (list, tuple)):
            return {"success": False, "error": "paths must be a list"}
        controls: list[tuple[str, tuple[str, ...]]] = []
        for field, values in (("directory_hints", directory_hints), ("exclude_paths", exclude_paths), ("force_include_paths", force_include_paths)):
            if not isinstance(values, (list, tuple)):
                return {"success": False, "error": f"{field} must be a list"}
            if len(values) > _MAX_PATH_CONTROLS:
                return {"success": False, "error": f"{field} exceeds the path limit"}
            try:
                normalized = tuple(
                    self._validated_context_path(base, value, field, reject_symlink=field == "directory_hints")[0]
                    for value in values
                )
            except ValueError as exc:
                return {"success": False, "error": str(exc)}
            controls.append((field, normalized))
        directory_values, excluded_values, forced_values = (item[1] for item in controls)
        normalized_inputs: list[tuple[str, Path]] = []
        for value in paths[:_MAX_PATH_CONTROLS]:
            try:
                normalized_inputs.append(self._validated_context_path(base, value, "paths"))
            except ValueError as exc:
                if "repository-relative" in str(exc) or "symlinks" in str(exc):
                    return {"success": False, "error": str(exc)}
                # Stale in-repository candidates are hints; traversal and symlink
                # attempts are rejected above.
                continue
        normalized_inputs.extend(
            self._validated_context_path(base, value, "force_include_paths") for value in forced_values
        )

        if isinstance(max_directory_files, bool):
            return {"success": False, "error": "max_directory_files must be an integer"}
        try:
            expansion_cap = max(0, min(int(max_directory_files), _MAX_DIRECTORY_HINT_FILES))
        except (TypeError, ValueError, OverflowError):
            return {"success": False, "error": "max_directory_files must be an integer"}
        if isinstance(max_directory_files, float) and max_directory_files != int(max_directory_files):
            return {"success": False, "error": "max_directory_files must be an integer"}

        hinted_directories = {value.casefold() for value in directory_values}
        targets: list[tuple[str, Path]] = []
        seen_targets: set[str] = set()
        expanded = 0
        for rel, candidate in normalized_inputs:
            key = rel.casefold()
            if key in seen_targets:
                continue
            seen_targets.add(key)
            if candidate.is_symlink():
                return {"success": False, "error": "paths cannot traverse symlinks"}
            if candidate.is_file():
                forced = self._path_control_matches(rel, forced_values)
                if not self._path_control_matches(rel, excluded_values) and self._searchable_context_file(
                    base, candidate, force_include=forced, project_settings=project_settings,
                ):
                    targets.append((rel, candidate))
            elif candidate.is_dir() and key in hinted_directories:
                children = self._expand_context_directory(
                    base, rel, candidate, expansion_cap - expanded,
                    project_settings=project_settings,
                )
                for child_rel, child_path in children:
                    expanded += 1
                    forced = self._path_control_matches(child_rel, forced_values)
                    if self._path_control_matches(child_rel, excluded_values):
                        continue
                    child_key = child_rel.casefold()
                    if child_key not in seen_targets:
                        targets.append((child_rel, child_path))
                        seen_targets.add(child_key)
                if expanded >= expansion_cap:
                    break
        terms = self._terms(query)
        phrase = query.strip().lower()
        effective_snippet_lines = max(1, min(int(context_lines), 40)) if context_lines is not None else self.snippet_lines
        hits: list[dict[str, Any]] = []
        scanned = 0
        seen_paths: set[str] = set()
        path_rank = {rel: rank for rank, (rel, _path) in enumerate(targets)}
        for rel, path in targets:
            if rel in seen_paths:
                continue
            seen_paths.add(rel)
            path = (base / rel).resolve(strict=False)
            try:
                relative = path.relative_to(base)
            except ValueError:
                continue
            forced = self._path_control_matches(rel, forced_values)
            if self._is_ignored_relative_path(relative) and not forced:
                continue
            if not path.is_file():
                continue
            if git_paths is not None and rel not in git_paths and not forced and not path_is_allowed(
                base, rel, project_settings, phase="search", soft_ignored=True,
            ):
                continue
            scanned += 1
            try:
                file_hash, lines = self._read_snapshot(path)
            except Exception:
                continue
            path_lower = rel.lower()
            for idx, line in enumerate(lines):
                low = line.lower()
                matched = [t for t in terms if t in low]
                path_matches = sum(1 for t in terms if t in path_lower)
                if not matched and not path_matches:
                    continue
                score = float(len(matched) * 3 + path_matches * 2)
                if phrase and len(phrase) <= 120 and phrase in low:
                    score += 8
                score += sum(min(low.count(t), 3) * 0.5 for t in matched)
                start = max(0, idx - effective_snippet_lines)
                end = min(len(lines), idx + effective_snippet_lines + 1)
                snippet = "\n".join(f"{n + 1}: {lines[n]}" for n in range(start, end))
                hits.append({
                    "path": rel, "start_line": start + 1, "end_line": end,
                    "score": round(score, 3), "text": snippet, "file_sha256": file_hash,
                })
        hits.sort(
            key=lambda x: (
                -x["score"],
                path_rank.get(x["path"], len(path_rank)),
                x["path"],
                x["start_line"],
            )
        )
        dedup: list[dict[str, Any]] = []
        per_file: Counter[str] = Counter()
        for hit in hits:
            if per_file[hit["path"]] >= self.max_snippets_per_file:
                continue
            per_file[hit["path"]] += 1
            dedup.append(hit)
            if len(dedup) >= max(1, int(top_k)):
                break
        candidate_pool = hits[: max(len(dedup), max(1, int(top_k)) * 4)]
        candidate_tokens = sum(estimate_tokens(str(item.get("text", ""))) for item in candidate_pool)
        result = {"success": True, "root": str(base), "scanned_files": scanned, "terms": terms, "results": dedup, "targeted": True}
        if candidate_tokens:
            result["candidate_context_tokens_est"] = candidate_tokens
        return result

    def context_pack_paths(
        self, root: str, query: str, paths: list[str], max_tokens: int = 2600, top_k: int = 10, *,
        directory_hints: list[str] | tuple[str, ...] = (),
        exclude_paths: list[str] | tuple[str, ...] = (),
        force_include_paths: list[str] | tuple[str, ...] = (),
        max_directory_files: int = _MAX_DIRECTORY_HINT_FILES,
    ) -> dict[str, Any]:
        search = self.search_paths(
            root, query, paths, top_k=top_k, directory_hints=directory_hints,
            exclude_paths=exclude_paths, force_include_paths=force_include_paths,
            max_directory_files=max_directory_files,
        )
        if not search.get("success"):
            return search
        return self._pack_ranked_context(search, query, max_tokens, targeted=True)

    def _pack_ranked_context(
        self, search: dict[str, Any], query: str, max_tokens: int, *, targeted: bool = False,
    ) -> dict[str, Any]:
        """Render ranked evidence once; keep snippets whole and provenance aligned.

        ``max_tokens`` limits context text. HTTP/MCP callers enforce their separate
        serialized-envelope budget at the transport boundary.
        """
        pieces: list[str] = []
        evidence: list[dict[str, Any]] = []
        candidate_tokens = 0
        context_bytes = 0
        results = search.get("results", [])
        token_limit = max(0, int(max_tokens)) if results else 0
        for item in results:
            header = f"--- {item['path']}:{item['start_line']}-{item['end_line']} score={item['score']} ---\n"
            candidate_tokens += estimate_tokens(header + item["text"] + "\n")
        for item in results:
            header = f"--- {item['path']}:{item['start_line']}-{item['end_line']} score={item['score']} ---\n"
            piece = header + item["text"] + "\n"
            trial_bytes = context_bytes + (1 if pieces else 0) + len(piece.encode("utf-8"))
            if max(1, math.ceil(trial_bytes / 3.4)) > token_limit:
                # Ranked order is authoritative; lower-ranked short snippets must
                # not jump ahead of a higher-ranked excerpt that did not fit.
                break
            pieces.append(piece)
            context_bytes = trial_bytes
            ev = {k: item[k] for k in ("path", "start_line", "end_line", "score", "file_sha256")}
            ev["raw"] = item.get("text", "")
            evidence.append(ev)
        packed = "\n".join(pieces)
        result = {
            "success": True, "root": search["root"], "query": query, "context": packed,
            "evidence": evidence, "estimated_tokens": estimate_tokens(packed),
            "original_estimated_tokens": max(candidate_tokens, estimate_tokens(packed)),
            "scanned_files": search.get("scanned_files", 0),
        }
        if targeted:
            result["targeted"] = True
        return result

    def file_inventory(self, root: str, include_hashes: bool = True) -> dict[str, Any]:
        """Return a deterministic file inventory backed by the shared snapshot cache.

        Preprocessing uses this as its durable content-addressed source of truth.
        """
        base = self._root(root)
        items: list[dict[str, Any]] = []
        total_bytes = 0
        for path, stat in self._iter_files_with_stat(str(base)):
            try:
                rel = str(path.relative_to(base)).replace("\\", "/")
                item: dict[str, Any] = {
                    "path": rel, "size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
                    "extension": path.suffix.lower(),
                }
                if include_hashes:
                    digest, _lines = self._read_snapshot(path, stat=stat)
                    item["sha256"] = digest
                items.append(item)
                total_bytes += int(stat.st_size)
            except Exception:
                continue
        items.sort(key=lambda x: x["path"])
        digest = hashlib.sha256(
            "\n".join(f"{x['path']}:{x.get('sha256','')}:{x['size']}" for x in items).encode("utf-8")
        ).hexdigest()
        return {"success": True, "root": str(base), "files": items, "file_count": len(items), "total_bytes": total_bytes, "inventory_sha256": digest}

    def file_slice(self, root: str, path: str, start_line: int = 1, end_line: int = 240, max_chars: int = 16000) -> dict[str, Any]:
        """Read an exact bounded source slice through the snapshot cache."""
        base = self._root(root)
        candidate = (base / path).resolve(strict=False)
        try:
            candidate.relative_to(base)
        except ValueError:
            return {"success": False, "error": "path escapes repository root"}
        if not candidate.is_file():
            return {"success": False, "error": f"file not found: {path}"}
        try:
            digest, lines = self._read_snapshot(candidate)
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        rel = str(candidate.relative_to(base)).replace("\\", "/")
        if not lines:
            return {
                "success": True, "root": str(base), "path": rel, "start_line": 1, "end_line": 0,
                "text": "", "file_sha256": digest, "truncated": False,
            }
        start = max(1, min(int(start_line), len(lines)))
        end = max(start, min(int(end_line), len(lines)))
        rendered = "\n".join(f"{n}: {lines[n-1]}" for n in range(start, end + 1))
        truncated = len(rendered) > max_chars
        if truncated:
            rendered = rendered[:max_chars] + "\n[…slice truncated…]"
        return {
            "success": True, "root": str(base), "path": rel, "start_line": start, "end_line": end,
            "text": rendered, "file_sha256": digest, "truncated": truncated,
        }

    def context_pack(self, root: str, query: str, max_tokens: int = 4500, top_k: int = 14) -> dict[str, Any]:
        search = self.search(root, query, top_k=top_k)
        if not search.get("success"):
            return search
        return self._pack_ranked_context(search, query, max_tokens)
