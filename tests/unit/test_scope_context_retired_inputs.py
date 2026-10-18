import pytest

from local_ai_hub.agent_identity import ScopeContext


@pytest.mark.parametrize("field", ["tenant", "tenant_id", "tenant_key", "tenant_scope", "tenant_identity", "tenant_partition", "principal", "schema_version"])
@pytest.mark.parametrize("value", [None, "", False, "old-owner"])
def test_scope_context_rejects_retired_and_unknown_fields_by_presence(field, value):
    with pytest.raises(ValueError, match="unsupported fields"):
        ScopeContext.from_dict({"repository_id": "project-a", field: value})


def test_scope_context_keeps_independent_canonical_identities():
    values = {
        "repository_id": "repository-a", "clone_id": "clone-b",
        "worktree_id": "worktree-c", "branch": "feature-d",
        "task_id": "task-e", "session_id": "session-f",
    }
    assert ScopeContext.from_dict(values).to_dict() == values
    assert ScopeContext.from_dict({}).is_empty()
