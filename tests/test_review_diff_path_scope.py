from types import SimpleNamespace
import asyncio
import hashlib
import subprocess
import threading
import mcp.types as mcp_types
import pytest

from local_ai_hub import mcp_server
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.services import LocalAIServices
from local_ai_hub.repo_tools import RepositoryTools


def test_review_diff_mcp_forwards_explicit_path(monkeypatch, tmp_path):
    calls = []
    client = mcp_server.HubClient(auto_start=False)
    monkeypatch.setattr(client, 'post', lambda endpoint, payload, **kw: calls.append((endpoint, payload)) or {'success': True, 'text': 'ok'})
    monkeypatch.setattr(mcp_server, 'CLIENT', client)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda event: None)
    result = mcp_server.local_ai_repo(action='review_diff', root=str(tmp_path), path='src/example.py')
    assert result['success'] is True
    assert calls[0][1]['path'] == 'src/example.py'


def test_review_diff_service_passes_path_to_diff_collector():
    calls = []
    def repo_diff(*args, **kwargs):
        calls.append((args, kwargs))
        return {'success': True, 'diff': '', 'changed_files': [], 'untracked_inventory_complete': True}
    service = SimpleNamespace(repo_diff=repo_diff, config={})
    result = LocalAIServices.review_diff(service, {'root':'C:/fixture', 'path':'src/example.py'})
    assert result['success'] is True
    assert calls[0][1]['path'] == 'src/example.py'


def test_review_diff_missing_inventory_cannot_claim_complete():
    service = SimpleNamespace(repo_diff=lambda *a, **kw: {'success': True, 'diff': '', 'changed_files': []}, config={})
    result = LocalAIServices.review_diff(service, {'root': 'C:/fixture'})
    assert result['success'] is False
    assert result['review_scope_complete'] is False


def test_ast_review_cancelled_during_diff_collection_does_not_succeed():
    cancel = threading.Event()
    def collect(*args, **kwargs):
        cancel.set()
        return {'success': True, 'diff': '--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n',
                'changed_files': ['a.py'], 'untracked_inventory_complete': True}
    service = SimpleNamespace(config={}, repo_diff=collect, deterministic=object.__new__(DeterministicEngine))
    result = LocalAIServices.review_diff(service, {'root': 'C:/fixture', 'mode': 'ast'}, cancel_event=cancel)
    assert result['success'] is False
    assert result['cancelled'] is True


def test_repo_diff_filters_tracked_files_and_cache_key(tmp_path):
    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True, timeout=10)
    git('init')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.invalid')
    for name in ('a.py', 'b.py'):
        (tmp_path / name).write_text('before\n', encoding='utf-8')
    git('add', 'a.py', 'b.py')
    git('commit', '-m', 'base')
    for name in ('a.py', 'b.py'):
        (tmp_path / name).write_text('after\n', encoding='utf-8')
    (tmp_path / 'new_test.py').write_text('assert False\n', encoding='utf-8')
    keys = []
    def cached(kind, root, key, load):
        keys.append(key)
        return load()
    service = SimpleNamespace(_repo_cached=cached, repo_tools=RepositoryTools({}))
    a = LocalAIServices.repo_diff(service, str(tmp_path), path='a.py')
    b = LocalAIServices.repo_diff(service, str(tmp_path), path='b.py')
    assert a['success'] and b['success']
    assert 'a.py' in a['diff'] and 'b.py' not in a['diff']
    assert 'b.py' in b['diff'] and 'a.py' not in b['diff']
    assert keys[0] != keys[1]
    untracked = LocalAIServices.repo_diff(service, str(tmp_path), path='new_test.py')
    assert untracked['untracked_files_excluded'] == ['new_test.py']
    assert untracked['untracked_inventory_complete'] is True


def test_review_does_not_claim_no_diff_for_untracked_file():
    service = SimpleNamespace(config={}, repo_diff=lambda *args, **kwargs: {
        'success':True, 'diff':'', 'changed_files':[], 'untracked_files_excluded':['new_test.py'], 'untracked_inventory_complete':True,
    })
    result = LocalAIServices.review_diff(service, {'root':'C:/fixture', 'path':'new_test.py'})
    assert result['success'] is False
    assert result['untracked_files_excluded'] == ['new_test.py']
    assert result['review_scope_complete'] is False


