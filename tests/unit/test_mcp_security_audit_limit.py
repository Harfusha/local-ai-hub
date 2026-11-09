from jsonschema import Draft202012Validator
import pytest

from local_ai_hub.features import FeatureSet
from local_ai_hub.operation_contracts import operation_argument_hint, operation_tool_input_schema
from local_ai_hub.search_pagination import MAX_PAGE_SIZE
from local_ai_hub import mcp_server


def test_security_audit_limit_is_exposed_and_validated_by_schema():
    schema = operation_tool_input_schema('local_ai_repo', FeatureSet({'hardware': {'profile': 'high'}}))
    assert Draft202012Validator(schema).is_valid({'action': 'security_audit', 'limit': 3})
    assert 'limit' in operation_argument_hint('local_ai_repo', 'security_audit')['allowed_arguments']
    registered = mcp_server._ALL_REGISTERED_TOOLS['local_ai_repo'].parameters
    assert Draft202012Validator(registered).is_valid({'action': 'security_audit', 'limit': 3})


@pytest.mark.parametrize('value', [0, -1, True, MAX_PAGE_SIZE + 1, 1.5, '3'])
def test_security_audit_rejects_invalid_limit_before_http(tmp_path, monkeypatch, value):
    calls = []
    monkeypatch.setattr(mcp_server.CLIENT, 'post', lambda *args, **kwargs: calls.append(args))
    result = mcp_server._local_ai_repo_impl(action='security_audit', root=str(tmp_path), limit=value)
    assert result['success'] is False, result
    assert not calls


def test_security_audit_forwards_explicit_limit_and_preserves_default(tmp_path, monkeypatch):
    calls = []
    def post(path, payload, **kwargs):
        calls.append((path, payload))
        return {'success': True, 'scan_complete': False, 'is_clean': False, 'findings': [],
                'inventory_incomplete_reasons': ['oversized_file'],
                'inventory_incomplete_examples': {'oversized_file': ['large.py']},
                'inventory_examples_truncated': False}
    monkeypatch.setattr(mcp_server.CLIENT, 'post', post)
    first = mcp_server._local_ai_repo_impl(action='security_audit', root=str(tmp_path), limit=3)
    second = mcp_server._local_ai_repo_impl(action='security_audit', root=str(tmp_path))
    assert first['success'] and second['success']
    assert first['scan_complete'] is False and first['is_clean'] is False
    assert first['inventory_incomplete_examples'] == {'oversized_file': ['large.py']}
    assert calls[0][1]['limit'] == 3
    assert 'limit' not in calls[1][1]


def test_security_audit_accepts_largest_supported_limit(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server.CLIENT, 'post', lambda path, payload, **kwargs: (
        calls.append(payload) or {'success': True, 'scan_complete': False, 'is_clean': False, 'findings': []}
    ))
    result = mcp_server._local_ai_repo_impl(action='security_audit', root=str(tmp_path), limit=MAX_PAGE_SIZE)
    assert result['success'] is True and calls[0]['limit'] == MAX_PAGE_SIZE
