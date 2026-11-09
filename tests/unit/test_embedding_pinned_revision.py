import sys
from types import SimpleNamespace

import local_ai_hub.embeddings as embeddings


def test_cpu_model_fallback_does_not_discard_explicit_revision(tmp_path, monkeypatch):
    calls = []
    def load(name, **kwargs):
        calls.append((name, kwargs))
        if name == 'unit-test/pinned-model':
            raise OSError('pinned revision unavailable')
        return SimpleNamespace(config=SimpleNamespace(_commit_hash=None))
    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=load))
    monkeypatch.setattr(embeddings, 'load_model', lambda _owner, *, uses_cuda, factory: factory())
    model = embeddings.EmbeddingModel({
        'server': {'state_dir': str(tmp_path)},
        'models': {'embedding': 'unit-test/pinned-model', 'embedding_backend': 'sentence-transformers',
                   'embedding_device': 'cpu', 'embedding_revision': 'f' * 40},
    })
    assert model._load_candidate(0) is False
    assert [name for name, _ in calls] == ['unit-test/pinned-model']
    assert model._model is None