def test_review_explicit_small_untracked_file_as_added_text(tmp_path):
    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True, timeout=10)
    git('init')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.invalid')
    (tmp_path / 'tracked.py').write_text('x = 1\n', encoding='utf-8')
    git('add', 'tracked.py')
    git('commit', '-m', 'seed')
    (tmp_path / 'new_test.py').write_text('assert False\n', encoding='utf-8')
    repo = RepositoryTools({})
    service = SimpleNamespace(config={}, deterministic=object.__new__(DeterministicEngine),
                              repo_diff=lambda root, base, staged, max_tokens, path=None: repo.git_diff(root, base, staged, max_tokens, path=path))
    result = LocalAIServices.review_diff(service, {'root': str(tmp_path), 'path': 'new_test.py', 'mode': 'ast'})
    assert result['success'] is True
    assert result['changed_files'] == ['new_test.py']
    assert result['diff_facts']['additions'] == 1
    assert result['review_scope_complete'] is True
    assert result['review_source_sha256'] == hashlib.sha256((tmp_path / 'new_test.py').read_bytes()).hexdigest()
    (tmp_path / 'new_test.py').write_text('++ header-like content\n', encoding='utf-8')
    header_like = LocalAIServices.review_diff(service, {'root': str(tmp_path), 'path': 'new_test.py', 'mode': 'ast'})
    assert header_like['diff_facts']['additions'] == 1
    (tmp_path / 'new file.py').write_text('spaced = True\n', encoding='utf-8')
    spaced = LocalAIServices.review_diff(service, {'root': str(tmp_path), 'path': 'new file.py', 'mode': 'ast'})
    assert spaced['success'] is True
    assert spaced['changed_files'] == ['new file.py']
    assert spaced['review_scope_complete'] is True
    (tmp_path / 'new_test.py').write_bytes(b'line\n' * 201)
    paged = LocalAIServices.review_diff(service, {'root': str(tmp_path), 'path': 'new_test.py', 'mode': 'ast'})
    assert paged['success'] is True
    assert paged['diff_facts']['additions'] == 201
    assert paged['review_source_sha256'] == hashlib.sha256(b'line\n' * 201).hexdigest()
    for content in (b'line\n' * 3201, b'bad\x00binary', b'bare\rcarriage', b'x' * 12001):
        (tmp_path / 'new_test.py').write_bytes(content)
        rejected = LocalAIServices.review_diff(service, {'root': str(tmp_path), 'path': 'new_test.py', 'mode': 'ast'})
        assert rejected['success'] is False
        assert rejected['review_scope_complete'] is False
    (tmp_path / 'new_test.py').write_text('x' * 2000, encoding='utf-8')
    rejected = LocalAIServices.review_diff(service, {'root': str(tmp_path), 'path': 'new_test.py', 'mode': 'ast', 'diff_tokens': 64})
    assert rejected['success'] is False
    assert rejected['review_scope_complete'] is False


def test_untracked_review_rejects_source_change_between_pages(tmp_path, monkeypatch):
    from local_ai_hub import source_slice
    path = tmp_path / 'new.py'
    path.write_bytes(b'line\n' * 201)
    original = source_slice.read_source_slice
    count = 0
    def read(*args, **kwargs):
        nonlocal count
        result = original(*args, **kwargs)
        count += 1
        if count == 2 and result.get('success'):
            result = {**result, 'file_sha256': '0' * 64}
        return result
    monkeypatch.setattr(source_slice, 'read_source_slice', read)
    service = SimpleNamespace(config={}, repo_diff=lambda *args, **kwargs: {
        'success': True, 'diff': '', 'changed_files': [], 'untracked_files_excluded': ['new.py'],
        'untracked_inventory_complete': True,
    })
    result = LocalAIServices.review_diff(service, {'root': str(tmp_path), 'path': 'new.py', 'mode': 'ast'})
    assert count == 2
    assert result['success'] is False
    assert result['review_scope_complete'] is False


