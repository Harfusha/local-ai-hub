import pytest

from local_ai_hub.embeddings import EmbeddingModel


def _model(tmp_path):
    model = EmbeddingModel({
        'server': {'state_dir': str(tmp_path / 'state')},
        'models': {'embedding': 'test-model', 'embedding_backend': 'sentence-transformers', 'embedding_device': 'cuda'},
        'cache': {'embeddings': True},
    })
    model._active_cache_identity = 'sentence-transformers:cuda:test-model'
    model.active_backend = 'sentence-transformers'
    model.active_device = 'cuda'
    model._loaded_model_name = 'test-model'
    model._remember_dimension(model._active_cache_identity, 2, persist=False)
    return model


def _seed(model, text, vector=(1.0, 2.0)):
    identity = model._active_cache_identity
    key = model._embedding_cache_key(identity, False, text)
    model.cache.set(key, {'identity': identity, 'dimension': len(vector), 'vector': list(vector)})


def test_all_cache_hits_do_not_acquire_gpu(tmp_path, monkeypatch):
    model = _model(tmp_path)
    _seed(model, 'cached')
    calls = []
    monkeypatch.setattr(model, '_claim_embedding_gpu', lambda: calls.append(True) or False)
    result = model.encode(['cached', 'cached'])
    assert result['success'] is True, result
    assert result['cache_hits'] == 2 and result['computed'] == 0
    assert result['embeddings'] == [[1.0, 2.0], [1.0, 2.0]]
    assert not calls
    second = model.encode(['cached'])
    assert second['success'] is True and second['cache_hits'] == 1 and not calls


@pytest.mark.parametrize('case', ['partial', 'invalid', 'unknown_identity', 'unknown_dimension', 'changed_identity'])
def test_cache_fast_path_never_infers_without_gpu_or_mixes_identity(tmp_path, monkeypatch, case):
    model = _model(tmp_path)
    if case == 'unknown_dimension':
        model._dimensions_by_identity.clear()
    _seed(model, 'cached', vector=(0.0, 0.0) if case == 'invalid' else (1.0, 2.0))
    if case == 'unknown_identity':
        model._active_cache_identity = None
    if case == 'changed_identity':
        original = model.cache.get_many
        def change_identity(keys):
            result = original(keys)
            model._active_cache_identity = 'sentence-transformers:cuda:other'
            return result
        monkeypatch.setattr(model.cache, 'get_many', change_identity)
    calls = []
    monkeypatch.setattr(model, '_claim_embedding_gpu', lambda: calls.append(True) or False)
    texts = ['cached', 'missing'] if case == 'partial' else ['cached']
    result = model.encode(texts)
    assert result['success'] is False and result['error_code'] == 'gpu_reserved', result
    assert calls == [True]
    assert 'embeddings' not in result


def test_partial_cache_still_fences_gpu_and_counts_hits_once(tmp_path, monkeypatch):
    model = _model(tmp_path)
    _seed(model, 'cached')
    calls = []
    monkeypatch.setattr(model, '_gpu_reservation_store', None)
    monkeypatch.setattr(model, '_claim_embedding_gpu', lambda: calls.append('claim') or ('generation', 'owner'))
    monkeypatch.setattr(model, '_release_embedding_gpu', lambda _reservation: calls.append('release'))
    monkeypatch.setattr(model, '_encode_st_batch', lambda texts, **_kwargs: ([[3.0, 4.0] for _ in texts], 'sentence-transformers'))
    result = model.encode(['cached', 'missing'])
    assert result['success'] is True, result
    assert result['embeddings'] == [[1.0, 2.0], [3.0, 4.0]]
    assert result['cache_hits'] == 1 and result['computed'] == 1
    assert model._memory_hits == 1 and calls == ['claim', 'release']
