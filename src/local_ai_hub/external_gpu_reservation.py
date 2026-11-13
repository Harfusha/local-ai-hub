"""Cross-process, generation-fenced metadata for external GPU reservations."""

from __future__ import annotations

import contextlib
import hmac
import json
import math
import os
import re
import stat
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterator


_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def conservative_gpu_capacity_budget_bytes() -> int | None:
    """Return a telemetry-backed full-device owner cap, or fail closed."""
    try:
        from .gpu_monitor import get_gpu_telemetry

        telemetry = get_gpu_telemetry()
    except Exception:
        return None
    if not isinstance(telemetry, dict) or telemetry.get("available") is not True:
        return None
    total_mb = telemetry.get("vram_total_mb")
    if isinstance(total_mb, bool) or not isinstance(total_mb, (int, float)) or not math.isfinite(total_mb) or total_mb <= 0:
        total_mb = telemetry.get("unified_memory_mb")
    if isinstance(total_mb, bool) or not isinstance(total_mb, (int, float)) or not math.isfinite(total_mb) or total_mb <= 0:
        return None
    return int(total_mb * 1024 * 1024)


def _validate_capacity_bytes(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class ExternalGpuReservationStore:
    """Persist reservation lease metadata beside the legacy digest fence.

    The digest file remains the scheduler's exclusive fence. Metadata updates
    are serialized with a persistent sidecar lock and compare the generation
    before changing either file. Invalid metadata and unexpired legacy fences fail closed.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        ttl_seconds: float = 60,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if (isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float))
                or not math.isfinite(ttl_seconds) or ttl_seconds <= 0):
            raise ValueError("ttl_seconds must be positive")
        self.path = Path(path)
        self.metadata_path = self.path.with_name(self.path.name + ".lease.json")
        self.capacity_leases_path = self.path.with_name(self.path.name + ".capacity.json")
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.audit_path = self.path.with_name(self.path.name + ".audit.jsonl")
        self.operator_release_path = self.path.with_name(self.path.name + ".operator-release.json")
        self.ttl_seconds = float(ttl_seconds)
        self._clock = clock

    def operator_release_marker(self) -> str | None:
        """Return the latest durable consented-release marker for scheduler reconciliation."""
        with self._locked():
            return self._operator_release_marker_unlocked()

    def read(self) -> dict[str, Any] | None:
        with self._locked():
            return self._read_unlocked()

    def status_snapshot(self) -> tuple[dict[str, Any] | None, bool, str | None]:
        """Observe metadata and fence presence under the same reservation lock."""
        with self._locked():
            record = self._read_unlocked()
            present = record is not None or self.path.exists() or self.path.is_symlink()
            reason_code = None
            if record is None and present:
                if self.path.is_symlink():
                    reason_code = "reservation_fence_symlink"
                elif self.metadata_path.is_symlink():
                    reason_code = "reservation_metadata_symlink"
                elif not self.path.exists():
                    reason_code = "reservation_metadata_without_fence"
                elif self.metadata_path.exists():
                    reason_code = "reservation_metadata_invalid_or_mismatched"
                elif self._read_internal_digest_unlocked() is not None:
                    reason_code = "legacy_digest_only_fence"
                else:
                    reason_code = "reservation_fence_unreadable"
            return record, present, reason_code

    def scheduler_snapshot(self) -> tuple[bool, dict[str, Any] | None, str | None]:
        """Reap expired state and read scheduler metadata under one file lock."""
        with self._locked():
            record = self._read_unlocked()
            if record is None:
                reaped = self._reap_expired_legacy_fence_unlocked()
            elif (record["expires_at"] <= self._clock()
                  and not self._has_capacity_lease_for_generation_unlocked(record["generation"])):
                reaped = self._remove_unlocked(record["generation"])
                record = None if reaped else self._read_unlocked()
            else:
                reaped = False
            return reaped, record, self._operator_release_marker_unlocked()

    def _operator_release_marker_unlocked(self) -> str | None:
        if self.operator_release_path.is_symlink():
            return None
        try:
            if self.operator_release_path.stat().st_size > 1024:
                return None
            payload = json.loads(self.operator_release_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        marker = payload.get("release_id") if isinstance(payload, dict) else None
        return marker if isinstance(marker, str) and re.fullmatch(r"[0-9a-f]{32}", marker) else None

    def owns_internal_fence(self, digest: str) -> bool:
        """Verify a scheduler-owned digest-only fence without trusting metadata."""
        _validate_digest(digest)
        with self._locked():
            if (self.path.is_symlink() or self.metadata_path.is_symlink()
                    or self.metadata_path.exists()):
                return False
            try:
                with self.path.open("rb") as stream:
                    info = os.fstat(stream.fileno())
                    raw = stream.read(65)
                    after = os.fstat(stream.fileno())
                    current = self.path.stat(follow_symlinks=False)
                return (stat.S_ISREG(info.st_mode) and info.st_size == 64
                        and not self.path.is_symlink()
                        and os.path.samestat(info, after) and os.path.samestat(after, current)
                        and hmac.compare_digest(raw, digest.encode("ascii")))
            except OSError:
                return False

    def reap_expired(self) -> bool:
        with self._locked():
            record = self._read_unlocked()
            if record is None:
                return self._reap_expired_legacy_fence_unlocked()
            if record["expires_at"] > self._clock():
                return False
            return self._remove_unlocked(record["generation"])

    def _reap_expired_legacy_fence_unlocked(self) -> bool:
        """Clear only a valid digest-only fence after one full lease TTL."""
        if self.metadata_path.exists() or self.path.is_symlink():
            return False
        try:
            with self.path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size != 64:
                    return False
                raw_digest = stream.read(65)
                after = os.fstat(stream.fileno())
            current = self.path.stat(follow_symlinks=False)
            if (
                not os.path.samestat(before, after)
                or not os.path.samestat(after, current)
                or len(raw_digest) != 64
            ):
                return False
            _validate_digest(raw_digest.decode("ascii"))
        except (OSError, UnicodeDecodeError, ValueError):
            return False

        expires_at = after.st_mtime + self.ttl_seconds
        now = self._clock()
        if not math.isfinite(expires_at) or expires_at > now:
            return False
        event = {
            "action": "legacy_fence_expired",
            "owner": "unknown",
            "reason": "valid digest-only legacy fence exceeded the configured lease TTL",
            "expires_at": expires_at,
            "released_at": now,
        }
        try:
            self._append_audit(event)
            self.path.unlink()
        except OSError:
            return False
        return True

    def claim_internal(self, digest: str) -> bool:
        _validate_digest(digest)
        with self._locked():
            record = self._read_unlocked()
            if record is not None and record["expires_at"] <= self._clock():
                self._remove_unlocked(record["generation"])
            elif record is None:
                self._reap_expired_legacy_fence_unlocked()
            if (self.path.exists() or self.metadata_path.exists()
                    or self.capacity_leases_path.exists() or self.capacity_leases_path.is_symlink()):
                return False
            try:
                self._write_digest_exclusive(digest)
                return True
            except OSError:
                return False

    def renew_internal(self, digest: str) -> bool:
        """Refresh a live digest-only internal fence without changing ownership."""
        _validate_digest(digest)
        with self._locked():
            for attempt in range(6):
                if self.metadata_path.exists() or self.path.is_symlink():
                    return False
                try:
                    with self.path.open("rb") as stream:
                        before = os.fstat(stream.fileno())
                        if not stat.S_ISREG(before.st_mode) or before.st_size != 64:
                            return False
                        raw_digest = stream.read(65)
                        after = os.fstat(stream.fileno())
                        current = self.path.stat(follow_symlinks=False)
                        if (not os.path.samestat(before, after)
                                or not os.path.samestat(after, current)
                                or raw_digest.decode("ascii") != digest):
                            return False
                        now = self._clock()
                        os.utime(self.path, (now, now))
                        renewed = os.fstat(stream.fileno())
                        if self.path.is_symlink():
                            return False
                        current = self.path.stat(follow_symlinks=False)
                        return os.path.samestat(after, renewed) and os.path.samestat(renewed, current)
                except UnicodeDecodeError:
                    return False
                except OSError as exc:
                    # Brief Windows sharing violations must not strand the scheduler
                    # in outcome_unknown while the same internal fence is still valid.
                    if getattr(exc, "winerror", None) != 32 or attempt == 5:
                        return False
                    time.sleep(0.01)
            return False

    def release_internal(self, digest: str) -> bool:
        _validate_digest(digest)
        with self._locked():
            for attempt in range(6):
                if self.metadata_path.exists() or self.path.is_symlink():
                    return False
                try:
                    current = self.path.read_text(encoding="ascii")
                except FileNotFoundError:
                    return True
                except OSError:
                    return False
                if not hmac.compare_digest(current, digest):
                    return False
                capacity = self._read_capacity_leases_unlocked()
                if capacity is None or capacity["leases"]:
                    return False
                try:
                    self.path.unlink()
                    return True
                except FileNotFoundError:
                    return True
                except OSError as exc:
                    if getattr(exc, "winerror", None) != 32 or attempt == 5:
                        return False
                    time.sleep(0.01)
            return False

    def reserve(
        self, token_digest: str, *, owner: str, owner_vram_budget_bytes: int,
    ) -> dict[str, Any] | None:
        _validate_digest(token_digest)
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 256:
            raise ValueError("owner must be a non-empty bounded string")
        _validate_capacity_bytes(owner_vram_budget_bytes, "owner_vram_budget_bytes")
        with self._locked():
            capacity = self._read_capacity_leases_unlocked()
            if capacity is None or capacity["leases"]:
                return None
            current = self._read_unlocked()
            if current is not None:
                if current["expires_at"] > self._clock():
                    return None
                if not self._remove_unlocked(current["generation"]):
                    return None
            elif self.path.exists() or self.metadata_path.exists():
                # Legacy, malformed, symlinked, or partially committed state
                # stays fenced unless a valid digest-only lease has expired.
                if not self._reap_expired_legacy_fence_unlocked():
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
            record["owner_vram_budget_bytes"] = owner_vram_budget_bytes
            digest_file_stat = None
            try:
                digest_file_stat = self._write_digest_exclusive(token_digest)
                if not self._write_metadata(record):
                    self._remove_uncommitted_digest_unlocked(token_digest, expected_stat=digest_file_stat)
                    return None
            except OSError:
                if digest_file_stat is not None:
                    self._remove_uncommitted_digest_unlocked(token_digest, expected_stat=digest_file_stat)
                return None
            return dict(record)

    def acquire_capacity_lease(
        self,
        *,
        owner: str,
        requested_bytes: int,
        total_bytes: int,
        available_bytes: int,
        expected_reservation_generation: str | None = None,
        expected_internal_digest: str | None = None,
    ) -> dict[str, Any] | None:
        """Atomically reserve residency budget without unloading another model."""
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 256:
            raise ValueError("owner must be a non-empty bounded string")
        _validate_capacity_bytes(requested_bytes, "requested_bytes")
        _validate_capacity_bytes(total_bytes, "total_bytes")
        if (isinstance(available_bytes, bool) or not isinstance(available_bytes, int)
                or available_bytes < 0 or available_bytes > total_bytes):
            raise ValueError("available_bytes must be a non-negative integer no greater than total_bytes")
        if expected_reservation_generation is not None and (
                not isinstance(expected_reservation_generation, str) or not expected_reservation_generation):
            raise ValueError("expected_reservation_generation must be a non-empty string or None")
        if expected_internal_digest is not None:
            _validate_digest(expected_internal_digest)

        with self._locked():
            reservation = self._read_unlocked()
            if (reservation is not None and reservation["expires_at"] <= self._clock()
                    and not self._has_capacity_lease_for_generation_unlocked(reservation["generation"])):
                if not self._remove_unlocked(reservation["generation"]):
                    return None
                reservation = None
            if expected_internal_digest is not None:
                if (reservation is not None or self.metadata_path.exists()
                        or self.metadata_path.is_symlink()
                        or self._read_internal_digest_unlocked() != expected_internal_digest):
                    return None
                reservation_generation = f"internal:{expected_internal_digest}"
            else:
                if reservation is None and (
                        self.path.exists() or self.path.is_symlink()
                        or self.metadata_path.exists() or self.metadata_path.is_symlink()):
                    return None
                reservation_generation = reservation.get("generation") if reservation else None
            if expected_reservation_generation is not None and reservation_generation != expected_reservation_generation:
                return None

            capacity = self._read_capacity_leases_unlocked()
            if capacity is None or available_bytes < requested_bytes:
                return None
            if any(item["reservation_generation"] != reservation_generation
                   for item in capacity["leases"]):
                return None
            lease_total = sum(item["requested_bytes"] for item in capacity["leases"])
            if lease_total + requested_bytes > total_bytes:
                return None
            lease = {
                "lease_id": uuid.uuid4().hex,
                "generation": uuid.uuid4().hex,
                "owner": owner.strip(),
                "requested_bytes": requested_bytes,
                "reservation_generation": reservation_generation,
                "created_at": self._clock(),
            }
            if len(capacity["leases"]) >= 64:
                return None
            if not self._write_capacity_leases({
                "schema_version": 1,
                "leases": [*capacity["leases"], lease],
            }):
                return None
            return dict(lease)

    def release_capacity_lease(self, lease_id: str, owner: str, generation: str) -> bool:
        if not isinstance(lease_id, str) or not lease_id:
            return False
        if not isinstance(owner, str) or not owner.strip():
            return False
        if not isinstance(generation, str) or not generation:
            return False
        with self._locked():
            capacity = self._read_capacity_leases_unlocked()
            if capacity is None:
                return False
            leases = capacity["leases"]
            matched = [item for item in leases if (
                item["lease_id"] == lease_id
                and item["owner"] == owner
                and item["generation"] == generation
            )]
            if len(matched) != 1:
                return False
            remaining = [item for item in leases if item not in matched]
            return self._write_capacity_leases({"schema_version": 1, "leases": remaining})

    def has_capacity_lease(self) -> bool:
        """Fail closed for malformed ledgers and report active residency claims."""
        with self._locked():
            capacity = self._read_capacity_leases_unlocked()
            if capacity is None:
                return self.capacity_leases_path.exists() or self.capacity_leases_path.is_symlink()
            return bool(capacity["leases"])

    def capacity_snapshot(self, *, expected_internal_digest: str | None = None) -> dict[str, Any] | None:
        """Return validated reservation and lease accounting under the file lock."""
        if expected_internal_digest is not None:
            _validate_digest(expected_internal_digest)
        with self._locked():
            reservation = self._read_unlocked()
            if (reservation is not None and reservation["expires_at"] <= self._clock()
                    and not self._has_capacity_lease_for_generation_unlocked(reservation["generation"])):
                if not self._remove_unlocked(reservation["generation"]):
                    return None
                reservation = None
            internal_fence_digest = None
            if expected_internal_digest is not None:
                if (reservation is not None or self.metadata_path.exists()
                        or self.metadata_path.is_symlink()
                        or self._read_internal_digest_unlocked() != expected_internal_digest):
                    return None
                internal_fence_digest = expected_internal_digest
            elif reservation is None and (
                    self.path.exists() or self.path.is_symlink()
                    or self.metadata_path.exists() or self.metadata_path.is_symlink()):
                return None
            leases = self._read_capacity_leases_unlocked()
            if leases is None:
                return None
            reservation_generation = (
                reservation.get("generation") if reservation is not None
                else f"internal:{internal_fence_digest}" if internal_fence_digest is not None
                else None
            )
            if any(item["reservation_generation"] != reservation_generation for item in leases["leases"]):
                return None
            snapshot = {
                "reservation": dict(reservation) if reservation is not None else None,
                "leases": [dict(item) for item in leases["leases"]],
            }
            if internal_fence_digest is not None:
                snapshot["internal_fence_digest"] = internal_fence_digest
            return snapshot

    def _read_internal_digest_unlocked(self) -> str | None:
        if self.path.is_symlink() or self.metadata_path.exists() or self.metadata_path.is_symlink():
            return None
        try:
            with self.path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_size != 64:
                    return None
                raw_digest = stream.read(65)
                after = os.fstat(stream.fileno())
            current = self.path.stat(follow_symlinks=False)
            if (not os.path.samestat(before, after) or not os.path.samestat(after, current)
                    or len(raw_digest) != 64):
                return None
            digest = raw_digest.decode("ascii")
            _validate_digest(digest)
            return digest
        except (OSError, UnicodeDecodeError, ValueError):
            return None

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

    @contextlib.contextmanager
    def keepalive(self, token_digest: str, generation: str, *, state: str = "active") -> Iterator[threading.Event]:
        """Renew an owned reservation until the protected operation finishes.

        The returned event is set if ownership is lost or any renewal fails.
        The daemon worker stops with its owning process, so ordinary TTL
        recovery still applies after process exit.
        """
        _validate_digest(token_digest)
        if not isinstance(generation, str) or not generation:
            raise ValueError("generation must be a non-empty string")
        if not isinstance(state, str) or state not in {"idle", "active"}:
            raise ValueError("state must be idle or active")

        stopped = threading.Event()
        lost = threading.Event()
        interval = self.ttl_seconds / 3.0

        def renew_until_stopped() -> None:
            while not stopped.wait(interval):
                try:
                    if not self.renew(token_digest, generation, state=state):
                        lost.set()
                        return
                except Exception:
                    lost.set()
                    return

        if not self.renew(token_digest, generation, state=state):
            lost.set()
        else:
            worker = threading.Thread(
                target=renew_until_stopped,
                name="gpu-reservation-keepalive",
                daemon=True,
            )
            worker.start()
        try:
            yield lost
        finally:
            stopped.set()
            if "worker" in locals():
                worker.join(timeout=min(2.0, max(interval, 0.05)))

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
            if self._has_capacity_lease_for_generation_unlocked(generation):
                return False
            expired = record["expires_at"] <= self._clock()
            dead_owner_release = (
                not expired
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

    def release_current_with_consent(self, *, consent: bool, audit_reason: str) -> bool:
        if type(consent) is not bool or not consent:
            return False
        if not isinstance(audit_reason, str) or not audit_reason.strip() or len(audit_reason) > 1000:
            return False
        with self._locked():
            if self.metadata_path.is_symlink() or self.path.is_symlink():
                return False

            record = self._read_unlocked()
            if record is not None:
                event = {
                    "action": "consented_release_current_reservation",
                    "generation": record["generation"],
                    "owner": record["owner"],
                    "reason": audit_reason.strip(),
                    "released_at": self._clock(),
                }
                try:
                    self._append_audit(event)
                except OSError:
                    return False
                if not self._write_operator_release_marker():
                    return False
                return self._remove_unlocked(record["generation"])

            if not self.path.exists() and self.metadata_path.exists():
                orphan = self._read_metadata_unlocked()
                if orphan is None:
                    return False
                event = {
                    "action": "consented_release_orphaned_metadata",
                    "generation": orphan["generation"],
                    "owner": orphan["owner"],
                    "reason": audit_reason.strip(),
                    "released_at": self._clock(),
                }
                try:
                    self._append_audit(event)
                    if not self._write_operator_release_marker():
                        return False
                    self.metadata_path.unlink()
                except OSError:
                    return False
                return True

            if self.metadata_path.exists():
                return False
            if not self.path.exists():
                try:
                    self._append_audit({
                        "action": "consented_release_no_current_reservation",
                        "owner": "unknown",
                        "reason": audit_reason.strip(),
                        "released_at": self._clock(),
                    })
                except OSError:
                    return False
                return self._write_operator_release_marker()
            try:
                with self.path.open("rb") as stream:
                    before = os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode) or before.st_size != 64:
                        return False
                    raw_digest = stream.read(65)
                    after = os.fstat(stream.fileno())
                current = self.path.stat(follow_symlinks=False)
                if (
                    not os.path.samestat(before, after)
                    or not os.path.samestat(after, current)
                    or len(raw_digest) != 64
                ):
                    return False
                _validate_digest(raw_digest.decode("ascii"))
            except (OSError, UnicodeDecodeError, ValueError):
                return False

            event = {
                "action": "consented_release_current_legacy_fence",
                "owner": "unknown",
                "reason": audit_reason.strip(),
                "released_at": self._clock(),
            }
            try:
                self._append_audit(event)
                if not self._write_operator_release_marker():
                    return False
                self.path.unlink()
            except OSError:
                return False
            return True

    @staticmethod
    def _owner_process_is_gone(owner: Any) -> bool:
        if not isinstance(owner, str):
            return False
        parts = owner.split(":")
        if len(parts) != 3 or parts[0] not in {"embedding", "reranker"}:
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
                or ("owner_vram_budget_bytes" in record
                    and (isinstance(record.get("owner_vram_budget_bytes"), bool)
                         or not isinstance(record.get("owner_vram_budget_bytes"), int)
                         or record["owner_vram_budget_bytes"] <= 0))
                or any(isinstance(record.get(key), bool) or not isinstance(record.get(key), (int, float))
                       or not math.isfinite(record[key])
                       for key in ("created_at", "updated_at", "expires_at"))):
            return None
        return record

    def _read_capacity_leases_unlocked(self) -> dict[str, Any] | None:
        if self.capacity_leases_path.is_symlink():
            return None
        try:
            with self.capacity_leases_path.open("rb") as stream:
                raw_bytes = stream.read(32_769)
            if len(raw_bytes) > 32_768:
                return None
            payload = json.loads(raw_bytes.decode("utf-8"))
        except FileNotFoundError:
            return {"schema_version": 1, "leases": []}
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if (not isinstance(payload, dict) or payload.get("schema_version") != 1
                or not isinstance(payload.get("leases"), list) or len(payload["leases"]) > 64):
            return None
        lease_ids: set[str] = set()
        generations: set[str] = set()
        for lease in payload["leases"]:
            if (not isinstance(lease, dict)
                    or not isinstance(lease.get("lease_id"), str) or not lease["lease_id"]
                    or not isinstance(lease.get("generation"), str) or not lease["generation"]
                    or not isinstance(lease.get("owner"), str) or not lease["owner"].strip()
                    or isinstance(lease.get("requested_bytes"), bool)
                    or not isinstance(lease.get("requested_bytes"), int) or lease["requested_bytes"] <= 0
                    or (lease.get("reservation_generation") is not None
                        and (not isinstance(lease.get("reservation_generation"), str)
                             or not lease["reservation_generation"]))
                    or isinstance(lease.get("created_at"), bool)
                    or not isinstance(lease.get("created_at"), (int, float))
                    or not math.isfinite(lease["created_at"])):
                return None
            if lease["lease_id"] in lease_ids or lease["generation"] in generations:
                return None
            lease_ids.add(lease["lease_id"])
            generations.add(lease["generation"])
        return payload

    def _write_capacity_leases(self, payload: dict[str, Any]) -> bool:
        if self.capacity_leases_path.is_symlink():
            return False
        if not payload["leases"]:
            try:
                self.capacity_leases_path.unlink(missing_ok=True)
                return True
            except OSError:
                return False
        fd, temp_name = tempfile.mkstemp(
            prefix=self.capacity_leases_path.name + ".", suffix=".tmp", dir=self.capacity_leases_path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.capacity_leases_path)
            return True
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(temp_name)
            return False

    def _has_capacity_lease_for_generation_unlocked(self, generation: str) -> bool:
        capacity = self._read_capacity_leases_unlocked()
        if capacity is None:
            return self.capacity_leases_path.exists() or self.capacity_leases_path.is_symlink()
        return any(item.get("reservation_generation") == generation for item in capacity["leases"])

    def _matches(self, record: dict[str, Any] | None, token_digest: str, generation: str) -> bool:
        return bool(
            record is not None
            and record.get("generation") == generation
            and isinstance(record.get("token_digest"), str)
            and hmac.compare_digest(record["token_digest"], token_digest)
        )

    def _remove_unlocked(self, generation: str) -> bool:
        record = self._read_unlocked()
        if (record is None or record.get("generation") != generation
                or self._has_capacity_lease_for_generation_unlocked(generation)):
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
        for attempt in range(6):
            try:
                if self.metadata_path.is_symlink():
                    return False
                self.metadata_path.unlink()
                return True
            except OSError as exc:
                if getattr(exc, "winerror", None) != 32 or attempt == 5:
                    # Missing metadata with a stale digest is fail-closed; never mask it.
                    return False
                time.sleep(0.01)
                current = self._read_metadata_unlocked()
                if (current is None
                        or current.get("generation") != generation
                        or not hmac.compare_digest(current["token_digest"], record["token_digest"])):
                    return False
        return False

    def _remove_uncommitted_digest_unlocked(
        self, digest: str, *, expected_stat: os.stat_result, allow_prefix: bool = False,
    ) -> bool:
        """Remove only the digest file created by this failed reservation transaction."""
        if self.path.is_symlink() or self.metadata_path.exists() or self.metadata_path.is_symlink():
            return False
        expected = digest.encode("ascii")
        try:
            with self.path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                raw = stream.read(65)
                after = os.fstat(stream.fileno())
                current = self.path.stat(follow_symlinks=False)
            if (not stat.S_ISREG(before.st_mode) or before.st_size > 64
                    or not os.path.samestat(expected_stat, before)
                    or not os.path.samestat(before, after)
                    or not os.path.samestat(after, current)
                    or len(raw) > 64):
                return False
            matches = (expected.startswith(raw) if allow_prefix else raw == expected)
            if not matches or self.path.is_symlink():
                return False
            current = self.path.stat(follow_symlinks=False)
            if not os.path.samestat(after, current):
                return False
            self.path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    def _write_digest_exclusive(self, digest: str) -> os.stat_result:
        created_stat = None
        try:
            with self.path.open("xb") as stream:
                created_stat = os.fstat(stream.fileno())
                stream.write(digest.encode("ascii"))
                stream.flush()
                os.fsync(stream.fileno())
                return os.fstat(stream.fileno())
        except OSError:
            if created_stat is not None:
                self._remove_uncommitted_digest_unlocked(
                    digest, expected_stat=created_stat, allow_prefix=True,
                )
            raise

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

    def _write_operator_release_marker(self) -> bool:
        if self.operator_release_path.is_symlink():
            return False
        fd, temp_name = tempfile.mkstemp(
            prefix=self.operator_release_path.name + ".", suffix=".tmp", dir=self.operator_release_path.parent,
        )
        payload = {"schema_version": 1, "release_id": uuid.uuid4().hex, "released_at": self._clock()}
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, separators=(",", ":"), sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.operator_release_path)
            return True
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(temp_name)
            return False

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        if (self.path.is_symlink() or self.metadata_path.is_symlink() or self.capacity_leases_path.is_symlink()
                or self.lock_path.is_symlink()
                or self.operator_release_path.is_symlink()):
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
