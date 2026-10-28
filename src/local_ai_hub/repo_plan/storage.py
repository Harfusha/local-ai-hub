"""Durable write protocol, atomic replacement, and crash recovery for repo plans."""

from __future__ import annotations

import hashlib
import base64
import json
import logging
import os
import subprocess
import time
import uuid
from itertools import islice
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..file_locks import exclusive_file_update
from ..process_utils import clean_git_env, hidden_run_kwargs

from .schema_validation import (
    RepoPlanConflictError,
    RepoPlanError,
    RepoPlanValidationError,
    parse_plan_json,
    serialize_plan_json,
    validate_plan_dict,
    validate_repo_path,
)

logger = logging.getLogger(__name__)


def compute_bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_file_sha256(file_path: Path) -> str:
    if not file_path.exists() or not file_path.is_file():
        return ""
    return compute_bytes_sha256(file_path.read_bytes())


def get_git_context(repo_root: Path) -> tuple[str | None, str | None]:
    """Return (branch, head_commit) if git repository is present, else (None, None)."""
    try:
        git_dir = repo_root / ".git"
        if not git_dir.exists():
            return None, None

        cmd_branch = ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"]
        proc_b = subprocess.run(cmd_branch, capture_output=True, timeout=2.0,
                                env=clean_git_env(), **hidden_run_kwargs(text=True))
        branch = proc_b.stdout.strip() if proc_b.returncode == 0 else None

        cmd_head = ["git", "-C", str(repo_root), "rev-parse", "HEAD"]
        proc_h = subprocess.run(cmd_head, capture_output=True, timeout=2.0,
                                env=clean_git_env(), **hidden_run_kwargs(text=True))
        head = proc_h.stdout.strip() if proc_h.returncode == 0 else None

        return branch, head
    except Exception as exc:
        logger.debug("Failed to read git context: %s", exc)
        return None, None


@dataclass
class IntentTarget:
    rel_path: str
    expected_sha256: str
    candidate_sha256: str
    status: str = "pending"  # pending, written, confirmed
    candidate_base64: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntentTarget:
        return cls(**data)


@dataclass
class OperationIntent:
    intent_id: str
    operation: str
    idempotency_key: str
    payload_sha256: str
    owner: str
    created_at: float
    status: str  # pending, completed, aborted, reconciled
    targets: list[IntentTarget] = field(default_factory=list)
    git_branch: str | None = None
    git_head: str | None = None
    context: dict[str, Any] | None = None
    result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "operation": self.operation,
            "idempotency_key": self.idempotency_key,
            "payload_sha256": self.payload_sha256,
            "owner": self.owner,
            "created_at": self.created_at,
            "status": self.status,
            "targets": [t.to_dict() for t in self.targets],
            "git_branch": self.git_branch,
            "git_head": self.git_head,
            "context": self.context,
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OperationIntent:
        targets = [IntentTarget.from_dict(t) for t in data.get("targets", [])]
        return cls(
            intent_id=data.get("intent_id", ""),
            operation=data.get("operation", ""),
            idempotency_key=data.get("idempotency_key", ""),
            payload_sha256=data.get("payload_sha256", ""),
            owner=data.get("owner", ""),
            created_at=float(data.get("created_at", 0.0)),
            status=data.get("status", "pending"),
            targets=targets,
            git_branch=data.get("git_branch"),
            git_head=data.get("git_head"),
            context=data.get("context"),
            result=data.get("result"),
        )


