"""Root-scoped Laya training-candidate lifecycle in local state storage."""

from __future__ import annotations

import hashlib
import base64
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
import unicodedata
import uuid
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .agent_tasks import _canonical_repository_root, _task_matches_scope
from .evidence import is_evidence_id
from .json_utils import dumps as json_dumps
from .laya_decisions import (
    ContextSourceEvidence,
    DecisionCategory,
    DecisionInput,
    DecisionRequest,
    DecisionResult,
    _CATEGORY_INSTRUCTIONS,
    _CATEGORY_OPTIONS,
)
from .sqlite_support import connect_sqlite

_SCHEMA_VERSION = 1
_CHECKPOINT = "convaiinnovations/laya-multilingual"
_CHECKPOINT_REVISION = "1720e3e3357cfe1e281542e223f8273b0890ca34"
_TOKENIZER_SHA256 = "609d8f4c067cd3950f88594c5a802616cea245823836ef5848ee4fc40aab5b6f"
_MAX_STATE_BYTES = 16 * 1024
_MAX_CANDIDATE_BYTES = 64 * 1024
_MAX_CAPTURE_BATCH_SIZE = 100
_RUNTIME_CAPTURE_TOKEN = object()
_RUNTIME_BASELINE_METHODS = {
    DecisionCategory.COMPLETION_GAP: "agent_os_completion_gate",
}
_MAX_CANDIDATES_PER_EXPORT = 20_000
_MAX_SPLIT_SHINGLES = 1_000_000
_MAX_DUPLICATE_COMPARISONS = 250_000
_NEAR_DUPLICATE_JACCARD = 0.80
_LABEL_RUBRIC_VERSION = "laya-source-label-v1"
_REVIEW_SIGNATURE_PURPOSE = "local-ai-hub-laya-review-v1"
_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_LANG = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\Z")
_STATES = {"captured", "pending", "reviewed", "verified", "rejected", "ambiguous", "exported"}


def _canonical_json(value: Any) -> str:
    # Keep insertion order: Laya choice criteria are positional model inputs.
    return json_dumps(value, ensure_ascii=False, separators=(",", ":"))


def _strict_object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"{label} fields invalid")
    return value


def _identity(value: Any, label: str) -> str:
    if type(value) is not str or not _IDENT.fullmatch(value):
        raise ValueError(f"{label} invalid")
    return value


