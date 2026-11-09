import pytest

from local_ai_hub.services import LocalAIServices


class Cache:
    def __init__(self): self.values = {}
    def get_many(self, keys): return {key: self.values[key] for key in keys if key in self.values}
    def set_many(self, values): self.values.update(values)


class Embedder:
    def __init__(self):
        self.space = 'space-a'
        self.calls = 0
        self.uncertain = False
    def embedding_space_id(self): return self.space
    def encode(self, texts, **_kwargs):
        self.calls += 1
        value = 1.0 if self.space == 'space-a' else 2.0
        result = {'success': True, 'embedding_space_id': self.space,
                  'embedding_dimension': 2, 'embeddings': [[value, 1.0] for _ in texts]}
        if self.uncertain: result['outcome_unknown'] = True
        return result


def _service():
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {'models': {'embedding_backend': 'sentence-transformers', 'embedding': 'same-name'}, 'cache': {'embeddings': True}}
    service.embedding_cache = Cache()
    service.embedding_cache_enabled = True
    service.embeddings = Embedder()
    return service


def test_embedding_service_does_not_reuse_vectors_across_embedding_spaces():
    service = _service()
    first = service.embed(['same input'])
    service.embeddings.space = 'space-b'
    second = service.embed(['same input'])
    assert first['embedding_space_id'] == 'space-a'
    assert second['embedding_space_id'] == 'space-b', second
    assert second['embeddings'] == [[2.0, 1.0]] and service.embeddings.calls == 2


@pytest.mark.parametrize('backend', ['sentence-transformers', 'openvino'])
@pytest.mark.parametrize('flag', [
    'outcome_unknown', 'timed_out', 'cancelled', 'preempted',
    'cleanup_unconfirmed', '_lah_partial_response', 'in_progress',
    'output_truncated', 'partial',
])
def test_embedding_service_never_caches_unknown_outcome(backend, flag):
    service = _service()
    service.config['models']['embedding_backend'] = backend
    original_encode = service.embeddings.encode
    def uncertain_encode(*args, **kwargs):
        return {**original_encode(*args, **kwargs), flag: True}
    service.embeddings.encode = uncertain_encode
    result = service.embed(['input'])
    assert result.get(flag) is True and result['success'] is False, result
    assert 'embeddings' not in result
    assert service.embedding_cache.values == {}
