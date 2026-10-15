"""Deferred MCP refactor argument acceptance cases."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.operation_contracts import OPERATION_CONTRACTS


def _use_active_mode(monkeypatch):
    from local_ai_hub.operational_mode import OperationalModeSnapshot

    snapshot = OperationalModeSnapshot("active", 1, None)
    monkeypatch.setattr(mcp_server, "load_operational_mode", lambda _state_dir: snapshot)


@pytest.mark.parametrize('arguments,expected', [
    ({'old_symbol': 'before', 'new_symbol': 'after'}, ('before', 'after')),
])
def test_canonical_refactor_arguments_reach_http(tmp_path, monkeypatch, arguments, expected):
    _use_active_mode(monkeypatch)
    calls = []
    def post(path, payload, **kwargs):
        calls.append((path, payload))
        return {'success': True, 'dry_run': True}
    monkeypatch.setattr(mcp_server, 'CLIENT', SimpleNamespace(post=post))
    monkeypatch.setattr(mcp_server.FEATURES, 'repo', True)
    monkeypatch.setattr(mcp_server, '_record_tool_accounting', lambda **_: None)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda _event: None)
    wire = asyncio.run(mcp_server.mcp.call_tool('local_ai_repo', {
        'action': 'ast_refactor', 'root': str(tmp_path), 'path': 'module.py', **arguments,
    }))
    contents = wire[0] if isinstance(wire, tuple) else wire
    result = json.loads(next(item.text for item in contents if item.type == 'text'))
    assert result['success'], result
    assert calls[0][0] == '/api/code/ast_rename'
    assert (calls[0][1]['old_symbol'], calls[0][1]['new_symbol']) == expected
    assert calls[0][1]['apply'] is False


def test_explicit_empty_refactor_name_is_not_replaced_by_legacy_alias(tmp_path, monkeypatch):
    _use_active_mode(monkeypatch)
    monkeypatch.setattr(mcp_server.FEATURES, 'repo', True)
    calls = []
    monkeypatch.setattr(mcp_server, 'CLIENT', SimpleNamespace(post=lambda *a, **kw: calls.append(a)))
    result = mcp_server.local_ai_repo(
        action='ast_refactor', root=str(tmp_path), path='module.py',
        old_symbol='', new_symbol='after',
    )
    assert result['success'] is False
    assert calls == []
    properties = OPERATION_CONTRACTS['local_ai_repo']['properties']
    assert {'old_symbol', 'new_symbol'} <= properties.keys()
