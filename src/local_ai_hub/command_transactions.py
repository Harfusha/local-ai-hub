from __future__ import annotations

import hashlib
import ntpath
import os
import shutil
import stat
import subprocess
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .process_utils import clean_git_env, hidden_run_kwargs


@dataclass(frozen=True)
class _TreeEntry:
    kind: str
    mode: int
    size: int
    mtime_ns: int
    digest: str = ""
    target: str = ""


def _write_set(paths: Iterable[str]) -> dict[str, str]:
    if isinstance(paths, (str, bytes)):
        raise ValueError("transaction write set must be a collection of relative file paths")
    try:
        values = tuple(paths)
    except TypeError as exc:
        raise ValueError("transaction write set must be a collection of relative file paths") from exc
    if len(values) > 128:
        raise ValueError("transaction write set exceeds 128 paths")
    normalized: dict[str, str] = {}
    for raw in values:
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            raise ValueError("transaction write set contains an invalid path")
        portable = raw.replace("\\", "/")
        drive, _ = ntpath.splitdrive(raw)
        parts = portable.split("/")
        if drive or ntpath.isabs(raw) or portable.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            raise ValueError(f"transaction write path must be relative and normalized: {raw[:160]}")
        reserved = {
            "CON", "PRN", "AUX", "NUL",
            *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)),
            "COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³",
        }
        if any(
            ":" in part or part.endswith((".", " "))
            or part.split(".", 1)[0].rstrip(" .").upper() in reserved
            for part in parts
        ):
            raise ValueError(f"transaction write path is not portable: {raw[:160]}")
        key = "/".join(parts)
        comparison = key.casefold() if os.name == "nt" else key
        if comparison in normalized:
            raise ValueError(f"duplicate transaction write path: {raw[:160]}")
        normalized[comparison] = key
    if not normalized:
        raise ValueError("transaction write set is required")
    keys = tuple(normalized)
    for left in keys:
        if any(right.startswith(left + "/") for right in keys if right != left):
            raise ValueError("transaction write paths cannot contain another write path")
    return normalized


def _manifest_index(manifest: Mapping[str, _TreeEntry]) -> dict[str, tuple[str, _TreeEntry]]:
    indexed: dict[str, tuple[str, _TreeEntry]] = {}
    for path, entry in manifest.items():
        key = path.casefold() if os.name == "nt" else path
        if key in indexed:
            raise ValueError(f"transaction tree contains case-aliased paths: {path}")
        indexed[key] = (path, entry)
    return indexed


def _entry_changed(
    before: tuple[str, _TreeEntry] | None,
    after: tuple[str, _TreeEntry] | None,
) -> bool:
    if before is None or after is None:
        return before is not after
    before_path, before_entry = before
    after_path, after_entry = after
    if before_entry.kind == after_entry.kind == "directory":
        return before_path != after_path or before_entry.mode != after_entry.mode
    return before != after


def validate_transaction_output(
    baseline: Mapping[str, _TreeEntry],
    transaction_root: str | Path,
    paths: Iterable[str],
) -> dict[str, _TreeEntry | None]:
    """Return declared postimages; reject any transaction change outside its write set."""
    write_set = _write_set(paths)
    baseline_index = _manifest_index(baseline)
    current_index = _manifest_index(_tree_manifest(Path(transaction_root).resolve(strict=True)))
    changes: dict[str, _TreeEntry | None] = {}
    for key in baseline_index.keys() | current_index.keys():
        before = baseline_index.get(key)
        after = current_index.get(key)
        if not _entry_changed(before, after):
            continue
        relative = (after or before)[0]
        entry = after[1] if after else None
        declared = write_set.get(key)
        if (
            entry is not None
            and entry.kind == "directory"
            and (before is None or after is None)
        ):
            if any(
                (target.casefold() if os.name == "nt" else target).startswith(key + "/")
                for target in write_set.values()
            ):
                continue
        if declared is None:
            raise ValueError(f"undeclared transaction output: {relative}")
        if entry is not None and entry.kind != "file":
            raise ValueError(f"transaction write path is not a regular file: {declared}")
        changes[declared] = entry
    return changes


