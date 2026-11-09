from local_ai_hub.repo_state import RepoStateTracker
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices


def _search_service(tmp_path, _preprocessor):
    config = {
        'server': {'state_dir': str(tmp_path / 'state')},
        'rag': {'extensions': ['.py']},
        'search': {'prefer_git_files': False, 'use_git_grep_fallback': False,
                   'use_ripgrep_if_available': False, 'max_files': 50, 'max_hits': 20},
    }
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = config
    services.learner = None
    services.deterministic = None
    services.code_index = None
    services.preprocessor = None
    services.repo_tools = RepositoryTools(config)
    services.evidence_store = None
    services._repo_cache_state = lambda _root: {'fingerprint': 'rev-1', 'kind': 'test'}
    services._repo_cached = lambda _operation, _root, _params, compute, **_kwargs: compute()
    return services


def test_search_cache_must_notice_edit_before_fingerprint_ttl(tmp_path):
    class Cache:
        def __init__(self):
            self.values = {}

        def get_or_compute(self, key, compute):
            if key in self.values:
                return self.values[key], True, False
            result = compute()
            self.values[key] = result
            return result, False, False

    source = tmp_path / 'example.py'
    source.write_text('needle_old\n', encoding='utf-8')
    services = _search_service(tmp_path, None)
    del services._repo_cached
    services._touch_project = lambda _root: None
    services.repo_state = RepoStateTracker({'workspace_cache': {'fingerprint_ttl_seconds': 60}})
    services.repo_flight = Cache()
    first = services.repo_search(str(tmp_path), 'needle_old', search_mode='lexical')
    warm = services.repo_search(str(tmp_path), 'needle_old', search_mode='lexical')
    assert warm['cache_hit'] is False, warm
    source.write_text('needle_new\n', encoding='utf-8')
    changed = services.repo_search(str(tmp_path), 'needle_old', search_mode='lexical')
    assert not changed['results'], changed


def test_search_cache_must_notice_edit_to_ignored_file_if_filesystem_search_reads_it(tmp_path):
    import subprocess
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True, timeout=10)
    (tmp_path / '.gitignore').write_text('ignored.py\n', encoding='utf-8')
    source = tmp_path / 'ignored.py'
    source.write_text('needle_old\n', encoding='utf-8')
    class Cache:
        def __init__(self): self.values = {}
        def get_or_compute(self, key, compute):
            if key in self.values: return self.values[key], True, False
            result = compute()
            self.values[key] = result
            return result, False, False
    services = _search_service(tmp_path, None)
    del services._repo_cached
    services._touch_project = lambda _root: None
    services.repo_state = RepoStateTracker({'workspace_cache': {'fingerprint_ttl_seconds': 60}})
    services.repo_flight = Cache()
    first = services.repo_search(str(tmp_path), 'needle_old', search_mode='lexical')
    assert first['results'], first
    warm = services.repo_search(str(tmp_path), 'needle_old', search_mode='lexical')
    assert warm['cache_hit'] is False, warm
    source.write_text('needle_new\n', encoding='utf-8')
    changed = services.repo_search(str(tmp_path), 'needle_old', search_mode='lexical')
    assert not changed['results'], changed
