from __future__ import annotations

import hashlib
import os
import re
import stat
import sys
import tempfile
import uuid
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from .work_contracts import (
    _JournalEntry,
    _delete_windows_rollback_file,
    _patch_changes,
    _pin_windows_rollback_files,
    _pin_windows_work_directories,
    _run_git_patch,
    _safe_work_target,
    _write_windows_rollback_file,
)
from .work_fencing import (
    FencingLease,
    LeaseLostError,
    WorkAttemptFence,
    canonical_resource,
    normalize_paths,
)


def _dyn_write_windows_rollback_file(fd: int, data: bytes) -> None:
    mod = sys.modules.get("local_ai_hub.work_orchestrator")
    fn = getattr(mod, "_write_windows_rollback_file", _write_windows_rollback_file) if mod is not None else _write_windows_rollback_file
    return fn(fd, data)


def _dyn_delete_windows_rollback_file(handle: int) -> None:
    mod = sys.modules.get("local_ai_hub.work_orchestrator")
    fn = getattr(mod, "_delete_windows_rollback_file", _delete_windows_rollback_file) if mod is not None else _delete_windows_rollback_file
    return fn(handle)


def _dyn_pin_windows_rollback_files(root: Path, journal: list[_JournalEntry]):
    mod = sys.modules.get("local_ai_hub.work_orchestrator")
    fn = getattr(mod, "_pin_windows_rollback_files", _pin_windows_rollback_files) if mod is not None else _pin_windows_rollback_files
    return fn(root, journal)


def _dyn_pin_windows_work_directories(root: Path, paths: list[str]):
    mod = sys.modules.get("local_ai_hub.work_orchestrator")
    fn = getattr(mod, "_pin_windows_work_directories", _pin_windows_work_directories) if mod is not None else _pin_windows_work_directories
    return fn(root, paths)


