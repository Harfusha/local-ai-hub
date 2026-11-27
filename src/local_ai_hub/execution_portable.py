"""Portable execution observations in the existing Git-native knowledge store.

Export is a read-only candidate. The normal operator preview/apply workflow
owns publication. Imported records remain historical, unverified leads.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .agent_task_models import _task_scope_root
from .execution_problems import PROBLEM_STATE_KEY, _validated_records
from .repo_knowledge import RepoKnowledgeStore, _encode, _path_for, validate_knowledge_file
from .repo_knowledge_privacy import contains_private_project_data
from .repo_plan.schema_validation import RepoPlanValidationError
from .verified_execution import _canonical

PREFIX = "execution-lead-"
TITLE = "Historical execution problem"
MAX_LEADS = 8


def _statement(criterion: str, title: str) -> str:
    return json.dumps({"criterion": criterion, "observation": title},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _identity(statement: str) -> str:
    return PREFIX + hashlib.sha256(statement.encode("utf-8")).hexdigest()


def _scope(task: Any, request: Any) -> str:
    if request.scoped_task_only or not request.root:
        return ""
    root = _task_scope_root(task)
    if not root or not task.context.repository_id:
        return ""
    if any(getattr(task.context, key) != getattr(request, key)
           for key in ("repository_id", "clone_id", "worktree_id", "branch")):
        return ""
    try:
        return root if Path(root).samefile(request.root) else ""
    except (OSError, ValueError):
        return ""


def build_publication_candidate(report: Mapping[str, Any], project_id: str) -> dict[str, Any]:
    if report.get("share_repository") is not True:
        raise ValueError("execution observation is private")
    criterion = _canonical(report.get("criterion"), "criterion")
    title = _canonical(report.get("title"), "problem title", 240)
    statement = _statement(criterion, title)
    if contains_private_project_data({"criterion": criterion, "observation": title}):
        raise ValueError("execution observation contains recognizable private data")
    record = {
        "schema_version": 1, "project_id": project_id, "kind": "observation",
        "id": _identity(statement),
        "payload": {"title": TITLE, "statement": statement, "layer": "interpretation"},
        "provenance": {"origin_kind": "model"}, "evidence": [], "relations": [],
    }
    return validate_knowledge_file(_path_for("observation", record["id"]), _encode(record))


def publication_candidates(task: Any, request: Any) -> list[dict[str, Any]]:
    root = _scope(task, request)
    if not root:
        return []
    store = RepoKnowledgeStore(root)
    manifest, revision = store.manifest()
    if manifest["mode"] == "read_only":
        return []
    result = []
    for entry in _validated_records(task.checkpoint.state_data.get(PROBLEM_STATE_KEY, {})).values():
        report = entry["report"]
        if report.get("share_repository") is not True:
            continue
        try:
            candidate = build_publication_candidate(report, manifest["project_id"])
        except (ValueError, RepoPlanValidationError):
            continue
        if candidate not in result:
            result.append(candidate)
        if len(result) >= MAX_LEADS:
            break
    if store.manifest()[1] != revision:
        raise ValueError("knowledge project changed during candidate construction")
    return result


def portable_leads(task: Any, request: Any) -> list[dict[str, Any]]:
    root = _scope(task, request)
    if not root:
        return []
    store = RepoKnowledgeStore(root)
    epoch = store.read_epoch()
    manifest, revision = store.manifest()
    catalog = store.catalog(verify_sources=False)
    criteria = set(task.contract.acceptance_criteria)
    result = []
    for item in catalog["records"]:
        record = item["record"]
        if record["kind"] != "observation" or not record["id"].startswith(PREFIX):
            continue
        payload = record["payload"]
        try:
            decoded = json.loads(payload["statement"])
            if type(decoded) is not dict or set(decoded) != {"criterion", "observation"}:
                continue
            if decoded["criterion"] not in criteria:
                continue
            expected = build_publication_candidate({
                "share_repository": True, "criterion": decoded["criterion"],
                "title": decoded["observation"],
            }, manifest["project_id"])
            if expected != record:
                continue
        except (TypeError, KeyError, ValueError, RepoPlanValidationError):
            continue
        if store.get("observation", record["id"], verify_sources=False)["revision"] != item["revision"]:
            raise ValueError("execution observation changed during read")
        result.append({"id": record["id"], "criterion": decoded["criterion"],
                       "title": decoded["observation"], "record_revision": item["revision"],
                       "status": "historical_unverified", "catalog_complete": catalog["complete"]})
        if len(result) >= MAX_LEADS:
            break
    if store.manifest()[1] != revision:
        raise ValueError("knowledge project changed during lead retrieval")
    store.require_read_epoch(epoch)
    return result
