import threading
import time
from concurrent.futures import ThreadPoolExecutor

from local_ai_hub.embeddings import EmbeddingModel


def test_loaded_cpu_fallback_does_not_reserve_cuda(tmp_path, monkeypatch):
    class CpuModel:
        prompts = {}
        def encode(self, texts, **kwargs): return [[1.0, 2.0] for _ in texts]

    model = EmbeddingModel({'server': {'state_dir': str(tmp_path)},
                            'models': {'embedding': 'model', 'embedding_backend': 'sentence-transformers', 'embedding_device': 'cuda'},
                            'cache': {'embeddings': False}})
    model._model = CpuModel()
    model.active_backend = 'sentence-transformers'
    model.active_device = 'cpu'
    model._loaded_model_name = 'model'
    monkeypatch.setattr(model, '_claim_embedding_gpu', lambda: False)
    result = model.encode(['uncached'])
    assert result['success'] is True, result
    assert result['embeddings'] == [[1.0, 2.0]] and result['device'] == 'cpu'


def test_cpu_fallback_runs_while_external_gpu_owner_keeps_reservation(tmp_path):
    from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore

    class CpuModel:
        prompts = {}
        def encode(self, texts, **kwargs): return [[1.0, 2.0] for _ in texts]

    model = EmbeddingModel({'server': {'state_dir': str(tmp_path)},
                            'models': {'embedding': 'model', 'embedding_backend': 'sentence-transformers', 'embedding_device': 'cuda'},
                            'cache': {'embeddings': False}})
    model._model, model.active_backend, model.active_device = CpuModel(), 'sentence-transformers', 'cpu'
    store = ExternalGpuReservationStore(tmp_path / 'external-gpu-reservation')
    record = store.reserve('a' * 64, owner='other-work')
    model._gpu_reservation_store = store
    model._gpu_reservation_path = store.path

    result = model.encode(['uncached'])
    assert result['success'] is True and result['embeddings'] == [[1.0, 2.0]]
    assert store.read()['generation'] == record['generation']


def test_cpu_inference_fences_model_release(tmp_path, monkeypatch):
    started, finish = threading.Event(), threading.Event()
    class CpuModel:
        prompts = {}
        def encode(self, texts, **kwargs):
            started.set()
            assert finish.wait(5)
            return [[1.0, 2.0] for _ in texts]

    model = EmbeddingModel({'server': {'state_dir': str(tmp_path)},
                            'models': {'embedding': 'model', 'embedding_backend': 'sentence-transformers', 'embedding_device': 'cuda'},
                            'cache': {'embeddings': False}})
    model._model, model.active_backend, model.active_device = CpuModel(), 'sentence-transformers', 'cpu'
    monkeypatch.setattr(model, '_claim_embedding_gpu', lambda: False)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(model.encode, ['uncached'])
        assert started.wait(5)
        try:
            assert model.release(timeout_seconds=0.01) is False
        finally:
            finish.set()
        assert future.result(timeout=5)['success'] is True


def test_auto_backend_still_requires_gpu_reservation(tmp_path, monkeypatch):
    model = EmbeddingModel({'server': {'state_dir': str(tmp_path)},
                            'models': {'embedding': 'model', 'embedding_backend': 'auto', 'embedding_device': 'cuda'},
                            'cache': {'embeddings': False}})
    model._model, model.active_backend, model.active_device = object(), 'sentence-transformers', 'cpu'
    monkeypatch.setattr(model, '_claim_embedding_gpu', lambda: False)
    assert model.encode(['uncached'])['error_code'] == 'gpu_reserved'


def test_cpu_preflight_rechecks_device_before_unfenced_inference(tmp_path, monkeypatch):
    observed, resume = threading.Event(), threading.Event()
    class CpuModel:
        prompts = {}
        def encode(self, texts, **kwargs):
            raise AssertionError('must not run after device switched to CUDA')

    model = EmbeddingModel({'server': {'state_dir': str(tmp_path)},
                            'models': {'embedding': 'model', 'embedding_backend': 'sentence-transformers', 'embedding_device': 'cuda'},
                            'cache': {'embeddings': False}})
    model._model, model.active_backend, model.active_device = CpuModel(), 'sentence-transformers', 'cpu'
    original_do = model.flight_group.do
    def held_do(key, fn):
        observed.set()
        assert resume.wait(5)
        return original_do(key, fn)
    monkeypatch.setattr(model.flight_group, 'do', held_do)
    monkeypatch.setattr(model, '_claim_embedding_gpu', lambda: False)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(model.encode, ['uncached'])
        assert observed.wait(5)
        with model._encoder_lock:
            model.active_device = 'cuda'
        resume.set()
        assert future.result(timeout=5)['error_code'] == 'gpu_reserved'


def test_cpu_preflight_sentinel_is_not_shared_with_gpu_flight(tmp_path, monkeypatch):
    observed, resume = threading.Event(), threading.Event()
    model = EmbeddingModel({'server': {'state_dir': str(tmp_path)},
                            'models': {'embedding': 'model', 'embedding_backend': 'sentence-transformers', 'embedding_device': 'cuda'},
                            'cache': {'embeddings': False}})
    model._model, model.active_backend, model.active_device = object(), 'sentence-transformers', 'cpu'
    original_do = model.flight_group.do
    keys = []
    def held_do(key, fn):
        keys.append(key)
        if key.startswith('cpu-fallback:'):
            observed.set()
            assert resume.wait(5)
        return original_do(key, fn)
    monkeypatch.setattr(model.flight_group, 'do', held_do)
    monkeypatch.setattr(model, '_claim_embedding_gpu', lambda: None)
    monkeypatch.setattr(model, '_encode_uncached', lambda *_args, **_kwargs: {'success': True, 'embeddings': [[1.0, 2.0]]})
    with ThreadPoolExecutor(max_workers=2) as pool:
        cpu_preflight = pool.submit(model.encode, ['same'])
        assert observed.wait(5)
        with model._encoder_lock:
            model.active_device = 'cuda'
        gpu_request = pool.submit(model.encode, ['same'])
        try:
            assert gpu_request.result(timeout=5)['success'] is True
        finally:
            resume.set()
        assert cpu_preflight.result(timeout=5)['success'] is True
    assert any(key.startswith('cpu-fallback:') for key in keys)
    assert any(not key.startswith('cpu-fallback:') for key in keys)


def test_duplicate_cpu_requests_share_one_inference(tmp_path, monkeypatch):
    started, finish = threading.Event(), threading.Event()
    calls = []
    class CpuModel:
        prompts = {}
        def encode(self, texts, **kwargs):
            calls.append(list(texts))
            started.set()
            assert finish.wait(5)
            return [[1.0, 2.0] for _ in texts]

    model = EmbeddingModel({'server': {'state_dir': str(tmp_path)},
                            'models': {'embedding': 'model', 'embedding_backend': 'sentence-transformers', 'embedding_device': 'cuda'},
                            'cache': {'embeddings': False}})
    model._model, model.active_backend, model.active_device = CpuModel(), 'sentence-transformers', 'cpu'
    monkeypatch.setattr(model, '_claim_embedding_gpu', lambda: False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(model.encode, ['same'])
        assert started.wait(5)
        second = pool.submit(model.encode, ['same'])
        deadline = time.monotonic() + 5
        try:
            while model.flight_group.coalesced_calls == 0 and time.monotonic() < deadline:
                threading.Event().wait(0.005)
            assert model.flight_group.coalesced_calls == 1
        finally:
            finish.set()
        first_result, second_result = first.result(timeout=5), second.result(timeout=5)
    assert first_result['success'] and second_result['success']
    assert calls == [['same']]
