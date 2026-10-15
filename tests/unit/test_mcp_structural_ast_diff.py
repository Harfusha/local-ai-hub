"""Deferred source-pair transport cases for the existing semantic_diff action."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from local_ai_hub import mcp_server


def test_source_pair_reaches_shared_http_and_preserves_artifact(tmp_path, monkeypatch):
    calls = []
    def post(path, payload, **kwargs):
        calls.append((path, payload))
        return {'success': True, 'artifact_id': 'ast-diff-result', 'changes_total': 1,
                'changes_returned': 1, 'summary': {'renamed': 1}, 'behavior_equivalence_proven': False}
    monkeypatch.setattr(mcp_server, 'CLIENT', SimpleNamespace(post=post))
    monkeypatch.setattr(mcp_server.FEATURES, 'repo', True)
    monkeypatch.setattr(mcp_server.FEATURES, 'agent_os', True)
    monkeypatch.setattr(mcp_server, '_record_tool_accounting', lambda **_: None)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda _event: None)
    wire = asyncio.run(mcp_server.mcp.call_tool('local_ai_repo', {
        'action': 'semantic_diff', 'root': str(tmp_path),
        'old_code': 'def before(): pass', 'new_code': 'def after(): pass',
    }))
    contents = wire[0] if isinstance(wire, tuple) else wire
    result = json.loads(next(item.text for item in contents if item.type == 'text'))
    assert result['success'], result
    assert result['artifact_id'] == 'ast-diff-result'
    assert result['behavior_equivalence_proven'] is False
    assert calls == [('/api/repo/call_graph_diff', {
        'root': str(tmp_path), 'old_code': 'def before(): pass', 'new_code': 'def after(): pass',
    })]


def test_incomplete_source_pair_is_rejected_before_dispatch(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server.FEATURES, 'repo', True)
    monkeypatch.setattr(mcp_server.FEATURES, 'agent_os', True)
    monkeypatch.setattr(mcp_server, 'CLIENT', SimpleNamespace(post=lambda *a, **kw: calls.append(a)))
    result = mcp_server.local_ai_repo(action='semantic_diff', root=str(tmp_path), old_code='value = 1')
    assert result['success'] is False
    assert calls == []
