"""Cross-process, generation-fenced metadata for external GPU reservations."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import math
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator


_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class ExternalGpuReservationStore:
    """Persist reservation lease metadata beside the legacy digest fence.

    The digest file remains the scheduler's exclusive fence. Metadata updates
    are serialized with a persistent sidecar lock and compare the generation
    before changing either file. Invalid and legacy records fail closed.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        ttl_seconds: float = 900,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if (isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float))
                or not math.isfinite(ttl_seconds) or ttl_seconds <= 0):
            raise ValueError("ttl_seconds must be positive")
        self.path = Path(path)
        self.metadata_path = self.path.with_name(self.path.name + ".lease.json")
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.audit_path = self.path.with_name(self.path.name + ".audit.jsonl")
        self.ttl_seconds = float(ttl_seconds)
        self._clock = clock

    def read(self) -> dict[str, Any] | None:
        with self._locked():
            return self._read_unlocked()

    def reap_expired(self) -> bool:
        with self._locked():
            record = self._read_unlocked()
            if record is None or record["expires_at"] > self._clock():
                return False
            return self._remove_unlocked(record["generation"])

    def claim_internal(self, digest: str) -> bool:
        _validate_digest(digest)
        with self._locked():
            record = self._read_unlocked()
            if record is not None and record["expires_at"] <= self._clock():
                self._remove_unlocked(record["generation"])
            if self.path.exists() or self.metadata_path.exists():
                return False
            try:
                self._write_digest_exclusive(digest)
                return True
            except OSError:
                return False

    def release_internal(self, digest: str) -> bool:
        _validate_digest(digest)
        with self._locked():
            if self.metadata_path.exists() or self.path.is_symlink():
                return False
            try:
                current = self.path.read_text(encoding="ascii")
            except OSError:
                return False
            if not hmac.compare_digest(current, digest):
                return False
            try:
                self.path.unlink()
            except OSError:
                return False
            return True

    def reserve(self, token_digest: str, *, owner: str) -> dict[str, Any] | None:
        _validate_digest(token_digest)
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 256:
            raise ValueError("owner must be a non-empty bounded string")
        with self._locked():
            current = self._read_unlocked()
            if current is not None:
                if current["expires_at"] > self._clock():
                    return None
                if not self._remove_unlocked(current["generation"]):
                    return None
            elif self.path.exists() or self.metadata_path.exists():
                # Legacy, malformed, symlinked, or partially committed state.
                # Never infer that it is safe to erase.
                return None
            record = {
                "schema_version": 1,
                "generation": uuid.uuid4().hex,
                "token_digest": token_digest,
                "owner": owner.strip(),
                "state": "idle",
                "created_at": self._clock(),
                "updated_at": self._clock(),
                "expires_at": self._clock() + self.ttl_seconds,
            }
            try:
                self._write_digest_exclusive(token_digest)
                self._write_metadata(record)
            except OSError:
                # A digest without metadata is intentionally left fail-closed.
                return None
            return dict(record)

    def renew(self, token_digest: str, generation: str, *, state: str = "idle") -> bool:
        _validate_digest(token_digest)
        if not isinstance(generation, str) or not generation:
            return False
        if not isinstance(state, str) or state not in {"idle", "active"}:
            return False
        with self._locked():
            record = self._read_unlocked()
            if not self._matches(record, token_digest, generation):
                return False
            now = self._clock()
            updated = {**record, "state": state, "updated_at": now, "expires_at": now + self.ttl_seconds}
            return self._write_metadata(updated)

    def release(self, token_digest: str, generation: str) -> bool:
        _validate_digest(token_digest)
        with self._locked():
            record = self._read_unlocked()
            if not self._matches(record, token_digest, generation) or record["state"] != "idle":
                return False
            return self._remove_unlocked(generation)

    def release_with_consent(self, generation: str, *, consent: bool, audit_reason: str) -> bool:
        if type(consent) is not bool or not consent:
            return False
        if not isinstance(generation, str) or not generation:
            return False
        if not isinstance(audit_reason, str) or not audit_reason.strip() or len(audit_reason) > 1000:
            return False
        with self._locked():
            record = self._read_unlocked()
            metadata_orphan = False
            if record is None:
                # A previous consented cleanup may have removed the digest
                # fence before failing to remove its metadata. Recover only
                # that exact metadata-only state, with explicit generation
                # consent and the same expiry check as a normal release.
                if (self.path.exists() or self.path.is_symlink()
                        or not self.metadata_path.exists() or self.metadata_path.is_symlink()):
                    return False
                record = self._read_metadata_unlocked()
                metadata_orphan = record is not None
            if record is None or record["generation"] != generation:
                return False
            expired = record["expires_at"] <= self._clock()
            dead_owner_release = (
                not metadata_orphan and not expired
                and self._owner_process_is_gone(record.get("owner"))
            )
            if not expired and not dead_owner_release:
                return False
            event = {
                "action": (
                    "consented_release_recovery" if metadata_orphan else
                    "consented_release_dead_owner" if dead_owner_release else
                    "consented_release"
                ),
                "generation": generation,
                "owner": record["owner"],
                "reason": audit_reason.strip(),
                "released_at": self._clock(),
            }
            try:
                self._append_audit(event)
            except OSError:
                return False
            if metadata_orphan:
                try:
                    self.metadata_path.unlink()
                except OSError:
                    return False
                return True
            return self._remove_unlocked(generation)

    @staticmethod
    def _owner_process_is_gone(owner: Any) -> bool:
        if not isinstance(owner, str):
            return False
        parts = owner.split(":")
        if len(parts) != 3 or parts[0] != "reranker":
            return False
        try:
            pid = int(parts[1])
            thread_id = int(parts[2])
        except (TypeError, ValueError):
            return False
        if pid <= 0 or thread_id <= 0:
            return False
        try:
            from .process_utils import process_is_alive

            return process_is_alive(pid) is False
        except Exception:
            return False

    def _read_unlocked(self) -> dict[str, Any] | None:
        if self.path.is_symlink():
            return None
        record = self._read_metadata_unlocked()
        if record is None:
            return None
        try:
            with self.path.open("rb") as stream:
                digest_bytes = stream.read(65)
            if len(digest_bytes) > 64:
                return None
            digest = digest_bytes.decode("ascii")
        except (OSError, UnicodeError):
            return None
        stored_digest = record["token_digest"]
        if not hmac.compare_digest(digest, stored_digest) or not _DIGEST_RE.fullmatch(digest):
            return None
        return record

    def _read_metadata_unlocked(self) -> dict[str, Any] | None:
        if self.metadata_path.is_symlink():
            return None
        try:
            with self.metadata_path.open("rb") as stream:
                raw_bytes = stream.read(16_385)
            if len(raw_bytes) > 16_384:
                return None
            raw = raw_bytes.decode("utf-8")
            record = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(record, dict) or record.get("schema_version") != 1:
            return None
        stored_digest = record.get("token_digest")
        if not isinstance(stored_digest, str) or not _DIGEST_RE.fullmatch(stored_digest):
            return None
        if (not isinstance(record.get("generation"), str) or not record["generation"]
                or not isinstance(record.get("owner"), str)
                or record.get("state") not in {"idle", "active"}
                or any(isinstance(record.get(key), bool) or not isinstance(record.get(key), (int, float))
                       or not math.isfinite(record[key])
                       for key in ("created_at", "updated_at", "expires_at"))):
            return None
        return record

    def _matches(self, record: dict[str, Any] | None, token_digest: str, generation: str) -> bool:
        return bool(
            record is not None
            and record.get("generation") == generation
            and isinstance(record.get("token_digest"), str)
            and hmac.compare_digest(record["token_digest"], token_digest)
        )

    def _remove_unlocked(self, generation: str) -> bool:
        record = self._read_unlocked()
        if record is None or record.get("generation") != generation:
            return False
        for attempt in range(6):
            try:
                self.path.unlink()
                break
            except OSError as exc:
                if getattr(exc, "winerror", None) != 32 or attempt == 5:
                    return False
                time.sleep(0.01)
                current = self._read_unlocked()
                if current is None or current.get("generation") != generation:
                    return False
        try:
            self.metadata_path.unlink()
        except OSError:
            # Missing metadata with a stale digest is fail-closed; never mask it.
            return False
        return True

    def _write_digest_exclusive(self, digest: str) -> None:
        with self.path.open("xb") as stream:
            stream.write(digest.encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())

    def _write_metadata(self, record: dict[str, Any]) -> bool:
        if self.metadata_path.is_symlink():
            return False
        fd, temp_name = tempfile.mkstemp(prefix=self.metadata_path.name + ".", suffix=".tmp", dir=self.metadata_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(record, stream, separators=(",", ":"), sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.metadata_path)
            return True
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(temp_name)
            return False

    def _append_audit(self, event: dict[str, Any]) -> None:
        if self.audit_path.is_symlink():
            raise OSError("audit path cannot be a symlink")
        with self.audit_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        if self.path.is_symlink() or self.metadata_path.is_symlink() or self.lock_path.is_symlink():
            raise OSError("reservation paths cannot be symlinks")
        key = str(self.lock_path.resolve())
        with _LOCKS_GUARD:
            thread_lock = _LOCKS.setdefault(key, threading.RLock())
        with thread_lock:
            with self.lock_path.open("a+b") as stream:
                _lock_file(stream)
                try:
                    yield
                finally:
                    _unlock_file(stream)


def _validate_digest(value: str) -> None:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError("token_digest must be a lowercase SHA-256 digest")


def _lock_file(stream: Any) -> None:
    deadline = time.monotonic() + 5.0
    if os.name == "nt":
        import msvcrt

        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        while True:
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
    else:
        import fcntl

        while True:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)


def _unlock_file(stream: Any) -> None:
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
