import pytest

from local_ai_hub.services import LocalAIServices


class Cache:
    def __init__(self): self.values = {}
    def get_many(self, keys): return {k: self.values[k] for k in keys if k in self.values}
    def set_many(self, values): self.values.update(values)


class Runtime:
    def __init__(self): self.version = 1; self.batches = []
    def request(self, _path, payload):
        self.batches.append(list(payload['input']))
        return {'embeddings': [[float(self.version), 1.0] for _ in payload['input']]}


class Scheduler:
    def submit(self, *_args, execute, **_kwargs): return execute()


@pytest.mark.parametrize('cache_enabled', [True, False])
def test_mutable_ollama_model_name_does_not_reuse_unknown_identity(cache_enabled):
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {'models': {'embedding_backend': 'ollama', 'embedding': 'mutable:tag'}, 'cache': {'embeddings': True}}
    service.embedding_cache = Cache()
    service.embedding_cache_enabled = cache_enabled
    service.runtime = Runtime()
    service.scheduler = Scheduler()

    first = service.embed(['same', 'same', 'other'])
    service.runtime.version = 2
    second = service.embed(['same'])
    assert first['embeddings'] == [[1.0, 1.0], [1.0, 1.0], [1.0, 1.0]]
    assert second['embeddings'] == [[2.0, 1.0]]
    assert service.runtime.batches == [['same', 'other'], ['same']]
    assert service.embedding_cache.values == {}


def test_ollama_short_embedding_response_is_failure():
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {'models': {'embedding_backend': 'ollama', 'embedding': 'mutable:tag'}}
    service.runtime = Runtime()
    service.scheduler = Scheduler()
    service.runtime.request = lambda *_args: {'embeddings': []}
    result = service.embed(['one'])
    assert result['success'] is False
    assert 'embeddings' not in result