class RepoPlanStorage:
    """Manages atomic, durable, revision-checked reads and writes for plan files."""

    def __init__(self, repo_root: str | Path, intents_dir: str | Path | None = None) -> None:
        self.repo_root = Path(repo_root).resolve()
        try:
            relative_intents_dir = (
                ".local-ai-hub/local/intents" if intents_dir is None else os.fspath(intents_dir)
            )
        except TypeError as exc:
            raise RepoPlanError("Intent directory must be a project-relative path") from exc
        if not isinstance(relative_intents_dir, str):
            raise RepoPlanError("Intent directory must be a project-relative path")
        requested_intents_dir = Path(relative_intents_dir)
        if requested_intents_dir.is_absolute():
            resolved_intents_dir = requested_intents_dir.resolve()
            try:
                relative_intents_dir = resolved_intents_dir.relative_to(self.repo_root).as_posix()
            except ValueError as exc:
                raise RepoPlanValidationError(
                    f"Intent directory escapes repository root '{self.repo_root}'"
                ) from exc
        validate_repo_path(relative_intents_dir, repo_root=self.repo_root)
        self.intents_dir_rel = relative_intents_dir
        self.intents_dir = self.repo_root / relative_intents_dir
        self._lock_path = self.repo_root / ".local-ai-hub" / "local" / "repo-plan-storage"

    def _ensure_intents_dir(self) -> None:
        validate_repo_path(self.intents_dir_rel, repo_root=self.repo_root)
        validate_repo_path(".local-ai-hub/local/repo-plan-storage", repo_root=self.repo_root)
        self.intents_dir.mkdir(parents=True, exist_ok=True)
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)

    def _intent_path(self, intent_id: str) -> Path:
        if not intent_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in intent_id):
            raise RepoPlanError("Invalid operation intent identity")
        return self.intents_dir / f"{intent_id}.intent.json"

    def _save_intent(self, intent: OperationIntent) -> None:
        self._ensure_intents_dir()
        path = self._intent_path(intent.intent_id)
        raw = json.dumps(intent.to_dict(), indent=2, sort_keys=True)
        temp_path = self.intents_dir / f".tmp_{intent.intent_id}_{uuid.uuid4().hex[:6]}"
        try:
            with open(temp_path, "wb") as f:
                f.write(raw.encode("utf-8"))
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _atomic_write_bytes(self, target_path: Path, data: bytes) -> None:
        """Write bytes to target_path using atomic replacement with Windows file-sharing retries."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.parent / f".tmp_{target_path.name}_{uuid.uuid4().hex[:8]}"

        try:
            with open(temp_path, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())

            # Windows-friendly retry loop for os.replace in case of AV / sharing locks
            last_err: Exception | None = None
            for attempt in range(8):
                try:
                    os.replace(temp_path, target_path)
                    last_err = None
                    break
                except (PermissionError, OSError) as exc:
                    last_err = exc
                    time.sleep(0.02 * (2**attempt))

            if last_err is not None:
                raise OSError(f"Failed to atomically write {target_path}: {last_err}") from last_err
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def read_plan_file(self, rel_path: str) -> tuple[dict[str, Any], str]:
        """Read plan file, returning (parsed_dict, content_sha256).

        Raises RepoPlanValidationError if invalid, FileNotFoundError if missing.
        """
        validate_repo_path(rel_path, repo_root=self.repo_root)
        full_path = self.repo_root / rel_path
        if not full_path.exists():
            raise FileNotFoundError(f"Plan file not found: {rel_path}")

        raw_bytes = full_path.read_bytes()
        sha = compute_bytes_sha256(raw_bytes)
        data = parse_plan_json(raw_bytes)
        validate_plan_dict(data, repo_root=self.repo_root)
        return data, sha

    def _context(self) -> dict[str, Any]:
        branch, head = get_git_context(self.repo_root)
        marker = self.repo_root / ".git"
        if marker.exists() and (branch is None or head is None):
            raise RepoPlanConflictError("Git context unavailable for repository write")
        identity = str(marker.resolve())
        if marker.is_file():
            identity += ":" + compute_file_sha256(marker)
        return {"root": str(self.repo_root), "git_identity": identity,
                "git_branch": branch, "git_head": head}

    def _check_fence(self, context: dict[str, Any], lease_check_fn: Callable[[], bool] | None) -> None:
        if lease_check_fn is not None and not lease_check_fn():
            raise RepoPlanConflictError("Writer lease expired or invalid during save fence")
        if self._context() != context:
            raise RepoPlanConflictError("Repository or Git context changed during save")

    def _request_path(self, key: str) -> Path:
        digest = compute_bytes_sha256(key.encode("utf-8"))
        return self.intents_dir / f"request_{digest}.json"

    def _save_request(self, key: str, data: dict[str, Any]) -> None:
        if key:
            if not self._request_path(key).exists() and len(list(islice(self.intents_dir.glob("request_*.json"), 4096))) >= 4096:
                raise RepoPlanError("Idempotency record capacity reached; explicit archival required")
            self._atomic_record(self._request_path(key), data)

    @staticmethod
    def _read_record(path: Path) -> dict[str, Any]:
        if path.stat().st_size > 12 * 1024 * 1024:
            raise RepoPlanError("Operation record exceeds 12 MiB limit")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise RepoPlanError("Operation record must be an object")
        return data

    def _atomic_record(self, path: Path, data: dict[str, Any]) -> None:
        # Separate from target publication so tests/cancellation can interrupt targets only.
        raw = json.dumps(data, sort_keys=True).encode("utf-8")
        temporary = path.with_name(f".tmp_{uuid.uuid4().hex}")
        try:
            with temporary.open("wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _request_replay(self, key: str, payload_sha: str) -> dict[str, Any] | None:
        if not key or not self._request_path(key).exists():
            return None
        record = self._read_record(self._request_path(key))
        if record.get("payload_sha256") != payload_sha:
            raise RepoPlanConflictError(f"Idempotency key '{key}' reused with different payload")
        if record.get("status") == "pending" and record.get("intent_id"):
            intent_path = self._intent_path(record["intent_id"])
            if intent_path.exists():
                intent = OperationIntent.from_dict(self._read_record(intent_path))
                if (intent.status == "completed" and intent.payload_sha256 == payload_sha
                        and intent.idempotency_key == key and isinstance(intent.result, dict)):
                    record = {"payload_sha256": payload_sha, "status": "completed", "result": intent.result}
                    self._save_request(key, record)
        if record.get("status") != "completed" or not isinstance(record.get("result"), dict):
            raise RepoPlanConflictError("Idempotent operation remains pending or requires reconciliation")
        return record["result"]

    def save_plan_file(
        self, rel_path: str, plan_dict: dict[str, Any], *,
        expected_revision: str | None = None, owner: str = "agent",
        idempotency_key: str = "", lease_check_fn: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        validate_plan_dict(plan_dict, repo_root=self.repo_root)
        return self._save_targets("save_plan", [(rel_path, serialize_plan_json(plan_dict).encode("utf-8"), expected_revision)],
                                  owner, idempotency_key, lease_check_fn)

    def save_spec_and_plan(
        self, spec_rel_path: str, spec_content: str, plan_rel_path: str,
        plan_dict: dict[str, Any], *, expected_spec_rev: str | None = None,
        expected_plan_rev: str | None = None, owner: str = "agent",
        idempotency_key: str = "", lease_check_fn: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        validate_plan_dict(plan_dict, repo_root=self.repo_root)
        return self._save_targets("save_spec_and_plan", [
            (spec_rel_path, spec_content.encode("utf-8"), expected_spec_rev),
            (plan_rel_path, serialize_plan_json(plan_dict).encode("utf-8"), expected_plan_rev),
        ], owner, idempotency_key, lease_check_fn)

    def _save_targets(
        self, operation: str, candidates: list[tuple[str, bytes, str | None]],
        owner: str, key: str, lease_check_fn: Callable[[], bool] | None,
    ) -> dict[str, Any]:
        paths = [path for path, _, _ in candidates]
        if not isinstance(owner, str) or not owner or len(owner) > 256:
            raise RepoPlanError("Operation owner must be a nonempty string of at most 256 characters")
        if not isinstance(key, str) or len(key) > 1024:
            raise RepoPlanError("Idempotency key must be a string of at most 1024 characters")
        for path in paths:
            validate_repo_path(path, repo_root=self.repo_root)
        if len({str((self.repo_root / path).resolve()).casefold() if os.name == "nt" else str((self.repo_root / path).resolve()) for path in paths}) != len(paths):
            raise RepoPlanConflictError("Operation targets must be distinct files")
        if sum(len(data) for _, data, _ in candidates) > 8 * 1024 * 1024:
            raise RepoPlanError("Recovery candidate exceeds 8 MiB operation limit")
        self._ensure_intents_dir()
        # One physical-worktree lock covers revision checks, request keys, both targets,
        # and recovery. A custom intents directory must not create another lock domain.
        with exclusive_file_update(self._lock_path, reentrant=True):
            context = self._context()
            self._check_fence(context, lease_check_fn)
            fingerprint = {"operation": operation, "owner": owner, "context": context,
                           "targets": [{"path": path, "candidate": compute_bytes_sha256(data), "expected": expected}
                                       for path, data, expected in candidates]}
            payload_sha = compute_bytes_sha256(json.dumps(fingerprint, sort_keys=True).encode("utf-8"))
            replay = self._request_replay(key, payload_sha)
            if replay is not None:
                return replay
            targets = []
            for path, data, expected in candidates:
                actual = compute_file_sha256(self.repo_root / path)
                if expected is not None and expected != actual:
                    raise RepoPlanConflictError(f"Content revision conflict on {path}: expected {expected}, found {actual}")
                targets.append(IntentTarget(path, actual, compute_bytes_sha256(data),
                                            candidate_base64=base64.b64encode(data).decode("ascii")))
            changed = [target.rel_path for target in targets if target.expected_sha256 != target.candidate_sha256]
            result: dict[str, Any] = {"success": True, "saved": True, "no_op": not changed, "changed_paths": changed}
            if operation == "save_plan":
                result["file_revision"] = targets[0].candidate_sha256
            else:
                result.update(spec_revision=targets[0].candidate_sha256, plan_revision=targets[1].candidate_sha256)
            if not changed:
                self._save_request(key, {"payload_sha256": payload_sha, "status": "completed", "result": result})
                return result
            # No automatic retention eviction: retry keys never silently become reusable.
            # Capacity exhaustion is explicit; unresolved operations remain recoverable.
            if len(list(islice(self.intents_dir.glob("*.intent.json"), 4096))) >= 4096:
                raise RepoPlanError("Operation intent capacity reached; explicit archival required")
            intent_id = f"intent_{uuid.uuid4().hex}"
            result["intent_id"] = intent_id
            intent = OperationIntent(intent_id, operation, key, payload_sha, owner, time.time(), "pending", targets,
                                     context["git_branch"], context["git_head"], context, result)
            self._save_request(key, {"payload_sha256": payload_sha, "status": "pending", "intent_id": intent_id})
            self._save_intent(intent)
            for target, (_, data, _) in zip(targets, candidates):
                self._check_fence(context, lease_check_fn)
                validate_repo_path(target.rel_path, repo_root=self.repo_root)
                if compute_file_sha256(self.repo_root / target.rel_path) != target.expected_sha256:
                    raise RepoPlanConflictError(f"Content revision conflict before publish: {target.rel_path}")
                if target.expected_sha256 != target.candidate_sha256:
                    self._atomic_write_bytes(self.repo_root / target.rel_path, data)
                if compute_file_sha256(self.repo_root / target.rel_path) != target.candidate_sha256:
                    raise RepoPlanError(f"Stored byte verification failed: {target.rel_path}")
                target.status = "confirmed"
                self._save_intent(intent)
            self._check_fence(context, lease_check_fn)
            for target in targets:
                if compute_file_sha256(self.repo_root / target.rel_path) != target.candidate_sha256:
                    raise RepoPlanConflictError(f"Content changed before acknowledgement: {target.rel_path}")
            self._complete_intent(intent)
            return result

    def _complete_intent(self, intent: OperationIntent) -> None:
        intent.status = "completed"
        self._save_intent(intent)
        if intent.result is not None:
            self._save_request(intent.idempotency_key, {"payload_sha256": intent.payload_sha256,
                                                       "status": "completed", "result": intent.result})

    def recover_pending_intents(self, *, lease_check_fn: Callable[[], bool] | None = None) -> list[dict[str, Any]]:
        """Recover only verified partial saves; retain ambiguity for explicit reconciliation."""
        if not self.intents_dir.exists():
            return []
        self._ensure_intents_dir()
        outcomes = []
        with exclusive_file_update(self._lock_path):
            for path in islice(self.intents_dir.glob("*.intent.json"), 4096):
                try:
                    intent = OperationIntent.from_dict(self._read_record(path))
                    if intent.status != "pending":
                        continue
                    if path != self._intent_path(intent.intent_id) or not intent.targets:
                        raise RepoPlanError("Invalid pending intent identity or targets")
                    for target in intent.targets:
                        validate_repo_path(target.rel_path, repo_root=self.repo_root)
                    current = [compute_file_sha256(self.repo_root / target.rel_path) for target in intent.targets]
                    if intent.context is not None and intent.context != self._context():
                        resolution, status = "context_changed", "reconciled"
                    elif all(actual == target.candidate_sha256 for target, actual in zip(intent.targets, current)):
                        self._check_fence(intent.context or self._context(), lease_check_fn)
                        for target in intent.targets:
                            target.status = "confirmed"
                        self._complete_intent(intent)
                        resolution, status = "already_applied", "completed"
                    elif any(actual not in (target.expected_sha256, target.candidate_sha256)
                             for target, actual in zip(intent.targets, current)):
                        resolution, status = "diverged", "reconciled"
                    elif all(actual == target.expected_sha256 for target, actual in zip(intent.targets, current)):
                        resolution, status = "unapplied_discarded", "aborted"
                    elif intent.context is None or any(target.candidate_base64 is None for target in intent.targets):
                        resolution, status = "recovery_material_missing", "pending"
                    else:
                        # Verify every recovery candidate before publishing any remaining file.
                        payloads = [base64.b64decode(target.candidate_base64, validate=True) for target in intent.targets]
                        if sum(map(len, payloads)) > 8 * 1024 * 1024:
                            raise RepoPlanError("Recovery candidate exceeds operation limit")
                        for target, data in zip(intent.targets, payloads):
                            if compute_bytes_sha256(data) != target.candidate_sha256:
                                raise RepoPlanError("Recovery candidate hash mismatch")
                            if target.rel_path.endswith(".plan.json"):
                                validate_plan_dict(parse_plan_json(data), repo_root=self.repo_root)
                        for target, actual, data in zip(intent.targets, current, payloads):
                            self._check_fence(intent.context, lease_check_fn)
                            validate_repo_path(target.rel_path, repo_root=self.repo_root)
                            if compute_file_sha256(self.repo_root / target.rel_path) != actual:
                                raise RepoPlanConflictError("Recovery target changed during reconciliation")
                            if actual != target.candidate_sha256:
                                self._atomic_write_bytes(self.repo_root / target.rel_path, data)
                            target.status = "confirmed"
                            self._save_intent(intent)
                        self._check_fence(intent.context, lease_check_fn)
                        if not all(compute_file_sha256(self.repo_root / t.rel_path) == t.candidate_sha256 for t in intent.targets):
                            raise RepoPlanConflictError("Recovery bytes changed before acknowledgement")
                        self._complete_intent(intent)
                        resolution, status = "forward_recovered", "completed"
                    intent.status = status
                    self._save_intent(intent)
                    outcomes.append({"intent_id": intent.intent_id, "resolution": resolution, "status": status})
                except Exception as exc:
                    # Corrupt records or lost fences never become completion evidence.
                    logger.warning("Pending intent recovery stopped for %s: %s", path, exc)
                    outcomes.append({"intent_id": path.name, "resolution": "recovery_blocked", "status": "pending"})
        return outcomes