def verify_transaction_source_unchanged(
    source_root: str | Path,
    baseline: Mapping[str, _TreeEntry],
    paths: Iterable[str],
) -> None:
    """Fail if a declared import target changed while private command ran."""
    write_set = _write_set(paths)
    baseline_index = _manifest_index(baseline)
    current_index = _manifest_index(_tree_manifest(Path(source_root).resolve(strict=True)))
    for key, relative in write_set.items():
        if _entry_changed(baseline_index.get(key), current_index.get(key)):
            raise OSError(f"transaction source path changed while command was running: {relative}")


_clean_git_env = clean_git_env


def _git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
        env=_clean_git_env(),
        **hidden_run_kwargs(),
    )
    if result.returncode != 0:
        raise OSError(f"git {' '.join(args)} failed: {result.stderr[-512:]}")
    return result.stdout.strip()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _snapshot_depth_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 512:
        raise ValueError("transaction maximum depth must be an integer between 1 and 512")
    return value


def _tree_manifest(root: Path, max_depth: int = 64) -> dict[str, _TreeEntry]:
    max_depth = _snapshot_depth_limit(max_depth)
    manifest: dict[str, _TreeEntry] = {}
    pending = [root]
    seen_dirs: set[tuple[int, int] | Path] = set()
    root_stat = root.stat()
    if root_stat.st_ino != 0:
        seen_dirs.add((root_stat.st_dev, root_stat.st_ino))
    else:
        seen_dirs.add(root.resolve())

    while pending:
        directory = pending.pop()
        relative_dir = directory.relative_to(root)
        if len(relative_dir.parts) >= max_depth:
            raise ValueError(f"maximum directory depth exceeded in transaction inputs: {relative_dir.as_posix()}")
        try:
            with os.scandir(directory) as scanner:
                entries = sorted(scanner, key=lambda entry: entry.name.casefold())
        except OSError as exc:
            raise OSError(f"cannot enumerate transaction input: {exc}") from exc
        for entry in entries:
            if not relative_dir.parts and entry.name.casefold() == ".git":
                continue
            if entry.name.casefold() == ".git":
                raise ValueError("nested Git metadata is unsupported in transaction inputs")
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            try:
                # Windows scandir metadata may omit file identity (st_dev/st_ino
                # are zero); use handle-backed stat before comparing with fstat.
                before = os.stat(path, follow_symlinks=False)
            except OSError as exc:
                raise OSError(f"cannot inspect transaction input {relative}: {exc}") from exc
            attrs = int(getattr(before, "st_file_attributes", 0))
            if attrs & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
                if not entry.is_symlink():
                    raise ValueError(f"unsupported reparse point in transaction inputs: {relative}")
            if entry.is_symlink():
                target = os.readlink(path)
                resolved_target = (path.parent / target).resolve(strict=False)
                if not _inside(resolved_target, root):
                    raise ValueError(f"external symlink in transaction inputs: {relative}")
                manifest[relative] = _TreeEntry(
                    "symlink", int(before.st_mode), int(before.st_size),
                    int(before.st_mtime_ns), target=target,
                )
                continue
            if stat.S_ISDIR(before.st_mode):
                dir_key = (before.st_dev, before.st_ino) if before.st_ino != 0 else path.resolve()
                if dir_key in seen_dirs:
                    raise ValueError(f"directory cycle detected in transaction inputs: {relative}")
                seen_dirs.add(dir_key)
                manifest[relative] = _TreeEntry(
                    "directory", int(before.st_mode), 0, int(before.st_mtime_ns)
                )
                pending.append(path)
                continue
            if not stat.S_ISREG(before.st_mode):
                raise ValueError(f"unsupported file type in transaction inputs: {relative}")
            digest = hashlib.sha256()
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(path, flags)
                with os.fdopen(fd, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
                        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
                    ):
                        raise OSError(f"transaction input changed while opening: {relative}")
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                    after = os.fstat(stream.fileno())
            except OSError as exc:
                raise OSError(f"cannot read transaction input {relative}: {exc}") from exc
            if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
                before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
            ):
                raise OSError(f"transaction input changed while reading: {relative}")
            manifest[relative] = _TreeEntry(
                "file", int(before.st_mode), int(before.st_size),
                int(before.st_mtime_ns), digest=digest.hexdigest(),
            )
    return manifest


