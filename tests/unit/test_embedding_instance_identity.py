from types import SimpleNamespace

from local_ai_hub.embeddings import EmbeddingModel


class FakeModel:
    prompts = {}
    def __init__(self, value, revision=None):
        self.value = value
        self.config = SimpleNamespace(_commit_hash=revision)
        self.calls = 0
    def encode(self, texts, **_kwargs):
        self.calls += 1
        return [[self.value, 1.0] for _ in texts]


def model_for(root, value, revision=None):
    model = EmbeddingModel({'server': {'state_dir': str(root)},
                            'models': {'embedding': 'unit-model', 'embedding_backend': 'sentence-transformers', 'embedding_device': 'cpu'},
                            'cache': {'embeddings': True}})
    model._model = FakeModel(value, revision)
    model.active_backend, model.active_device = 'sentence-transformers', 'cpu'
    model._loaded_model_name = 'unit-model'
    model._record_model_provenance('sentence-transformers:cpu:unit-model', model=model._model)
    return model


def test_unresolved_revision_cache_is_private_to_one_loaded_model(tmp_path):
    first = model_for(tmp_path, 1.0)
    first_result = first.encode(['same'])
    assert first.encode(['same'])['cache_hits'] == 1
    second = model_for(tmp_path, 2.0)
    second_result = second.encode(['same'])
    assert second_result['embeddings'] == [[2.0, 1.0]]
    assert second_result['cache_hits'] == 0 and second._model.calls == 1
    assert first_result['embedding_space_id'] != second_result['embedding_space_id']
    assert second_result['model_revision'] is None


def test_verified_immutable_revision_shares_persistent_cache(tmp_path):
    first = model_for(tmp_path, 1.0, 'a' * 40)
    first_result = first.encode(['same'])
    second = model_for(tmp_path, 2.0, 'a' * 40)
    second_result = second.encode(['same'])
    assert second_result['embeddings'] == [[1.0, 1.0]]
    assert second_result['cache_hits'] == 1 and second._model.calls == 0
    assert first_result['embedding_space_id'] == second_result['embedding_space_id']


def test_unresolved_revision_changes_identity_after_model_reload(tmp_path, monkeypatch):
    model = model_for(tmp_path, 1.0)
    first = model.encode(['same'])
    monkeypatch.setattr('local_ai_hub.embeddings.release_model', lambda *_args, **_kwargs: None)
    assert model.release() is True
    model._model = FakeModel(2.0)
    model.active_backend, model.active_device = 'sentence-transformers', 'cpu'
    model._record_model_provenance('sentence-transformers:cpu:unit-model', model=model._model)
    second = model.encode(['same'])
    assert second['embeddings'] == [[2.0, 1.0]] and second['cache_hits'] == 0
    assert first['embedding_space_id'] != second['embedding_space_id']


def test_unresolved_models_do_not_share_dimension_metadata(tmp_path):
    first = model_for(tmp_path, 1.0)
    assert first.encode(['same'])['embedding_dimension'] == 2
    second = model_for(tmp_path, 2.0)
    second._model.encode = lambda texts, **_kwargs: [[2.0, 1.0, 1.0] for _ in texts]
    result = second.encode(['same'])
    assert result['success'] is True and result['embedding_dimension'] == 3
    assert second.encode(['same'])['cache_hits'] == 1
    assert first.encode(['same'])['embedding_dimension'] == 2


def test_cache_only_does_not_return_vector_if_model_reloads_during_read(tmp_path, monkeypatch):
    model = model_for(tmp_path, 1.0)
    model.device = 'cuda'
    model.active_device = 'cuda'
    identity = 'sentence-transformers:cuda:unit-model'
    model._active_cache_identity = identity
    model._record_model_provenance(identity, model=model._model)
    model._remember_dimension(identity, 2, persist=False)
    key = model._embedding_cache_key(identity, False, 'same')
    model.cache.set(key, {'identity': identity, 'dimension': 2, 'vector': [1.0, 1.0]})
    original = model.cache.get_many
    def reload_during_read(keys):
        cached = original(keys)
        model._model = FakeModel(2.0)
        model._record_model_provenance(identity, model=model._model)
        return cached
    monkeypatch.setattr(model.cache, 'get_many', reload_during_read)
    monkeypatch.setattr(model, '_claim_embedding_gpu', lambda: False)
    result = model.encode(['same'])
    assert result['success'] is False and result['error_code'] == 'gpu_reserved'
    assert 'embeddings' not in result