def test_review_marks_tracked_diff_incomplete_when_untracked_files_are_excluded():
    class Facts:
        def diff_facts(self, text):
            return {'additions':1, 'deletions':0, 'hunks':1}
    service = SimpleNamespace(config={}, deterministic=Facts(), repo_diff=lambda *args, **kwargs: {
        'success':True, 'diff':'+change', 'changed_files':['tracked.py'], 'untracked_files_excluded':['new_test.py'],
        'untracked_inventory_complete':True, 'truncated':False,
    })
    result = LocalAIServices.review_diff(service, {'root':'C:/fixture', 'mode':'ast'})
    assert result['success'] is True
    assert result['review_scope_complete'] is False
    assert result['untracked_files_excluded'] == ['new_test.py']


def test_mcp_reports_untracked_scope_omission(monkeypatch, tmp_path):
    service = SimpleNamespace(config={}, repo_diff=lambda *args, **kwargs: {
        'success':True, 'diff':'', 'changed_files':[], 'untracked_files_excluded':['new_test.py'], 'untracked_inventory_complete':True,
    })
    client = mcp_server.HubClient(auto_start=False)
    monkeypatch.setattr(client, 'post', lambda endpoint, payload, **kw: LocalAIServices.review_diff(service, payload))
    monkeypatch.setattr(mcp_server, 'CLIENT', client)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda event: None)
    result = mcp_server.local_ai_repo(action='review_diff', root=str(tmp_path), path='new_test.py', max_response_tokens=800)
    assert result['success'] is False
    assert result['untracked_files_excluded'] == ['new_test.py']
    assert result['review_scope_complete'] is False


def test_mcp_failure_preserves_incomplete_scope_at_small_budget(monkeypatch, tmp_path):
    client = mcp_server.HubClient(auto_start=False)
    result = {'success': False, 'error': 'No tracked diff to review; untracked files are excluded or their inventory is incomplete.',
              'request_id': 'req_f6d82576cec5', 'review_scope_complete': False, 'untracked_inventory_complete': True, 'untracked_files_excluded': ['new_test.py']}
    monkeypatch.setattr(client, 'post', lambda endpoint, payload, **kw: result)
    monkeypatch.setattr(mcp_server, 'CLIENT', client)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda event: None)
    output = mcp_server.local_ai_repo(action='review_diff', root=str(tmp_path), path='new_test.py', max_response_tokens=256)
    assert output['success'] is False
    assert output.get('review_scope_complete') is False


@pytest.mark.parametrize('budget', [128, 256])
def test_mcp_wire_failure_preserves_incomplete_scope_at_small_budget(monkeypatch, tmp_path, budget):
    client = mcp_server.HubClient(auto_start=False)
    result = {'success': False, 'error': 'No tracked diff to review; untracked files are excluded or their inventory is incomplete.',
              'request_id': 'req_f6d82576cec5', 'review_scope_complete': False, 'untracked_inventory_complete': True, 'untracked_files_excluded': ['new_test.py']}
    monkeypatch.setattr(client, 'post', lambda endpoint, payload, **kw: result)
    monkeypatch.setattr(mcp_server, 'CLIENT', client)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda event: None)
    captured = []
    original_compact = mcp_server._compact
    def capture(*args, **kwargs):
        value = original_compact(*args, **kwargs)
        captured.append(value)
        return value
    monkeypatch.setattr(mcp_server, '_compact', capture)
    request = mcp_types.CallToolRequest(method='tools/call', params=mcp_types.CallToolRequestParams(
        name='local_ai_repo', arguments={'action': 'review_diff', 'root': str(tmp_path), 'path': 'new_test.py', 'max_response_tokens': budget}))
    response = asyncio.run(mcp_server.mcp._mcp_server.request_handlers[mcp_types.CallToolRequest](request)).root
    assert captured[0].get('review_scope_complete') is False, captured
    assert response.structuredContent['success'] is False
    assert response.structuredContent.get('review_scope_complete') is False


