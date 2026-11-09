import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.owned_model import _load


def _cache_snapshot(cache, revision):
    path = cache / 'hub' / 'models--unit-test--revision-model' / 'snapshots' / revision
    path.mkdir(parents=True)
    (path / 'config.json').write_text('{}', encoding='utf-8')
    (path / 'model.safetensors').write_bytes(b'fixture')
    return path


def _install_backend(monkeypatch, cache):
    monkeypatch.setenv('HF_HOME', str(cache))
    loaded = []
    def constructor(name, **kwargs):
        if name == 'unit-test/revision-model':
            raise OSError('local metadata unavailable')
        loaded.append(Path(name))
        return SimpleNamespace(config=SimpleNamespace(_commit_hash=None))
    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(
        CrossEncoder=constructor, SentenceTransformer=constructor,
    ))
    return loaded


def _spec(revision):
    return {'kind': 'reranker', 'model_name': 'unit-test/revision-model',
            'kwargs': {'revision': revision}, 'max_length': 512, 'allow_downloads': False}


def test_snapshot_fallback_uses_only_exact_configured_revision(tmp_path, monkeypatch):
    _cache_snapshot(tmp_path, '0' * 40)
    expected = _cache_snapshot(tmp_path, 'f' * 40)
    loaded = _install_backend(monkeypatch, tmp_path)
    _load(_spec('f' * 40))
    assert loaded == [expected]


@pytest.mark.parametrize('revision', ['f' * 40, 'main'])
def test_snapshot_fallback_rejects_unproven_revision(tmp_path, monkeypatch, revision):
    _cache_snapshot(tmp_path, '0' * 40)
    loaded = _install_backend(monkeypatch, tmp_path)
    with pytest.raises(OSError, match='local metadata unavailable'):
        _load(_spec(revision))
    assert loaded == []


def test_explicit_revision_failure_does_not_switch_embedding_model(tmp_path, monkeypatch):
    _cache_snapshot(tmp_path, '0' * 40)
    loaded = _install_backend(monkeypatch, tmp_path)
    spec = _spec('f' * 40)
    spec['kind'] = 'embedding'
    with pytest.raises(OSError, match='local metadata unavailable'):
        _load(spec)
    assert loaded == []


def test_unpinned_snapshot_fallback_keeps_existing_behavior(tmp_path, monkeypatch):
    expected = _cache_snapshot(tmp_path, '0' * 40)
    loaded = _install_backend(monkeypatch, tmp_path)
    spec = _spec(None)
    spec['kwargs'] = {}
    _load(spec)
    assert loaded == [expected]
