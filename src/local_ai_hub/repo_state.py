from __future__ import annotations

import os
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .cache import MemoryLRUCache, stable_hash
from .process_utils import canonical_root, hidden_run_kwargs


class RepoStateTracker:
    """Fast, failure-tolerant workspace fingerprints for deterministic caches.

    Repository fingerprints sit on every search/context/command cache lookup, so they
    must never turn a slow ``git status`` into a 15-second foreground stall. Git remains
    authoritative when it is healthy; metadata signatures and a short stale fallback
    keep requests bounded when Git is temporarily slow (large worktrees, antivirus,
    network-backed paths, concurrent maintenance, etc.). Exact source readers still
    verify bytes before returning evidence.
    """

    def __init__(self, config: dict[str, Any]):
        cfg = config.get("workspace_cache", {})
        self.ttl = max(0.1, float(cfg.get("fingerprint_ttl_seconds", 2.0)))
        self.git_probe_timeout = max(0.2, float(cfg.get("git_probe_timeout_seconds", 1.0)))
        self.git_status_timeout = max(0.5, float(cfg.get("git_status_timeout_seconds", 5.0)))
        # Waiting behind another fingerprint owner is bounded independently from Git
        # itself. If an owner stalls in a pathological filesystem call, a waiter may
        # do one bounded duplicate probe rather than inheriting an unbounded lock wait.
        self.fingerprint_flight_timeout = max(0.05, float(cfg.get("fingerprint_flight_timeout_seconds", 8.0)))
        self.slow_git_cooldown = max(1.0, float(cfg.get("slow_git_cooldown_seconds", 12.0)))
        self.max_changed_paths = max(32, int(cfg.get("max_changed_paths", 512)))
        self.max_untracked_walk_files = max(32, int(cfg.get("max_untracked_walk_files", 2048)))
        self.non_git_max_files = int(cfg.get("non_git_max_files", config.get("search", {}).get("max_files", 8000)))
        self.degraded_max_files = max(128, int(cfg.get("degraded_fingerprint_max_files", 2048)))
        self.non_git_ignore_dirs = set(config.get("rag", {}).get("ignore_dirs", [".git", "node_modules", "vendor", "dist", "build", "bin", "obj", ".cache"]))
        self.cache = MemoryLRUCache(int(cfg.get("fingerprint_l1_entries", 128)), self.ttl)
        self._lock = threading.RLock()
        self._flight_lock = threading.Lock()
        self._flights: dict[str, tuple[threading.Lock, int]] = {}
        self._last_good: dict[str, dict[str, Any]] = {}
        self._slow_until: dict[str, float] = {}
        self._stats = {"git": 0, "filesystem": 0, "degraded": 0, "git_timeouts": 0, "cache_hits": 0, "flight_timeouts": 0}

    @contextmanager
    def _root_flight(self, cache_key: str) -> Iterator[bool]:
        """Serialize one root with a bounded wait and release per-root lock metadata.

        ``False`` means this caller timed out waiting for the owner and should proceed
        with its own already-bounded fingerprint computation. This intentionally trades
        rare duplicate work for a hard upper bound on foreground lock latency.
        """
        with self._flight_lock:
            current = self._flights.get(cache_key)
            lock, refs = current if current is not None else (threading.Lock(), 0)
            self._flights[cache_key] = (lock, refs + 1)
        acquired = lock.acquire(timeout=self.fingerprint_flight_timeout)
        if not acquired:
            self._bump("flight_timeouts")
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()
            with self._flight_lock:
                current = self._flights.get(cache_key)
                if current is not None and current[0] is lock:
                    refs = current[1] - 1
                    if refs <= 0:
                        self._flights.pop(cache_key, None)
                    else:
                        self._flights[cache_key] = (lock, refs)

    def _bump(self, key: str) -> None:
        with self._lock:
            self._stats[key] = int(self._stats.get(key, 0)) + 1

    @staticmethod
    def _run_git(root: Path, *args: str, timeout: float = 8.0) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", "-C", str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, timeout=timeout, check=False,
            **hidden_run_kwargs(),
        )

    @staticmethod
    def _stat_tuple(path: Path) -> tuple[int, int, int, int] | str:
        try:
            stat = path.stat()
            return (
                int(stat.st_mtime_ns), int(stat.st_size),
                int(getattr(stat, "st_ctime_ns", 0)), int(getattr(stat, "st_ino", 0)),
            )
        except OSError:
            return "missing"

    def _directory_signature(self, path: Path, root: Path) -> dict[str, Any]:
        entries: list[tuple[str, int, int, int, int]] = []
        truncated = False
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                dirnames[:] = sorted(d for d in dirnames if d not in self.non_git_ignore_dirs)
                for name in sorted(filenames):
                    child = Path(dirpath) / name
                    try:
                        stat = child.stat()
                        rel = str(child.relative_to(root)).replace("\\", "/")
                        entries.append((rel, int(stat.st_mtime_ns), int(stat.st_size), int(getattr(stat, "st_ctime_ns", 0)), int(getattr(stat, "st_ino", 0))))
                    except OSError:
                        continue
                    if len(entries) >= self.max_untracked_walk_files:
                        truncated = True
                        break
                if truncated:
                    break
        except OSError:
            pass
        # If a huge untracked directory is truncated, make the signature intentionally
        # volatile at the foreground fingerprint TTL. That keeps work bounded without
        # pretending the unseen tail is cache-stable. Filesystem watchers still provide
        # immediate invalidation on the normal warm path.
        return {
            "entries": entries, "truncated": truncated,
            "volatile_bucket": int(time.time() / max(1.0, self.ttl)) if truncated else None,
        }

    def _path_signature(self, root: Path, rel: str) -> Any:
        path = (root / rel).resolve(strict=False)
        try:
            path.relative_to(root)
        except ValueError:
            return "outside-root"
        if path.is_dir():
            return self._directory_signature(path, root)
        return self._stat_tuple(path)

    @staticmethod
    def _parse_porcelain_v1(status_raw: bytes) -> list[str]:
        records = status_raw.split(b"\0")
        changed: set[str] = set()
        i = 0
        while i < len(records):
            rec = records[i]
            i += 1
            if len(rec) < 4:
                continue
            status = rec[:2]
            rel_b = rec[3:]
            if status[:1] in {b"R", b"C"} or status[1:2] in {b"R", b"C"}:
                if i < len(records) and records[i]:
                    # Include both sides of a rename/copy: deletion and destination can
                    # independently invalidate path-based indexes.
                    if rel_b:
                        changed.add(rel_b.decode("utf-8", errors="surrogateescape"))
                    rel_b = records[i]
                    i += 1
            if rel_b:
                changed.add(rel_b.decode("utf-8", errors="surrogateescape"))
        return sorted(changed)

    def _filesystem_result(self, root_path: Path, *, limit: int, degraded_reason: str = "") -> dict[str, Any]:
        entries: list[tuple[str, int, int, int, int]] = []
        truncated = False
        try:
            for dirpath, dirnames, filenames in os.walk(root_path):
                dirnames[:] = sorted(d for d in dirnames if d not in self.non_git_ignore_dirs)
                for name in sorted(filenames):
                    path = Path(dirpath) / name
                    try:
                        stat = path.stat()
                        rel = str(path.relative_to(root_path)).replace("\\", "/")
                        entries.append((rel, int(stat.st_mtime_ns), int(stat.st_size), int(getattr(stat, "st_ctime_ns", 0)), int(getattr(stat, "st_ino", 0))))
                    except OSError:
                        continue
                    if len(entries) >= limit:
                        truncated = True
                        break
                if truncated:
                    break
            digest = stable_hash({"entries": entries, "truncated": truncated})
        except OSError:
            digest = stable_hash(str(root_path))
        result = {
            "success": True, "root": str(root_path), "kind": "filesystem" if not degraded_reason else "degraded-filesystem",
            "head": None, "dirty": True, "changed_files": None, "files_seen": len(entries), "truncated": truncated,
            "fingerprint": digest, "created_at": time.time(),
        }
        if degraded_reason:
            result.update({"degraded": True, "stale": False, "degraded_reason": degraded_reason})
        return result

    def _degraded_result(self, root_path: Path, cache_key: str, reason: str) -> dict[str, Any]:
        now = time.monotonic()
        self._slow_until[cache_key] = now + self.slow_git_cooldown
        self._bump("degraded")
        previous = self._last_good.get(cache_key)
        if previous:
            result = dict(previous)
            result.update({
                "created_at": time.time(), "degraded": True, "stale": True,
                "degraded_reason": reason, "kind": f"{previous.get('kind', 'git')}-stale",
            })
        else:
            result = self._filesystem_result(root_path, limit=self.degraded_max_files, degraded_reason=reason)
        self.cache.set(cache_key, result)
        return dict(result)

    def fingerprint(self, root: str, force: bool = False) -> dict[str, Any]:
        canon = canonical_root(root)
        root_path = Path(canon)
        if not root_path.is_dir():
            raise ValueError(f"root directory does not exist: {root_path}")
        cache_key = canon
        if not force:
            cached = self.cache.get(cache_key)
            if isinstance(cached, dict):
                self._bump("cache_hits")
                return dict(cached)
            if time.monotonic() < self._slow_until.get(cache_key, 0.0):
                previous = self._last_good.get(cache_key)
                if previous:
                    result = dict(previous)
                    result.update({"created_at": time.time(), "degraded": True, "stale": True, "degraded_reason": "git slow-path cooldown", "kind": f"{previous.get('kind', 'git')}-stale"})
                    self.cache.set(cache_key, result)
                    self._bump("degraded")
                    return result

        # Coalesce only callers for the same repository. Independent worktrees must
        # never queue behind another root's slow Git/filesystem probe.
        with self._root_flight(cache_key):
            # Re-check after waiting for an in-flight fingerprint owner. A timed-out
            # waiter can still observe a just-completed result before doing duplicate work.
            if not force:
                cached = self.cache.get(cache_key)
                if isinstance(cached, dict):
                    self._bump("cache_hits")
                    return dict(cached)
            try:
                probe = self._run_git(root_path, "rev-parse", "--is-inside-work-tree", timeout=self.git_probe_timeout)
            except subprocess.TimeoutExpired:
                self._bump("git_timeouts")
                return self._degraded_result(root_path, cache_key, "git repository probe timed out")
            except OSError:
                probe = None

            if probe is not None and probe.returncode == 0 and probe.stdout.strip() == b"true":
                try:
                    head_proc = self._run_git(root_path, "rev-parse", "HEAD", timeout=self.git_probe_timeout)
                    head = head_proc.stdout.decode("utf-8", errors="replace").strip() if head_proc.returncode == 0 else ""
                    # ``normal`` collapses untracked directories, avoiding Git's very
                    # expensive all-files enumeration. Those directories are signed by
                    # bounded filesystem metadata below, preserving invalidation.
                    status_proc = self._run_git(
                        root_path, "status", "--porcelain=v1", "-z", "--untracked-files=normal",
                        timeout=self.git_status_timeout,
                    )
                    if status_proc.returncode != 0:
                        return self._degraded_result(root_path, cache_key, f"git status exited {status_proc.returncode}")
                    status_raw = status_proc.stdout
                except subprocess.TimeoutExpired:
                    self._bump("git_timeouts")
                    return self._degraded_result(root_path, cache_key, "git status timed out")
                except OSError as exc:
                    return self._degraded_result(root_path, cache_key, f"git unavailable: {type(exc).__name__}")

                changed_names = self._parse_porcelain_v1(status_raw)
                signatures = [(rel, self._path_signature(root_path, rel)) for rel in changed_names[: self.max_changed_paths]]
                changed_truncated = len(changed_names) > self.max_changed_paths
                digest = stable_hash({
                    "head": head,
                    "status": status_raw.hex(),
                    "changed": signatures,
                    "changed_truncated": changed_truncated,
                    # If we deliberately cap per-path stat work, expire the aggregate
                    # identity every TTL so an edited file beyond the cap cannot remain
                    # indefinitely hidden behind an unchanged porcelain path list.
                    "volatile_bucket": int(time.time() / max(1.0, self.ttl)) if changed_truncated else None,
                })
                result = {
                    "success": True, "root": str(root_path), "kind": "git", "head": head,
                    "dirty": bool(status_raw), "changed_files": len(changed_names),
                    "changed_paths": changed_names[: self.max_changed_paths], "fingerprint": digest,
                    "created_at": time.time(), "degraded": False, "stale": False,
                }
                self._last_good[cache_key] = dict(result)
                self._slow_until.pop(cache_key, None)
                self._bump("git")
            else:
                result = self._filesystem_result(root_path, limit=self.non_git_max_files)
                self._last_good[cache_key] = dict(result)
                self._bump("filesystem")

            self.cache.set(cache_key, result)
            return dict(result)

    def stats(self) -> dict[str, Any]:
        with self._lock, self._flight_lock:
            return {
                **self._stats,
                "l1": self.cache.stats(),
                "slow_roots": sum(1 for until in self._slow_until.values() if until > time.monotonic()),
                "fingerprint_flights": len(self._flights),
            }
