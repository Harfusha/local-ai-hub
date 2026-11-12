"""Backup-protected, consecutive offline state migrations for setup/update."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import time
from pathlib import Path
from typing import Callable

from local_ai_hub.state_lifecycle import (
    BOOTSTRAP_STATE_ENTRIES,
    CURRENT_STATE_VERSION,
    ensure_state_version,
    read_state_version,
    write_state_version,
)

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class StateMigration:
    def __init__(
        self,
        source_version: int,
        target_version: int,
        migrate: Callable[[Path], None],
        verify: Callable[[Path], bool],
    ) -> None:
        self.source_version = source_version
        self.target_version = target_version
        self.migrate = migrate
        self.verify = verify


# Add only verified N -> N+1 transformations. Startup must never guess a schema.
MIGRATIONS: tuple[StateMigration, ...] = ()


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _reject_links(root: Path) -> None:
    if _is_link(root):
        raise ValueError(f"state migration path is a symlink or junction: {root}")
    for base, dirs, files in os.walk(root, followlinks=False):
        parent = Path(base)
        for name in (*dirs, *files):
            item = parent / name
            if _is_link(item):
                raise ValueError(f"state migration refuses symlink or junction: {item}")


def _reject_link_components(path: Path) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    if any(_is_link(component) for component in (absolute, *absolute.parents)):
        raise ValueError(f"state migration path contains a symlink or junction: {absolute}")


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix()):
        if _is_link(item):
            raise ValueError(f"state migration refuses symlink or junction: {item}")
        relative = item.relative_to(root).as_posix().encode("utf-8")
        if item.is_dir():
            digest.update(b"D\0" + relative + b"\0")
        elif item.is_file():
            digest.update(b"F\0" + relative + b"\0")
            with item.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\0")
        else:
            raise ValueError(f"unsupported state entry: {item}")
    return digest.hexdigest()


def _make_backup(source: Path, version: int) -> Path:
    backup = source.with_name(f"{source.name}.backup-v{version}-{time.time_ns()}")
    shutil.copytree(source, backup, symlinks=False)
    if _tree_digest(source) != _tree_digest(backup):
        shutil.rmtree(backup, ignore_errors=True)
        raise OSError(f"state backup verification failed: {backup}")
    return backup


def _apply_chain(
    state_dir: Path,
    migrations: tuple[StateMigration, ...],
    current: int,
) -> tuple[Path, list[str]]:
    backup = _make_backup(state_dir, current)
    stage: Path | None = None
    try:
        stage = Path(tempfile.mkdtemp(prefix=f".{state_dir.name}.migration-", dir=state_dir.parent))
        stage.rmdir()
        shutil.copytree(backup, stage, symlinks=False)
        for migration in migrations:
            if migration.source_version != current or migration.target_version != current + 1:
                raise ValueError("state migrations must be consecutive N-to-N+1 steps")
            migration.migrate(stage)
            if migration.verify(stage) is not True:
                raise ValueError(f"state migration verification failed for {current}->{current + 1}")
            write_state_version(stage, version=current + 1, migrated_from=current)
            _reject_links(stage)
            if migration.verify(stage) is not True:
                raise ValueError(f"state migration post-marker verification failed for {current}->{current + 1}")
            current += 1
        if _tree_digest(state_dir) != _tree_digest(backup):
            raise OSError(
                f"state changed after verified backup {backup}; "
                "refusing to replace the original state"
            )
        swap = state_dir.with_name(f".{state_dir.name}.pre-migration-{time.time_ns()}")
        os.replace(state_dir, swap)
        try:
            os.replace(stage, state_dir)
        except OSError as install_error:
            try:
                os.replace(swap, state_dir)
            except OSError as restore_error:
                raise RuntimeError(
                    f"staged state install failed and original could not be restored; "
                    f"original is at {swap}, verified backup at {backup}: {restore_error}"
                ) from install_error
            raise
        cleanup_warnings: list[str] = []
        try:
            shutil.rmtree(swap)
        except OSError as exc:
            cleanup_warnings.append(f"old-state swap retained at {swap}: {exc}")
        return backup, cleanup_warnings
    except Exception as exc:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
        raise RuntimeError(f"state migration failed; verified original backup retained at {backup}: {exc}") from exc


def inspect_state_migration_path(
    state_dir: Path | str,
    *,
    migrations: tuple[StateMigration, ...] = MIGRATIONS,
    target_version: int = CURRENT_STATE_VERSION,
) -> dict[str, object]:
    """Validate state and the full migration chain without changing state."""
    if type(target_version) is not int or target_version < 1:
        raise ValueError("target_version must be a positive integer")
    root = Path(state_dir)
    _reject_link_components(root)
    if not root.exists():
        return {"status": "initialize", "version": target_version, "backups": []}
    _reject_links(root)
    if not root.is_dir():
        raise RuntimeError(f"state path is not a directory; state unchanged: {root}")
    current = read_state_version(root)
    if current is None:
        if (root / "state_version.json").exists():
            raise RuntimeError("state version marker is corrupt; state is unchanged. See docs/INSTALLER_RECOVERY.md.")
        unexpected = sorted(item.name for item in root.iterdir() if item.name not in BOOTSTRAP_STATE_ENTRIES)
        if unexpected:
            raise RuntimeError(
                f"unversioned state contains data {unexpected}; state is unchanged. "
                "See docs/INSTALLER_RECOVERY.md."
            )
        return {"status": "initialize", "version": target_version, "backups": []}
    if current > target_version:
        raise RuntimeError(f"state version {current} is newer than supported version {target_version}; state unchanged")
    if current == target_version:
        return {"status": "current", "version": current, "backups": []}
    by_source: dict[int, StateMigration] = {}
    for migration in migrations:
        if migration.source_version in by_source or migration.target_version != migration.source_version + 1:
            raise ValueError("migration registry has duplicate or non-consecutive versions")
        by_source[migration.source_version] = migration
    missing = [version for version in range(current, target_version) if version not in by_source]
    if missing:
        version = missing[0]
        raise RuntimeError(
            f"no verified state migration registered for {version}->{version + 1}; "
            "state is unchanged. See docs/INSTALLER_RECOVERY.md."
        )
    return {"status": "migratable", "version": current, "backups": [], "migration_count": target_version - current}


def run_state_migrations(
    state_dir: Path | str,
    *,
    migrations: tuple[StateMigration, ...] = MIGRATIONS,
    target_version: int = CURRENT_STATE_VERSION,
) -> dict[str, object]:
    root = Path(state_dir)
    plan = inspect_state_migration_path(root, migrations=migrations, target_version=target_version)
    if plan["status"] == "initialize":
        result = ensure_state_version(root, target_version)
        return {**result, "backups": []}
    current = int(plan["version"])
    if plan["status"] == "current":
        return {"status": "current", "version": current, "backups": []}
    by_source: dict[int, StateMigration] = {}
    for migration in migrations:
        by_source[migration.source_version] = migration
    steps = tuple(by_source[version] for version in range(current, target_version))
    backup, cleanup_warnings = _apply_chain(root, steps, current)
    return {
        "status": "migrated",
        "version": target_version,
        "backups": [str(backup)],
        "warnings": cleanup_warnings,
    }