def _copy_tree(source: Path, destination: Path, max_depth: int = 64) -> None:
    max_depth = _snapshot_depth_limit(max_depth)
    pending = [(source, destination)]
    directory_metadata: list[tuple[Path, Path]] = []
    seen_dirs: set[tuple[int, int] | Path] = set()
    source_stat = source.stat()
    if source_stat.st_ino != 0:
        seen_dirs.add((source_stat.st_dev, source_stat.st_ino))
    else:
        seen_dirs.add(source.resolve())

    while pending:
        source_dir, destination_dir = pending.pop()
        rel = source_dir.relative_to(source)
        if len(rel.parts) >= max_depth:
            raise ValueError(f"maximum directory depth exceeded in transaction inputs: {rel.as_posix()}")

        with os.scandir(source_dir) as scanner:
            entries = sorted(scanner, key=lambda entry: entry.name.casefold())
        for entry in entries:
            if source_dir == source and entry.name.casefold() == ".git":
                continue
            source_path = Path(entry.path)
            target_path = destination_dir / entry.name
            info = entry.stat(follow_symlinks=False)
            if entry.is_symlink():
                link = os.readlink(source_path)
                resolved = (source_path.parent / link).resolve(strict=False)
                if not _inside(resolved, source):
                    raise ValueError(f"external symlink in transaction inputs: {source_path.relative_to(source)}")
                os.symlink(link, target_path, target_is_directory=resolved.is_dir())
                shutil.copystat(source_path, target_path, follow_symlinks=False)
            elif stat.S_ISDIR(info.st_mode):
                dir_key = (info.st_dev, info.st_ino) if info.st_ino != 0 else source_path.resolve()
                if dir_key in seen_dirs:
                    raise ValueError(f"directory cycle detected in transaction inputs: {source_path.relative_to(source)}")
                seen_dirs.add(dir_key)
                target_path.mkdir()
                pending.append((source_path, target_path))
                directory_metadata.append((source_path, target_path))
            elif stat.S_ISREG(info.st_mode):
                shutil.copy2(source_path, target_path, follow_symlinks=False)
            else:
                raise ValueError(f"unsupported file type in transaction inputs: {source_path.relative_to(source)}")
    for source_dir, target_dir in sorted(
        directory_metadata, key=lambda pair: len(pair[0].parts), reverse=True
    ):
        shutil.copystat(source_dir, target_dir, follow_symlinks=False)


def _git_path(root: Path, path: str) -> Path:
    value = Path(_git_output(root, "rev-parse", "--git-path", path))
    return value if value.is_absolute() else (root / value).resolve(strict=False)


def _stable_file_digest(path: Path) -> tuple[int, int, int, int, int, str]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise OSError(f"Git index metadata is not a regular file: {path.name}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    digest = hashlib.sha256()
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_mode)
        opened_identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_mode)
        if opened_identity != identity:
            raise OSError(f"Git index metadata changed while opening: {path.name}")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        after = os.fstat(stream.fileno())
    current = path.lstat()
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_mode)
    if after_identity != identity:
        raise OSError(f"Git index metadata changed while reading: {path.name}")
    current_identity = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_mode)
    if current_identity != identity:
        raise OSError(f"Git index metadata path changed while reading: {path.name}")
    return (*identity, digest.hexdigest())


