from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import _memory_matches_request_scope


def _repository_match(*, scope=AgentScope.REPOSITORY, scope_id="", provenance=None, root="C:/repo"):
    return _memory_matches_request_scope(
        scope=scope,
        scope_id=scope_id,
        provenance=provenance or {"root": root},
        root=root,
        task_id="task-a",
        session_id="session-a",
        clone_id="clone-a",
        worktree_id="worktree-a",
        branch="main",
    )


def test_repository_memory_match_uses_physical_root():
    assert _repository_match()
    assert not _repository_match(provenance={"root": "C:/other"})
    assert not _repository_match(scope="repository")


def test_scoped_memory_match_uses_exact_task_or_session_identity():
    assert _repository_match(scope=AgentScope.TASK, scope_id="task-a")
    assert not _repository_match(scope=AgentScope.TASK, scope_id="task-b")
    assert _repository_match(scope=AgentScope.SESSION, scope_id="session-a")
    assert not _repository_match(scope=AgentScope.SESSION, scope_id="session-b")


def test_retired_provenance_fields_fail_closed_even_when_falsy():
    for field in ("tenant", "tenant_key"):
        try:
            _repository_match(provenance={"root": "C:/repo", field: None})
        except ValueError as exc:
            assert "retired" in str(exc)
        else:
            raise AssertionError(f"{field} provenance was accepted")
