from types import SimpleNamespace

import pytest

from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools


@pytest.mark.parametrize('prefer_git', [False, True])
def test_security_scan_does_not_claim_complete_when_inventory_is_capped(tmp_path, prefer_git):
    import subprocess
    if prefer_git:
        subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True, timeout=10)
    (tmp_path / 'a.py').write_text('safe = 1\n', encoding='utf-8')
    (tmp_path / 'z.py').write_text('import pickle\npickle.loads(payload)\n', encoding='utf-8')
    tools = RepositoryTools({'search': {'max_files': 1, 'prefer_git_files': prefer_git}, 'rag': {}})
    engine = SimpleNamespace(_root=lambda _value: str(tmp_path), repo_tools=tools)
    result = DeterministicEngine.security_audit(engine, str(tmp_path))
    assert result['scan_complete'] is False, result
    assert result['is_clean'] is False, result


@pytest.mark.parametrize('prefer_git', [False, True])
def test_security_scan_does_not_claim_complete_when_inventory_skips_oversized_file(tmp_path, prefer_git):
    import subprocess
    if prefer_git:
        subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True, timeout=10)
    (tmp_path / 'large.py').write_text('x = 1\n' * 30, encoding='utf-8')
    tools = RepositoryTools({'search': {'max_files': 10, 'prefer_git_files': prefer_git}, 'rag': {'max_file_bytes': 32}})
    engine = SimpleNamespace(_root=lambda _value: str(tmp_path), repo_tools=tools)
    result = DeterministicEngine.security_audit(engine, str(tmp_path))
    assert result['scan_complete'] is False, result
    assert result['is_clean'] is False, result
    assert result['inventory_incomplete_examples']['oversized_file'] == ['large.py']


@pytest.mark.parametrize('prefer_git', [False, True])
def test_security_scan_keeps_findings_when_another_file_is_oversized(tmp_path, prefer_git):
    import subprocess
    if prefer_git:
        subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True, timeout=10)
    (tmp_path / 'large.py').write_text('x = 1\n' * 60, encoding='utf-8')
    (tmp_path / 'unsafe.py').write_text('import pickle\npickle.loads(payload)\n', encoding='utf-8')
    tools = RepositoryTools({'search': {'max_files': 10, 'prefer_git_files': prefer_git}, 'rag': {'max_file_bytes': 64}})
    engine = SimpleNamespace(_root=lambda _value: str(tmp_path), repo_tools=tools)
    result = DeterministicEngine.security_audit(engine, str(tmp_path))
    assert result['scan_complete'] is False, result
    assert any(item['path'] == 'unsafe.py' for item in result['findings']), result
    assert 'oversized_file' in result['inventory_incomplete_reasons']


@pytest.mark.parametrize('prefer_git', [False, True])
def test_security_scan_can_prove_exactly_at_file_limit(tmp_path, prefer_git):
    import subprocess
    if prefer_git:
        subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True, timeout=10)
    (tmp_path / 'a.py').write_text('safe = 1\n', encoding='utf-8')
    tools = RepositoryTools({'search': {'max_files': 1, 'prefer_git_files': prefer_git}, 'rag': {}})
    engine = SimpleNamespace(_root=lambda _value: str(tmp_path), repo_tools=tools)
    result = DeterministicEngine.security_audit(engine, str(tmp_path))
    assert result['scan_complete'] is True, result
    assert result['is_clean'] is True, result


def test_security_scan_rechecks_git_inventory_instead_of_reusing_stale_cache(tmp_path):
    import subprocess
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True, timeout=10)
    (tmp_path / 'a.py').write_text('safe = 1\n', encoding='utf-8')
    tools = RepositoryTools({'search': {'max_files': 10, 'prefer_git_files': True, 'git_files_cache_ttl': 60}, 'rag': {}})
    engine = SimpleNamespace(_root=lambda _value: str(tmp_path), repo_tools=tools)
    first = DeterministicEngine.security_audit(engine, str(tmp_path))
    assert first['is_clean'] is True, first
    (tmp_path / 'z.py').write_text('import pickle\npickle.loads(payload)\n', encoding='utf-8')
    second = DeterministicEngine.security_audit(engine, str(tmp_path))
    assert second['is_clean'] is False, second
    assert any(item['path'] == 'z.py' for item in second['findings']), second


