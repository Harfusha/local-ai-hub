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


def test_service_uses_model_cache_without_reserving_gpu(tmp_path, monkeypatch):
    from local_ai_hub.embeddings import EmbeddingModel

    service = _service()
    service.config['server'] = {'state_dir': str(tmp_path)}
    service.config['models']['embedding_device'] = 'cuda'
    model = EmbeddingModel(service.config)
    model._active_cache_identity = 'sentence-transformers:cuda:same-name'
    model.active_backend = 'sentence-transformers'
    model.active_device = 'cuda'
    model._loaded_model_name = 'same-name'
    model._remember_dimension(model._active_cache_identity, 2, persist=False)
    key = model._embedding_cache_key(model._active_cache_identity, False, 'cached')
    model.cache.set(key, {'identity': model._active_cache_identity, 'dimension': 2, 'vector': [1.0, 2.0]})
    monkeypatch.setattr(model, '_claim_embedding_gpu', lambda: pytest.fail('cached input requested GPU'))
    service.embeddings = model

    result = service.embed(['cached'])
    assert result['success'] is True and result['embeddings'] == [[1.0, 2.0]]
    assert result['cache_hits'] == 1 and result['embedding_space_id'] == model.embedding_space_id()


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


@pytest.mark.parametrize('cache_enabled', [True, False])
def test_ollama_scheduler_unknown_outcome_is_not_cached(cache_enabled):
    service = _service()
    service.config['models']['embedding_backend'] = 'ollama'
    service.embedding_cache_enabled = cache_enabled

    class Scheduler:
        def submit(self, *_args, **_kwargs):
            return {'success': True, 'outcome_unknown': True, 'embeddings': [[1.0, 1.0]]}

    service.scheduler = Scheduler()
    result = service.embed(['input'])
    assert result['outcome_unknown'] is True and result['success'] is False
    assert 'embeddings' not in result
    assert service.embedding_cache.values == {}


def test_ollama_partial_backend_response_is_not_cached():
    service = _service()
    service.config['models']['embedding_backend'] = 'ollama'

    class Runtime:
        def request(self, *_args):
            return {'partial': True, 'embeddings': [[1.0, 1.0]]}

    class Scheduler:
        def submit(self, *_args, execute, **_kwargs):
            return execute()

    service.runtime = Runtime()
    service.scheduler = Scheduler()
    result = service.embed(['input'])
    assert result['partial'] is True and result['success'] is False
    assert 'embeddings' not in result and service.embedding_cache.values == {}
