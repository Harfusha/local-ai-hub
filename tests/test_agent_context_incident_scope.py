from __future__ import annotations

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