def test_concurrent_security_audits_keep_independent_inventory_evidence(tmp_path):
    import subprocess
    from concurrent.futures import ThreadPoolExecutor
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True, timeout=10)
    for i in range(20):
        (tmp_path / f'{i:02}.py').write_text('safe = 1\n', encoding='utf-8')
    tools = RepositoryTools({'search': {'max_files': 30, 'prefer_git_files': True}, 'rag': {}})
    engine = SimpleNamespace(_root=lambda _value: str(tmp_path), repo_tools=tools)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(DeterministicEngine.security_audit, engine, str(tmp_path)) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert all(row['scan_complete'] is True and row['is_clean'] is True and row['scanned_files'] == 20
               for row in results), results


@pytest.mark.parametrize('mutation', ['new_file', 'changed_file'])
@pytest.mark.parametrize('prefer_git', [False, True])
def test_security_scan_cannot_claim_complete_when_workspace_changes_during_audit(tmp_path, monkeypatch, mutation, prefer_git):
    import subprocess
    if prefer_git:
        subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True, timeout=10)
    source = tmp_path / 'a.py'
    source.write_text('safe = 1\n', encoding='utf-8')
    tools = RepositoryTools({'search': {'max_files': 10, 'prefer_git_files': prefer_git}, 'rag': {}})
    original = tools.security_inventory
    calls = []
    def inventory(root, **kwargs):
        result = original(root, **kwargs)
        calls.append(1)
        if len(calls) == 1:
            if mutation == 'new_file':
                (tmp_path / 'z.py').write_text('import pickle\npickle.loads(payload)\n', encoding='utf-8')
            else:
                source.write_text('import pickle\npickle.loads(payload)\n', encoding='utf-8')
        return result
    monkeypatch.setattr(tools, 'security_inventory', inventory)
    engine = SimpleNamespace(_root=lambda _value: str(tmp_path), repo_tools=tools)
    result = DeterministicEngine.security_audit(engine, str(tmp_path))
    assert result['scan_complete'] is False, result
    assert result['is_clean'] is False, result
    assert 'workspace_changed' in result['inventory_incomplete_reasons']


def test_security_scan_preserves_final_inventory_error_examples(tmp_path, monkeypatch):
    (tmp_path / 'safe.py').write_text('safe = 1\n', encoding='utf-8')
    tools = RepositoryTools({'search': {'max_files': 10, 'prefer_git_files': False}, 'rag': {'max_file_bytes': 32}})
    original = tools.security_inventory
    calls = []
    def inventory(root, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            (tmp_path / 'new-large.py').write_text('x = 1\n' * 30, encoding='utf-8')
        return original(root, **kwargs)
    monkeypatch.setattr(tools, 'security_inventory', inventory)
    engine = SimpleNamespace(_root=lambda _value: str(tmp_path), repo_tools=tools)
    result = DeterministicEngine.security_audit(engine, str(tmp_path))
    assert result['scan_complete'] is False and result['is_clean'] is False, result
    assert result['inventory_incomplete_examples']['oversized_file'] == ['new-large.py'], result


def test_security_scan_exposes_directory_enumeration_failure(tmp_path, monkeypatch):
    from local_ai_hub import repo_tools
    def failed_walk(_root, *, followlinks, onerror):
        onerror(PermissionError('unavailable directory'))
        return iter(())
    real_os = repo_tools.os
    class FakeOS:
        walk = staticmethod(failed_walk)
        def __getattr__(self, name): return getattr(real_os, name)
    monkeypatch.setattr(repo_tools, 'os', FakeOS())
    tools = RepositoryTools({'search': {'max_files': 10, 'prefer_git_files': False}, 'rag': {}})
    engine = SimpleNamespace(_root=lambda _value: str(tmp_path), repo_tools=tools)
    result = DeterministicEngine.security_audit(engine, str(tmp_path))
    assert result['scan_complete'] is False, result
    assert result['is_clean'] is False, result
    assert 'inventory_error' in result['inventory_incomplete_reasons']


def test_security_scan_does_not_silently_skip_unavailable_regular_file(tmp_path, monkeypatch):
    source = tmp_path / 'private.py'
    source.write_text('safe = 1\n', encoding='utf-8')
    tools = RepositoryTools({'search': {'max_files': 10, 'prefer_git_files': False}, 'rag': {}})
    original = tools._inventory_path_safe
    monkeypatch.setattr(tools, '_inventory_path_safe', lambda root, path: False if path == source else original(root, path))
    engine = SimpleNamespace(_root=lambda _value: str(tmp_path), repo_tools=tools)
    result = DeterministicEngine.security_audit(engine, str(tmp_path))
    assert result['scan_complete'] is False, result
    assert result['is_clean'] is False, result
    assert 'unavailable_path' in result['inventory_incomplete_reasons']
    assert result['inventory_incomplete_examples']['unavailable_path'] == ['private.py']


@pytest.mark.parametrize('prefer_git', [False, True])
def test_security_scan_bounds_inventory_path_examples(tmp_path, prefer_git):
    import subprocess
    if prefer_git:
        subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True, timeout=10)
    for i in range(8):
        (tmp_path / f'{i}.py').write_text('x = 1\n' * 30, encoding='utf-8')
    tools = RepositoryTools({'search': {'max_files': 10, 'prefer_git_files': prefer_git}, 'rag': {'max_file_bytes': 32}})
    engine = SimpleNamespace(_root=lambda _value: str(tmp_path), repo_tools=tools)
    result = DeterministicEngine.security_audit(engine, str(tmp_path))
    assert len(result['inventory_incomplete_examples']['oversized_file']) <= 3
    assert result['inventory_examples_truncated'] is True