def test_supplied_diff_reports_files_in_ast_review():
    service = SimpleNamespace(deterministic=object.__new__(DeterministicEngine))
    diff = 'diff --git a/src/example.py b/src/example.py\n--- a/src/example.py\n+++ b/src/example.py\n@@ -1,0 +1 @@\n+new\n'
    result = LocalAIServices.review_diff(service, {'diff': diff, 'mode': 'ast'})
    assert result['success'] is True
    assert result['changed_files'] == ['src/example.py']
    assert result['summary'].startswith('AST Diff Summary: 1 files')
    assert result['review_scope_complete'] is False


def test_diff_facts_treats_header_like_hunk_lines_as_content():
    diff = ('--- a/one.py\n+++ b/one.py\n@@ -1 +1 @@\n--- a/not_a_header\n+++ b/not_a_header\n'
            '--- a/two.py\n+++ b/two.py\n@@ -0,0 +1 @@\n+++ added content\n')
    facts = object.__new__(DeterministicEngine).diff_facts(diff)
    assert facts['files'] == ['one.py', 'two.py']
    assert facts['additions'] == 2
    assert facts['deletions'] == 1


@pytest.mark.parametrize('separator', ['\u2028', '\u2029', '\x85', '\v', '\f'])
def test_diff_facts_does_not_treat_unicode_separator_as_diff_newline(separator):
    content = separator.join(['real', '+++ b/fake.py', '@@ -0,0 +1 @@', '+fabricated'])
    diff = '--- /dev/null\n+++ b/real.py\n@@ -0,0 +1 @@\n+' + content + '\n'
    facts = object.__new__(DeterministicEngine).diff_facts(diff)
    assert facts['files'] == ['real.py']
    assert facts['additions'] == 1


def test_review_diff_mcp_preserves_unverified_citation_status(monkeypatch, tmp_path):
    client = mcp_server.HubClient(auto_start=False)
    result = {'success':True, 'text':'unstructured finding', 'advisory_only':True,
              'review_consistency':{'usable':False, 'reason':'structured_review_unavailable', 'semantic_truth_verified':False},
              'quality_warning':'advisory review requires verification'}
    monkeypatch.setattr(client, 'post', lambda endpoint, payload, **kw: result)
    monkeypatch.setattr(mcp_server, 'CLIENT', client)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda event: None)
    output = mcp_server.local_ai_repo(action='review_diff', root=str(tmp_path), diff='--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n', max_response_tokens=800)
    assert output['review_consistency']['usable'] is False
    assert output['review_consistency']['semantic_truth_verified'] is False


def test_review_diff_small_budget_never_silently_promotes_unverified_result(monkeypatch, tmp_path):
    client = mcp_server.HubClient(auto_start=False)
    result = {'success':True, 'text':'x' * 2000, 'advisory_only':True,
              'review_consistency':{'usable':False, 'reason':'invalid_citation', 'semantic_truth_verified':False},
              'quality_warning':'advisory review requires verification'}
    monkeypatch.setattr(client, 'post', lambda endpoint, payload, **kw: result)
    monkeypatch.setattr(mcp_server, 'CLIENT', client)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda event: None)
    output = mcp_server.local_ai_repo(action='review_diff', root=str(tmp_path), diff='--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n', max_response_tokens=128)
    assert output.get('success') is False or output.get('review_consistency', {}).get('usable') is False


def test_review_diff_small_budget_preserves_incomplete_scope(monkeypatch, tmp_path):
    client = mcp_server.HubClient(auto_start=False)
    result = {'success':True, 'text':'x' * 2000, 'review_scope_complete':False,
              'untracked_files_excluded':['new_test.py'], 'untracked_inventory_complete':True}
    monkeypatch.setattr(client, 'post', lambda endpoint, payload, **kw: result)
    monkeypatch.setattr(mcp_server, 'CLIENT', client)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, 'record', lambda event: None)
    output = mcp_server.local_ai_repo(action='review_diff', root=str(tmp_path), path='a.py', max_response_tokens=128)
    assert output.get('success') is False or output.get('review_scope_complete') is False
