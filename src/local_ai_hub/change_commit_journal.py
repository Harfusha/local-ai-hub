"""Durable local commit intent log; inspection never retries a mutation."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from .process_utils import clean_git_env, run_hidden

_ID = re.compile(r"[0-9a-f]{32}")
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


class CommitJournal:
    def __init__(self, state_dir: Path):
        self.path = state_dir / "git-commit-journal.sqlite"
        state_dir.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("Redirecting commit journal is not supported")
        with closing(self._connect()) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS git_commit_intents_v1 (
                id TEXT PRIMARY KEY, root TEXT NOT NULL, branch TEXT NOT NULL,
                parent TEXT NOT NULL, tree TEXT NOT NULL, candidate TEXT NOT NULL,
                state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS git_tree_checks_v1 (
                id TEXT PRIMARY KEY, root TEXT NOT NULL, tree TEXT NOT NULL,
                command_id TEXT NOT NULL, environment_id TEXT NOT NULL,
                checks TEXT NOT NULL, digest TEXT NOT NULL, observed REAL NOT NULL, expires REAL NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS git_tree_checks_lookup ON git_tree_checks_v1(root,tree,command_id,environment_id,expires)")
            db.execute("""CREATE TABLE IF NOT EXISTS git_tree_check_attempt_v1 (
                root TEXT NOT NULL, tree TEXT NOT NULL, command_id TEXT NOT NULL,
                environment_id TEXT NOT NULL, attempt TEXT NOT NULL, observed REAL NOT NULL,
                PRIMARY KEY(root,tree,command_id,environment_id)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS git_tree_check_failures_v1 (
                root TEXT NOT NULL, tree TEXT NOT NULL, command_id TEXT NOT NULL,
                environment_id TEXT NOT NULL, attempt TEXT NOT NULL, reason TEXT NOT NULL,
                observed REAL NOT NULL, PRIMARY KEY(root,tree,command_id,environment_id)
            )""")
            db.commit()

    def begin_tree_checks(self, *, root: str, tree: str, command_id: str, environment_id: str) -> str:
        attempt = uuid.uuid4().hex
        with closing(self._connect()) as db, db:
            db.execute("INSERT OR REPLACE INTO git_tree_check_attempt_v1 VALUES (?,?,?,?,?,?)",
                       (root, tree, command_id, environment_id, attempt, time.time()))
            db.execute("DELETE FROM git_tree_checks_v1 WHERE root=? AND tree=? AND command_id=? AND environment_id=?",
                       (root, tree, command_id, environment_id))
            db.execute("DELETE FROM git_tree_check_failures_v1 WHERE root=? AND tree=? AND command_id=? AND environment_id=?",
                       (root, tree, command_id, environment_id))
            db.execute("DELETE FROM git_tree_check_attempt_v1 WHERE observed < ?", (time.time() - 86400,))
            db.execute("DELETE FROM git_tree_check_failures_v1 WHERE observed < ?", (time.time() - 86400,))
        return attempt

    def record_tree_check_failure(self, *, root: str, tree: str, command_id: str, environment_id: str,
                                  attempt: str, reason: str) -> bool:
        """Persist only a bounded failure code for the current fenced attempt."""
        if reason not in {"command_failed", "incomplete_output", "verification_interrupted"}:
            raise ValueError("Invalid tree check failure reason")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT attempt FROM git_tree_check_attempt_v1 WHERE root=? AND tree=? AND command_id=? AND environment_id=?",
                                 (root, tree, command_id, environment_id)).fetchone()
            if current is None or current["attempt"] != attempt:
                return False
            db.execute("INSERT OR REPLACE INTO git_tree_check_failures_v1 VALUES (?,?,?,?,?,?,?)",
                       (root, tree, command_id, environment_id, attempt, reason, time.time()))
        return True

    def tree_check_observation(self, *, root: str, tree: str, command_id: str, environment_id: str) -> dict[str, Any]:
        scope = dict(root=root, tree=tree, command_id=command_id, environment_id=environment_id)
        receipt = self.current_tree_checks(**scope)
        if receipt:
            return {"status": "current", "receipt_id": receipt}
        now = time.time()
        with closing(self._connect()) as db:
            attempt = db.execute("SELECT attempt, observed FROM git_tree_check_attempt_v1 WHERE root=? AND tree=? AND command_id=? AND environment_id=?",
                                 (root, tree, command_id, environment_id)).fetchone()
            failure = db.execute("SELECT attempt, reason, observed FROM git_tree_check_failures_v1 WHERE root=? AND tree=? AND command_id=? AND environment_id=?",
                                 (root, tree, command_id, environment_id)).fetchone()
            expired = db.execute("SELECT 1 FROM git_tree_checks_v1 WHERE root=? AND tree=? AND command_id=? AND environment_id=? AND expires<=? LIMIT 1",
                                 (root, tree, command_id, environment_id, now)).fetchone()
        if attempt is not None and failure is not None and attempt["attempt"] == failure["attempt"] and 0 <= now - failure["observed"] < 86400:
            return {"status": "failed", "receipt_id": None, "failure_reason": failure["reason"]}
        if expired is not None:
            return {"status": "expired", "receipt_id": None}
        if attempt is not None and 0 <= now - attempt["observed"] < 86400:
            return {"status": "in_progress_or_interrupted", "receipt_id": None}
        return {"status": "missing", "receipt_id": None}

    def record_tree_checks(self, *, root: str, tree: str, command_id: str, environment_id: str,
                           checks: list[dict[str, Any]], ttl: int, attempt: str) -> str:
        if (not _OID.fullmatch(tree) or not re.fullmatch(r"[0-9a-f]{64}", command_id)
                or not re.fullmatch(r"[0-9a-f]{64}", environment_id) or not 1 <= ttl <= 3600
                or not 1 <= len(checks) <= 4 or any(c.get("exit_code") != 0 or c.get("output_complete") is not True for c in checks)):
            raise ValueError("Invalid exact-tree check record")
        receipt = uuid.uuid4().hex
        now = time.time()
        serialized = json.dumps(checks, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(json.dumps([receipt, root, tree, command_id, environment_id, serialized, now, now + ttl],
                                           ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
        with closing(self._connect()) as db, db:
            # Fence against concurrent verification attempts and refuse a stale
            # success when a newer attempt has started.
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT attempt FROM git_tree_check_attempt_v1 WHERE root=? AND tree=? AND command_id=? AND environment_id=?",
                                 (root, tree, command_id, environment_id)).fetchone()
            if current is None or current["attempt"] != attempt:
                raise ValueError("Verification attempt superseded")
            db.execute("INSERT INTO git_tree_checks_v1 VALUES (?,?,?,?,?,?,?,?,?)",
                       (receipt, root, tree, command_id, environment_id, serialized, digest, now, now + ttl))
            db.execute("DELETE FROM git_tree_check_failures_v1 WHERE root=? AND tree=? AND command_id=? AND environment_id=?",
                       (root, tree, command_id, environment_id))
            db.execute("DELETE FROM git_tree_checks_v1 WHERE expires < ?", (now - 86400,))
            db.execute("DELETE FROM git_tree_check_attempt_v1 WHERE observed < ?", (now - 86400,))
        return receipt

    def current_tree_checks(self, *, root: str, tree: str, command_id: str, environment_id: str) -> str | None:
        now = time.time()
        with closing(self._connect()) as db:
            row = db.execute("""SELECT * FROM git_tree_checks_v1 WHERE root=? AND tree=? AND command_id=?
                              AND environment_id=? AND observed<=? AND expires>? ORDER BY observed DESC LIMIT 1""",
                             (root, tree, command_id, environment_id, now, now)).fetchone()
        if row is None:
            return None
        digest = hashlib.sha256(json.dumps([row["id"], root, tree, command_id, environment_id, row["checks"],
                                           row["observed"], row["expires"]], ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
        if row["digest"] != digest or not 0 < row["expires"] - row["observed"] <= 3600:
            return None
        try:
            checks = json.loads(row["checks"])
            if not isinstance(checks, list) or not 1 <= len(checks) <= 4 or any(
                not isinstance(c, dict) or type(c.get("exit_code")) is not int or c["exit_code"] != 0
                or c.get("output_complete") is not True for c in checks
            ):
                return None
        except (TypeError, ValueError):
            return None
        return row["id"]

    @contextmanager
    def publication_guard(self) -> Iterator[None]:
        """Exclude receipt-revoking writers during final checks and branch CAS."""
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        return db

    def prepare(self, *, operation_id: str, root: str, branch: str, parent: str, tree: str, candidate: str) -> None:
        if not _ID.fullmatch(operation_id) or not all(_OID.fullmatch(v) for v in (parent, tree, candidate)):
            raise ValueError("Invalid commit journal identity")
        now = time.time()
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO git_commit_intents_v1 VALUES (?, ?, ?, ?, ?, ?, 'prepared', ?, ?)",
                       (operation_id, root, branch, parent, tree, candidate, now, now))

    def published(self, operation_id: str) -> None:
        with closing(self._connect()) as db, db:
            updated = db.execute("UPDATE git_commit_intents_v1 SET state='published', updated=? WHERE id=? AND state='prepared'",
                                 (time.time(), operation_id))
            if updated.rowcount != 1:
                raise ValueError("Commit journal transition rejected")

    def list_recent(self, root: str, *, limit: int = 20) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100:
            return {"success": False, "error": "Limit must be 1–100"}
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM git_commit_intents_v1 WHERE root=? ORDER BY created DESC LIMIT ?",
                              (root, limit + 1)).fetchall()
        return {"success": True, "operations": [dict(row) for row in rows[:limit]],
                "has_more": len(rows) > limit, "retry_authorized": False}

    def inspect(self, root: str, operation_id: str) -> dict[str, Any]:
        if not isinstance(operation_id, str) or not _ID.fullmatch(operation_id):
            return {"success": False, "error": "Invalid operation ID"}
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM git_commit_intents_v1 WHERE id=? AND root=?", (operation_id, root)).fetchone()
        if row is None:
            return {"success": False, "error": "Scoped operation not found"}
        entry = dict(row)
        branch = entry["branch"]
        if not isinstance(branch, str) or not branch.startswith("refs/heads/"):
            return {"success": False, "error": "Invalid stored branch"}
        cp = run_hidden(["git", "--no-pager", "rev-parse", "--verify", "--end-of-options", branch],
                        cwd=root, capture_output=True, check=False, timeout=10,
                        max_output_bytes=4096, env=clean_git_env(extra_env={"GIT_OPTIONAL_LOCKS":"0",
                        "GIT_NO_REPLACE_OBJECTS":"1", "GIT_NO_LAZY_FETCH":"1"}))
        observed = cp.stdout.strip().decode("ascii", errors="replace") if cp.returncode == 0 else ""
        if not _OID.fullmatch(observed):
            status = "branch_unavailable"
        elif observed == entry["candidate"]:
            status = "candidate_is_branch_tip"
        elif observed == entry["parent"]:
            status = "parent_is_branch_tip"
        else:
            status = "branch_moved"
        return {"success": True, **entry, "observed_branch_tip": observed,
                "recovery_status": status, "retry_authorized": False,
                "index_lock_present": (Path(root) / ".git" / "index.lock").exists()}
