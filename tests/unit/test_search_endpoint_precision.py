import pytest
from pathlib import Path
from types import SimpleNamespace

from local_ai_hub import project_config
from local_ai_hub.search_modes import default_search_mode, lexical_precision_query
from local_ai_hub.services import LocalAIServices


@pytest.mark.parametrize(('query', 'anchor'), [
    ('POST /api/embed endpoint', '/api/embed'),
    ('GET /v1/chat/completions', '/v1/chat/completions'),
    ('Find /api/jobs/{id}', '/api/jobs/{id}'),
    ('Find `/api/health`.', '/api/health'),
])
def test_explicit_api_endpoint_uses_literal_lexical_search(query, anchor):
    assert default_search_mode(query) == 'lexical'
    assert lexical_precision_query(query) == anchor


def test_repo_search_skips_semantic_backend_for_explicit_endpoint(monkeypatch):
    service = LocalAIServices.__new__(LocalAIServices)
    calls = []
    def lexical(_root, query, *_args, **_kwargs):
        calls.append(query)
        return {'success': True, 'results': [{'path': 'client.py', 'text': 'POST /api/embed'}],
                'truncated': False, 'has_more': False, 'read_errors': 0}
    monkeypatch.setattr(service, '_repo_search_lexical', lexical)
    def unexpected(*_args, **_kwargs):
        raise AssertionError('exact endpoint must not call RAG')
    monkeypatch.setattr(service, '_repo_rag_search', unexpected)
    result = service.repo_search('C:/repo', 'POST /api/embed endpoint', limit=5)
    assert result['success'] is True and result['search_mode'] == 'lexical'
    assert calls == ['/api/embed']


def test_repo_search_reuses_project_context_root_without_resolving_again(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    root.mkdir()
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {}
    service.learner = None
    service.repo_state = None
    service.deterministic = None
    service.preprocessor = None
    service.repo_tools = SimpleNamespace(
        search=lambda *_args, **_kwargs: {
            'success': True,
            'results': [],
            'total_matches': 0,
            'has_more': False,
            'truncated': False,
        },
        ignore_dirs=set(),
    )

    canonical_root = Path(str(root))
    context = SimpleNamespace(
        root=canonical_root,
        resolution=SimpleNamespace(error_codes=()),
        config_digest='config',
        settings=SimpleNamespace(
            force_include_paths=(),
            path_overrides={},
            entry_points=(),
        ),
        path_hints=lambda **_kwargs: (),
        prioritize_paths=lambda paths, **_kwargs: SimpleNamespace(
            paths=paths,
            hint_used=False,
            fallback_used=False,
        ),
    )
    monkeypatch.setattr(project_config, 'resolve_project_context', lambda *_args, **_kwargs: context)
    monkeypatch.setattr(service, '_repo_cache_state', lambda _root: {})

    original_resolve = Path.resolve
    resolved_root_calls = 0

    def count_root_resolves(path, *args, **kwargs):
        nonlocal resolved_root_calls
        if path == root:
            resolved_root_calls += 1
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'resolve', count_root_resolves)

    result = service._repo_search_lexical(str(root), 'button', limit=5, exact_count=False)

    assert result['success'] is True, result
    assert resolved_root_calls == 1


def test_natural_language_with_document_path_keeps_existing_semantic_default():
    assert default_search_mode('explain docs/guide.md') == 'hybrid'