def _export_label_provenance(candidate: Mapping[str, Any], targets: Mapping[str, Any]) -> dict[str, Any]:
    """Project verified human-label provenance without exporting reviewer identifiers."""
    if candidate.get("label_status") != "verified":
        raise ValueError("Laya training export requires independently verified labels")
    provenance = candidate.get("label_provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("verified Laya candidate has no label provenance")
    annotations = provenance.get("annotations")
    adjudication = provenance.get("adjudication")
    verification = provenance.get("verification")
    rubric_version = provenance.get("rubric_version")
    if not isinstance(verification, Mapping) or verification.get("method") != "authenticated_human_review":
        raise ValueError("authenticated human-review provenance is unavailable")
    if rubric_version != _LABEL_RUBRIC_VERSION:
        raise ValueError("verified Laya candidate has no current label rubric version")
    if not isinstance(annotations, list) or len(annotations) != 2:
        raise ValueError("verified Laya candidate needs two independent annotations")
    annotators = [
        annotation.get("annotator_ref") if isinstance(annotation, Mapping) else None
        for annotation in annotations
    ]
    adjudicator = adjudication.get("reviewer_ref") if isinstance(adjudication, Mapping) else None
    verifier = verification.get("reviewer_ref") if isinstance(verification, Mapping) else None
    identities = annotators + [adjudicator, verifier]
    if any(not isinstance(identity, str) or not identity for identity in identities):
        raise ValueError("verified Laya candidate has incomplete independent reviewer provenance")
    identity_hashes = [hashlib.sha256(identity.encode("utf-8")).hexdigest() for identity in identities]
    if len(set(identity_hashes)) != 4:
        raise ValueError("verified Laya candidate reviewers are not independent")
    canonical_targets = json.dumps(targets, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {
        "status": "verified",
        "method": "blind_double_annotation",
        "rubric_version": rubric_version,
        "target_sha256": hashlib.sha256(canonical_targets.encode("utf-8")).hexdigest(),
        "annotation_identity_sha256": sorted(identity_hashes[:2]),
        "agreement": annotations[0].get("target") == annotations[1].get("target"),
        "adjudicator_identity_sha256": identity_hashes[2],
        "verification_identity_sha256": identity_hashes[3],
    }


def _event_payload(status: str, *, details: Mapping[str, Any] | None = None) -> str:
    return _canonical_json({"status": status, "details": dict(details or {})})


def _state_text(candidate: Mapping[str, Any]) -> str:
    state = candidate.get("state")
    if isinstance(state, Mapping):
        text = " ".join(f"{key} {state[key]}" for key in sorted(state))
    else:
        text = str(state or "")
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.findall(r"[^\W_]+", normalized, flags=re.UNICODE))


def _near_duplicate_clusters(rows: list[sqlite3.Row]) -> tuple[dict[str, str], int, int]:
    """Join task/session groups and conservatively merge near-identical states."""
    parents: dict[str, str] = {}

    def find(group_id: str) -> str:
        parent = parents.setdefault(group_id, group_id)
        while parent != parents[parent]:
            parents[parent] = parents[parents[parent]]
            parent = parents[parent]
        return parent

    def union(left: str, right: str) -> bool:
        a, b = find(left), find(right)
        if a != b:
            low, high = sorted((a, b))
            parents[high] = low
            return True
        return False

    buckets: dict[str, list[int]] = defaultdict(list)
    shingle_sets: list[set[str]] = []
    group_ids: list[str] = []
    identity_groups: dict[tuple[str, str], str] = {}
    related_group_merges = 0
    near_duplicate_merges = 0
    shingle_count = 0
    comparisons = 0
    for index, row in enumerate(rows):
        group_id = str(row["group_id"])
        group_ids.append(group_id)
        find(group_id)
        for identity in (("task", str(row["task_id"])), ("session", str(row["session_id"]))):
            previous_group = identity_groups.setdefault(identity, group_id)
            if union(group_id, previous_group):
                related_group_merges += 1
        candidate = json.loads(row["candidate_json"])
        text = _state_text(candidate)
        shingles = {text[start:start + 3] for start in range(len(text) - 2)} if len(text) >= 3 else ({text} if text else set())
        shingle_sets.append(shingles)
        shingle_count += len(shingles)
        if shingle_count > _MAX_SPLIT_SHINGLES:
            raise ValueError("split duplicate scan exceeds bounded shingle limit")
        previous: set[int] = set()
        for shingle in shingles:
            previous.update(buckets[shingle])
        for prior in previous:
            if group_ids[prior] == group_id:
                continue
            comparisons += 1
            if comparisons > _MAX_DUPLICATE_COMPARISONS:
                raise ValueError("split duplicate scan exceeds comparison limit; review candidates before retry")
            union_size = len(shingles | shingle_sets[prior])
            similarity = len(shingles & shingle_sets[prior]) / union_size if union_size else 1.0
            if similarity >= _NEAR_DUPLICATE_JACCARD:
                if union(group_id, group_ids[prior]):
                    near_duplicate_merges += 1
        for shingle in shingles:
            buckets[shingle].append(index)
    roots = {group_id: find(group_id) for group_id in parents}
    return roots, related_group_merges, near_duplicate_merges


def _split_for_group(cluster_id: str) -> str:
    bucket = int(hashlib.sha256(cluster_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    if bucket < 80:
        return "train"
    if bucket < 90:
        return "calibration"
    return "test"


class LayaCandidateStore:
    """Stores bounded, explicitly captured candidates in the existing Agent State database."""

    def __init__(
        self,
        state_dir: str | Path,
        *,
        reviewer_public_keys: list[str] | tuple[str, ...] = (),
        reviewer_authenticator: Callable[[str, str, str], bool] | None = None,
    ):
        if reviewer_authenticator is not None and not callable(reviewer_authenticator):
            raise TypeError("reviewer_authenticator must be callable")
        self.state_dir = Path(state_dir).resolve()
        self.path: Path | None = None
        self._lock = threading.RLock()
        self._reviewer_authenticator = reviewer_authenticator
        if type(reviewer_public_keys) not in (list, tuple) or any(
            type(line) is not str or not line.strip() for line in reviewer_public_keys
        ):
            raise ValueError("laya reviewer public keys must be OpenSSH public-key lines")
        self._reviewer_keys: dict[str, Ed25519PublicKey] = {}
        for line in reviewer_public_keys:
            fingerprint = self.reviewer_fingerprint(line)
            try:
                key = serialization.load_ssh_public_key(line.encode("ascii"))
            except (ValueError, UnicodeEncodeError) as exc:
                raise ValueError("invalid Laya reviewer OpenSSH public key") from exc
            if not isinstance(key, Ed25519PublicKey):
                raise ValueError("Laya reviewer keys must use Ed25519")
            if fingerprint in self._reviewer_keys:
                raise ValueError("duplicate Laya reviewer public key")
            self._reviewer_keys[fingerprint] = key

    @staticmethod
    def reviewer_fingerprint(public_key_line: str) -> str:
        if type(public_key_line) is not str:
            raise ValueError("Laya reviewer public key must be text")
        parts = public_key_line.strip().split()
        if len(parts) < 2 or parts[0] != "ssh-ed25519":
            raise ValueError("Laya reviewer public key must be an OpenSSH Ed25519 key")
        try:
            blob = base64.b64decode(parts[1], validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid Laya reviewer OpenSSH key encoding") from exc
        if not blob.startswith(b"\x00\x00\x00\x0bssh-ed25519"):
            raise ValueError("invalid Laya reviewer OpenSSH Ed25519 key blob")
        digest = base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")
        return "SHA256:" + digest

    @staticmethod
    def _review_message(
        *,
        action: str,
        role: str,
        target: str,
        reviewer_fingerprint: str,
        candidate_id: str,
        content_hash: str,
        scope: str,
        task_id: str,
        session_id: str,
        label_targets_sha256: str | None = None,
    ) -> bytes:
        return _canonical_json({
            "purpose": _REVIEW_SIGNATURE_PURPOSE,
            "schema_version": 1,
            "action": action,
            "role": role,
            "target": target,
            "reviewer_fingerprint": reviewer_fingerprint,
            "candidate_id": candidate_id,
            "candidate_sha256": content_hash,
            "repository_scope_sha256": scope,
            "task_id": task_id,
            "session_id": session_id,
            "rubric_version": _LABEL_RUBRIC_VERSION,
            "label_targets_sha256": label_targets_sha256,
        }).encode("utf-8")

    def _verify_review_proof(self, proof: Any, message: bytes) -> str:
        proof = _strict_object(proof, {"reviewer_fingerprint", "signature"}, "review proof")
        fingerprint = proof["reviewer_fingerprint"]
        signature_text = proof["signature"]
        if type(fingerprint) is not str or fingerprint not in self._reviewer_keys:
            raise ValueError("authenticated human reviewer provenance is unavailable")
        if type(signature_text) is not str or len(signature_text) > 256:
            raise ValueError("authenticated human reviewer provenance is unavailable")
        try:
            signature = base64.b64decode(signature_text, validate=True)
            self._reviewer_keys[fingerprint].verify(signature, message)
        except (ValueError, InvalidSignature):
            raise ValueError("authenticated human reviewer provenance is unavailable") from None
        return fingerprint

    def _connect(self, task_store: Any) -> sqlite3.Connection:
        state_store = getattr(task_store, "state_store", None)
        database = getattr(state_store, "db_path", None)
        if state_store is None or getattr(state_store, "enabled", False) is not True or database is None:
            raise RuntimeError("Laya candidates require the existing enabled Agent State database")
        path = Path(database).resolve(strict=False)
        if path.parent != self.state_dir:
            raise ValueError("Agent State database must remain inside configured state_dir")
        ensure_schema = getattr(state_store, "_ensure_schema", None)
        if not callable(ensure_schema):
            raise RuntimeError("Agent State schema initializer is unavailable")
        ensure_schema()
        self.path = path
        con = connect_sqlite(
            path,
            timeout_seconds=2.0,
            isolation_level=None,
            row_factory=sqlite3.Row,
            foreign_keys=True,
            wal=True,
        )
        con.execute("PRAGMA secure_delete=ON")
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS laya_candidates (
                candidate_id TEXT PRIMARY KEY,
                repository_scope TEXT NOT NULL,
                task_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN
                    ('captured','pending','reviewed','verified','rejected','ambiguous','exported')),
                candidate_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(repository_scope, content_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_laya_candidates_scope_status
                ON laya_candidates(repository_scope, status, task_id);
            CREATE TABLE IF NOT EXISTS laya_candidate_events (
                event_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                repository_scope TEXT NOT NULL,
                task_id TEXT NOT NULL,
                action TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_laya_candidate_events_scope_time
                ON laya_candidate_events(repository_scope, created_at);
            CREATE TABLE IF NOT EXISTS laya_dataset_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                repository_scope TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('prepared','exported','invalidated')),
                manifest_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE(repository_scope, snapshot_hash)
            );
            CREATE TABLE IF NOT EXISTS laya_dataset_assignments (
                snapshot_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                group_id TEXT NOT NULL,
                split_name TEXT NOT NULL CHECK(split_name IN ('train','calibration','test')),
                content_hash TEXT NOT NULL,
                PRIMARY KEY(snapshot_id, candidate_id)
            );
            CREATE INDEX IF NOT EXISTS idx_laya_dataset_assignments_candidate
                ON laya_dataset_assignments(candidate_id, snapshot_id);
            """
        )
        return con

    def _purge_snapshot_export(self, snapshot_id: str) -> None:
        if (
            type(snapshot_id) is not str
            or len(snapshot_id) != len("laya_snapshot_") + 32
            or not snapshot_id.startswith("laya_snapshot_")
            or any(char not in "0123456789abcdef" for char in snapshot_id[len("laya_snapshot_"):])
        ):
            raise ValueError("candidate snapshot ID is invalid")

        data_dir = self.state_dir / "experiments" / "model-training" / "data"
        current = self.state_dir
        for part in ("experiments", "model-training", "data"):
            current = current / part
            is_junction = getattr(current, "is_junction", None)
            if current.is_symlink() or (callable(is_junction) and is_junction()):
                raise ValueError("candidate export directory cannot contain a symlink or junction")
        resolved_data_dir = data_dir.resolve(strict=False)
        if not resolved_data_dir.is_relative_to(self.state_dir):
            raise ValueError("candidate export directory escaped configured state_dir")

        output = resolved_data_dir / f"laya-{snapshot_id}.train.jsonl"
        is_junction = getattr(output, "is_junction", None)
        if output.is_symlink() or (callable(is_junction) and is_junction()):
            raise ValueError("candidate export cannot be a symlink or junction")
        resolved_output = output.resolve(strict=False)
        if not resolved_output.is_relative_to(resolved_data_dir):
            raise ValueError("candidate export path escaped its data directory")
        if output.exists():
            if not output.is_file():
                raise ValueError("candidate export path is not a regular file")
            output.unlink()

    @staticmethod
    def _repo_scope(root: str) -> str:
        canonical = _canonical_repository_root(root)
        return hashlib.sha256(os.path.normcase(canonical).encode("utf-8")).hexdigest()

    @staticmethod
    def _session_for_task(task: Any) -> str:
        context = getattr(task, "context", None)
        if isinstance(context, Mapping):
            value = context.get("session_id")
        else:
            value = getattr(context, "session_id", None)
        return _identity(value, "task session_id")

    @staticmethod
    def _find_task(task_store: Any, root: str, task_id: str) -> Any:
        for task in task_store.list_tasks(limit=5000):
            if task.task_id == task_id and _task_matches_scope(task, root, None):
                return task
        raise ValueError("task_id is outside the authorized repository scope")

    @staticmethod
    def _candidate_input(value: Any) -> dict[str, Any]:
        row = _strict_object(
            value,
            {"decision_schema_version", "category", "state", "options", "language", "preprocessing", "evidence_ids"},
            "candidate",
        )
        schema_version = row["decision_schema_version"]
        if type(schema_version) is not str or not _IDENT.fullmatch(schema_version):
            raise ValueError("decision_schema_version invalid")
        try:
            category = DecisionCategory(row["category"])
        except (TypeError, ValueError) as exc:
            raise ValueError("candidate category invalid") from exc
        state = row["state"]
        context_source = None
        if category is DecisionCategory.CONTEXT_SOURCE:
            expected_state_fields = {"gap_code", "source_codes", "freshness_codes", "coverage_codes"}
            raw_fields = {"raw_task_input", "raw_context_excerpt"}
            metadata_fields = {
                "training_redacted_fields", "training_missing_fields", "training_missing_reason",
            }
            if type(state) is not dict or set(state) - (expected_state_fields | raw_fields | metadata_fields) or not expected_state_fields <= set(state):
                raise ValueError("context_source state fields invalid")
            if any(type(state.get(key)) is not str for key in metadata_fields if key in state):
                raise ValueError("context_source training-content metadata invalid")
            context_input = {
                **{key: value for key, value in state.items() if key in expected_state_fields},
                "evidence_ids": row["evidence_ids"],
                "training_content": {
                    key.removeprefix("raw_"): value
                    for key, value in state.items()
                    if key in raw_fields
                },
            }
            try:
                context_source = ContextSourceEvidence.from_mapping(context_input)
            except ValueError as exc:
                if "evidence ID" in str(exc) or "evidence_ids" in str(exc):
                    raise ValueError("context_source evidence_ids invalid") from exc
                raise ValueError("context_source state codes invalid") from exc
            state = {
                **{key: value for key, value in state.items() if key in expected_state_fields},
                **{f"raw_{key}": value for key, value in context_source.training_content.items()},
                **{
                    key: context_source.model_input()[key]
                    for key in metadata_fields
                },
            }
            if len(_canonical_json(state).encode("utf-8")) > _MAX_CANDIDATE_BYTES - 4096:
                raise ValueError("context_source state is too large")
        elif type(state) is str:
            if not state.strip() or len(state.encode("utf-8")) > _MAX_STATE_BYTES or "\x00" in state:
                raise ValueError("candidate state invalid or too large")
        elif type(state) is dict:
            if not state or len(state) > 32 or any(
                type(key) is not str or not _IDENT.fullmatch(key)
                or type(item) is not str or not item.strip() or "\x00" in item
                for key, item in state.items()
            ):
                raise ValueError("candidate state fields invalid")
            if len(_canonical_json(state).encode("utf-8")) > _MAX_STATE_BYTES:
                raise ValueError("candidate state is too large")
        else:
            raise ValueError("candidate state must be a string or flat string object")
        options = row["options"]
        if (type(options) is not list or not 2 <= len(options) <= 32
                or any(type(item) is not str for item in options)
                or len(set(options)) != len(options)
                or any(item not in _CATEGORY_OPTIONS[category] for item in options)):
            raise ValueError("candidate options invalid for category")
        if context_source is not None:
            allowed_context_options = set(context_source.decision_options) | {"more_evidence"}
            if any(item not in allowed_context_options for item in options):
                raise ValueError("candidate option not present in context_source codes")
        language = row["language"]
        if type(language) is not str or not _LANG.fullmatch(language):
            raise ValueError("candidate language invalid")
        preprocessing = _strict_object(row["preprocessing"], {"name", "version"}, "preprocessing")
        if any(type(preprocessing[k]) is not str or not _IDENT.fullmatch(preprocessing[k]) for k in preprocessing):
            raise ValueError("preprocessing identity invalid")
        evidence_ids = row["evidence_ids"]
        if category is DecisionCategory.CONTEXT_SOURCE:
            if (
                type(evidence_ids) is not list
                or len(evidence_ids) != len(state["source_codes"])
                or any(type(item) is not str or not is_evidence_id(item) for item in evidence_ids)
            ):
                raise ValueError("context_source evidence_ids invalid")
        else:
            if type(evidence_ids) is not list or len(evidence_ids) > 64:
                raise ValueError("candidate evidence_ids invalid")
            evidence_ids = [_identity(item, "evidence_id") for item in evidence_ids]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("duplicate evidence_id")
        question = {
            "id": category.value,
            "type": "choice",
            "instructions": _CATEGORY_INSTRUCTIONS[category],
            "criteria": {option: option.replace("_", " ") for option in options},
        }
        candidate = {
            "schema_version": _SCHEMA_VERSION,
            "decision_schema_version": schema_version,
            "category": category.value,
            "state": state,
            "questions": {category.value: question},
            "language": language,
            "preprocessing": preprocessing,
            "checkpoint": {"repository": _CHECKPOINT, "revision": _CHECKPOINT_REVISION},
            "tokenizer": {"sha256": _TOKENIZER_SHA256},
            "serialization": "laya-python-input-v1",
            "evidence_ids": evidence_ids,
            "targets": {},
            "label_status": "pending",
            "label_provenance": {"annotations": [], "events": []},
            "model_output": None,
        }
        if len(_canonical_json(candidate).encode("utf-8")) > _MAX_CANDIDATE_BYTES:
            raise ValueError("candidate exceeds byte limit")
        return candidate

    @staticmethod
    def _validate_context_source_evidence(
        candidate: Mapping[str, Any],
        *,
        evidence_store: Any,
        canonical_root: str,
    ) -> None:
        evidence_ids = candidate["evidence_ids"]
        if not evidence_ids:
            return
        is_context_source = candidate.get("category") == DecisionCategory.CONTEXT_SOURCE.value
        if not is_context_source and evidence_store is None:
            return
        evidence_error = (
            "context_source evidence is not authorized and current"
            if is_context_source
            else "Laya evidence is not authorized and current"
        )
        get_many = getattr(evidence_store, "get_many", None)
        if not callable(get_many):
            raise ValueError(evidence_error)
        try:
            rows = get_many(evidence_ids, verify=True, root=canonical_root)
        except Exception as exc:
            raise ValueError(evidence_error) from exc
        if type(rows) is not list or len(rows) != len(evidence_ids) or any(
            type(row) is not dict
            or row.get("success") is not True
            or row.get("evidence_id") != evidence_id
            or row.get("root") != canonical_root
            or row.get("stale") is not False
            for row, evidence_id in zip(rows, evidence_ids, strict=True)
        ):
            raise ValueError(evidence_error)
        if not is_context_source:
            return
        validate_provenance = getattr(evidence_store, "validate_source_provenance", None)
        if not callable(validate_provenance):
            raise ValueError("context_source evidence source provenance is unavailable")
        try:
            provenance_valid = validate_provenance(
                evidence_ids,
                candidate["state"]["source_codes"],
                root=canonical_root,
            )
        except Exception as exc:
            raise ValueError("context_source evidence source provenance is unavailable") from exc
        if provenance_valid is not True:
            raise ValueError("context_source source codes do not match recorded provenance")

    def handle(
        self,
        operation: Any,
        *,
        root: str,
        task_store: Any,
        evidence_store: Any = None,
        _runtime_capture_token: object | None = None,
    ) -> dict[str, Any]:
        if type(operation) is not dict or type(operation.get("action")) is not str:
            raise ValueError("laya_operation must be an object with an action")
        action = operation["action"]
        if operation.get("_runtime_capture_token") is _RUNTIME_CAPTURE_TOKEN:
            if _runtime_capture_token is None:
                _runtime_capture_token = _RUNTIME_CAPTURE_TOKEN
            operation = {key: value for key, value in operation.items() if key != "_runtime_capture_token"}
        canonical_root = _canonical_repository_root(root)
        scope = self._repo_scope(canonical_root)
        if action == "capture":
            if _runtime_capture_token is not _RUNTIME_CAPTURE_TOKEN:
                raise ValueError("candidate capture is available only from an actual Laya runtime callback")
            op = _strict_object(
                operation,
                {"action", "task_id", "session_id", "candidate"},
                "capture",
            )
            task_id = _identity(op["task_id"], "task_id")
            task = self._find_task(task_store, canonical_root, task_id)
            session_id = _identity(op["session_id"], "session_id")
            if self._session_for_task(task) != session_id:
                raise ValueError("session_id does not match the scoped task")
            candidate = self._candidate_input(op["candidate"])
            self._validate_context_source_evidence(
                candidate, evidence_store=evidence_store, canonical_root=canonical_root
            )
            content_hash = hashlib.sha256(_canonical_json(candidate).encode("utf-8")).hexdigest()
            group_id = "grp_" + hashlib.sha256(f"{scope}\0{task_id}\0{session_id}".encode()).hexdigest()[:32]
            now = time.time()
            with self._lock, closing(self._connect(task_store)) as con:
                con.execute("BEGIN IMMEDIATE")
                existing = con.execute(
                    "SELECT candidate_id,status FROM laya_candidates WHERE repository_scope=? AND content_hash=?",
                    (scope, content_hash),
                ).fetchone()
                candidate_id = str(existing["candidate_id"]) if existing else "laya_" + uuid.uuid4().hex
                if existing:
                    self._event(
                        con, candidate_id, scope, task_id, "duplicate_capture",
                        {"schema_version": _SCHEMA_VERSION, "data_class": "local_scoped"}, now,
                    )
                    con.commit()
                    return {"success": True, "duplicate": True, "candidate_id": candidate_id, "status": existing["status"]}
                con.execute(
                    "INSERT INTO laya_candidates VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (candidate_id, scope, task_id, session_id, group_id, content_hash,
                     "pending", _canonical_json(candidate), now, now),
                )
                self._event(
                    con, candidate_id, scope, task_id, "captured",
                    {"schema_version": _SCHEMA_VERSION, "data_class": "local_scoped"}, now,
                )
                self._event(con, candidate_id, scope, task_id, "pending", {"label_status": "pending"}, now)
                con.commit()
            return {"success": True, "duplicate": False, "candidate_id": candidate_id, "status": "pending"}
        if action == "capture_batch":
            raise ValueError("capture_batch is unavailable; only actual per-decision runtime callbacks may capture")
            op = _strict_object(
                operation,
                {"action", "task_id", "session_id", "examples"},
                "capture_batch",
            )
            task_id = _identity(op["task_id"], "task_id")
            task = self._find_task(task_store, canonical_root, task_id)
            session_id = _identity(op["session_id"], "session_id")
            if self._session_for_task(task) != session_id:
                raise ValueError("session_id does not match the scoped task")
            examples = op["examples"]
            if type(examples) is not list or not 1 <= len(examples) <= _MAX_CAPTURE_BATCH_SIZE:
                raise ValueError(f"capture_batch requires 1..{_MAX_CAPTURE_BATCH_SIZE} examples")
            prepared: list[tuple[str, dict[str, Any]]] = []
            for example in examples:
                row = _strict_object(
                    example,
                    {"candidate"},
                    "capture_batch example",
                )
                candidate = self._candidate_input(row["candidate"])
                self._validate_context_source_evidence(
                    candidate, evidence_store=evidence_store, canonical_root=canonical_root
                )
                content_hash = hashlib.sha256(_canonical_json(candidate).encode("utf-8")).hexdigest()
                prepared.append((content_hash, candidate))
            group_id = "grp_" + hashlib.sha256(f"{scope}\0{task_id}\0{session_id}".encode()).hexdigest()[:32]
            now = time.time()
            results: list[dict[str, Any]] = []
            with self._lock, closing(self._connect(task_store)) as con:
                con.execute("BEGIN IMMEDIATE")
                seen: dict[str, str] = {}
                captured_count = 0
                try:
                    for content_hash, candidate in prepared:
                        candidate_id = seen.get(content_hash)
                        existing = None
                        duplicate = candidate_id is not None
                        if not duplicate:
                            existing = con.execute(
                                "SELECT candidate_id,status FROM laya_candidates WHERE repository_scope=? AND content_hash=?",
                                (scope, content_hash),
                            ).fetchone()
                            if existing is not None:
                                candidate_id = str(existing["candidate_id"])
                                duplicate = True
                        if not duplicate and existing is None:
                            candidate_id = "laya_" + uuid.uuid4().hex
                        if not duplicate:
                            if existing is None:
                                con.execute(
                                    "INSERT INTO laya_candidates VALUES(?,?,?,?,?,?,?,?,?,?)",
                                    (candidate_id, scope, task_id, session_id, group_id, content_hash,
                                     "pending", _canonical_json(candidate), now, now),
                                )
                                self._event(
                                    con, candidate_id, scope, task_id, "captured",
                                    {"schema_version": _SCHEMA_VERSION, "data_class": "local_scoped"}, now,
                                )
                                self._event(con, candidate_id, scope, task_id, "pending", {"label_status": "pending"}, now)
                                captured_count += 1
                            seen[content_hash] = candidate_id
                        else:
                            self._event(
                                con, candidate_id, scope, task_id, "duplicate_capture",
                                {"schema_version": _SCHEMA_VERSION, "data_class": "local_scoped"}, now,
                            )
                        status = str(existing["status"]) if existing is not None else "pending"
                        results.append({"candidate_id": candidate_id, "duplicate": duplicate, "status": status})
                    con.commit()
                except BaseException:
                    con.rollback()
                    raise
            duplicate_count = len(results) - captured_count
            return {
                "success": True,
                "count": len(results),
                "captured_count": captured_count,
                "duplicate_count": duplicate_count,
                "results": results,
            }
        if action == "get":
            op = _strict_object(operation, {"action", "candidate_id"}, "get")
            candidate_id = _identity(op["candidate_id"], "candidate_id")
            with closing(self._connect(task_store)) as con:
                row = con.execute(
                    "SELECT candidate_id,task_id,candidate_json,created_at,updated_at "
                    "FROM laya_candidates WHERE repository_scope=? AND candidate_id=?",
                    (scope, candidate_id),
                ).fetchone()
            if row is None:
                raise ValueError("candidate not found in authorized repository scope")
            self._find_task(task_store, canonical_root, row["task_id"])
            candidate = json.loads(row["candidate_json"])
            if type(candidate) is not dict:
                raise ValueError("stored candidate is invalid")
            # Reviewers need the bounded request/evidence payload, but must not
            # see Laya's answer or any existing human annotations.
            for field in ("model_output", "targets", "label_status", "label_provenance"):
                candidate.pop(field, None)
            return {
                "success": True,
                "candidate_id": str(row["candidate_id"]),
                "task_id": str(row["task_id"]),
                "created_at": float(row["created_at"]),
                "updated_at": float(row["updated_at"]),
                "candidate": candidate,
            }
        if action == "list":
            allowed = {"action", "task_id", "status"}
            if set(operation) - allowed or "action" not in operation:
                raise ValueError("list fields invalid")
            task_id = operation.get("task_id")
            if task_id is not None:
                task_id = _identity(task_id, "task_id")
                self._find_task(task_store, canonical_root, task_id)
            status = operation.get("status")
            if status is not None and status not in _STATES:
                raise ValueError("candidate status invalid")
            query = "SELECT candidate_id,task_id,session_id,group_id,status,created_at,updated_at FROM laya_candidates WHERE repository_scope=?"
            args: list[Any] = [scope]
            if task_id is not None:
                query += " AND task_id=?"; args.append(task_id)
            if status is not None:
                query += " AND status=?"; args.append(status)
            query += " ORDER BY created_at,candidate_id LIMIT 1000"
            with closing(self._connect(task_store)) as con:
                rows = con.execute(query, args).fetchall()
            return {"success": True, "count": len(rows), "candidates": [dict(row) for row in rows]}
        if action == "review_challenge":
            return self._review_challenge(
                operation, scope=scope, root=canonical_root, task_store=task_store
            )
        if action in {"label", "verify", "reject", "delete"}:
            return self._transition(operation, action=action, scope=scope, root=canonical_root, task_store=task_store)
        if action == "prepare_splits":
            return self._prepare_splits(operation, scope=scope, task_store=task_store)
        if action == "export":
            op = _strict_object(operation, {"action", "snapshot_id"}, "export")
            snapshot_id = _identity(op["snapshot_id"], "snapshot_id")
            out_dir = (self.state_dir / "experiments" / "model-training" / "data").resolve()
            if not out_dir.is_relative_to(self.state_dir):
                raise ValueError("candidate export path escaped configured state_dir")
            out_file = out_dir / f"laya-{snapshot_id}.train.jsonl"
            with self._lock, closing(self._connect(task_store)) as con:
                con.execute("BEGIN IMMEDIATE")
                snapshot = con.execute(
                    "SELECT status,manifest_json FROM laya_dataset_snapshots WHERE snapshot_id=? AND repository_scope=?",
                    (snapshot_id, scope),
                ).fetchone()
                if snapshot is None:
                    raise ValueError("snapshot_id is outside the authorized repository scope")
                if snapshot["status"] == "invalidated":
                    raise ValueError("dataset snapshot is invalidated")
                assignments = con.execute(
                    "SELECT a.candidate_id,a.group_id,a.content_hash,c.candidate_json,c.status,c.task_id,c.session_id "
                    "FROM laya_dataset_assignments a JOIN laya_candidates c ON c.candidate_id=a.candidate_id "
                    "WHERE a.snapshot_id=? AND a.split_name='train' AND c.repository_scope=? "
                    "ORDER BY c.created_at,c.candidate_id LIMIT ?",
                    (snapshot_id, scope, _MAX_CANDIDATES_PER_EXPORT + 1),
                ).fetchall()
                if any(row["status"] not in {"verified", "exported"} for row in assignments):
                    raise ValueError("dataset snapshot contains a candidate no longer verified")
                if any(hashlib.sha256(row["candidate_json"].encode("utf-8")).hexdigest() != row["content_hash"] for row in assignments):
                    raise ValueError("dataset snapshot candidate content changed")
                rows = []
                for row in assignments:
                    candidate = json.loads(row["candidate_json"])
                    task = self._find_task(task_store, canonical_root, str(row["task_id"]))
                    if self._session_for_task(task) != row["session_id"]:
                        raise ValueError("candidate session identity no longer matches its task")
                    question_id = candidate["category"]
                    target = candidate.get("targets", {}).get(question_id)
                    if not isinstance(target, str) or target not in candidate["questions"][question_id]["criteria"]:
                        raise ValueError("verified candidate has no valid Laya training target")
                    rows.append({
                        "id": str(row["candidate_id"]),
                        "group_id": str(row["group_id"]),
                        "source_sha256": str(row["content_hash"]),
                        "state": candidate["state"],
                        "questions": candidate["questions"],
                        "expected": {question_id: target},
                        "provenance": {
                            "source": "laya_candidate_store",
                            "data_class": "local_scoped",
                            "candidate_id": str(row["candidate_id"]),
                            "candidate_sha256": str(row["content_hash"]),
                            "repository_scope_sha256": scope,
                            "task_id": str(row["task_id"]),
                            "session_id": str(row["session_id"]),
                            "evidence_ids": list(candidate["evidence_ids"]),
                            "label_provenance": _export_label_provenance(candidate, {question_id: target}),
                        },
                    })
                if len(rows) > _MAX_CANDIDATES_PER_EXPORT:
                    raise ValueError("candidate export exceeds row limit")
                payload = "".join(_canonical_json(row) + "\n" for row in rows)
                if len(payload.encode("utf-8")) > 16 * 1024 * 1024:
                    raise ValueError("candidate export exceeds byte limit")
                if not rows:
                    raise ValueError("dataset snapshot has no train candidates to export")
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file = out_file.resolve(strict=False)
                if not out_file.is_relative_to(self.state_dir):
                    raise ValueError("candidate export path escaped configured state_dir")
                fd, tmp_name = tempfile.mkstemp(prefix=".laya-export-", dir=out_file.parent)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                        stream.write(payload); stream.flush(); os.fsync(stream.fileno())
                    os.replace(tmp_name, out_file)
                except BaseException:
                    try: os.unlink(tmp_name)
                    except OSError: pass
                    raise
                now = time.time()
                for row in assignments:
                    changed = con.execute(
                        "UPDATE laya_candidates SET status='exported',updated_at=? "
                        "WHERE candidate_id=? AND status IN ('verified','exported')",
                        (now, row["candidate_id"]),
                    ).rowcount
                    if changed != 1:
                        raise ValueError("train candidate changed during export")
                    task_id = con.execute(
                        "SELECT task_id FROM laya_candidates WHERE candidate_id=?",
                        (row["candidate_id"],),
                    ).fetchone()[0]
                    self._event(con, row["candidate_id"], scope, task_id, "exported", {"format": "jsonl", "snapshot_id": snapshot_id}, now)
                con.execute("UPDATE laya_dataset_snapshots SET status='exported' WHERE snapshot_id=? AND repository_scope=?", (snapshot_id, scope))
                con.commit()
            return {"success": True, "count": len(rows), "output_path": str(out_file), "format": "jsonl", "dataset_kind": "laya_candidates", "split": "train", "snapshot_id": snapshot_id}
        raise ValueError("unsupported laya_operation action")

    def capture_runtime_outcome(
        self,
        request: DecisionRequest,
        evidence: ContextSourceEvidence | DecisionInput,
        outcome: Any,
        *,
        root: str,
        task_store: Any,
        evidence_store: Any,
        baseline: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a real runtime result through the normal scoped candidate lifecycle."""
        if not isinstance(request, DecisionRequest):
            raise ValueError("validated Laya request is required")
        if request.category is DecisionCategory.CONTEXT_SOURCE:
            if not isinstance(evidence, ContextSourceEvidence):
                raise ValueError("validated context-source evidence is required")
        elif not isinstance(evidence, DecisionInput):
            raise ValueError("validated typed decision input is required")
        decision = getattr(outcome, "decision", None)
        runtime = getattr(outcome, "runtime", None)
        if not isinstance(decision, DecisionResult) or decision.request != request or runtime is None:
            raise ValueError("only an executed Laya runtime outcome can be captured")
        if request.task_id is None or request.session_id is None:
            raise ValueError("runtime capture requires server-bound task and session identity")
        if isinstance(evidence, ContextSourceEvidence) and (
            request.evidence_ids != evidence.evidence_ids or request.options != evidence.decision_options
        ):
            raise ValueError("runtime request does not match its validated evidence")
        if baseline is None:
            baseline_record = {"status": "not_available"}
        else:
            baseline = _strict_object(baseline, {"method", "suggestion", "evidence_id"}, "baseline")
            suggestion = _identity(baseline["suggestion"], "baseline suggestion")
            evidence_id = _identity(baseline["evidence_id"], "baseline evidence_id")
            if evidence_id not in request.evidence_ids:
                raise ValueError("deterministic baseline must match a request evidence ID")
            if isinstance(evidence, ContextSourceEvidence):
                if (
                    suggestion not in request.options
                    or baseline["method"] != "retrieval_rank_order"
                    or suggestion not in evidence.source_codes
                    or evidence_id != evidence.evidence_ids[evidence.source_codes.index(suggestion)]
                ):
                    raise ValueError("deterministic baseline does not match validated context-source evidence")
            else:
                if baseline["method"] != _RUNTIME_BASELINE_METHODS.get(request.category):
                    raise ValueError("deterministic baseline method is not registered for this Laya category")
                if request.category is DecisionCategory.COMPLETION_GAP and suggestion not in {"ready", "not_ready"}:
                    raise ValueError("completion-gap baseline suggestion must be ready or not_ready")
            baseline_record = {
                "status": "recorded",
                "method": baseline["method"],
                "suggestion": suggestion,
                "evidence_id": evidence_id,
            }
        canonical_root = _canonical_repository_root(root)
        task_id = _identity(request.task_id, "task_id")
        session_id = _identity(request.session_id, "session_id")
        task = self._find_task(task_store, canonical_root, task_id)
        if self._session_for_task(task) != session_id:
            raise ValueError("runtime session identity does not match its scoped task")
        if isinstance(evidence, ContextSourceEvidence):
            evidence_mapping = evidence.model_input()
            state = {key: value for key, value in evidence_mapping.items() if key != "evidence_ids"}
        else:
            state = evidence.model_state()
        runtime_version = _identity(str(getattr(runtime, "runtime_version", "")), "runtime_version")
        candidate = {
            "decision_schema_version": "laya-decision-v1",
            "category": request.category.value,
            "state": state,
            "options": list(request.options),
            "language": "und",
            "preprocessing": {"name": "laya-runtime", "version": runtime_version},
            "evidence_ids": list(request.evidence_ids),
        }
        captured = self.handle(
            {
                "action": "capture", "task_id": task_id, "session_id": session_id,
                "candidate": candidate,
            },
            root=canonical_root,
            task_store=task_store,
            evidence_store=evidence_store,
            _runtime_capture_token=_RUNTIME_CAPTURE_TOKEN,
        )
        candidate_id = _identity(captured.get("candidate_id"), "candidate_id")
        runtime_record = {
            "decision_id": request.decision_id,
            "success": decision.success,
            "status": decision.status.value,
            "suggestion": decision.suggestion,
            "reason_codes": list(decision.reason_codes),
            "baseline": baseline_record,
            "downstream_outcome": {
                "status": "not_observed",
                "reason": "shadow_only_not_user_exposed",
            },
            "runtime": {
                "model_id": runtime.model_id,
                "revision": runtime.revision,
                "provider": runtime.provider,
                "runtime_version": runtime.runtime_version,
                "device": runtime.device,
                "device_class": runtime.device_class,
                "device_name": runtime.device_name,
                "parameter_device": runtime.parameter_device,
                "execution_verification": runtime.execution_verification,
                "quality_status": runtime.quality_status,
                "latency_ms": runtime.latency_ms,
                "input_tokens": runtime.input_tokens,
                "output_tokens": runtime.output_tokens,
                "fallback_reason": runtime.fallback_reason,
            },
        }
        _canonical_json(runtime_record)
        scope = self._repo_scope(canonical_root)
        now = time.time()
        with self._lock, closing(self._connect(task_store)) as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT task_id,session_id,content_hash,candidate_json FROM laya_candidates "
                "WHERE candidate_id=? AND repository_scope=?",
                (candidate_id, scope),
            ).fetchone()
            if row is None or row["task_id"] != task_id or row["session_id"] != session_id:
                raise ValueError("captured runtime candidate escaped its repository/task/session scope")
            if hashlib.sha256(row["candidate_json"].encode("utf-8")).hexdigest() != row["content_hash"]:
                raise ValueError("captured runtime candidate content changed")
            self._event(con, candidate_id, scope, task_id, "runtime_output", runtime_record, now)
            con.commit()
        return {**captured, "runtime_output_recorded": True}

    def export_train_payload(self, operation: Any, *, root: str, task_store: Any) -> bytes:
        """Build an explicit, scope-checked upstream training JSONL payload in memory."""
        op = _strict_object(operation, {"snapshot_id"}, "candidate ZIP export")
        canonical_root = _canonical_repository_root(root)
        scope = self._repo_scope(canonical_root)
        snapshot_id = _identity(op["snapshot_id"], "snapshot_id")
        with self._lock, closing(self._connect(task_store)) as con:
            con.execute("BEGIN IMMEDIATE")
            snapshot = con.execute(
                "SELECT status FROM laya_dataset_snapshots WHERE snapshot_id=? AND repository_scope=?",
                (snapshot_id, scope),
            ).fetchone()
            if snapshot is None:
                raise ValueError("snapshot_id is outside the authorized repository scope")
            if snapshot["status"] == "invalidated":
                raise ValueError("dataset snapshot is invalidated")
            assignments = con.execute(
                    "SELECT a.candidate_id,a.group_id,a.content_hash,c.candidate_json,c.status,c.task_id,c.session_id "
                "FROM laya_dataset_assignments a JOIN laya_candidates c ON c.candidate_id=a.candidate_id "
                "WHERE a.snapshot_id=? AND a.split_name='train' AND c.repository_scope=? "
                "ORDER BY c.created_at,c.candidate_id LIMIT ?",
                (snapshot_id, scope, _MAX_CANDIDATES_PER_EXPORT + 1),
            ).fetchall()
            if len(assignments) > _MAX_CANDIDATES_PER_EXPORT:
                raise ValueError("candidate export exceeds row limit")
            if not assignments:
                raise ValueError("dataset snapshot has no train candidates to export")
            rows: list[dict[str, Any]] = []
            for row in assignments:
                if row["status"] not in {"verified", "exported"}:
                    raise ValueError("dataset snapshot contains a candidate no longer verified")
                if hashlib.sha256(row["candidate_json"].encode("utf-8")).hexdigest() != row["content_hash"]:
                    raise ValueError("dataset snapshot candidate content changed")
                task = self._find_task(task_store, canonical_root, row["task_id"])
                if self._session_for_task(task) != row["session_id"]:
                    raise ValueError("candidate session identity no longer matches its task")
                candidate = json.loads(row["candidate_json"])
                question_id = candidate["category"]
                target = candidate.get("targets", {}).get(question_id)
                if not isinstance(target, str) or target not in candidate["questions"][question_id]["criteria"]:
                    raise ValueError("verified candidate has no valid Laya training target")
                rows.append({
                    "id": str(row["candidate_id"]),
                    "group_id": str(row["group_id"]),
                    "source_sha256": str(row["content_hash"]),
                    "state": candidate["state"],
                    "questions": candidate["questions"],
                    "expected": {question_id: target},
                    "provenance": {
                        "source": "laya_candidate_store",
                            "data_class": "local_scoped",
                        "candidate_id": str(row["candidate_id"]),
                        "candidate_sha256": str(row["content_hash"]),
                        "repository_scope_sha256": scope,
                        "task_id": str(row["task_id"]),
                        "session_id": str(row["session_id"]),
                        "evidence_ids": list(candidate["evidence_ids"]),
                        "label_provenance": _export_label_provenance(candidate, {question_id: target}),
                    },
                })
            payload = "".join(_canonical_json(row) + "\n" for row in rows).encode("utf-8")
            if len(payload) > 16 * 1024 * 1024:
                raise ValueError("candidate export exceeds byte limit")
            con.commit()
            return payload

    def _prepare_splits(self, operation: dict[str, Any], *, scope: str, task_store: Any) -> dict[str, Any]:
        _strict_object(operation, {"action"}, "prepare_splits")
        with self._lock, closing(self._connect(task_store)) as con:
            con.execute("BEGIN IMMEDIATE")
            status_counts = {
                row["status"]: row["count"]
                for row in con.execute(
                    "SELECT status,COUNT(*) AS count FROM laya_candidates WHERE repository_scope=? GROUP BY status",
                    (scope,),
                ).fetchall()
            }
            rows = con.execute(
                "SELECT candidate_id,task_id,session_id,group_id,content_hash,candidate_json FROM laya_candidates "
                "WHERE repository_scope=? AND status IN ('verified','exported') "
                "ORDER BY candidate_id LIMIT ?",
                (scope, _MAX_CANDIDATES_PER_EXPORT + 1),
            ).fetchall()
            if len(rows) > _MAX_CANDIDATES_PER_EXPORT:
                con.rollback()
                raise ValueError("candidate split preparation exceeds row limit")
            if not rows:
                con.commit()
                return {
                    "success": True,
                    "snapshot_id": None,
                    "candidate_count": 0,
                    "split_counts": {"train": 0, "calibration": 0, "test": 0},
                    "status_counts": status_counts,
                    "sufficiency_status": "INSUFFICIENT DATA",
                    "sufficiency_reasons": ["no_verified_candidates"],
                }

            group_roots, related_group_merges, near_duplicate_merges = _near_duplicate_clusters(rows)
            split_counts = {"train": 0, "calibration": 0, "test": 0}
            group_counts = {"train": set(), "calibration": set(), "test": set()}
            category_language_counts: dict[str, dict[str, dict[str, int]]] = {}
            category_language_groups: dict[str, dict[str, dict[str, set[str]]]] = {}
            label_distributions: dict[str, dict[str, dict[str, int]]] = {}
            assignment_rows = []
            manifest_entries = []
            for row in rows:
                candidate = json.loads(row["candidate_json"])
                group_root = group_roots[row["group_id"]]
                split_name = _split_for_group(group_root)
                record_hash = hashlib.sha256(row["candidate_json"].encode("utf-8")).hexdigest()
                assignment_rows.append((row["candidate_id"], record_hash, group_root, split_name))
                manifest_entries.append((row["candidate_id"], record_hash, row["group_id"], group_root, split_name))
                split_counts[split_name] += 1
                group_counts[split_name].add(group_root)
                category = candidate["category"]
                language = candidate["language"]
                category_language_counts.setdefault(category, {}).setdefault(
                    language, {"train": 0, "calibration": 0, "test": 0}
                )[split_name] += 1
                category_language_groups.setdefault(category, {}).setdefault(
                    language, {"train": set(), "calibration": set(), "test": set()}
                )[split_name].add(group_root)
                target = candidate.get("targets", {}).get(category)
                if target is not None:
                    label_distributions.setdefault(category, {}).setdefault(language, {}).setdefault(target, 0)
                    label_distributions[category][language][target] += 1

            insufficiency_reasons = []
            for category, languages in category_language_groups.items():
                for language, by_split in languages.items():
                    if not by_split["train"]:
                        insufficiency_reasons.append(f"missing_train_groups:{category}:{language}")
                    for heldout in ("calibration", "test"):
                        if len(by_split[heldout]) < 2:
                            insufficiency_reasons.append(f"fewer_than_two_{heldout}_groups:{category}:{language}")
            sufficiency_status = "INSUFFICIENT DATA" if insufficiency_reasons else "UNASSESSED"
            assessment_reasons = insufficiency_reasons or ["predeclared_case_count_and_quality_thresholds_not_set"]
            manifest = {
                "schema_version": _SCHEMA_VERSION,
                "split_policy": "group_hash_80_10_10_near_duplicate_jaccard_0.80_v1",
                "candidate_count": len(rows),
                "split_counts": split_counts,
                "independent_group_counts": {name: len(groups) for name, groups in group_counts.items()},
                "category_language_counts": category_language_counts,
                "label_distributions": label_distributions,
                "status_counts_at_snapshot": status_counts,
                "related_group_merges": related_group_merges,
                "near_duplicate_group_merges": near_duplicate_merges,
                "sufficiency_status": sufficiency_status,
                "sufficiency_reasons": assessment_reasons,
            }
            snapshot_material = {
                "schema_version": _SCHEMA_VERSION,
                "split_policy": manifest["split_policy"],
                "entries": sorted(manifest_entries),
            }
            snapshot_hash = hashlib.sha256(_canonical_json(snapshot_material).encode("utf-8")).hexdigest()
            snapshot_id = "laya_snapshot_" + snapshot_hash[:32]
            existing = con.execute(
                "SELECT status,manifest_json FROM laya_dataset_snapshots WHERE repository_scope=? AND snapshot_hash=?",
                (scope, snapshot_hash),
            ).fetchone()
            if existing:
                con.commit()
                return {
                    "success": True,
                    "snapshot_id": snapshot_id,
                    **json.loads(existing["manifest_json"]),
                    "snapshot_status": existing["status"],
                    "reused": True,
                }
            manifest["snapshot_hash"] = snapshot_hash
            now = time.time()
            con.execute(
                "INSERT INTO laya_dataset_snapshots VALUES(?,?,?,?,?,?)",
                (snapshot_id, scope, snapshot_hash, "prepared", _canonical_json(manifest), now),
            )
            con.executemany(
                "INSERT INTO laya_dataset_assignments(snapshot_id,candidate_id,group_id,split_name,content_hash) "
                "VALUES(?,?,?,?,?)",
                [
                    (snapshot_id, candidate_id, group_id, split_name, record_hash)
                    for candidate_id, record_hash, group_id, split_name in assignment_rows
                ],
            )
            con.commit()
            return {
                "success": True,
                "snapshot_id": snapshot_id,
                **manifest,
                "snapshot_status": "prepared",
                "reused": False,
            }

    def _authenticated_human_reviewer(self, reviewer_ref: str, root: str, task_id: str) -> bool:
        authenticate = self._reviewer_authenticator
        if not callable(authenticate):
            return False
        try:
            return authenticate(reviewer_ref, root, task_id) is True
        except Exception:
            return False

    def _review_challenge(
        self,
        operation: Any,
        *,
        scope: str,
        root: str,
        task_store: Any,
    ) -> dict[str, Any]:
        if type(operation) is not dict:
            raise ValueError("review_challenge fields invalid")
        review_action = operation.get("review_action")
        fields = (
            {"action", "candidate_id", "review_action", "role", "reviewer_fingerprint", "target"}
            if review_action == "label"
            else {"action", "candidate_id", "review_action", "role", "reviewer_fingerprint"}
        )
        op = _strict_object(operation, fields, "review_challenge")
        candidate_id = _identity(op["candidate_id"], "candidate_id")
        role = op["role"]
        fingerprint = op["reviewer_fingerprint"]
        if type(fingerprint) is not str or fingerprint not in self._reviewer_keys:
            raise ValueError("authenticated human reviewer provenance is unavailable")
        with closing(self._connect(task_store)) as con:
            row = con.execute(
                "SELECT candidate_id,task_id,session_id,content_hash,candidate_json,status "
                "FROM laya_candidates WHERE repository_scope=? AND candidate_id=?",
                (scope, candidate_id),
            ).fetchone()
        if row is None:
            raise ValueError("candidate not found in authorized repository scope")
        task = self._find_task(task_store, root, str(row["task_id"]))
        if self._session_for_task(task) != row["session_id"]:
            raise ValueError("candidate session identity no longer matches its task")
        candidate = json.loads(row["candidate_json"])
        if review_action == "label":
            if row["status"] not in {"pending", "reviewed", "ambiguous"}:
                raise ValueError("candidate cannot be labeled in current state")
            if role not in {"annotation", "adjudication"}:
                raise ValueError("review challenge role is invalid")
            target = _identity(op["target"], "review target")
            if target not in candidate["questions"][candidate["category"]]["criteria"]:
                raise ValueError("review target is not an allowed option")
            label_targets_sha256 = None
        elif review_action == "verify":
            if row["status"] != "reviewed" or role != "verification":
                raise ValueError("verify challenge requires a reviewed candidate and verification role")
            targets = candidate.get("targets")
            target = targets.get(candidate["category"]) if isinstance(targets, dict) else None
            if type(target) is not str:
                raise ValueError("reviewed candidate has no valid target")
            label_targets_sha256 = hashlib.sha256(
                _canonical_json(targets).encode("utf-8")
            ).hexdigest()
        else:
            raise ValueError("review_action must be label or verify")
        message = self._review_message(
            action=review_action,
            role=role,
            target=target,
            reviewer_fingerprint=fingerprint,
            candidate_id=candidate_id,
            content_hash=str(row["content_hash"]),
            scope=scope,
            task_id=str(row["task_id"]),
            session_id=str(row["session_id"]),
            label_targets_sha256=label_targets_sha256,
        )
        return {
            "success": True,
            "candidate_id": candidate_id,
            "review_action": review_action,
            "role": role,
            "reviewer_fingerprint": fingerprint,
            "challenge_b64": base64.b64encode(message).decode("ascii"),
        }

    def _transition(self, operation: dict[str, Any], *, action: str, scope: str, root: str, task_store: Any) -> dict[str, Any]:
        fields = {
            "label": {"action", "candidate_id", "annotations", "adjudication"},
            "verify": {"action", "candidate_id", "proof"} if not callable(self._reviewer_authenticator) else {"action", "candidate_id", "reviewer_ref"},
            "reject": {"action", "candidate_id", "status", "reason_code"},
            "delete": {"action", "candidate_id"},
        }[action]
        op = _strict_object(operation, fields, action)
        candidate_id = _identity(op["candidate_id"], "candidate_id")
        with self._lock, closing(self._connect(task_store)) as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM laya_candidates WHERE repository_scope=? AND candidate_id=?", (scope, candidate_id)).fetchone()
            if row is None:
                con.rollback(); raise ValueError("candidate not found in authorized repository scope")
            self._find_task(task_store, root, row["task_id"])
            candidate = json.loads(row["candidate_json"])
            current = row["status"]
            now = time.time()
            if action == "label":
                if current not in {"pending", "reviewed", "ambiguous"}:
                    con.rollback(); raise ValueError("candidate cannot be labeled in current state")
                annotations = op["annotations"]
                if type(annotations) is not list or len(annotations) != 2:
                    con.rollback(); raise ValueError("two independent annotations are required")
                proof_mode = not callable(self._reviewer_authenticator)
                parsed = []
                for item in annotations:
                    item = _strict_object(
                        item,
                        {"target", "proof"} if proof_mode else {"annotator_ref", "target"},
                        "annotation",
                    )
                    target = _identity(item["target"], "annotation target")
                    if target not in candidate["questions"][candidate["category"]]["criteria"]:
                        con.rollback(); raise ValueError("annotation target is not an allowed option")
                    if proof_mode:
                        proof = _strict_object(item["proof"], {"reviewer_fingerprint", "signature"}, "review proof")
                        annotator = proof["reviewer_fingerprint"]
                    else:
                        proof = None
                        annotator = _identity(item["annotator_ref"], "annotator_ref")
                    parsed.append({"annotator_ref": annotator, "target": target, **({"proof": proof} if proof_mode else {})})
                if parsed[0]["annotator_ref"] == parsed[1]["annotator_ref"]:
                    con.rollback(); raise ValueError("independent annotators must differ")
                adjudication = _strict_object(
                    op["adjudication"],
                    {"target", "proof"} if proof_mode else {"reviewer_ref", "target"},
                    "adjudication",
                )
                target = _identity(adjudication["target"], "adjudication target")
                if proof_mode:
                    proof = _strict_object(adjudication["proof"], {"reviewer_fingerprint", "signature"}, "review proof")
                    reviewer = proof["reviewer_fingerprint"]
                else:
                    proof = None
                    reviewer = _identity(adjudication["reviewer_ref"], "adjudicator_ref")
                if reviewer in {parsed[0]["annotator_ref"], parsed[1]["annotator_ref"]}:
                    con.rollback(); raise ValueError("adjudicator must be independent")
                if target not in candidate["questions"][candidate["category"]]["criteria"]:
                    con.rollback(); raise ValueError("adjudication target is not an allowed option")
                if proof_mode:
                    for annotation in parsed:
                        challenge = self._review_message(
                            action="label", role="annotation", target=annotation["target"],
                            reviewer_fingerprint=annotation["annotator_ref"], candidate_id=candidate_id,
                            content_hash=str(row["content_hash"]), scope=scope,
                            task_id=str(row["task_id"]), session_id=str(row["session_id"]),
                        )
                        self._verify_review_proof(annotation["proof"], challenge)
                    challenge = self._review_message(
                        action="label", role="adjudication", target=target,
                        reviewer_fingerprint=reviewer, candidate_id=candidate_id,
                        content_hash=str(row["content_hash"]), scope=scope,
                        task_id=str(row["task_id"]), session_id=str(row["session_id"]),
                    )
                    self._verify_review_proof(proof, challenge)
                elif any(
                    not self._authenticated_human_reviewer(reviewer_ref, root, row["task_id"])
                    for reviewer_ref in (parsed[0]["annotator_ref"], parsed[1]["annotator_ref"], reviewer)
                ):
                    con.rollback(); raise ValueError("authenticated human reviewer provenance is unavailable")
                candidate["targets"] = {candidate["category"]: target}
                candidate["label_provenance"] = {
                    "rubric_version": _LABEL_RUBRIC_VERSION,
                    "annotations": parsed,
                    "adjudication": {"reviewer_ref": reviewer, "target": target},
                }
                candidate["label_status"] = "reviewed"
                new_status = "reviewed"
                details = {"annotator_count": 2, "adjudicator_ref": reviewer}
            elif action == "verify":
                if current != "reviewed":
                    con.rollback(); raise ValueError("verify requires a reviewed candidate")
                proof_mode = not callable(self._reviewer_authenticator)
                if proof_mode:
                    proof = _strict_object(op["proof"], {"reviewer_fingerprint", "signature"}, "review proof")
                    reviewer = proof["reviewer_fingerprint"]
                else:
                    proof = None
                    reviewer = _identity(op["reviewer_ref"], "reviewer_ref")
                provenance = candidate.get("label_provenance", {})
                annotators = {item["annotator_ref"] for item in provenance.get("annotations", [])}
                adjudicator = provenance.get("adjudication", {}).get("reviewer_ref")
                if reviewer in annotators or reviewer == adjudicator:
                    con.rollback(); raise ValueError("verification reviewer must be independent")
                if proof_mode:
                    label_targets = candidate.get("targets")
                    target = label_targets.get(candidate["category"]) if isinstance(label_targets, dict) else None
                    challenge = self._review_message(
                        action="verify", role="verification", target=target,
                        reviewer_fingerprint=reviewer, candidate_id=candidate_id,
                        content_hash=str(row["content_hash"]), scope=scope,
                        task_id=str(row["task_id"]), session_id=str(row["session_id"]),
                        label_targets_sha256=hashlib.sha256(_canonical_json(label_targets).encode("utf-8")).hexdigest(),
                    )
                    self._verify_review_proof(proof, challenge)
                elif not self._authenticated_human_reviewer(reviewer, root, row["task_id"]):
                    con.rollback()
                    raise ValueError("authenticated human reviewer provenance is unavailable")
                candidate["label_status"] = "verified"
                candidate["label_provenance"]["verification"] = {
                    "reviewer_ref": reviewer,
                    "method": "authenticated_human_review",
                }
                new_status = "verified"
                details = {"reviewer_ref": reviewer, "method": "authenticated_human_review"}
            elif action == "reject":
                if current not in {"pending", "reviewed", "ambiguous"}:
                    con.rollback(); raise ValueError("reject requires a reviewable candidate")
                new_status = op["status"]
                if new_status not in {"rejected", "ambiguous"}:
                    con.rollback(); raise ValueError("reject status must be rejected or ambiguous")
                reason_code = _identity(op["reason_code"], "reason_code")
                candidate["label_status"] = new_status
                candidate["label_provenance"].setdefault("events", []).append(
                    {"status": new_status, "reason_code": reason_code}
                )
                details = {"reason_code": reason_code}
            else:
                snapshots = con.execute(
                    "SELECT DISTINCT snapshot_id FROM laya_dataset_assignments WHERE candidate_id=?",
                    (candidate_id,),
                ).fetchall()
                for snapshot in snapshots:
                    self._purge_snapshot_export(str(snapshot["snapshot_id"]))
                con.execute(
                    "UPDATE laya_dataset_snapshots SET status='invalidated' "
                    "WHERE snapshot_id IN (SELECT snapshot_id FROM laya_dataset_assignments WHERE candidate_id=?)",
                    (candidate_id,),
                )
                con.execute("DELETE FROM laya_candidate_events WHERE candidate_id=?", (candidate_id,))
                self._event(
                    con, candidate_id, scope, row["task_id"], "deleted", {"status": "deleted"}, now
                )
                con.execute("DELETE FROM laya_candidates WHERE candidate_id=?", (candidate_id,))
                con.commit()
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                return {"success": True, "candidate_id": candidate_id, "deleted": True}
            con.execute("UPDATE laya_candidates SET status=?,candidate_json=?,updated_at=? WHERE candidate_id=?", (new_status, _canonical_json(candidate), now, candidate_id))
            self._event(con, candidate_id, scope, row["task_id"], action, details, now)
            con.commit()
        return {"success": True, "candidate_id": candidate_id, "status": new_status}

    @staticmethod
    def _event(con: sqlite3.Connection, candidate_id: str, scope: str, task_id: str, action: str, metadata: Mapping[str, Any], now: float) -> None:
        con.execute(
            "INSERT INTO laya_candidate_events VALUES(?,?,?,?,?,?,?)",
            ("evt_" + uuid.uuid4().hex, candidate_id, scope, task_id, action, _canonical_json(metadata), now),
        )