def test_security_inventory_never_exposes_path_outside_root(tmp_path):
    from local_ai_hub.repo_tools import _record_security_inventory_issue
    root = tmp_path / 'root'
    root.mkdir()
    status = {'complete': True, 'reasons': [], 'examples': {}, 'examples_truncated': False}
    _record_security_inventory_issue(status, root, 'inventory_error', tmp_path / 'outside.py')
    _record_security_inventory_issue(status, root, 'inventory_error', root / '..' / 'outside.py')
    assert status['complete'] is False
    assert status['examples'] == {}


def test_security_scan_rejects_git_inventory_without_coverage_evidence(tmp_path, monkeypatch):
    tools = RepositoryTools({'search': {'max_files': 10, 'prefer_git_files': True}, 'rag': {}})
    monkeypatch.setattr(tools, '_git_files', lambda *_args, **_kwargs: [])
    engine = SimpleNamespace(_root=lambda _value: str(tmp_path), repo_tools=tools)
    result = DeterministicEngine.security_audit(engine, str(tmp_path))
    assert result['scan_complete'] is False, result
    assert result['is_clean'] is False, result
    assert 'inventory_coverage_unknown' in result['inventory_incomplete_reasons']


def test_security_inventory_marks_expired_deadline_incomplete(tmp_path):
    import time
    tools = RepositoryTools({'search': {'max_files': 10, 'prefer_git_files': False}, 'rag': {}})
    paths, status = tools.security_inventory(str(tmp_path), deadline=time.monotonic() - 1)
    assert paths == []
    assert status['complete'] is False and status['reasons'] == ['time_limit']


def test_security_git_inventory_bounds_subprocess_to_audit_deadline(tmp_path, monkeypatch):
    import io
    import time
    from local_ai_hub import repo_tools
    (tmp_path / '.git').mkdir()
    intervals = []
    class Timer:
        def __init__(self, interval, _callback):
            intervals.append(interval)
            self.daemon = False
        def start(self): pass
        def cancel(self): pass
    class Process:
        pid = 123
        stdout = io.BytesIO(b'')
        def wait(self, timeout=None): return 0
        def poll(self): return 0
    real_threading = repo_tools.threading
    class FakeThreading:
        def Timer(self, *args): return Timer(*args)
        def __getattr__(self, name): return getattr(real_threading, name)
    monkeypatch.setattr(repo_tools, 'threading', FakeThreading())
    monkeypatch.setattr(repo_tools, 'popen_managed', lambda *_args, **_kwargs: Process())
    tools = RepositoryTools({'search': {'max_files': 10, 'prefer_git_files': True}, 'rag': {}})
    deadline = time.monotonic() + 2
    paths, status = tools.security_inventory(str(tmp_path), deadline=deadline)
    assert paths == [] and status['complete'] is True
    assert len(intervals) == 1 and 0 < intervals[0] <= 2


