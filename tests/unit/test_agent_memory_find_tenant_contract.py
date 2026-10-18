"""Retired selectors fail before any memory storage access."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryStore


@pytest.mark.parametrize("call", ["find", "find_for_context", "get", "task_retrieval_scope"])
def test_memory_apis_reject_retired_tenant_keyword_before_storage(call, tmp_path, monkeypatch):
    store = object.__new__(MemoryStore)
    store.state_store = SimpleNamespace(enabled=True, db_path=Path(tmp_path) / "state.sqlite")
    store.state_store.db_path.touch()
    monkeypatch.setattr(
        store, "_init_table", lambda: (_ for _ in ()).throw(AssertionError("storage reached"))
    )
    with pytest.raises(TypeError, match="tenant"):
        if call == "find":
            store.find(tenant=None)
        elif call == "find_for_context":
            store.find_for_context(tenant=False)
        elif call == "get":
            store.get("record-1", scope=AgentScope.REPOSITORY, tenant="")
        else:
            with store.task_retrieval_scope("goal", root=str(tmp_path), task_id="task-1", tenant=7):
                pass
