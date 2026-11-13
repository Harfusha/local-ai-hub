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


def _service_with_rag_candidates(tmp_path, candidates):
    services = _search_service(tmp_path, None)
    services.config["features"] = {"rag": True, "reranker": False}
    services.config["resilience"] = {
        "repository_search_source_validation_timeout_seconds": 1.5,
        "repository_search_source_validation_max_bytes": 8_000_000,
    }

    class Rag:
        def workspace_id(self, _root):
            return "workspace"

        def require_workspace_root(self, *, workspace, root):
            assert workspace == "workspace"
            assert root == str(tmp_path)

        def has_workspace_chunks(self, *, workspace):
            return workspace == "workspace"

        def search(self, *_args, **_kwargs):
            return {"success": True, "results": candidates, "reranked": False, "fallbacks": []}

        def project_context(self, _root):
            return {}

        def _project_path_decision(self, _root, _target, _context, *, phase, size_bytes):
            assert phase == "search"
            return True, "text"

    services.rag = Rag()
    return services


def test_rag_source_validation_stops_at_aggregate_byte_limit(tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("needle", encoding="utf-8")
    second.write_text("needle", encoding="utf-8")
    candidates = [
        {"path": "first.py", "text": "needle", "chunk_no": 0},
        {"path": "second.py", "text": "needle", "chunk_no": 0},
    ]
    services = _service_with_rag_candidates(tmp_path, candidates)
    services.config["resilience"]["repository_search_source_validation_max_bytes"] = 6

    rows, meta = services._repo_rag_search(str(tmp_path), "needle", 2)

    assert [row["path"] for row in rows] == ["first.py"]
    assert meta["source_validation"] == {
        "complete": False,
        "candidates_checked": 1,
        "bytes_read": 6,
        "limit_bytes": 6,
        "limit_seconds": 1.5,
        "reason": "byte_limit",
    }
    assert meta["degraded"] is True
    assert meta["candidate_freshness"] == "partially_verified"
    assert meta["degradation_reason"] == "source_validation_byte_limit"

    response = services.repo_search(str(tmp_path), "needle workflow", search_mode="hybrid")
    assert response["source_validation"]["complete"] is False
    assert response["candidate_freshness"] == "partially_verified"
    assert response["degradation_reason"] == "source_validation_byte_limit"


def test_rag_source_validation_stops_at_deadline(tmp_path, monkeypatch):
    source = tmp_path / "slow.py"
    source.write_text("needle", encoding="utf-8")
    services = _service_with_rag_candidates(
        tmp_path, [{"path": "slow.py", "text": "needle", "chunk_no": 0}]
    )
    clock = iter((0.0, 0.0, 2.0))
    monkeypatch.setattr("local_ai_hub.services.time.perf_counter", lambda: next(clock))

    rows, meta = services._repo_rag_search(str(tmp_path), "needle", 1)

    assert rows == []
    assert meta["source_validation"]["complete"] is False
    assert meta["source_validation"]["candidates_checked"] == 0
    assert meta["source_validation"]["bytes_read"] == 0
    assert meta["source_validation"]["reason"] == "time_limit"
    assert meta["candidate_freshness"] == "partially_verified"
    assert meta["degradation_reason"] == "source_validation_time_limit"


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
