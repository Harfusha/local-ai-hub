from types import SimpleNamespace

import pytest

from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryStore


def test_memory_find_rejects_nonstring_tenant_before_store_access():
    store = object.__new__(MemoryStore)
    store.state_store = SimpleNamespace(enabled=False)

    with pytest.raises(ValueError, match="tenant"):
        store.find(tenant=7)

    with pytest.raises(ValueError, match="tenant"):
        store.find_for_context(tenant=7)

    with pytest.raises(ValueError, match="tenant"):
        store.get("record-1", scope=AgentScope.REPOSITORY, tenant=7, repository_id="repo-1")


def test_task_retrieval_scope_rejects_nonstring_tenant():
    store = object.__new__(MemoryStore)

    with pytest.raises(ValueError, match="tenant"):
        with store.task_retrieval_scope("goal", root="C:/repo", tenant=7, task_id="task-1"):
            pass