class WorkRollbackMixin:
    def _snapshot(self, root: Path, paths: list[str]) -> list[_JournalEntry]:
        root = root.resolve()
        entries=[]
        for rel in paths:
            p = _safe_work_target(root, rel)
            if p.exists() and p.is_dir(): raise ValueError(f"refusing to patch directory: {rel}")
            data=p.read_bytes() if p.exists() else b""
            if b"\x00" in data[:8192]: raise ValueError(f"refusing to edit binary file: {rel}")
            entries.append(_JournalEntry(rel,p.exists(),data))
        return entries

    @staticmethod
    def _failed_patch_source(root: Path, patch: str) -> str:
        """Return a small, path-confined preimage for a failed patch retry."""
        try:
            paths, _, _ = _patch_changes(patch)
        except Exception:
            return ""
        root = root.resolve()
        chunks: list[str] = []
        remaining = 12_000
        for rel in paths[:8]:
            lowered = rel.lower()
            if any(marker in lowered for marker in (
                ".env", "secret", "credential", "password", "token", "private",
                "api_key", "apikey", "id_rsa", "id_ed25519", ".pem", ".p12", ".pfx", ".key",
            )):
                continue
            try:
                target = _safe_work_target(root, rel)
                if not target.is_file():
                    continue
                data = target.read_bytes()
                if b"\x00" in data[:8192]:
                    continue
                source = data.decode("utf-8")
            except (OSError, UnicodeError, ValueError):
                continue
            header = f"\n--- {rel} (current workspace source) ---\n"
            available = remaining - len(header)
            if available <= 0:
                break
            clipped = source[:available]
            chunks.append(header + clipped)
            remaining -= len(header) + len(clipped)
            if len(clipped) < len(source) or remaining <= 0:
                chunks.append("\n[remaining source omitted to keep retry context bounded]\n")
                break
        if not chunks:
            return ""
        return "CURRENT SOURCE FOR FAILED PATCH PATHS:" + "".join(chunks)

    @staticmethod
    def _preview_postimages(patch: str, snapshot: list[_JournalEntry]) -> list[_JournalEntry]:
        """Compute patch outputs in an isolated directory before workspace mutation."""
        with tempfile.TemporaryDirectory(prefix="local-ai-work-preview-") as temporary:
            preview_root = Path(temporary)
            for entry in snapshot:
                if entry.existed:
                    path = preview_root / entry.path
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(entry.data)
            checked = _run_git_patch(
                ["git", "-C", str(preview_root), "apply", "--recount", "--check", "--whitespace=nowarn", "-"],
                patch,
            )
            recount_used = True
            if checked.returncode != 0:
                fallback_check = _run_git_patch(
                    ["git", "-C", str(preview_root), "apply", "--check", "--whitespace=nowarn", "-"],
                    patch,
                )
                if fallback_check.returncode == 0:
                    checked = fallback_check
                    recount_used = False
                else:
                    raise ValueError((checked.stderr or checked.stdout or fallback_check.stderr or "git apply preview check failed")[:1000])
            applied_cmd = ["git", "-C", str(preview_root), "apply"]
            if recount_used:
                applied_cmd.append("--recount")
            applied_cmd.extend(["--whitespace=nowarn", "-"])
            applied = _run_git_patch(
                applied_cmd,
                patch,
            )
            if applied.returncode != 0:
                raise ValueError((applied.stderr or applied.stdout or "git apply preview failed")[:1000])
            postimages: list[_JournalEntry] = []
            for entry in snapshot:
                path = preview_root / entry.path
                exists = path.exists()
                data = path.read_bytes() if exists else b""
                postimages.append(
                    _JournalEntry(
                        entry.path,
                        exists,
                        data,
                        exists,
                        hashlib.sha256(data).hexdigest(),
                    )
                )
            return postimages

    @staticmethod
    def _preflight_rollback(root: Path, journal: list[_JournalEntry]) -> dict[str, Path]:
        root = root.resolve()
        targets: dict[str, Path] = {}
        for entry in journal:
            rel = str(entry.path).replace("\\", "/")
            parts = rel.split("/")
            if (
                not rel
                or rel.startswith("/")
                or re.match(r"^[A-Za-z]:", rel)
                or any(part in {"", ".", ".."} for part in parts)
            ):
                raise ValueError("unsafe work journal path")
            path = root.joinpath(*parts)
            resolved = path.resolve(strict=False)
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise ValueError("work journal path escapes repository") from exc
            cursor = root
            for index, part in enumerate(parts):
                cursor = cursor / part
                try:
                    metadata = cursor.lstat()
                except FileNotFoundError:
                    continue
                attributes = int(getattr(metadata, "st_file_attributes", 0))
                reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
                if stat.S_ISLNK(metadata.st_mode) or attributes & reparse_flag:
                    raise ValueError("refusing to restore through a symlink or reparse point")
                if index < len(parts) - 1 and cursor.exists() and not cursor.is_dir():
                    raise RuntimeError(f"rollback refused non-directory ancestor: {entry.path}")
            if path.exists() and path.is_dir():
                raise ValueError(f"rollback refused directory path: {entry.path}")
            targets[entry.path] = path
        return targets

    @staticmethod
    def _rollback(root: Path, journal: list[_JournalEntry]) -> None:
        targets = WorkRollbackMixin._preflight_rollback(root, journal)
        with _dyn_pin_windows_work_directories(root, [entry.path for entry in journal]), _dyn_pin_windows_rollback_files(root, journal) as pinned:
            WorkRollbackMixin._rollback_pinned(root, journal, pinned, targets=targets)

    @staticmethod
    def _rollback_pinned(
        root: Path,
        journal: list[_JournalEntry],
        pinned: dict[str, tuple[int, int]],
        targets: dict[str, Path] | None = None,
    ) -> None:
        if targets is None:
            targets = WorkRollbackMixin._preflight_rollback(root, journal)
        root = root.resolve()

        simulated: dict[str, tuple[bool, bytes]] = {}
        restore: list[_JournalEntry] = []
        for entry in reversed(journal):
            current = simulated.get(entry.path)
            if current is None:
                path = targets[entry.path]
                if os.name == "nt" and entry.path in pinned:
                    fd = pinned[entry.path][1]
                    os.lseek(fd, 0, os.SEEK_SET)
                    chunks = []
                    while chunk := os.read(fd, 65536):
                        chunks.append(chunk)
                    current = (True, b"".join(chunks))
                else:
                    current = (path.exists(), path.read_bytes() if path.exists() else b"")
            before = (entry.existed, entry.data)
            if current == before:
                simulated[entry.path] = before
                continue
            postimage_matches = (
                entry.postimage_existed is not None
                and current[0] is entry.postimage_existed
                and hashlib.sha256(current[1]).hexdigest() == entry.postimage_sha256
            )
            if not postimage_matches:
                raise RuntimeError(f"rollback refused: postimage changed for {entry.path}")
            target = targets[entry.path]
            if entry.existed and target.exists() and target.stat().st_nlink > 1:
                raise RuntimeError(f"rollback refused hardlinked postimage: {entry.path}")
            restore.append(entry)
            simulated[entry.path] = before

        final_restore = {entry.path: entry for entry in restore}
        for entry in final_restore.values():
            path = targets[entry.path]
            if entry.existed:
                path.parent.mkdir(parents=True, exist_ok=True)
                if os.name == "nt":
                    if entry.path in pinned:
                        _dyn_write_windows_rollback_file(pinned[entry.path][1], entry.data)
                    else:
                        with path.open("xb") as target:
                            target.write(entry.data)
                else:
                    path.write_bytes(entry.data)
            else:
                if os.name == "nt" and entry.path in pinned:
                    _dyn_delete_windows_rollback_file(pinned[entry.path][0])
                elif os.name != "nt":
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                elif path.exists():
                    raise RuntimeError(f"rollback refused unpinned replacement: {entry.path}")

    def _rollback_transaction(
        self, work_id: str, root: Path, journal: list[_JournalEntry], *,
        keep: bool = False, attempt: WorkAttemptFence | None = None,
        task_guard: tuple[Any, str, str] | None = None, allowed_paths: list[str] | None = None,
    ) -> bool:
        pending = False
        if task_guard is not None:
            task = task_guard[0].get(task_guard[1])
            state = getattr(getattr(task, "checkpoint", None), "state_data", None)
            marker = state.get("_pending_fenced_work") if isinstance(state, dict) else None
            pending = isinstance(marker, dict) and marker.get("work_id") == work_id
        if not journal and not pending:
            self._clear_journal(work_id, attempt=attempt)
            return False
        root = root.resolve(strict=False)
        resource = canonical_resource(root)
        if attempt is not None and attempt.work_id != work_id:
            raise LeaseLostError("work attempt does not own this rollback journal")
        if any(
            entry.fencing_token <= 0
            or entry.fencing_resource != resource
            or not entry.fencing_lease_id
            or not entry.fencing_owner
            or not entry.attempt_id
            or entry.attempt_token <= 0
            for entry in journal
        ):
            raise RuntimeError("work journal lacks authoritative writer fencing metadata")
        paths = normalize_paths([entry.path for entry in journal] if journal else (allowed_paths or []), root=root)
        coordination_id = self._coordination_id(root)
        owns_attempt = attempt is None
        if attempt is None:
            attempt = self.fencing_store.claim_attempt(
                str(root), work_id, f"rollback:{work_id}:{uuid.uuid4().hex}", ttl_seconds=900,
                coordination_id=coordination_id,
            )
        fence: FencingLease | None = None
        try:
            fence = self.fencing_store.acquire(
                str(root), f"rollback:{work_id}:{uuid.uuid4().hex}", paths,
                ttl_seconds=900, attempt=attempt, coordination_id=coordination_id,
            )
            had_journal = bool(journal)
            def finish_rollback() -> None:
                if keep or not self.rollback_on_failure:
                    # The caller explicitly owns the partially-mutated workspace from here.
                    self._clear_journal(work_id)
                    return
                if journal:
                    self._rollback(root, journal)
                    if not self._record_recovery_checkpoint(work_id, journal):
                        raise RuntimeError("work rollback state changed before checkpoint")
                    journal.clear()
                self._clear_journal(work_id)
            if pending:
                task_store, task_id, owner = task_guard
                task_store._finish_fenced_work_mutation(
                    task_id, root=str(root), owner=owner, fencing_store=self.fencing_store,
                    lease=fence, attempt=attempt, paths=list(paths),
                    rollback=not (keep or not self.rollback_on_failure), finalize=finish_rollback,
                )
            else:
                with self.fencing_store.commit_guard(fence, paths):
                    finish_rollback()
            return had_journal and not (keep or not self.rollback_on_failure)
        finally:
            if fence is not None:
                try:
                    self.fencing_store.release(fence)
                except Exception:
                    pass
            if owns_attempt and attempt is not None:
                try:
                    self.fencing_store.release_attempt(attempt)
                except Exception:
                    pass

    def _apply_patch(
        self, root: Path, patch: str, work_id: str,
        journal: list[_JournalEntry], *, permissions: dict[str, Any] | None = None,
        lease_ttl_seconds: int = 900, attempt: WorkAttemptFence | None = None,
        allowed_paths: list[str] | None = None,
        task_guard: tuple[Any, str, str] | None = None,
    ) -> tuple[list[str], str]:
        root = root.resolve()
        if not self.allow_edits: raise PermissionError("work orchestrator edits are disabled")
        if attempt is not None and (attempt.work_id != work_id or attempt.resource != canonical_resource(root)):
            raise LeaseLostError("work attempt does not own this patch target")
        permissions = permissions or {}
        raw=patch.encode("utf-8")
        if len(raw)>self.max_patch_bytes: raise ValueError("patch exceeds configured byte limit")
        if allowed_paths is not None:
            for line in patch.splitlines():
                if (line.startswith(("old mode ", "new mode ", "rename from ", "rename to ",
                                     "copy from ", "copy to ", "GIT binary patch", "Binary files "))
                        or (line.startswith("new file mode ") and line != "new file mode 100644")):
                    raise PermissionError("unsupported git metadata in bounded patch")
        paths, creates, deletes = _patch_changes(patch)
        if not paths or len(paths)>self.max_patch_files: raise ValueError("patch changes no files or exceeds file limit")
        if allowed_paths is not None and any(path.replace("\\", "/") not in allowed_paths for path in paths):
            raise PermissionError("patch exceeds bounded work scope")
        scope_paths = normalize_paths(paths, root=root)
        coordination_id = self._coordination_id(root)
        if creates and (not self.allow_create or not bool(permissions.get("create", True))):
            raise PermissionError(f"file creation disabled: {sorted(creates)[0]}")
        if deletes and (not self.allow_delete or not bool(permissions.get("delete", True))):
            raise PermissionError(f"file deletion disabled: {sorted(deletes)[0]}")
        claim=self.leases.claim_batch(
            owner=work_id,
            root=str(root),
            paths=paths,
            ttl_seconds=lease_ttl_seconds,
            purpose=f"work-order:{work_id}",
            coordination_id=coordination_id,
        )
        if not claim.get("success"): raise RuntimeError(f"edit lease unavailable: {claim.get('error','conflict')}")
        lease_id=str(claim.get("lease_id", ""))
        owns_attempt = attempt is None
        if attempt is None:
            try:
                attempt = self.fencing_store.claim_attempt(
                    str(root), work_id, f"work:{work_id}:{uuid.uuid4().hex}",
                    ttl_seconds=lease_ttl_seconds,
                    coordination_id=coordination_id,
                )
            except Exception as exc:
                try:
                    self.leases.release(owner=work_id, lease_id=lease_id)
                except Exception:
                    pass
                raise RuntimeError(f"work attempt fence unavailable: {exc}") from exc
        fence: FencingLease | None = None
        try:
            fence = self.fencing_store.acquire(
                str(root), f"work:{work_id}:{uuid.uuid4().hex}", scope_paths,
                ttl_seconds=lease_ttl_seconds, attempt=attempt,
                coordination_id=coordination_id,
            )
        except Exception as exc:
            try:
                self.leases.release(owner=work_id, lease_id=lease_id)
            except Exception:
                pass
            if owns_attempt and attempt is not None:
                try:
                    self.fencing_store.release_attempt(attempt)
                except Exception:
                    pass
            raise RuntimeError(f"writer fence unavailable: {exc}") from exc

        journal_start = len(journal)
        try:
            if task_guard is not None:
                task_store, task_id, task_owner = task_guard
                task_store._begin_fenced_work_mutation(
                    task_id, root=str(root), owner=task_owner, fencing_store=self.fencing_store,
                    lease=fence, attempt=attempt, paths=list(scope_paths),
                )
            path_guard = _dyn_pin_windows_work_directories(root, paths) if allowed_paths is not None else nullcontext()
            with self.fencing_store.commit_guard(fence, scope_paths), path_guard:
                snap = self._snapshot(root, paths)
                postimages = self._preview_postimages(patch, snap)
                entries = [
                    _JournalEntry(
                        before.path,
                        before.existed,
                        before.data,
                        after.existed,
                        hashlib.sha256(after.data).hexdigest(),
                        fence.resource,
                        fence.lease_id,
                        fence.owner_id,
                        fence.fencing_token,
                        attempt.attempt_id,
                        attempt.fencing_token,
                    )
                    for before, after in zip(snap, postimages)
                ]
                journal.extend(entries)
                try:
                    # Persist both images under the fence before mutating source.
                    self._persist_journal(work_id, journal)
                    check=_run_git_patch(["git","-C",str(root),"apply","--recount","--check","--whitespace=nowarn","-"], patch)
                    recount_used = True
                    if check.returncode != 0:
                        fallback_check = _run_git_patch(["git","-C",str(root),"apply","--check","--whitespace=nowarn","-"], patch)
                        if fallback_check.returncode == 0:
                            check = fallback_check
                            recount_used = False
                        else:
                            raise ValueError((check.stderr or check.stdout or fallback_check.stderr or "git apply --check failed")[:1000])
                    applied_cmd = ["git", "-C", str(root), "apply"]
                    if recount_used:
                        applied_cmd.append("--recount")
                    applied_cmd.extend(["--whitespace=nowarn", "-"])
                    applied=_run_git_patch(applied_cmd, patch)
                    if applied.returncode != 0: raise ValueError((applied.stderr or applied.stdout or "git apply failed")[:1000])
                    actual = self._snapshot(root, paths)
                    if any(
                        got.existed != expected.postimage_existed
                        or hashlib.sha256(got.data).hexdigest() != expected.postimage_sha256
                        for got, expected in zip(actual, entries)
                    ):
                        raise RuntimeError("applied patch did not match its journaled postimage")
                except Exception:
                    self._rollback(root, entries)
                    del journal[journal_start:]
                    self._persist_journal(work_id, journal)
                    raise
            return paths, lease_id
        except Exception:
            try:
                self.leases.release(owner=work_id, lease_id=lease_id)
            except Exception:
                pass
            raise
        finally:
            if fence is not None:
                try:
                    self.fencing_store.release(fence)
                except Exception:
                    pass
            if owns_attempt and attempt is not None:
                try:
                    self.fencing_store.release_attempt(attempt)
                except Exception:
                    pass

