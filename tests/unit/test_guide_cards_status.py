"""Deferred bundle tests; guide generation must execute no example or HTTP call."""
from types import SimpleNamespace

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import (
    OPERATION_CONTRACTS, operation_guide_cards, validate_operation_arguments,
)


def test_guide_cards_follow_public_contracts_and_example_requirements():
    result = operation_guide_cards()
    assert {card["tool"] for card in result["guide_cards"]} == set(OPERATION_CONTRACTS)
    assert "local_ai_command" not in OPERATION_CONTRACTS
    for card in result["guide_cards"]:
        contract = OPERATION_CONTRACTS[card["tool"]]
        action = card["example"][card["selector"]]
        assert action in contract["actions"]
        assert set(card["required"]).issubset(card["example"])
        assert validate_operation_arguments(card["tool"], action, card["example"]) is None
    assert result["schema_token_reduction_verified"] is False


def test_disabled_tools_do_not_have_guide_examples():
    features = SimpleNamespace(status=True, repo=False, commands=False, tasks=False,
                               rag=False, coord=False, artifacts=False, work_orchestrator=False)
    result = operation_guide_cards(features)
    assert [card["tool"] for card in result["guide_cards"]] == ["local_ai_status"]


@pytest.mark.parametrize("arguments", [{"detail": "guide"}])
def test_retired_mcp_guide_does_not_request_health_or_execute_examples(monkeypatch, arguments):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("guide must not call the Hub or execute examples")

    monkeypatch.setattr(mcp_server.FEATURES, "status", True)
    monkeypatch.setattr(mcp_server, "CLIENT", SimpleNamespace(get=forbidden, post=forbidden))
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_kwargs: None)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    result = mcp_server.local_ai_status(**arguments, max_response_tokens=3200)
    assert result["success"] is False
    assert result["status_code"] == 400