def test_mixed_cache_and_inference_rejects_model_reload(tmp_path, monkeypatch):
    model = model_for(tmp_path, 1.0)
    assert model.encode(['cached'])['success'] is True
    original = model._encode_st_batch
    def reload_then_encode(texts, **kwargs):
        model._model = FakeModel(2.0)
        model._record_model_provenance('sentence-transformers:cpu:unit-model', model=model._model)
        return original(texts, **kwargs)
    monkeypatch.setattr(model, '_encode_st_batch', reload_then_encode)
    result = model.encode(['cached', 'new'])
    assert result['success'] is False and result['retryable'] is True
    assert 'embeddings' not in result


def test_cache_publication_does_not_label_old_vector_as_new_model(tmp_path, monkeypatch):
    model = model_for(tmp_path, 1.0)
    original = model.cache.set_many
    def reload_before_write(values):
        model._model = FakeModel(2.0)
        model._record_model_provenance('sentence-transformers:cpu:unit-model', model=model._model)
        return original(values)
    monkeypatch.setattr(model.cache, 'set_many', reload_before_write)
    result = model.encode(['new'])
    assert result['success'] is False and result['retryable'] is True
    assert 'embeddings' not in result
    monkeypatch.setattr(model.cache, 'set_many', original)
    retried = model.encode(['new'])
    assert retried['success'] is True and retried['cache_hits'] == 0
    assert retried['embeddings'] == [[2.0, 1.0]]


def test_reload_during_inference_does_not_publish_old_vectors(tmp_path):
    model = model_for(tmp_path, 1.0)
    def reload_while_encoding(texts, **_kwargs):
        model._model = FakeModel(2.0)
        model._record_model_provenance('sentence-transformers:cpu:unit-model', model=model._model)
        return [[1.0, 1.0] for _ in texts]
    model._model.encode = reload_while_encoding
    result = model.encode(['new'])
    assert result['success'] is False and result['error_code'] == 'embedding_model_changed'
    assert 'embeddings' not in result


def test_configured_digest_without_runtime_proof_does_not_enable_cross_instance_reuse(tmp_path):
    first = model_for(tmp_path, 1.0)
    first.config['models']['embedding_digest'] = 'a' * 64
    first_result = first.encode(['same'])
    second = model_for(tmp_path, 2.0)
    second.config['models']['embedding_digest'] = 'a' * 64
    second_result = second.encode(['same'])
    assert second_result['embeddings'] == [[2.0, 1.0]]
    assert first_result['embedding_space_id'] != second_result['embedding_space_id']


def test_space_id_does_not_mix_generation_during_resolution(tmp_path, monkeypatch):
    model = model_for(tmp_path, 1.0)
    model._active_cache_identity = 'sentence-transformers:cpu:unit-model'
    original = model._embedding_cache_key
    calls = []
    def reload_after_key(*args, **kwargs):
        result = original(*args, **kwargs)
        if not calls:
            model._model = FakeModel(2.0)
            model._record_model_provenance(model._active_cache_identity, model=model._model)
        calls.append(result)
        return result
    monkeypatch.setattr(model, '_embedding_cache_key', reload_after_key)
    current = model.embedding_space_id()
    assert len(calls) == 2 and calls[0] != calls[1]
    assert current == calls[1]


def test_rag_reports_partial_rebuild_for_new_unresolved_model_instance(tmp_path):
    from local_ai_hub.rag import RAGStore

    root = tmp_path / 'project'
    root.mkdir()
    (root / 'one.py').write_text('def example():\n    return 1\n', encoding='utf-8')
    (root / 'two.py').write_text('def other():\n    return 2\n', encoding='utf-8')
    class Services:
        space_id = None
        def __init__(self, model): self.embeddings = model
        def embed(self, texts, **kwargs):
            return self.embeddings.encode(texts, query=kwargs.get('query', False))
    service = Services(model_for(tmp_path / 'embed', 1.0))
    store = RAGStore({'server': {'state_dir': str(tmp_path / 'rag-state')},
                      'models': {}, 'cpu_retrieval': {}, 'workspace_cache': {},
                      'rag': {'extensions': ['.py'], 'ignore_dirs': [], 'chunk_chars': 4096, 'chunk_overlap_chars': 0},
                      'resilience': {'singleflight_wait_timeout_seconds': 2}}, service, object())
    first = store.index_paths_step(str(root), workspace='test', paths=['one.py', 'two.py'])
    assert first['success'] is True, first
    service.embeddings = model_for(tmp_path / 'embed', 2.0)
    service.embeddings._active_cache_identity = 'sentence-transformers:cpu:unit-model'
    second = store.index_paths_step(str(root), workspace='test', paths=['one.py'])
    assert second['success'] is True and second['reused_chunks'] == 0, second
    search = store.search('unmatched query', workspace='test', use_reranker=False)
    assert search['reindex_required'] is True and search['degraded'] is True, search
    assert search['fallback'] == 'embedding_space_rebuild_pending'
    final = store.index_step(str(root), workspace='test', max_files=1)
    assert final['success'] is True and final['done'] is True, final
