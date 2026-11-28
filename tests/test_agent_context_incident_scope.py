from __future__ import annotations

import hashlib
import json
import subprocess
import uuid

from local_ai_hub.agent_context import ContextCompiler, ContextRequest
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore, ToolOutcome


def test_compiler_limits_incidents_to_root_and_requires_verified_resolution(tmp_path, monkeypatch):
    root_a, root_b = tmp_path / "a", tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    state = AgentStateStore(tmp_path / "state.sqlite3")
    incidents = IncidentStore(state)
    unresolved = incidents.capture(ToolOutcome(
        tool_name="command", error="local failure", exit_code=1, repository_root=str(root_a),
        metadata={"verified_fix": "unverified advice"},
    ))
    verified = incidents.capture(ToolOutcome(
        tool_name="command", error="verified failure", exit_code=1, repository_root=str(root_a),
    ))
    foreign = incidents.capture(ToolOutcome(
        tool_name="command", error="foreign private failure", exit_code=1, repository_root=str(root_b),
    ))
    assert unresolved is not None and verified is not None and foreign is not None
    incidents.resolve(verified.incident_id, verified_fix="validated repair")
    from local_ai_hub.repo_knowledge import RepoKnowledgeStore
    from local_ai_hub.repo_project_incidents import build_project_incident_record

    subprocess.run(["git", "init", str(root_a)], check=True, capture_output=True)
    config = root_a / ".local-ai-hub"
    incident_dir = config / "agent-os" / "incidents"
    incident_dir.mkdir(parents=True)
    (config / "project.json").write_text(json.dumps({
        "schema_version": 1,
        "project_id": str(uuid.uuid5(uuid.NAMESPACE_URL, str(root_a.resolve()))),
        "mode": "shared",
    }), encoding="utf-8")
    store = RepoKnowledgeStore(root_a)
    canonical = (
        build_project_incident_record(store, {
            "incident_id": unresolved.incident_id, "operation_class": "command",
            "error_class": "RuntimeError", "signature_hash": hashlib.sha256(b"unresolved").hexdigest(),
            "resolved": False, "redacted_message": "local failure",
        }),
        build_project_incident_record(store, {
            "incident_id": verified.incident_id, "operation_class": "command",
            "error_class": "RuntimeError", "signature_hash": hashlib.sha256(b"verified").hexdigest(),
            "resolved": True, "redacted_message": "verified failure", "verified_fix": "validated repair",
        }),
    )
    for record in canonical:
        (incident_dir / f"{record['id']}.json").write_text(json.dumps(record), encoding="utf-8")
    compiler = ContextCompiler(state, incident_store=incidents)
    scoped = compiler.compile(ContextRequest(task_id="task", root=str(root_a)))
    elements = {element.element_id: element for element in scoped.elements}
    assert foreign.incident_id not in elements
    assert elements[unresolved.incident_id].source_kind == "incident"
    assert "unverified advice" not in elements[unresolved.incident_id].content
    assert elements[verified.incident_id].source_kind == "incident_fix"
    assert "validated repair" in elements[verified.incident_id].content

    unscoped = compiler.compile(ContextRequest(task_id="task-without-root"))
    assert not any(element.source_kind in {"incident", "incident_fix"} for element in unscoped.elements)
    monkeypatch.chdir(tmp_path)
    relative = compiler.compile(ContextRequest(task_id="task-relative-root", root="a"))
    assert not any(element.source_kind in {"incident", "incident_fix"} for element in relative.elements)
