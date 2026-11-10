"""Explicit-consent Laya training-candidate lifecycle in local state storage."""

from __future__ import annotations

import hashlib
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
from typing import Any, Mapping

from .agent_tasks import _canonical_repository_root, _task_matches_scope
from .json_utils import dumps as json_dumps
from .laya_decisions import DecisionCategory, _CATEGORY_OPTIONS

_SCHEMA_VERSION = 1
_CHECKPOINT = "convaiinnovations/laya-multilingual"
_CHECKPOINT_REVISION = "1720e3e3357cfe1e281542e223f8273b0890ca34"
_TOKENIZER_SHA256 = "609d8f4c067cd3950f88594c5a802616cea245823836ef5848ee4fc40aab5b6f"
_MAX_STATE_BYTES = 16 * 1024
_MAX_CANDIDATE_BYTES = 64 * 1024
_MAX_CAPTURE_BATCH_SIZE = 100
_MAX_CANDIDATES_PER_EXPORT = 20_000
_MAX_SPLIT_SHINGLES = 1_000_000
_MAX_DUPLICATE_COMPARISONS = 250_000
_NEAR_DUPLICATE_JACCARD = 0.80
_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_LANG = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\Z")
_STATES = {"captured", "pending", "reviewed", "verified", "rejected", "ambiguous", "exported"}
_INSTRUCTIONS = {
    DecisionCategory.CONTEXT_SOURCE: "Choose the next authorized context source or evidence action.",
    DecisionCategory.CONTEXT_BUDGET: "Choose the bounded response context budget profile.",
    DecisionCategory.MODEL_ROUTE: "Choose an available model tier for the described task class.",
    DecisionCategory.REDUNDANT_STEP: "Choose whether the proposed step may be duplicate while preserving required validation.",
    DecisionCategory.NEXT_STEP: "Choose the next evidence or recovery step.",
    DecisionCategory.DELEGATION: "Choose a review or bounded-delegation recommendation; do not execute it.",
    DecisionCategory.COMPLETION_GAP: "Choose the missing verification or review recommendation.",
    DecisionCategory.WATCHDOG: "Choose a watchdog recommendation; do not stop or continue the task.",
}


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
    """Stores consented candidates in the existing Agent State database."""

    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir).resolve()
        self.path: Path | None = None
        self._lock = threading.RLock()

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
        con = sqlite3.connect(path, timeout=2.0, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=2000")
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA secure_delete=ON")
        con.execute("PRAGMA journal_mode=WAL")
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
        if type(state) is str:
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
        language = row["language"]
        if type(language) is not str or not _LANG.fullmatch(language):
            raise ValueError("candidate language invalid")
        preprocessing = _strict_object(row["preprocessing"], {"name", "version"}, "preprocessing")
        if any(type(preprocessing[k]) is not str or not _IDENT.fullmatch(preprocessing[k]) for k in preprocessing):
            raise ValueError("preprocessing identity invalid")
        evidence_ids = row["evidence_ids"]
        if type(evidence_ids) is not list or len(evidence_ids) > 64:
            raise ValueError("candidate evidence_ids invalid")
        evidence_ids = [_identity(item, "evidence_id") for item in evidence_ids]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("duplicate evidence_id")
        question = {
            "id": category.value,
            "type": "choice",
            "instructions": _INSTRUCTIONS[category],
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

    def handle(self, operation: Any, *, root: str, task_store: Any) -> dict[str, Any]:
        if type(operation) is not dict or type(operation.get("action")) is not str:
            raise ValueError("laya_operation must be an object with an action")
        action = operation["action"]
        canonical_root = _canonical_repository_root(root)
        scope = self._repo_scope(canonical_root)
        if action == "capture":
            op = _strict_object(operation, {"action", "consent", "task_id", "session_id", "candidate"}, "capture")
            if op["consent"] is not True:
                raise ValueError("capture requires explicit per-example consent=true")
            task_id = _identity(op["task_id"], "task_id")
            task = self._find_task(task_store, canonical_root, task_id)
            session_id = _identity(op["session_id"], "session_id")
            if self._session_for_task(task) != session_id:
                raise ValueError("session_id does not match the scoped task")
            candidate = self._candidate_input(op["candidate"])
            content_hash = hashlib.sha256(_canonical_json(candidate).encode("utf-8")).hexdigest()
            group_id = "grp_" + hashlib.sha256(f"{scope}\0{task_id}\0{session_id}".encode()).hexdigest()[:32]
            now = time.time()
            with self._lock, closing(self._connect(task_store)) as con:
                con.execute("BEGIN IMMEDIATE")
                existing = con.execute(
                    "SELECT candidate_id,status FROM laya_candidates WHERE repository_scope=? AND content_hash=?",
                    (scope, content_hash),
                ).fetchone()
                if existing:
                    con.rollback()
                    return {"success": True, "duplicate": True, "candidate_id": existing["candidate_id"], "status": existing["status"]}
                candidate_id = "laya_" + uuid.uuid4().hex
                con.execute(
                    "INSERT INTO laya_candidates VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (candidate_id, scope, task_id, session_id, group_id, content_hash, "pending", _canonical_json(candidate), now, now),
                )
                self._event(con, candidate_id, scope, task_id, "captured", {"schema_version": _SCHEMA_VERSION}, now)
                self._event(con, candidate_id, scope, task_id, "pending", {"label_status": "pending"}, now)
                con.commit()
            return {"success": True, "duplicate": False, "candidate_id": candidate_id, "status": "pending"}
        if action == "capture_batch":
            op = _strict_object(operation, {"action", "task_id", "session_id", "examples"}, "capture_batch")
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
                row = _strict_object(example, {"consent", "candidate"}, "capture_batch example")
                if row["consent"] is not True:
                    raise ValueError("capture_batch requires per-example consent=true")
                candidate = self._candidate_input(row["candidate"])
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
                            else:
                                candidate_id = "laya_" + uuid.uuid4().hex
                                con.execute(
                                    "INSERT INTO laya_candidates VALUES(?,?,?,?,?,?,?,?,?,?)",
                                    (candidate_id, scope, task_id, session_id, group_id, content_hash,
                                     "pending", _canonical_json(candidate), now, now),
                                )
                                self._event(con, candidate_id, scope, task_id, "captured", {"schema_version": _SCHEMA_VERSION}, now)
                                self._event(con, candidate_id, scope, task_id, "pending", {"label_status": "pending"}, now)
                                captured_count += 1
                            seen[content_hash] = candidate_id
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
        if action in {"label", "verify", "reject", "delete"}:
            return self._transition(operation, action=action, scope=scope, root=canonical_root, task_store=task_store)
        if action == "prepare_splits":
            return self._prepare_splits(operation, scope=scope, task_store=task_store)
        if action == "export":
            op = _strict_object(operation, {"action", "consent", "output_path", "snapshot_id"}, "export")
            if op["consent"] is not True:
                raise ValueError("candidate export requires explicit consent=true")
            snapshot_id = _identity(op["snapshot_id"], "snapshot_id")
            requested = Path(op["output_path"]).expanduser()
            if type(op["output_path"]) is not str or not op["output_path"].strip():
                raise ValueError("output_path is required for candidate export")
            if not requested.is_absolute():
                requested = Path(canonical_root) / requested
            out_file = requested.resolve(strict=False)
            if out_file == Path(canonical_root) or not out_file.is_relative_to(Path(canonical_root)):
                raise ValueError("candidate export path must remain inside authorized repository root")
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
                    "SELECT a.candidate_id,a.content_hash,c.candidate_json,c.status "
                    "FROM laya_dataset_assignments a JOIN laya_candidates c ON c.candidate_id=a.candidate_id "
                    "WHERE a.snapshot_id=? AND a.split_name='train' AND c.repository_scope=? "
                    "ORDER BY c.created_at,c.candidate_id LIMIT ?",
                    (snapshot_id, scope, _MAX_CANDIDATES_PER_EXPORT + 1),
                ).fetchall()
                if any(row["status"] not in {"verified", "exported"} for row in assignments):
                    raise ValueError("dataset snapshot contains a candidate no longer verified")
                if any(hashlib.sha256(row["candidate_json"].encode("utf-8")).hexdigest() != row["content_hash"] for row in assignments):
                    raise ValueError("dataset snapshot candidate content changed")
                rows = [json.loads(row["candidate_json"]) for row in assignments]
                if len(rows) > _MAX_CANDIDATES_PER_EXPORT:
                    raise ValueError("candidate export exceeds row limit")
                payload = "".join(_canonical_json(row) + "\n" for row in rows)
                if len(payload.encode("utf-8")) > 16 * 1024 * 1024:
                    raise ValueError("candidate export exceeds byte limit")
                if not rows:
                    raise ValueError("dataset snapshot has no train candidates to export")
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file = out_file.resolve(strict=False)
                if not out_file.is_relative_to(Path(canonical_root)):
                    raise ValueError("candidate export path escaped authorized repository root")
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

    def export_train_payload(self, operation: Any, *, root: str, task_store: Any) -> bytes:
        """Build an explicit, scope-checked upstream training JSONL payload in memory."""
        op = _strict_object(operation, {"consent", "snapshot_id"}, "candidate ZIP export")
        if op["consent"] is not True:
            raise ValueError("candidate ZIP export requires explicit consent=true")
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
                "SELECT a.content_hash,c.candidate_json,c.status,c.task_id,c.session_id "
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
                    "state": candidate["state"],
                    "questions": candidate["questions"],
                    "expected": {question_id: target},
                })
            payload = "".join(_canonical_json(row) + "\n" for row in rows).encode("utf-8")
            if len(payload) > 16 * 1024 * 1024:
                raise ValueError("candidate export exceeds byte limit")
            con.commit()
            return payload

    def _prepare_splits(self, operation: dict[str, Any], *, scope: str, task_store: Any) -> dict[str, Any]:
        op = _strict_object(operation, {"action", "consent"}, "prepare_splits")
        if op["consent"] is not True:
            raise ValueError("preparing dataset splits requires explicit consent=true")
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

    def _transition(self, operation: dict[str, Any], *, action: str, scope: str, root: str, task_store: Any) -> dict[str, Any]:
        fields = {
            "label": {"action", "candidate_id", "annotations", "adjudication"},
            "verify": {"action", "candidate_id", "consent", "reviewer_ref"},
            "reject": {"action", "candidate_id", "consent", "status", "reason_code"},
            "delete": {"action", "candidate_id", "consent"},
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
                parsed = []
                for item in annotations:
                    item = _strict_object(item, {"annotator_ref", "target"}, "annotation")
                    annotator = _identity(item["annotator_ref"], "annotator_ref")
                    target = _identity(item["target"], "annotation target")
                    if target not in candidate["questions"][candidate["category"]]["criteria"]:
                        con.rollback(); raise ValueError("annotation target is not an allowed option")
                    parsed.append({"annotator_ref": annotator, "target": target})
                if parsed[0]["annotator_ref"] == parsed[1]["annotator_ref"]:
                    con.rollback(); raise ValueError("independent annotators must differ")
                adjudication = _strict_object(op["adjudication"], {"reviewer_ref", "target"}, "adjudication")
                reviewer = _identity(adjudication["reviewer_ref"], "adjudicator_ref")
                target = _identity(adjudication["target"], "adjudication target")
                if reviewer in {parsed[0]["annotator_ref"], parsed[1]["annotator_ref"]}:
                    con.rollback(); raise ValueError("adjudicator must be independent")
                if target not in candidate["questions"][candidate["category"]]["criteria"]:
                    con.rollback(); raise ValueError("adjudication target is not an allowed option")
                candidate["targets"] = {candidate["category"]: target}
                candidate["label_provenance"] = {"annotations": parsed, "adjudication": {"reviewer_ref": reviewer, "target": target}}
                candidate["label_status"] = "reviewed"
                new_status = "reviewed"
                details = {"annotator_count": 2, "adjudicator_ref": reviewer}
            elif action == "verify":
                if current != "reviewed" or op["consent"] is not True:
                    con.rollback(); raise ValueError("verify requires reviewed candidate and explicit consent=true")
                reviewer = _identity(op["reviewer_ref"], "reviewer_ref")
                provenance = candidate.get("label_provenance", {})
                annotators = {item["annotator_ref"] for item in provenance.get("annotations", [])}
                adjudicator = provenance.get("adjudication", {}).get("reviewer_ref")
                if reviewer in annotators or reviewer == adjudicator:
                    con.rollback(); raise ValueError("verification reviewer must be independent")
                candidate["label_status"] = "verified"
                candidate["label_provenance"]["verification"] = {"reviewer_ref": reviewer, "method": "explicit_human_review"}
                new_status = "verified"
                details = {"reviewer_ref": reviewer, "method": "explicit_human_review"}
            elif action == "reject":
                if current not in {"pending", "reviewed", "ambiguous"} or op["consent"] is not True:
                    con.rollback(); raise ValueError("reject requires a reviewable candidate and consent=true")
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
                if op["consent"] is not True:
                    con.rollback(); raise ValueError("delete requires explicit consent=true")
                self._event(con, candidate_id, scope, row["task_id"], "deleted", {"previous_status": current}, now)
                con.execute(
                    "UPDATE laya_dataset_snapshots SET status='invalidated' "
                    "WHERE snapshot_id IN (SELECT snapshot_id FROM laya_dataset_assignments WHERE candidate_id=?)",
                    (candidate_id,),
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
