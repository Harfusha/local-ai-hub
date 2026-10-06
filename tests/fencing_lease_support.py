from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any


class FakeFencingLeaseStore:
    """Deterministic in-process stand-in for T16's cross-process fencing API."""

    def __init__(self, clock=time.time) -> None:
        self.clock = clock
        self.lock = threading.RLock()
        self.leases: dict[str, Any] = {}
        self.attempts: dict[tuple[str, str], Any] = {}
        self.generations: dict[str, int] = {}
        self.attempt_generations: dict[str, int] = {}

    @staticmethod
    def _normalize(paths) -> tuple[str, ...]:
        return tuple(sorted(str(path).replace("\\", "/").strip("/") for path in paths))

    @staticmethod
    def _overlaps(left: str, right: str) -> bool:
        return left == right or left.startswith(right + "/") or right.startswith(left + "/")

    def claim_attempt(self, resource, work_id, owner_id, *, ttl_seconds):
        with self.lock:
            now = self.clock()
            key = (resource, work_id)
            current = self.attempts.get(key)
            if current is not None and current.expires_at > now:
                raise RuntimeError("work attempt is already active")
            token = self.attempt_generations.get(resource, 0) + 1
            self.attempt_generations[resource] = token
            attempt = SimpleNamespace(
                resource=resource,
                work_id=work_id,
                attempt_id=f"attempt-{uuid.uuid4().hex}",
                owner_id=owner_id,
                fencing_token=token,
                expires_at=now + ttl_seconds,
            )
            self.attempts[key] = attempt
            return attempt

    def renew_attempt(self, attempt, *, ttl_seconds):
        with self.lock:
            self.assert_attempt_current(attempt)
            renewed = SimpleNamespace(
                resource=attempt.resource,
                work_id=attempt.work_id,
                attempt_id=attempt.attempt_id,
                owner_id=attempt.owner_id,
                fencing_token=attempt.fencing_token,
                expires_at=self.clock() + ttl_seconds,
            )
            self.attempts[(attempt.resource, attempt.work_id)] = renewed
            return renewed

    def release_attempt(self, attempt):
        with self.lock:
            key = (attempt.resource, attempt.work_id)
            current = self.attempts.get(key)
            if current is None or current.fencing_token != attempt.fencing_token:
                return False
            del self.attempts[key]
            return True

    def assert_attempt_current(self, attempt):
        current = self.attempts.get((attempt.resource, attempt.work_id))
        if (
            current is None
            or current.attempt_id != attempt.attempt_id
            or current.owner_id != attempt.owner_id
            or current.fencing_token != attempt.fencing_token
            or current.expires_at <= self.clock()
        ):
            raise RuntimeError("work attempt fence is expired or stale")

    def acquire(self, resource, owner_id, paths, *, ttl_seconds, attempt=None):
        normalized = self._normalize(paths)
        with self.lock:
            now = self.clock()
            if attempt is not None:
                self.assert_attempt_current(attempt)
            self.leases = {
                lease_id: lease for lease_id, lease in self.leases.items()
                if lease.expires_at > now
            }
            for current in self.leases.values():
                if current.resource == resource and any(
                    self._overlaps(left, right)
                    for left in normalized for right in current.paths
                ):
                    raise RuntimeError("write scope overlaps active fenced lease")
            token = self.generations.get(resource, 0) + 1
            self.generations[resource] = token
            lease = SimpleNamespace(
                resource=resource,
                lease_id=f"fence-{uuid.uuid4().hex}",
                owner_id=owner_id,
                fencing_token=token,
                expires_at=now + ttl_seconds,
                paths=normalized,
                attempt=attempt,
            )
            self.leases[lease.lease_id] = lease
            return lease

    def renew(self, lease, *, ttl_seconds):
        with self.lock:
            self.assert_current(lease)
            renewed = SimpleNamespace(
                resource=lease.resource,
                lease_id=lease.lease_id,
                owner_id=lease.owner_id,
                fencing_token=lease.fencing_token,
                expires_at=self.clock() + ttl_seconds,
                paths=lease.paths,
                attempt=lease.attempt,
            )
            self.leases[lease.lease_id] = renewed
            return renewed

    def release(self, lease):
        with self.lock:
            current = self.leases.get(lease.lease_id)
            if current is None or current.fencing_token != lease.fencing_token:
                return False
            del self.leases[lease.lease_id]
            return True

    def assert_current(self, lease, actual_paths=()):
        with self.lock:
            current = self.leases.get(lease.lease_id)
            if (
                current is None
                or current.owner_id != lease.owner_id
                or current.fencing_token != lease.fencing_token
                or current.expires_at <= self.clock()
            ):
                raise RuntimeError("mutation fencing lease is expired or stale")
            if current.attempt is not None:
                self.assert_attempt_current(current.attempt)
            if not set(self._normalize(actual_paths)).issubset(current.paths):
                raise RuntimeError("mutation exceeds fenced write set")

    @contextmanager
    def commit_guard(self, lease, actual_paths):
        with self.lock:
            self.assert_current(lease, actual_paths)
            yield


def install_test_work_attempt_fence(broker, store, *, work_id="task-owned", owner_id="test-caller"):
    """Model T16 passing a task-owned live attempt into broker mutation calls."""
    broker.set_fencing_lease_store(store)
    attempts = {}

    def wrap(method_name, root_getter):
        original = getattr(broker, method_name)

        def invoke(*args, **kwargs):
            if kwargs.get("_work_attempt_fence") is None:
                root = str(root_getter(args, kwargs))
                resource = str(Path(root).resolve())
                current_work_id = str(kwargs.get("task_id") or work_id)
                key = (resource, current_work_id)
                attempt = attempts.get(key)
                if attempt is None:
                    attempt = store.claim_attempt(
                        resource, current_work_id, owner_id, ttl_seconds=3600.0
                    )
                    attempts[key] = attempt
                kwargs["_work_attempt_fence"] = attempt
            return original(*args, **kwargs)

        setattr(broker, method_name, invoke)

    def positional_root(index):
        return lambda args, kwargs: kwargs.get("cwd", kwargs.get("root", args[index] if len(args) > index else ""))

    wrap("run", positional_root(1))
    wrap("patch_and_verify", positional_root(1))
    wrap("repair_loop", positional_root(1))
    wrap("format", positional_root(0))
    wrap("lint_fix", positional_root(0))
    return store