def test_security_git_inventory_stops_processing_buffer_after_deadline(tmp_path, monkeypatch):
    import io
    from local_ai_hub import repo_tools
    (tmp_path / '.git').mkdir()
    for i in range(5):
        (tmp_path / f'{i}.py').write_text('safe = 1\n', encoding='utf-8')
    class Timer:
        def __init__(self, *_args): self.daemon = False
        def start(self): pass
        def cancel(self): pass
    class Process:
        pid = 123
        stdout = io.BytesIO(b'0.py\0' + b'1.py\0' + b'2.py\0' + b'3.py\0' + b'4.py\0')
        def wait(self, timeout=None): return 0
        def poll(self): return 0
    real_threading = repo_tools.threading
    class FakeThreading:
        def Timer(self, *args): return Timer(*args)
        def __getattr__(self, name): return getattr(real_threading, name)
    monkeypatch.setattr(repo_tools, 'threading', FakeThreading())
    monkeypatch.setattr(repo_tools, 'popen_managed', lambda *_args, **_kwargs: Process())
    checks = []
    monkeypatch.setattr(repo_tools, 'terminate_tree', lambda *_args, **_kwargs: True)
    clock = [0.0]
    real_time = repo_tools.time
    class FakeTime:
        def monotonic(self): return clock[0]
        def __getattr__(self, name): return getattr(real_time, name)
    monkeypatch.setattr(repo_tools, 'time', FakeTime())
    tools = RepositoryTools({'search': {'max_files': 10, 'prefer_git_files': True}, 'rag': {}})
    def slow_check(_root, _path):
        checks.append(1)
        clock[0] = 2.0
        return True
    monkeypatch.setattr(tools, '_inventory_path_safe', slow_check)
    paths, status = tools.security_inventory(str(tmp_path), deadline=1.0)
    assert paths == []
    assert status['complete'] is False and 'time_limit' in status['reasons']
    assert len(checks) == 1


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows junction regression')
@pytest.mark.parametrize('prefer_git', [False, True])
def test_security_inventory_does_not_follow_external_junction(tmp_path, prefer_git):
    import os
    import stat
    import subprocess
    from local_ai_hub.process_utils import hidden_run_kwargs

    root = tmp_path / 'repo'
    outside = tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    (root / 'safe.py').write_text('safe = 1\n', encoding='utf-8')
    (outside / 'unsafe.py').write_text('import pickle\npickle.loads(payload)\n', encoding='utf-8')
    link = root / 'junction'
    env = os.environ.copy()
    env.update(LAH_TEST_JUNCTION=str(link), LAH_TEST_TARGET=str(outside))
    created = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
         'New-Item -ItemType Junction -Path $env:LAH_TEST_JUNCTION -Target $env:LAH_TEST_TARGET -ErrorAction Stop | Out-Null'],
        env=env, capture_output=True, timeout=10, **hidden_run_kwargs(),
    )
    if created.returncode != 0:
        pytest.skip('Windows junction creation unavailable')
    try:
        assert root.resolve().parent == outside.resolve().parent == tmp_path.resolve()
        assert os.lstat(link).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        if prefer_git:
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True, timeout=10, **hidden_run_kwargs())
        tools = RepositoryTools({'search': {'max_files': 10, 'prefer_git_files': prefer_git}, 'rag': {}})
        engine = SimpleNamespace(_root=lambda _value: str(root), repo_tools=tools)
        result = DeterministicEngine.security_audit(engine, str(root))
        assert not result['findings'], result
        assert result['scanned_files'] == 1, result
        assert 'reparse points excluded' in result['coverage_scope']
        assert (outside / 'unsafe.py').is_file()
    finally:
        assert link.parent.resolve() == root.resolve()
        os.rmdir(link)


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows junction regression')
def test_security_inventory_excludes_tracked_path_beneath_junction_without_false_error(tmp_path):
    import os
    import stat
    import subprocess
    from local_ai_hub.process_utils import hidden_run_kwargs

    root = tmp_path / 'repo'
    original = tmp_path / 'original'
    outside = tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    nested = root / 'linked'
    nested.mkdir()
    (nested / 'sentinel.py').write_text('safe = 1\n', encoding='utf-8')
    (outside / 'sentinel.py').write_text('import pickle\npickle.loads(payload)\n', encoding='utf-8')
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True, timeout=10, **hidden_run_kwargs())
    subprocess.run(['git', 'add', '--', 'linked/sentinel.py'], cwd=root, check=True, timeout=10, **hidden_run_kwargs())
    assert nested.resolve().parent == root.resolve() and original.parent.resolve() == tmp_path.resolve()
    nested.rename(original)
    env = os.environ.copy()
    env.update(LAH_TEST_JUNCTION=str(nested), LAH_TEST_TARGET=str(outside))
    created = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
         'New-Item -ItemType Junction -Path $env:LAH_TEST_JUNCTION -Target $env:LAH_TEST_TARGET -ErrorAction Stop | Out-Null'],
        env=env, capture_output=True, timeout=10, **hidden_run_kwargs(),
    )
    if created.returncode != 0:
        pytest.skip('Windows junction creation unavailable')
    try:
        assert os.lstat(nested).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        tools = RepositoryTools({'search': {'max_files': 10, 'prefer_git_files': True}, 'rag': {}})
        engine = SimpleNamespace(_root=lambda _value: str(root), repo_tools=tools)
        result = DeterministicEngine.security_audit(engine, str(root))
        assert result['scan_complete'] is True and result['is_clean'] is True, result
        assert 'unavailable_path' not in result['inventory_incomplete_reasons'], result
        assert result['scanned_files'] == 0 and (outside / 'sentinel.py').is_file()
    finally:
        assert nested.parent.resolve() == root.resolve()
        os.rmdir(nested)
