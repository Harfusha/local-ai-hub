from __future__ import annotations

import asyncio
import json

import pytest

from local_ai_hub import browser_bridge, mcp_server
from local_ai_hub.operation_contracts import validate_operation_output


@pytest.mark.parametrize('status', [400, 403, 408, 409, 503])
def test_browser_failure_uses_canonical_transport_status(status):
    result = browser_bridge._result_error('browser_unavailable', 'capture unavailable', status=status)

    assert validate_operation_output('local_ai_task', 'browser', result) is None
    assert result['status_code'] == status
    assert 'status' not in result
    assert result['success'] is False
    assert result['terminal'] is True
    assert result['retryable'] is False


def test_browser_mcp_preserves_real_producer_failure_without_contract_bypass(monkeypatch):
    monkeypatch.setattr(mcp_server.FEATURES, 'tasks', True)
    monkeypatch.setattr(mcp_server.FEATURES, 'vision', True)
    monkeypatch.setattr(mcp_server.FEATURES, 'has_any_model', lambda: True)
    monkeypatch.setattr(mcp_server, 'load_operational_mode',
                        lambda *_args, **_kwargs: mcp_server.OperationalModeSnapshot('active', 0, None))
    monkeypatch.setattr(mcp_server.CLIENT, 'post', lambda *_args, **_kwargs:
                        browser_bridge._result_error('browser_unavailable', 'capture unavailable', status=503))
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mcp_server.CONTEXT_LEDGER, 'record', lambda **_kwargs: None)

    response = asyncio.run(mcp_server.mcp.call_tool('local_ai_task', {
        'action': 'browser', 'url': 'http://127.0.0.1:11435/dashboard', 'max_response_tokens': 1600,
    }))
    contents, structured = response if isinstance(response, tuple) else (response, None)
    result = json.loads(contents[0].text)
    assert structured is not None

    assert result['success'] is False
    assert result['status_code'] == 503, result
    assert result['error_code'] == 'browser_unavailable'
    assert result['terminal'] is True
    assert result['retryable'] is False
    assert result.get('failure_kind') != 'output_contract_violation'


def test_canonical_browser_failure_still_rejects_malformed_status_code():
    result = browser_bridge._result_error('browser_unavailable', 'capture unavailable', status=503)
    result.pop('status', None)
    result['status_code'] = '503'
    assert validate_operation_output('local_ai_task', 'browser', result) is not None
