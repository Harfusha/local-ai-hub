from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import subprocess
import threading
import time
from types import MappingProxyType
from typing import Any

from .normalizer import tokenize_query_terms
from .process_utils import hidden_run_kwargs, popen_managed, terminate_tree
from .repo_tools_constants import _GENERIC_SEARCH_WORDS
from .repo_tools_models import GitBlobRecord, GitSnapshot
from .repo_tools_path_helpers import _windows_file_api


RepositoryTools = None


class RepoToolsSearchBackendMixin:
    _GENERIC_SEARCH_WORDS = _GENERIC_SEARCH_WORDS

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
        with self._resolved_paths_lock:
            self._resolved_paths.clear()

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
            "git", "-C", str(base), "grep", "-n", "-I", "-i", "-F", "--no-color", "--full-name", "--untracked",
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
                resolved_info = self._resolve_under_base(base, path)
                if resolved_info is None:
                    continue
                _resolved, relative_p = resolved_info
                relative = relative_p.as_posix()
                added_chars = len(relative) + 4
                if added_chars + fixed_chars > 20_000:
                    return None, True
                if current and (len(current) >= 512 or current_chars + added_chars + fixed_chars > 20_000):
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
            cmd = [self._rg, "--json", "--fixed-strings", "--ignore-case", "--max-count", str(max(2, self.max_snippets_per_file * 3))]
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
                resolved_info = self._resolve_under_base(base, str(path_text))
                if resolved_info is None:
                    continue
                _path, relative_p = resolved_info
                rel = str(relative_p).replace("\\", "/")
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
                if self._resolve_under_base(base, rel) is None:
                    continue
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

