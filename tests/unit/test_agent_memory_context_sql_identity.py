import pytest

from local_ai_hub.agent_memory import _context_scope_sql


def _scope_sql(tenant):
    return _context_scope_sql(
        root="",
        task_id="",
        tenant=tenant,
        session_id="",
        clone_id="",
        worktree_id="",
        branch="",
    )


def test_context_memory_sql_preserves_exact_tenant_identity():
    _, params = _scope_sql(" tenant-a ")
    assert " tenant-a " in params
    assert "tenant-a" not in params


def test_context_memory_sql_rejects_nonstring_tenant_identity():
    with pytest.raises(ValueError, match="tenant"):
        _scope_sql(7)
