"""Explicit publication of bounded change plan metadata into the shared artifact store."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024


def publish_change_plan(result: dict[str, Any], store: Any) -> dict[str, Any]:
    if result.get("success") is not True:
        return result
    if store is None:
        return {"success": False, "error": "Artifact store unavailable", "artifact_status": "unavailable"}
    # Exclude task context from globally addressable derived artifacts. Task
    # associations remain available from the authorized live plan interface.
    safe = {k: v for k, v in result.items() if k not in {"clusters", "task_context"}}
    safe["clusters"] = [
        {k: v for k, v in group.items() if k not in {"task_candidates", "task_candidates_omitted"}}
        for group in result.get("clusters", [])
    ]
    safe["commit_ready"] = False
    safe["verification_status"] = "unknown"
    safe["artifact_historical_observation"] = True
    size = len(json.dumps(safe, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    if size > _MAX_ARTIFACT_BYTES:
        return {"success": False, "error": "Change plan metadata exceeds artifact budget; narrow the scope",
                "artifact_status": "too_large", "commit_ready": False}
    try:
        artifact_id = store.put_json(safe, kind="git_change_plan")
    except (ValueError, OSError, sqlite3.Error):
        return {"success": False, "error": "Change plan artifact could not be stored", "artifact_status": "unavailable",
                "commit_ready": False}
    return {
        "success": True, "artifact_id": artifact_id, "artifact_kind": "git_change_plan",
        "artifact_status": "stored", "artifact_bytes": size,
        "observed_change_set_id": result.get("observed_change_set_id"),
        "total_files": result.get("total_files"), "cluster_count": result.get("cluster_count"),
        "git_visible_observation_complete": result.get("git_visible_observation_complete", False),
        "verification_status": "unknown", "commit_ready": False,
        "summary": "Historical metadata artifact; re-observe before any mutation.",
    }
