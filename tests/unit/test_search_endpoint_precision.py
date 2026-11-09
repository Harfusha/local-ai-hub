import pytest

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


def test_natural_language_with_document_path_keeps_existing_semantic_default():
    assert default_search_mode('explain docs/guide.md') == 'hybrid'
