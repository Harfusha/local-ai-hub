"""Local change observation and operator-declared review ledger.

Content identity is not authorship. An annotation is not a trusted verification
receipt, a write lease, or permission to omit independent review.
"""
from __future__ import annotations

import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

_HEX = re.compile(r"[0-9a-f]{64}")
_MAX_ATOMS = 256
_MAX_RETAINED = 10000


def _current(plan: dict[str, Any]) -> tuple[str, str, dict[str, tuple[str, str]]]:
    root, rev = plan.get("root"), plan.get("observed_change_set_id")
    if (plan.get("success") is not True or plan.get("comparison") is not None
            or plan.get("git_visible_observation_complete") is not True
            or plan.get("inventory_scope") != "git_visible_changes"
            or not isinstance(root, str) or not isinstance(rev, str) or not _HEX.fullmatch(rev)):
        raise ValueError("Complete worktree observation required")
    atoms: dict[str, tuple[str, str]] = {}
    for group in plan.get("clusters", []):
        for change in group.get("changes", []):
            for atom in change.get("atoms", []):
                aid, path, scope = atom.get("atom_id"), change.get("path"), atom.get("scope")
                if (not isinstance(aid, str) or not _HEX.fullmatch(aid) or aid in atoms
                        or not isinstance(path, str) or scope not in {"staged", "unstaged", "untracked"}):
                    raise ValueError("Invalid atom observation")
                atoms[aid] = (path, scope)
    if len(atoms) > _MAX_ATOMS:
        raise ValueError("Ledger atom budget exceeded")
    return root, rev, atoms