def _index_state(root: Path) -> tuple[Path, dict[str, tuple[int, int, int, int, int, str]]]:
    index = _git_path(root, "index")
    lock = index.with_name(index.name + ".lock")
    if lock.exists() or lock.is_symlink():
        raise OSError("source Git index is locked during transaction snapshot")
    paths = ([index] if index.exists() else []) + sorted(index.parent.glob("sharedindex.*"))
    state = {path.name: _stable_file_digest(path) for path in paths}
    if lock.exists() or lock.is_symlink():
        raise OSError("source Git index became locked during transaction snapshot")
    return index, state


def _copy_private_index(source: Path, destination: Path) -> None:
    source_index, source_state = _index_state(source)
    destination_index = _git_path(destination, "index")
    for name in source_state:
        shutil.copy2(source_index.parent / name, destination_index.parent / name)
        if _stable_file_digest(destination_index.parent / name)[-1] != source_state[name][-1]:
            raise OSError(f"private Git index metadata copy failed: {name}")

    staged = subprocess.run(
        ["git", "-C", str(source), "ls-files", "--stage", "-z"],
        capture_output=True,
        check=False,
        timeout=15,
        env=_clean_git_env(),
        **hidden_run_kwargs(),
    )
    if staged.returncode != 0:
        raise OSError(f"cannot inspect source Git index: {staged.stderr[-512:].decode(errors='replace')}")
    object_ids = {
        record.split(b" ", 2)[1].decode("ascii")
        for record in staged.stdout.split(b"\0")
        if record and b" " in record
    }
    for object_id in object_ids:
        _git_output(destination, "cat-file", "-e", f"{object_id}^{{blob}}")
    _, current_state = _index_state(source)
    if current_state != source_state:
        raise OSError("source Git index changed while transaction snapshot was being created")


def create_private_transaction_snapshot_with_manifest(
    source: str | Path,
    destination: str | Path,
    *,
    max_depth: int = 64,
) -> tuple[Path, Mapping[str, _TreeEntry]]:
    """Create private checkout and return the exact source manifest it preserves."""
    max_depth = _snapshot_depth_limit(max_depth)
    source_root = Path(source).expanduser().resolve(strict=True)
    if not source_root.is_dir():
        raise ValueError("transaction source must be a directory")
    destination_root = Path(destination).expanduser().resolve(strict=False)
    parent = destination_root.parent.resolve(strict=True)
    if destination_root.exists() or not parent.is_dir():
        raise ValueError("transaction destination must not exist and its parent must exist")
    if _inside(destination_root, source_root) or _inside(source_root, destination_root):
        raise ValueError("transaction source and destination must be disjoint")
    top = _git_output(source_root, "rev-parse", "--show-toplevel")
    if Path(top).resolve(strict=True) != source_root:
        raise ValueError("transaction source must be a Git worktree root")

    source_manifest = _tree_manifest(source_root, max_depth=max_depth)
    try:
        clone = subprocess.run(
            ["git", "clone", "--no-hardlinks", "--no-checkout", "--", str(source_root), str(destination_root)],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            env=_clean_git_env(),
            **hidden_run_kwargs(),
        )
        if clone.returncode != 0:
            raise OSError(f"cannot create private Git metadata: {clone.stderr[-512:]}")
        source_head = _git_output(source_root, "rev-parse", "HEAD")
        _git_output(destination_root, "cat-file", "-e", f"{source_head}^{{commit}}")
        _git_output(destination_root, "update-ref", "refs/heads/codex-transaction", source_head)
        _git_output(destination_root, "symbolic-ref", "HEAD", "refs/heads/codex-transaction")
        _git_output(destination_root, "remote", "remove", "origin")
        _git_output(destination_root, "config", "--local", "core.hooksPath", "/dev/null")
        _git_output(destination_root, "reset", "--mixed", source_head)
        _copy_private_index(source_root, destination_root)
        _copy_tree(source_root, destination_root, max_depth=max_depth)
        cloned_manifest = _tree_manifest(destination_root, max_depth=max_depth)
        current_source_manifest = _tree_manifest(source_root, max_depth=max_depth)
        if cloned_manifest != source_manifest or current_source_manifest != source_manifest:
            raise OSError("transaction source changed while snapshot was being created")
        source_common = Path(_git_output(source_root, "rev-parse", "--git-common-dir"))
        clone_common = Path(_git_output(destination_root, "rev-parse", "--git-common-dir"))
        if not source_common.is_absolute():
            source_common = (source_root / source_common).resolve(strict=True)
        if not clone_common.is_absolute():
            clone_common = (destination_root / clone_common).resolve(strict=True)
        if source_common == clone_common or not _inside(clone_common, destination_root):
            raise OSError("transaction Git metadata is not private")
        if _git_output(destination_root, "rev-parse", "HEAD") != source_head:
            raise OSError("transaction Git HEAD does not match source worktree")
        return destination_root, MappingProxyType(source_manifest)
    except Exception:
        if destination_root.exists():
            shutil.rmtree(destination_root, ignore_errors=True)
        raise


