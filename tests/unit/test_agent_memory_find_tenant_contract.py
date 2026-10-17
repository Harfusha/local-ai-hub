from types import SimpleNamespace

import pytest

from local_ai_hub.agent_memory import MemoryStore


def test_memory_find_rejects_nonstring_tenant_before_store_access():
    store = object.__new__(MemoryStore)
    store.state_store = SimpleNamespace(enabled=False)

    with pytest.raises(ValueError, match="tenant"):
        store.find(tenant=7)
