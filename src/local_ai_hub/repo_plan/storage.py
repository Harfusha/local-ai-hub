"""Durable write protocol, atomic replacement, and crash recovery for repo plans."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .schema_validation import (
    RepoPlanConflictError,
    RepoPlanError,
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
        proc_b = subprocess.run(cmd_branch, capture_output=True, text=True, timeout=2.0)
        branch = proc_b.stdout.strip() if proc_b.returncode == 0 else None

        cmd_head = ["git", "-C", str(repo_root), "rev-parse", "HEAD"]
        proc_h = subprocess.run(cmd_head, capture_output=True, text=True, timeout=2.0)
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
        )


class RepoPlanStorage:
    """Manages atomic, durable, revision-checked reads and writes for plan files."""

    def __init__(self, repo_root: str | Path, intents_dir: str | Path | None = None) -> None:
        self.repo_root = Path(repo_root).resolve()
        if intents_dir is not None:
            self.intents_dir = Path(intents_dir).resolve()
        else:
            self.intents_dir = self.repo_root / ".local-ai-hub" / "local" / "intents"
        self._idempotency_cache: dict[str, dict[str, Any]] = {}

    def _ensure_intents_dir(self) -> None:
        self.intents_dir.mkdir(parents=True, exist_ok=True)

    def _intent_path(self, intent_id: str) -> Path:
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
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
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
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass

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

    def save_plan_file(
        self,
        rel_path: str,
        plan_dict: dict[str, Any],
        *,
        expected_revision: str | None = None,
        owner: str = "agent",
        idempotency_key: str = "",
        lease_check_fn: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Execute the 9-step durable save protocol for a plan file."""
        validate_repo_path(rel_path, repo_root=self.repo_root)
        full_path = self.repo_root / rel_path

        # Step 1: Authorize scope and owner
        if lease_check_fn is not None and not lease_check_fn():
            raise RepoPlanConflictError("Writer lease expired or invalid before write")

        # Step 2: Reread actual bytes and Git context
        current_sha = compute_file_sha256(full_path)
        branch, head = get_git_context(self.repo_root)

        # Step 3: Compare expected revision
        if expected_revision is not None and expected_revision != current_sha:
            raise RepoPlanConflictError(
                f"Content revision conflict on {rel_path}: expected {expected_revision}, found {current_sha}"
            )

        # Step 4: Validate candidate file in memory
        validate_plan_dict(plan_dict, repo_root=self.repo_root)
        candidate_json = serialize_plan_json(plan_dict)
        candidate_bytes = candidate_json.encode("utf-8")
        candidate_sha = compute_bytes_sha256(candidate_bytes)
        payload_sha = hashlib.sha256(candidate_bytes + (idempotency_key or "").encode("utf-8")).hexdigest()

        # Idempotency check
        if idempotency_key:
            cached = self._idempotency_cache.get(idempotency_key)
            if cached is not None:
                if cached.get("payload_sha256") != payload_sha:
                    raise RepoPlanConflictError(
                        f"Idempotency key '{idempotency_key}' reused with different payload"
                    )
                return cached["result"]

        # No-op check: if identical bytes, avoid churning disk or Git diff
        if full_path.exists() and current_sha == candidate_sha:
            res = {
                "success": True,
                "saved": True,
                "no_op": True,
                "file_revision": candidate_sha,
                "changed_paths": [],
            }
            if idempotency_key:
                self._idempotency_cache[idempotency_key] = {"payload_sha256": payload_sha, "result": res}
            return res

        # Step 5: Persist durable intent
        intent_id = f"intent_{uuid.uuid4().hex[:12]}"
        intent = OperationIntent(
            intent_id=intent_id,
            operation="save_plan",
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha,
            owner=owner,
            created_at=time.time(),
            status="pending",
            targets=[IntentTarget(rel_path=rel_path, expected_sha256=current_sha, candidate_sha256=candidate_sha)],
            git_branch=branch,
            git_head=head,
        )
        self._save_intent(intent)

        # Step 6: Re-verify fencing and context
        if lease_check_fn is not None and not lease_check_fn():
            intent.status = "aborted"
            self._save_intent(intent)
            raise RepoPlanConflictError("Writer lease expired during preflight fence")

        new_branch, new_head = get_git_context(self.repo_root)
        if branch is not None and new_branch != branch:
            intent.status = "aborted"
            self._save_intent(intent)
            raise RepoPlanConflictError(f"Git branch changed during save preflight: was {branch}, now {new_branch}")

        # Step 7: Atomic save
        self._atomic_write_bytes(full_path, candidate_bytes)
        intent.targets[0].status = "written"
        self._save_intent(intent)

        # Step 8: Confirm actually stored bytes
        stored_sha = compute_file_sha256(full_path)
        if stored_sha != candidate_sha:
            intent.status = "reconciled"
            self._save_intent(intent)
            raise RepoPlanError(
                f"Stored byte verification failed: expected {candidate_sha}, read back {stored_sha}"
            )

        # Step 9: Confirm operation and mark intent completed
        intent.targets[0].status = "confirmed"
        intent.status = "completed"
        self._save_intent(intent)

        res = {
            "success": True,
            "saved": True,
            "no_op": False,
            "file_revision": stored_sha,
            "intent_id": intent_id,
            "changed_paths": [rel_path],
        }
        if idempotency_key:
            self._idempotency_cache[idempotency_key] = {"payload_sha256": payload_sha, "result": res}
        return res

    def save_spec_and_plan(
        self,
        spec_rel_path: str,
        spec_content: str,
        plan_rel_path: str,
        plan_dict: dict[str, Any],
        *,
        expected_spec_rev: str | None = None,
        expected_plan_rev: str | None = None,
        owner: str = "agent",
        idempotency_key: str = "",
        lease_check_fn: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Execute a coordinated multi-file durable intent to save a specification and a plan."""
        validate_repo_path(spec_rel_path, repo_root=self.repo_root)
        validate_repo_path(plan_rel_path, repo_root=self.repo_root)

        spec_full = self.repo_root / spec_rel_path
        plan_full = self.repo_root / plan_rel_path

        # 1. Lease check
        if lease_check_fn is not None and not lease_check_fn():
            raise RepoPlanConflictError("Writer lease invalid before multi-file save")

        # 2. Check current revisions
        current_spec_sha = compute_file_sha256(spec_full)
        current_plan_sha = compute_file_sha256(plan_full)
        branch, head = get_git_context(self.repo_root)

        if expected_spec_rev is not None and expected_spec_rev != current_spec_sha:
            raise RepoPlanConflictError(
                f"Spec revision conflict on {spec_rel_path}: expected {expected_spec_rev}, found {current_spec_sha}"
            )
        if expected_plan_rev is not None and expected_plan_rev != current_plan_sha:
            raise RepoPlanConflictError(
                f"Plan revision conflict on {plan_rel_path}: expected {expected_plan_rev}, found {current_plan_sha}"
            )

        # 3. Validate candidates
        validate_plan_dict(plan_dict, repo_root=self.repo_root)
        plan_json = serialize_plan_json(plan_dict)
        plan_bytes = plan_json.encode("utf-8")
        plan_cand_sha = compute_bytes_sha256(plan_bytes)

        spec_bytes = spec_content.encode("utf-8")
        spec_cand_sha = compute_bytes_sha256(spec_bytes)

        payload_sha = hashlib.sha256(
            spec_bytes + plan_bytes + (idempotency_key or "").encode("utf-8")
        ).hexdigest()

        if idempotency_key:
            cached = self._idempotency_cache.get(idempotency_key)
            if cached is not None:
                if cached.get("payload_sha256") != payload_sha:
                    raise RepoPlanConflictError(
                        f"Idempotency key '{idempotency_key}' reused with different payload"
                    )
                return cached["result"]

        # 4. Persist multi-file intent
        intent_id = f"intent_{uuid.uuid4().hex[:12]}"
        intent = OperationIntent(
            intent_id=intent_id,
            operation="save_spec_and_plan",
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha,
            owner=owner,
            created_at=time.time(),
            status="pending",
            targets=[
                IntentTarget(rel_path=spec_rel_path, expected_sha256=current_spec_sha, candidate_sha256=spec_cand_sha),
                IntentTarget(rel_path=plan_rel_path, expected_sha256=current_plan_sha, candidate_sha256=plan_cand_sha),
            ],
            git_branch=branch,
            git_head=head,
        )
        self._save_intent(intent)

        # 5. Save spec file
        self._atomic_write_bytes(spec_full, spec_bytes)
        intent.targets[0].status = "written"
        self._save_intent(intent)

        # Re-check fencing between writes
        if lease_check_fn is not None and not lease_check_fn():
            raise RepoPlanConflictError("Writer lease expired between specification and plan save")

        # 6. Save plan file
        self._atomic_write_bytes(plan_full, plan_bytes)
        intent.targets[1].status = "written"
        self._save_intent(intent)

        # 7. Confirm stored bytes for both
        if compute_file_sha256(spec_full) != spec_cand_sha:
            raise RepoPlanError(f"Stored byte verification failed for spec: {spec_rel_path}")
        intent.targets[0].status = "confirmed"

        if compute_file_sha256(plan_full) != plan_cand_sha:
            raise RepoPlanError(f"Stored byte verification failed for plan: {plan_rel_path}")
        intent.targets[1].status = "confirmed"

        intent.status = "completed"
        self._save_intent(intent)

        res = {
            "success": True,
            "saved": True,
            "intent_id": intent_id,
            "spec_revision": spec_cand_sha,
            "plan_revision": plan_cand_sha,
            "changed_paths": [spec_rel_path, plan_rel_path],
        }
        if idempotency_key:
            self._idempotency_cache[idempotency_key] = {"payload_sha256": payload_sha, "result": res}
        return res

    def recover_pending_intents(self) -> list[dict[str, Any]]:
        """Inspect and reconcile pending intents in the intents directory."""
        if not self.intents_dir.exists():
            return []

        outcomes = []
        for path in self.intents_dir.glob("*.intent.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                intent = OperationIntent.from_dict(data)
            except Exception as exc:
                logger.warning("Failed to parse intent file %s: %s", path, exc)
                continue

            if intent.status == "completed":
                continue

            # Check each target on disk
            all_targets_confirmed = True
            any_target_written = False

            for target in intent.targets:
                full = self.repo_root / target.rel_path
                actual_sha = compute_file_sha256(full)
                if actual_sha == target.candidate_sha256:
                    target.status = "confirmed"
                    any_target_written = True
                elif actual_sha == target.expected_sha256:
                    target.status = "pending"
                else:
                    target.status = "diverged"
                    all_targets_confirmed = False

            if all_targets_confirmed:
                intent.status = "completed"
                self._save_intent(intent)
                outcomes.append({"intent_id": intent.intent_id, "resolution": "already_applied", "status": "completed"})
            elif not any_target_written:
                intent.status = "aborted"
                self._save_intent(intent)
                outcomes.append({"intent_id": intent.intent_id, "resolution": "unapplied_discarded", "status": "aborted"})
            else:
                intent.status = "reconciled"
                self._save_intent(intent)
                outcomes.append({
                    "intent_id": intent.intent_id,
                    "resolution": "partial_reconciled",
                    "status": "reconciled",
                    "targets": [t.to_dict() for t in intent.targets],
                })

        return outcomes
