from local_ai_hub.mcp_lifecycle_contracts import (
    async_job_lifecycle_contract,
    semantic_handoff_contract,
    task_delivery_contract,
)
from local_ai_hub.mcp_server import (
    _async_job_lifecycle_contract,
    _semantic_handoff_contract,
    _task_delivery_contract,
)


def test_mcp_server_keeps_lifecycle_contract_compatibility_wrappers():
    assert _async_job_lifecycle_contract() == async_job_lifecycle_contract()
    assert _semantic_handoff_contract(False) == semantic_handoff_contract(False)
    assert _task_delivery_contract() == task_delivery_contract()


def test_contract_helpers_preserve_disabled_and_http_only_modes():
    assert "unavailable" in semantic_handoff_contract(False)
    assert "POST /api/async-jobs" in async_job_lifecycle_contract(
        include_mcp_tool=False
    )
    assert "MCP and HubClient retain" in async_job_lifecycle_contract(
        include_mcp_tool=False
    )


def test_task_delivery_contract_retains_durable_job_idempotency_details():
    contract = task_delivery_contract()

    assert "cold_start_rag_index" in contract
    assert "X-LocalAI-Request-ID" in contract
    assert "job_id" in contract

