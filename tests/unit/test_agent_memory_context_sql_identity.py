import pytest

from local_ai_hub.agent_memory import _context_scope_sql


def _scope_sql(*, root="C:/repo", task_id="task-1", session_id="chat-1"):
    return _context_scope_sql(
        root=root,
        task_id=task_id,
        session_id=session_id,
        clone_id="",
        worktree_id="",
        branch="",
        coordination_id="repo-id",
    )


def test_context_memory_sql_partitions_by_repository_task_and_session():
    sql, params = _scope_sql()
    assert "scope = ?" in sql
    assert "scope_id = ?" in sql
    assert "repository_id" in sql
    assert "repo-id" in params
    assert "task-1" in params
    assert "chat-1" in params


def test_context_memory_sql_rejects_noncanonical_real_scope_identity():
    with pytest.raises(ValueError, match="canonical strings"):
        _scope_sql(session_id=" chat-1 ")