def create_private_transaction_snapshot(
    source: str | Path,
    destination: str | Path,
    *,
    max_depth: int = 64,
) -> Path:
    """Copy a worktree's complete file input state into a private Git checkout."""
    transaction_root, _ = create_private_transaction_snapshot_with_manifest(
        source, destination, max_depth=max_depth
    )
    return transaction_root


class TransactionStashHook:
    """Hook to stash dirty working tree state and restore it upon abort or error."""

    def __init__(self, root: str | Path, message: str | None = None) -> None:
        self.root = Path(root).expanduser().resolve(strict=True)
        self.message = message or "transaction_stash_guard"
        self._stashed = False
        self._stash_sha: str | None = None

    @property
    def is_stashed(self) -> bool:
        return self._stashed

    def _is_dirty(self) -> bool:
        proc = subprocess.run(
            ["git", "-C", str(self.root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
            env=_clean_git_env(),
            **hidden_run_kwargs(),
        )
        if proc.returncode != 0:
            raise OSError(f"cannot inspect git status: {proc.stderr[-512:]}")
        return bool(proc.stdout.strip())

    def save(self) -> bool:
        if not self._is_dirty():
            return False
        msg = f"lah-transaction: {self.message}"
        proc = subprocess.run(
            ["git", "-C", str(self.root), "stash", "push", "--include-untracked", "-m", msg],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=_clean_git_env(),
            **hidden_run_kwargs(),
        )
        if proc.returncode != 0:
            raise OSError(f"cannot stash changes: {proc.stderr[-512:]}")
        rev_proc = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "-q", "--verify", "refs/stash"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
            env=_clean_git_env(),
            **hidden_run_kwargs(),
        )
        if rev_proc.returncode == 0:
            self._stash_sha = rev_proc.stdout.strip()
        self._stashed = True
        return True

    def restore(self) -> bool:
        if not self._stashed:
            return False
        proc = subprocess.run(
            ["git", "-C", str(self.root), "stash", "pop"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=_clean_git_env(),
            **hidden_run_kwargs(),
        )
        if proc.returncode != 0:
            raise OSError(f"cannot restore stash: {proc.stderr[-512:]}")
        self._stashed = False
        self._stash_sha = None
        return True

    def abort(self) -> bool:
        return self.restore()

    def drop(self) -> bool:
        if not self._stashed:
            return False
        proc = subprocess.run(
            ["git", "-C", str(self.root), "stash", "drop"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=_clean_git_env(),
            **hidden_run_kwargs(),
        )
        if proc.returncode != 0:
            raise OSError(f"cannot drop stash: {proc.stderr[-512:]}")
        self._stashed = False
        self._stash_sha = None
        return True

    def __enter__(self) -> TransactionStashHook:
        self.save()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None and self._stashed:
            self.restore()


@contextmanager
def stash_transaction_guard(
    root: str | Path,
    message: str | None = None,
    *,
    auto_restore_on_error: bool = True,
):
    """Context manager executing block with stashed changes, restoring stash on abort or error."""
    hook = TransactionStashHook(root, message=message)
    hook.save()
    try:
        yield hook
    except Exception:
        if auto_restore_on_error and hook.is_stashed:
            hook.restore()
        raise