class ChangeLedger:
    def __init__(self, state: Path):
        state.mkdir(parents=True, exist_ok=True)
        self.path = state / "git-change-ledger.sqlite"
        if self.path.is_symlink():
            raise ValueError("Redirecting ledger is not supported")
        with closing(self._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS change_atoms_v1 (
                root TEXT NOT NULL, atom TEXT NOT NULL, path TEXT NOT NULL, scope TEXT NOT NULL,
                first_seen REAL NOT NULL, last_seen REAL NOT NULL, revision TEXT NOT NULL,
                PRIMARY KEY(root,atom)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS change_annotations_v1 (
                root TEXT NOT NULL, atom TEXT NOT NULL, actor TEXT NOT NULL, task TEXT NOT NULL,
                status TEXT NOT NULL, revision TEXT NOT NULL, observed REAL NOT NULL,
                PRIMARY KEY(root,atom,actor)
            )""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=1)
        db.row_factory = sqlite3.Row
        return db

    def observe(self, plan: dict[str, Any]) -> None:
        root, rev, atoms = _current(plan)
        now = time.time()
        with closing(self._connect()) as db, db:
            db.executemany("""INSERT INTO change_atoms_v1 VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(root,atom) DO UPDATE SET last_seen=excluded.last_seen, revision=excluded.revision""",
                [(root, aid, path, scope, now, now, rev) for aid, (path, scope) in atoms.items()])
            db.execute("""DELETE FROM change_atoms_v1 WHERE root=? AND atom IN (
                SELECT atom FROM change_atoms_v1 WHERE root=? ORDER BY last_seen DESC,atom LIMIT -1 OFFSET ?
            ) AND NOT EXISTS (SELECT 1 FROM change_annotations_v1 a WHERE a.root=change_atoms_v1.root AND a.atom=change_atoms_v1.atom)""",
                       (root, root, _MAX_RETAINED))

    def annotate(self, plan: dict[str, Any], *, expected_revision: str, record: Any) -> dict[str, Any]:
        root, rev, atoms = _current(plan)
        if rev != expected_revision:
            raise ValueError("Observation changed; refresh before annotating")
        if not isinstance(record, dict) or set(record) != {"atom_ids", "actor", "task_id", "status"}:
            raise ValueError("Annotation requires atom_ids, actor, task_id and status")
        ids, actor, task, status = (record[k] for k in ("atom_ids", "actor", "task_id", "status"))
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 64
                or any(not isinstance(a, str) or a not in atoms for a in ids) or len(set(ids)) != len(ids)
                or not isinstance(actor, str) or not actor.strip() or len(actor) > 128
                or not isinstance(task, str) or len(task) > 128
                or any(ord(c) < 32 for c in actor + task)
                or not isinstance(status, str) or status not in {"assigned", "reviewed", "needs_review", "withdrawn"}):
            raise ValueError("Invalid or stale annotation")
        self.observe(plan)
        now = time.time()
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT count(*) FROM change_annotations_v1 WHERE root=?", (root,)).fetchone()[0]
            # Updates of existing declarations must not consume new retention slots.
            marks = ",".join("?" for _ in ids)
            existing = db.execute(
                "SELECT count(*) FROM change_annotations_v1 WHERE root=? AND actor=? AND atom IN (" + marks + ")",
                (root, actor, *ids),
            ).fetchone()[0]
            if count + len(ids) - existing > _MAX_RETAINED:
                raise ValueError("Local annotation retention limit reached")
            db.executemany("""INSERT INTO change_annotations_v1 VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(root,atom,actor) DO UPDATE SET task=excluded.task,status=excluded.status,
                revision=excluded.revision,observed=excluded.observed""",
                [(root, aid, actor, task, status, rev, now) for aid in ids])
        return {"success": True, "annotated_atom_count": len(ids), "observed_change_set_id": rev,
                "status": status, "authority": "operator_declaration_only", "commit_ready": False}

    def attach(self, plan: dict[str, Any]) -> None:
        root, rev, atoms = _current(plan)
        rows: dict[str, list[dict[str, Any]]] = {}
        if atoms:
            marks = ",".join("?" for _ in atoms)
            with closing(self._connect()) as db:
                records = db.execute("SELECT * FROM change_annotations_v1 WHERE root=? AND atom IN (" + marks + ") ORDER BY atom,actor",
                                     (root, *atoms)).fetchall()
            for row in records:
                if row["status"] == "withdrawn":
                    continue
                rows.setdefault(row["atom"], []).append({
                    "actor": row["actor"], "task_id": row["task"], "status": row["status"],
                    "current_observation": row["revision"] == rev,
                })
        covered = 0
        for group in plan.get("clusters", []):
            count = current = conflicting = 0
            for change in group.get("changes", []):
                for atom in change.get("atoms", []):
                    notes = rows.get(atom["atom_id"], [])
                    if notes:
                        count += 1
                    if any(n["current_observation"] for n in notes):
                        current += 1
                    if len({(n["actor"], n["task_id"]) for n in notes}) > 1:
                        conflicting += 1
                    atom["local_annotations"] = notes[:4]
                    atom["local_annotations_omitted"] = max(0, len(notes) - 4)
            covered += current
            group["local_ledger"] = {"annotated_atoms": count, "current_annotation_atoms": current,
                                     "multiple_actor_atoms": conflicting, "authority": "operator_declaration_only"}
        plan["local_ledger"] = {"observed_atoms": len(atoms), "current_annotation_atoms": covered,
                                "unannotated_or_stale_atoms": len(atoms) - covered,
                                "authoritative_ownership_proven": False, "verification_reuse_authorized": False}


def attach_watcher_candidates(plan: dict[str, Any], preprocessor: Any) -> None:
    """Correlate recent path events with the current observation, not with an actor."""
    root, _, atoms = _current(plan)
    paths = sorted({path for path, _ in atoms.values()})
    if preprocessor is None:
        events = {}
        available = False
    else:
        events = preprocessor.recent_change_events(root, paths)
        available = isinstance(events, dict)
        if not available:
            events = {}
    total = 0
    for group in plan.get("clusters", []):
        matched = 0
        for change in group.get("changes", []):
            event = events.get(change["path"])
            if not isinstance(event, dict) or event.get("event") not in {"created", "modified", "deleted", "moved"}:
                continue
            observed = event.get("observed_at")
            if type(observed) not in {int, float} or not 0 < observed <= time.time() + 1:
                continue
            change["watcher_candidate"] = {"event": event["event"], "observed_at": observed,
                                           "relation": "recent_same_path_only"}
            matched += 1
        group["watcher_candidate_paths"] = matched
        total += matched
    plan["watcher_context"] = {"status": "observed" if available else "unavailable",
                               "candidate_path_count": total, "coverage_complete": False,
                               "authorship_proven": False, "verification_reuse_authorized": False}
