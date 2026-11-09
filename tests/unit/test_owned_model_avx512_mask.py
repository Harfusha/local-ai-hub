import os

import pytest

from local_ai_hub import owned_model


@pytest.mark.parametrize(
    ('platform', 'device', 'avx512_available', 'expected'),
    [
        ('win32', 'cuda', False, '1'),
        ('win32', 'cuda:0', False, '1'),
        ('win32', 'cuda', True, None),
        ('win32', 'cpu', False, None),
        ('linux', 'cuda', False, None),
    ],
)
def test_cuda_worker_environment_masks_only_unsupported_windows_avx512(
    monkeypatch, platform, device, avx512_available, expected
):
    monkeypatch.delenv('CUBLASLT_DISABLE_CPU_INSTRUCTIONS_MASK', raising=False)
    monkeypatch.setattr(owned_model.sys, 'platform', platform)
    monkeypatch.setattr(owned_model, '_windows_avx512_available', lambda: avx512_available)
    env = owned_model._cuda_worker_environment({'device': device})
    assert (env or {}).get('CUBLASLT_DISABLE_CPU_INSTRUCTIONS_MASK') == expected
    assert 'CUBLASLT_DISABLE_CPU_INSTRUCTIONS_MASK' not in os.environ


def test_cuda_worker_environment_preserves_explicit_mask(monkeypatch):
    monkeypatch.setenv('CUBLASLT_DISABLE_CPU_INSTRUCTIONS_MASK', '0')
    monkeypatch.setattr(owned_model.sys, 'platform', 'win32')
    monkeypatch.setattr(owned_model, '_windows_avx512_available', lambda: False)
    env = owned_model._cuda_worker_environment({'device': 'cuda'})
    assert (env or os.environ)['CUBLASLT_DISABLE_CPU_INSTRUCTIONS_MASK'] == '0'


def test_owned_model_passes_compatibility_environment_to_child(monkeypatch):
    captured = {}

    class FakeProcess:
        def __init__(self, argv, *, env=None):
            captured['env'] = env

        def request(self, payload, *, timeout):
            return {'model_name': 'model', 'max_seq_length': 512}

        def close(self):
            pass

    monkeypatch.delenv('CUBLASLT_DISABLE_CPU_INSTRUCTIONS_MASK', raising=False)
    monkeypatch.setattr(owned_model.sys, 'platform', 'win32')
    monkeypatch.setattr(owned_model, '_windows_avx512_available', lambda: False)
    monkeypatch.setattr(owned_model, '_ModelProcess', FakeProcess)
    model = owned_model.OwnedNLPModel('embedding', 'model', {'device': 'cuda'}, max_length=512)
    try:
        assert captured['env']['CUBLASLT_DISABLE_CPU_INSTRUCTIONS_MASK'] == '1'
    finally:
        model.close()
