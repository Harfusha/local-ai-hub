from types import SimpleNamespace
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from local_ai_hub.scheduler import AffinityScheduler


def _set_embedding_reservation_store(model, reservation_path):
    from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore

    model._gpu_reservation_path = reservation_path
    model._gpu_reservation_store = ExternalGpuReservationStore(reservation_path)


def test_owned_external_reservation_expires_in_memory_after_files_disappear(tmp_path, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    scheduler = AffinityScheduler(
        SimpleNamespace(loaded_model_details=lambda: []),
        {"server": {"state_dir": str(tmp_path)}},
    )
    try:
        token = scheduler.reserve_external_gpu()
        assert token
        reservation_path = tmp_path / "external-gpu-reservation"
        metadata_path = tmp_path / "external-gpu-reservation.lease.json"
        reservation_path.unlink()
        metadata_path.unlink()

        assert scheduler._external_gpu_reserved()
        now[0] = 901.0
        assert not scheduler._external_gpu_reserved()
        assert scheduler.reserve_external_gpu()
    finally:
        scheduler.close()


def test_cuda_embedding_encode_excludes_external_session_and_retains_unknown(tmp_path):
    from local_ai_hub.embeddings import EmbeddingModel

    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []),
                                  {"server": {"state_dir": str(tmp_path)}})
    model = EmbeddingModel.__new__(EmbeddingModel)
    _set_embedding_reservation_store(model, tmp_path / "external-gpu-reservation")
    model._execution_local = SimpleNamespace()
    model.backend = "sentence-transformers"
    model.device = "cuda:0"
    model._model = None
    model._encode_request_key = lambda *_args: "key"
    called = []
    outcome = {"success": True, "embeddings": [[1.0]]}
    def compute(*_args, **_kwargs):
        called.append(True)
        assert scheduler.reserve_external_gpu() is None
        return outcome
    model._encode_uncached = compute
    model.flight_group = SimpleNamespace(do=lambda _key, fn: (fn(), False))
    try:
        assert model.encode(["text"])["success"] is True
        token = scheduler.reserve_external_gpu()
        assert token
        assert model.encode(["text"])["success"] is False
        assert len(called) == 1
        assert scheduler.release_external_gpu(token)
        outcome = {"success": False, "error": "unknown inference outcome"}
        assert model.encode(["text"])["success"] is False
        assert (tmp_path / "external-gpu-reservation").exists()
        assert scheduler.reserve_external_gpu() is None
    finally:
        scheduler.close()


def test_cuda_auto_embedding_reuses_fence_and_retains_uncertain_ollama(tmp_path, monkeypatch):
    from local_ai_hub.embeddings import EmbeddingModel

    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []),
                                  {"server": {"state_dir": str(tmp_path)}})
    model = EmbeddingModel.__new__(EmbeddingModel)
    _set_embedding_reservation_store(model, tmp_path / "external-gpu-reservation")
    model._execution_local = SimpleNamespace()
    model._ollama_model_name = "embedding-model"
    model.ollama_url = "http://127.0.0.1:11434"
    model.backend = "auto"
    model.device = "cuda:0"
    model._model = None
    model._encode_request_key = lambda *_args: "key"
    model.flight_group = SimpleNamespace(do=lambda _key, fn: (fn(), False))
    model._encode_uncached = lambda *_args, **_kwargs: {
        "success": True, "embeddings": model._encode_ollama(["text"]) or [[0.0]]}
    class Response:
        def __enter__(self):
            assert scheduler.reserve_external_gpu() is None
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return b'{"embeddings": [[1.0]]}'
    try:
        monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
        assert model.encode(["text"])["embeddings"] == [[1.0]]
        assert not model._gpu_reservation_path.exists()
        def timeout(*_args, **_kwargs):
            raise TimeoutError("unknown backend outcome")
        monkeypatch.setattr("urllib.request.urlopen", timeout)
        assert model.encode(["text"])["embeddings"] == [[0.0]]
        assert model._gpu_reservation_path.exists()
        assert scheduler.reserve_external_gpu() is None
    finally:
        scheduler.close()


def test_ollama_embedding_fence_excludes_separate_scheduler_process(tmp_path, monkeypatch):
    from local_ai_hub.embeddings import EmbeddingModel

    script = r'''
from types import SimpleNamespace
import sys
from local_ai_hub.scheduler import AffinityScheduler
s = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server": {"state_dir": sys.argv[1]}})
try:
    token = s.reserve_external_gpu()
    print("acquired" if token else "blocked", flush=True)
    if token:
        assert s.release_external_gpu(token)
finally:
    s.close()
'''
    def probe():
        result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True,
                                text=True, timeout=15, check=True,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.stdout.strip()

    model = EmbeddingModel.__new__(EmbeddingModel)
    _set_embedding_reservation_store(model, tmp_path / "external-gpu-reservation")
    model._execution_local = SimpleNamespace()
    model._ollama_model_name = "embedding-model"
    model.ollama_url = "http://127.0.0.1:11434"
    class Response:
        def __enter__(self):
            assert probe() == "blocked"
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return b'{"embeddings": [[1.0, 2.0]]}'
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    assert model._encode_ollama(["text"]) == [[1.0, 2.0]]
    assert probe() == "acquired"


def test_ollama_embedding_process_exit_preserves_gpu_fence(tmp_path):
    script = r'''
from pathlib import Path
from types import SimpleNamespace
import sys, urllib.request
from local_ai_hub.embeddings import EmbeddingModel
from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore
m = EmbeddingModel.__new__(EmbeddingModel)
m._gpu_reservation_path = Path(sys.argv[1]) / "external-gpu-reservation"
m._gpu_reservation_store = ExternalGpuReservationStore(m._gpu_reservation_path)
m._execution_local = SimpleNamespace()
m._ollama_model_name = "embedding-model"
m.ollama_url = "http://127.0.0.1:11434"
def block(*args, **kwargs):
    print("request-started", flush=True)
    sys.stdin.readline()
    raise TimeoutError("unknown outcome")
urllib.request.urlopen = block
m._encode_ollama(["text"])
'''
    child = subprocess.Popen([sys.executable, "-c", script, str(tmp_path)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = queue.Queue()
    reader = threading.Thread(target=lambda: lines.put(child.stdout.readline()), daemon=True)
    reader.start()
    try:
        assert lines.get(timeout=15).strip() == "request-started"
        child.terminate()
        child.communicate(timeout=10)
        scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []),
                                      {"server": {"state_dir": str(tmp_path)}})
        try:
            assert scheduler.reserve_external_gpu() is None
            assert (tmp_path / "external-gpu-reservation").is_file()
        finally:
            scheduler.close()
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)


def test_ollama_embeddings_exclude_external_session_and_keep_unknown_fence(tmp_path, monkeypatch):
    from local_ai_hub.embeddings import EmbeddingModel

    config = {"server": {"state_dir": str(tmp_path)}}
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), config)
    model = EmbeddingModel.__new__(EmbeddingModel)
    _set_embedding_reservation_store(model, tmp_path / "external-gpu-reservation")
    model._execution_local = SimpleNamespace()
    model._ollama_model_name = "embedding-model"
    model.ollama_url = "http://127.0.0.1:11434"
    class Response:
        def __enter__(self):
            assert scheduler.reserve_external_gpu() is None
            return self
        def __exit__(self, *_args):
            return False
        def read(self):
            return b'{"embeddings": [[1.0, 2.0]]}'
    try:
        monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
        assert model._encode_ollama(["text"]) == [[1.0, 2.0]]
        token = scheduler.reserve_external_gpu()
        assert token
        assert model._encode_ollama(["text"]) is None
        assert model._execution_local.ollama_gpu_fenced is True
        assert scheduler.release_external_gpu(token)
        model._execution_local.ollama_gpu_fenced = False
        def timeout(*_args, **_kwargs):
            raise TimeoutError("unknown backend outcome")
        monkeypatch.setattr("urllib.request.urlopen", timeout)
        assert model._encode_ollama(["text"]) is None
        assert model._execution_local.ollama_gpu_fenced is True
        assert model._gpu_reservation_path.exists()
        assert scheduler.reserve_external_gpu() is None
    finally:
        scheduler.close()


def test_fenced_auto_embedding_fallback_never_starts_cuda():
    from local_ai_hub.embeddings import EmbeddingModel

    model = EmbeddingModel.__new__(EmbeddingModel)
    model.backend = "auto"
    model.device = "cuda:0"
    model._execution_local = SimpleNamespace(ollama_gpu_fenced=True)
    model._model = object()
    model.active_backend = "sentence-transformers"
    model.active_device = "cuda:0"
    model._loaded_model_name = "test"
    model._model_provenance = lambda _identity: pytest.fail("CUDA model must not be touched")
    assert model._encode_st_batch_locked(["text"], query=False, priority=3)[0] is None
    attempts = []
    model._model = None
    model.active_backend = None
    model._ensure_st_model = lambda **kwargs: attempts.append(kwargs) or False
    assert model._encode_st_batch_locked(["text"], query=False, priority=3)[0] is None
    assert attempts == [{"ollama_fallback": True}]


def test_scheduler_started_during_reservation_resumes_after_owner_releases(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [], loaded_model_inventory=lambda **_: {
        "complete": True, "backend_available": True, "models": [], "errors": {}})
    owner = AffinityScheduler(runtime, config)
    observer = None
    try:
        token = owner.reserve_external_gpu()
        assert token
        observer = AffinityScheduler(runtime, config)
        assert not observer.acquire_background_gpu(0)
        assert owner.release_external_gpu(token)
        new_token = observer.reserve_external_gpu()
        assert new_token and observer.release_external_gpu(new_token)
        assert observer.acquire_background_gpu(0)
        observer.release_background_gpu()
    finally:
        if observer:
            observer.close()
        owner.close()


def test_owner_does_not_forget_its_missing_reservation(tmp_path):
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server": {"state_dir": str(tmp_path)}})
    try:
        token = scheduler.reserve_external_gpu()
        assert token
        scheduler._external_gpu_path.unlink()
        assert scheduler.foreground_busy()
        assert scheduler.reserve_external_gpu() is None
        assert not scheduler.release_external_gpu(token)
    finally:
        scheduler.close()


def test_cancel_before_model_preparation_does_not_quarantine_gpu(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    calls = []
    runtime = SimpleNamespace(loaded_model_details=lambda: [], prepare_model=lambda *_a, **_kw: calls.append(True))
    scheduler = AffinityScheduler(runtime, config)
    other = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), config)
    scheduler._has_active_preparation_waiter = lambda _target: False
    try:
        with pytest.raises(TimeoutError):
            scheduler.submit("model", source="test", execute=lambda: calls.append(True), wait_timeout=0.2)
        with scheduler._cond:
            assert scheduler._cond.wait_for(lambda: not scheduler._gpu_prepare_in_progress, timeout=2)
            assert not scheduler._internal_gpu_uncertain
            assert scheduler._release_internal_gpu()
        assert calls == []
        token = other.reserve_external_gpu()
        assert token and other.release_external_gpu(token)
    finally:
        scheduler.close()
        other.close()


def test_cancel_after_model_preparation_begins_retains_fence(tmp_path):
    class PreparationCancelled(Exception):
        preparation_cancelled = True
    config = {"server": {"state_dir": str(tmp_path)}}
    def prepare(*_args, **_kwargs):
        raise PreparationCancelled("backend outcome unknown")
    runtime = SimpleNamespace(loaded_model_details=lambda: [], prepare_model=prepare)
    scheduler = AffinityScheduler(runtime, config)
    other = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), config)
    try:
        with pytest.raises(TimeoutError):
            scheduler.submit("model", source="test", execute=lambda: {"success": True}, wait_timeout=0.2)
        with scheduler._cond:
            assert scheduler._internal_gpu_uncertain
            assert not scheduler._release_internal_gpu()
        assert other.reserve_external_gpu() is None
    finally:
        scheduler.close()
        other.close()


def test_confirmed_length_completion_allows_gpu_fence_release(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [], prepare_model=lambda *_a, **_kw: [])
    scheduler = AffinityScheduler(runtime, config)
    other = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), config)
    try:
        result = scheduler.submit("model", source="test", execute=lambda: {
            "success": False, "output_truncated": True, "stop_reason": "length",
            "error_code": "model_output_truncated", "terminal": True, "retryable": False,
            "_lah_backend_completed": True})
        assert result["success"] is False
        with scheduler._cond:
            assert not scheduler._internal_gpu_uncertain
            assert scheduler._release_internal_gpu()
        token = other.reserve_external_gpu()
        assert token and other.release_external_gpu(token)
    finally:
        scheduler.close()
        other.close()


@pytest.mark.parametrize("raises", [False, True])
def test_failed_prewarm_retains_gpu_fence(tmp_path, raises):
    config = {"server": {"state_dir": str(tmp_path)}}
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), config)
    other = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), config)
    def switch(_model):
        with scheduler._cond:
            scheduler._switching = False
        if raises:
            raise TimeoutError("model preparation outcome unknown")
        return False
    scheduler._perform_switch = switch
    try:
        if raises:
            with pytest.raises(TimeoutError):
                scheduler.prewarm("model")
        else:
            assert scheduler.prewarm("model") is False
        with scheduler._cond:
            assert not scheduler._release_internal_gpu()
        assert other.reserve_external_gpu() is None
    finally:
        scheduler.close()
        other.close()


def test_failed_dispatched_model_preparation_retains_gpu_fence(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    def prepare(*_args, **_kwargs):
        raise TimeoutError("backend preparation outcome unknown")
    runtime = SimpleNamespace(loaded_model_details=lambda: [], prepare_model=prepare)
    scheduler = AffinityScheduler(runtime, config)
    other = AffinityScheduler(runtime, config)
    try:
        result = scheduler.submit("model", source="test", execute=lambda: {"success": True}, wait_timeout=3)
        assert result["success"] is False
        with scheduler._cond:
            assert scheduler._cond.wait_for(lambda: not scheduler._gpu_prepare_in_progress, timeout=2)
            assert not scheduler._release_internal_gpu()
        assert other.reserve_external_gpu() is None
    finally:
        scheduler.close()
        other.close()


@pytest.mark.parametrize("failure", ["reported_unknown", "exception", "contradictory"])
def test_uncertain_internal_job_retains_gpu_fence(tmp_path, failure):
    config = {"server": {"state_dir": str(tmp_path)}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [])
    scheduler = AffinityScheduler(runtime, config)
    other = AffinityScheduler(runtime, config)
    def switch(model, **_kwargs):
        with scheduler._cond:
            scheduler._active_model = model
            scheduler._switching = False
            scheduler._cond.notify_all()
        return True
    def execute():
        if failure == "exception":
            raise TimeoutError("backend outcome unknown")
        if failure == "contradictory":
            return {"success": False, "operation_not_started": True, "outcome_unknown": True}
        return {"success": False, "error": "connection lost", "outcome_unknown": True}
    scheduler._perform_switch = switch
    try:
        result = scheduler.submit("model", source="test", execute=execute, wait_timeout=3)
        assert result["success"] is False
        with scheduler._cond:
            assert not scheduler._release_internal_gpu()
        assert other.reserve_external_gpu() is None
        called = []
        rejected = scheduler.submit("model", source="test", execute=lambda: called.append(True), wait_timeout=0.15)
        assert rejected["error_code"] == "gpu_outcome_unknown" and rejected["outcome_unknown"] is True
        assert called == []
    finally:
        scheduler.close()
        other.close()


def test_proven_unstarted_job_does_not_quarantine_gpu(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), config)
    other = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), config)
    def switch(model, **_kwargs):
        with scheduler._cond:
            scheduler._active_model = model
            scheduler._switching = False
            scheduler._cond.notify_all()
        return True
    scheduler._perform_switch = switch
    try:
        result = scheduler.submit("model", source="test", execute=lambda: {
            "success": False, "operation_not_started": True, "error": "not started"}, wait_timeout=3)
        assert result["operation_not_started"] is True
        with scheduler._cond:
            assert scheduler._release_internal_gpu()
        token = other.reserve_external_gpu()
        assert token and other.release_external_gpu(token)
    finally:
        scheduler.close()
        other.close()


def test_worker_close_keeps_gpu_fence_when_stop_unconfirmed(tmp_path):
    from local_ai_hub.background_gpu import IdleGPUWorker
    config = {"server": {"state_dir": str(tmp_path)}, "models": {"background_code": "test-model"},
              "background_gpu": {"enabled": True}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [], loaded_model_inventory=lambda **_: {
        "complete": True, "backend_available": True, "models": [], "errors": {}})
    scheduler = AffinityScheduler(runtime, config)
    other = AffinityScheduler(runtime, config)
    worker = IdleGPUWorker(config, scheduler)
    worker.runtime = SimpleNamespace(stop_managed_server=lambda: False)
    worker.cpu_runtime = SimpleNamespace(stop_managed_server=lambda: True)
    try:
        assert scheduler.acquire_background_gpu(0)
        worker._lease = True
        worker.close()
        assert scheduler._background_gpu_lease and worker._lease
        assert other.reserve_external_gpu() is None
        worker.runtime.stop_managed_server = lambda: True
        assert worker.preempt_foreground()
    finally:
        worker._executor.shutdown(wait=True, cancel_futures=True)
        scheduler.close()
        other.close()


@pytest.mark.parametrize("raises", [False, True])
def test_scheduler_retains_gpu_lease_on_failed_preemption(tmp_path, raises):
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server": {"state_dir": str(tmp_path)}})
    def hook():
        if raises:
            raise OSError("stop outcome unknown")
        return False
    try:
        scheduler._background_gpu_lease = True
        scheduler._foreground_preempting = True
        scheduler._run_foreground_preempt_hook(hook)
        assert scheduler._background_gpu_lease
        assert not scheduler._foreground_preempting
    finally:
        scheduler.close()


def test_failed_background_stop_blocks_foreground_dispatch(tmp_path):
    from local_ai_hub.background_gpu import IdleGPUWorker
    config = {"server": {"state_dir": str(tmp_path)}, "models": {"background_code": "test-model"},
              "background_gpu": {"enabled": True}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [], loaded_model_inventory=lambda **_: {
        "complete": True, "backend_available": True, "models": [], "errors": {}})
    scheduler = AffinityScheduler(runtime, config)
    other = AffinityScheduler(runtime, config)
    worker = IdleGPUWorker(config, scheduler)
    worker.runtime = SimpleNamespace(stop_managed_server=lambda: False)
    called = []
    try:
        assert scheduler.acquire_background_gpu(0)
        worker._lease = True
        scheduler.set_foreground_preempt_hook(worker.preempt_foreground)
        with pytest.raises(TimeoutError):
            scheduler.submit("model", source="test", execute=lambda: called.append(True), wait_timeout=0.3)
        assert called == [] and scheduler._background_gpu_lease
        assert other.reserve_external_gpu() is None
        worker.runtime.stop_managed_server = lambda: True
        assert worker.preempt_foreground()
    finally:
        worker._executor.shutdown(wait=True, cancel_futures=True)
        scheduler.close()
        other.close()


@pytest.mark.parametrize("stop_outcome", [False, "raises"])
def test_background_preemption_keeps_fence_until_stop_confirmed(tmp_path, stop_outcome):
    from local_ai_hub.background_gpu import IdleGPUWorker
    config = {"server": {"state_dir": str(tmp_path)}, "models": {"background_code": "test-model"},
              "background_gpu": {"enabled": True}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [], loaded_model_inventory=lambda **_: {
        "complete": True, "backend_available": True, "models": [], "errors": {}})
    scheduler = AffinityScheduler(runtime, config)
    other = AffinityScheduler(runtime, config)
    worker = IdleGPUWorker(config, scheduler)
    def stop():
        if stop_outcome == "raises":
            raise OSError("stop outcome unknown")
        return stop_outcome
    worker.runtime = SimpleNamespace(stop_managed_server=stop)
    try:
        assert scheduler.acquire_background_gpu(0)
        worker._lease = True
        worker.preempt_foreground()
        assert scheduler._background_gpu_lease and worker._lease
        assert other.reserve_external_gpu() is None
        worker.runtime.stop_managed_server = lambda: True
        worker.preempt_foreground()
        assert not scheduler._background_gpu_lease and not worker._lease
        token = other.reserve_external_gpu()
        assert token and other.release_external_gpu(token)
    finally:
        worker._executor.shutdown(wait=True, cancel_futures=True)
        scheduler.close()
        other.close()


def test_background_start_failure_keeps_fence_when_stop_unconfirmed(tmp_path):
    from local_ai_hub.background_gpu import IdleGPUWorker
    config = {"server": {"state_dir": str(tmp_path)}, "models": {"background_code": "test-model"},
              "background_gpu": {"enabled": True, "idle_seconds": 0}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [], loaded_model_inventory=lambda **_: {
        "complete": True, "backend_available": True, "models": [], "errors": {}})
    scheduler = AffinityScheduler(runtime, config)
    other = AffinityScheduler(runtime, config)
    worker = IdleGPUWorker(config, scheduler)
    def fail_prepare(*_args, **_kwargs):
        raise RuntimeError("preparation failed")
    worker.runtime = SimpleNamespace(is_online=lambda: False, ensure_running=lambda: True,
        managed_profile_status=lambda: {"managed": True}, prepare_model=fail_prepare,
        stop_managed_server=lambda: False)
    try:
        assert worker._acquire_session() is False
        assert scheduler._background_gpu_lease and worker._lease
        assert other.reserve_external_gpu() is None
        worker.runtime.stop_managed_server = lambda: True
        worker.preempt_foreground()
        assert not scheduler._background_gpu_lease and not worker._lease
    finally:
        worker._executor.shutdown(wait=True, cancel_futures=True)
        scheduler.close()
        other.close()


def test_preemption_waits_for_background_start_before_releasing_gpu(tmp_path):
    from local_ai_hub.background_gpu import IdleGPUWorker
    config = {"server": {"state_dir": str(tmp_path)}, "models": {"background_code": "test-model"},
              "background_gpu": {"enabled": True, "idle_seconds": 0}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [], loaded_model_inventory=lambda **_: {
        "complete": True, "backend_available": True, "models": [], "errors": {}})
    scheduler = AffinityScheduler(runtime, config)
    other = AffinityScheduler(runtime, config)
    worker = IdleGPUWorker(config, scheduler)
    starting, resume, stopped = threading.Event(), threading.Event(), threading.Event()
    def start():
        starting.set()
        return resume.wait(3)
    worker.runtime = SimpleNamespace(is_online=lambda: False, ensure_running=start,
        managed_profile_status=lambda: {"managed": True}, prepare_model=lambda *_a, **_kw: None,
        loaded_model_details=lambda: [], stop_managed_server=lambda: stopped.set() or True)
    setup = threading.Thread(target=worker._acquire_session)
    preempt = threading.Thread(target=worker.preempt_foreground)
    try:
        setup.start()
        assert starting.wait(2)
        preempt.start()
        assert not stopped.wait(0.1)
        assert other.reserve_external_gpu() is None
        resume.set()
        setup.join(3)
        preempt.join(3)
        assert not setup.is_alive() and not preempt.is_alive() and stopped.is_set()
        token = other.reserve_external_gpu()
        assert token and other.release_external_gpu(token)
    finally:
        resume.set()
        setup.join(3)
        if preempt.ident is not None:
            preempt.join(3)
        worker._executor.shutdown(wait=True, cancel_futures=True)
        scheduler.close()
        other.close()


def test_live_background_process_excludes_external_reservation(tmp_path):
    observer = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server": {"state_dir": str(tmp_path)}})
    script = '''
import sys
from types import SimpleNamespace
from local_ai_hub.scheduler import AffinityScheduler
runtime = SimpleNamespace(loaded_model_details=lambda: [], loaded_model_inventory=lambda **_: {
    "complete": True, "backend_available": True, "models": [], "errors": {}})
scheduler = AffinityScheduler(runtime, {"server": {"state_dir": sys.argv[1]}})
print("ready" if scheduler.acquire_background_gpu(0) else "failed", flush=True)
sys.stdin.readline()
scheduler.release_background_gpu()
scheduler.close()
'''
    proc = subprocess.Popen([sys.executable, "-u", "-c", script, str(tmp_path)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    output = queue.Queue()
    reader = threading.Thread(target=lambda: output.put(proc.stdout.readline()), daemon=True)
    reader.start()
    try:
        assert output.get(timeout=10).strip() == "ready"
        assert observer.reserve_external_gpu() is None
        _stdout, stderr = proc.communicate("release\n", timeout=10)
        assert proc.returncode == 0, stderr
        token = observer.reserve_external_gpu()
        assert token and observer.release_external_gpu(token)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)
        reader.join(5)
        observer.close()


def test_crashed_background_process_leaves_gpu_reservation(tmp_path):
    runtime = SimpleNamespace(loaded_model_details=lambda: [])
    observer = AffinityScheduler(runtime, {"server": {"state_dir": str(tmp_path)}})
    script = '''
import os, sys
from types import SimpleNamespace
from local_ai_hub.scheduler import AffinityScheduler
runtime = SimpleNamespace(loaded_model_details=lambda: [], loaded_model_inventory=lambda **_: {
    "complete": True, "backend_available": True, "models": [], "errors": {}})
scheduler = AffinityScheduler(runtime, {"server": {"state_dir": sys.argv[1]}})
if not scheduler.acquire_background_gpu(0):
    raise SystemExit(2)
os._exit(0)
'''
    try:
        result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], timeout=10,
                                capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == 0, result.stderr
        assert observer.reserve_external_gpu() is None
    finally:
        observer.close()


def test_external_reservation_rejects_other_scheduler_running_job(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [])
    worker = AffinityScheduler(runtime, config)
    owner = AffinityScheduler(runtime, config)
    started, finish = threading.Event(), threading.Event()
    def switch(model, **_kwargs):
        with worker._cond:
            worker._active_model = model
            worker._switching = False
            worker._cond.notify_all()
        return True
    def execute():
        started.set()
        assert finish.wait(3)
        return {"success": True}
    worker._perform_switch = switch
    result = []
    thread = threading.Thread(target=lambda: result.append(worker.submit("model", source="test", execute=execute, wait_timeout=3)))
    try:
        thread.start()
        assert started.wait(2)
        assert owner.reserve_external_gpu() is None
        finish.set()
        thread.join(3)
        assert not thread.is_alive() and len(result) == 1 and result[0]["success"] is True
    finally:
        finish.set()
        thread.join(3)
        worker.close()
        owner.close()


def test_external_reservation_rejects_other_scheduler_background_lease(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [],
                              loaded_model_inventory=lambda **_: {"complete": True, "backend_available": True,
                                                                  "models": [], "errors": {}})
    background = AffinityScheduler(runtime, config)
    owner = AffinityScheduler(runtime, config)
    try:
        assert background.acquire_background_gpu(0)
        assert owner.reserve_external_gpu() is None
        background.release_background_gpu()
        token = owner.reserve_external_gpu()
        assert token and owner.release_external_gpu(token)
    finally:
        background.close()
        owner.close()


def test_external_reservation_rejects_other_scheduler_prewarm(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [])
    warm = AffinityScheduler(runtime, config)
    owner = AffinityScheduler(runtime, config)
    started, finish = threading.Event(), threading.Event()
    def switch(_model):
        started.set()
        result = finish.wait(3)
        with warm._cond:
            warm._switching = False
            warm._cond.notify_all()
        return result
    warm._perform_switch = switch
    thread = threading.Thread(target=lambda: warm.prewarm("model"))
    try:
        thread.start()
        assert started.wait(2)
        assert owner.reserve_external_gpu() is None
        finish.set()
        thread.join(3)
        assert not thread.is_alive()
        token = owner.reserve_external_gpu()
        assert token and owner.release_external_gpu(token)
    finally:
        finish.set()
        thread.join(3)
        warm.close()
        owner.close()


def test_reservation_release_retries_transient_sharing_violation(tmp_path, monkeypatch):
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server": {"state_dir": str(tmp_path)}})
    real_unlink = Path.unlink
    attempts = []
    def transient_unlink(path, *args, **kwargs):
        if path == scheduler._external_gpu_path:
            attempts.append(True)
            if len(attempts) == 1:
                error = PermissionError("sharing violation")
                error.winerror = 32
                raise error
        return real_unlink(path, *args, **kwargs)
    try:
        token = scheduler.reserve_external_gpu()
        assert token
        monkeypatch.setattr(Path, "unlink", transient_unlink)
        assert scheduler.release_external_gpu(token)
        assert len(attempts) == 2
    finally:
        scheduler.close()


@pytest.mark.parametrize("failure", ["incomplete", "raises", "unload_fails", "still_loaded"])
def test_background_gpu_rejects_unverified_model_release(tmp_path, failure):
    row = {"name": "test-model", "backend": "ollama", "endpoint_id": "local"}
    calls = []
    def inventory(**_kwargs):
        if failure == "raises":
            raise OSError("inventory unavailable")
        calls.append(True)
        return {"complete": failure != "incomplete", "backend_available": True,
                "models": [row] if failure in ("unload_fails", "still_loaded") else [], "errors": {}}
    runtime = SimpleNamespace(loaded_models=lambda: ["test-model"] if failure in ("unload_fails", "still_loaded") else [],
                              loaded_model_details=lambda: [], loaded_model_inventory=inventory,
                              unload=lambda _model: False,
                              unload_inventory_model=lambda *_a, **_kw: failure == "still_loaded")
    scheduler = AffinityScheduler(runtime, {"server": {"state_dir": str(tmp_path)}, "models": {"fast_code": "test-model"}})
    try:
        assert not scheduler.acquire_background_gpu(0)
        assert not scheduler._background_gpu_lease
    finally:
        scheduler.close()


@pytest.mark.parametrize("foreign", [False, True])
def test_background_gpu_requires_verified_empty_inventory(tmp_path, foreign):
    rows = [{"name": "other-model" if foreign else "test-model", "backend": "ollama", "endpoint_id": "local"}]
    unloaded = []
    def unload(row, **_kwargs):
        unloaded.append(row["name"])
        rows.clear()
        return True
    runtime = SimpleNamespace(loaded_model_details=lambda: [],
                              loaded_model_inventory=lambda **_: {"complete": True, "backend_available": True,
                                                                  "models": list(rows), "errors": {}},
                              unload_inventory_model=unload)
    scheduler = AffinityScheduler(runtime, {"server": {"state_dir": str(tmp_path)}, "models": {"fast_code": "test-model"}})
    try:
        assert scheduler.acquire_background_gpu(0) is not foreign
        assert unloaded == ([] if foreign else ["test-model"])
        if not foreign:
            scheduler.release_background_gpu()
    finally:
        scheduler.close()


@pytest.mark.parametrize("other_scheduler", [False, True])
def test_prewarm_respects_external_gpu_reservation(tmp_path, other_scheduler):
    config = {"server": {"state_dir": str(tmp_path)}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [])
    owner = AffinityScheduler(runtime, config)
    target = AffinityScheduler(runtime, config) if other_scheduler else owner
    switches = []
    target._perform_switch = lambda model: switches.append(model) or True
    try:
        token = owner.reserve_external_gpu()
        assert token
        assert target.prewarm("model") is False
        assert switches == []
        with target._cond:
            target._active_model = "model"
        assert target.prewarm("model") is False
        with target._cond:
            target._active_model = None
        assert owner.release_external_gpu(token)
        assert target.prewarm("model") is True
        assert switches == ["model"]
    finally:
        if target is not owner:
            target.close()
        owner.close()


def test_existing_scheduler_observes_external_reservation(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    runtime = SimpleNamespace(loaded_models=lambda: [], loaded_model_details=lambda: [],
                              loaded_model_inventory=lambda **_: {"complete": True, "backend_available": True,
                                                                   "models": [], "errors": {}})
    owner = AffinityScheduler(runtime, config)
    other = AffinityScheduler(runtime, config)
    try:
        token = owner.reserve_external_gpu()
        assert token is not None
        assert not other.acquire_background_gpu(0)
        assert other.foreground_busy()
        assert not other.background_allowed()
        assert owner.release_external_gpu(token)
        assert other.acquire_background_gpu(0)
        other.release_background_gpu()
    finally:
        owner.close()
        other.close()


def test_existing_scheduler_does_not_dispatch_during_new_external_reservation(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    preparations, calls = [], []
    runtime = SimpleNamespace(loaded_model_details=lambda: [],
                              prepare_model=lambda *a, **k: preparations.append(True))
    owner = AffinityScheduler(runtime, config)
    other = AffinityScheduler(runtime, config)
    try:
        token = owner.reserve_external_gpu()
        assert token
        with pytest.raises(TimeoutError):
            other.submit("model", source="test", execute=lambda: calls.append(True), wait_timeout=0.2)
        assert preparations == [] and calls == []
        assert owner.release_external_gpu(token)
    finally:
        owner.close()
        other.close()


def test_background_worker_never_terminates_an_unmanaged_listener(tmp_path, monkeypatch):
    from local_ai_hub import background_gpu

    attempts, releases, stopped = [], [], []
    scheduler = SimpleNamespace(acquire_background_gpu=lambda _: True, release_background_gpu=lambda: releases.append(True),
                                foreground_busy=lambda: False)
    config = {"server": {"state_dir": str(tmp_path)}, "models": {"background_code": "test-model"},
              "background_gpu": {"enabled": True, "idle_seconds": 0}}
    worker = background_gpu.IdleGPUWorker(config, scheduler)
    worker.runtime = SimpleNamespace(is_online=lambda: True, managed_profile_status=lambda: {"managed": False},
                                     stop_managed_server=lambda: stopped.append(True))
    monkeypatch.setattr(background_gpu, "find_listening_pid", lambda _port: 12345, raising=False)
    monkeypatch.setattr(background_gpu, "process_executable", lambda _pid: "ollama.exe", raising=False)
    def forbidden(pid, **_kwargs):
        attempts.append(pid)
        raise RuntimeError("unmanaged process must never be terminated")
    monkeypatch.setattr(background_gpu, "terminate_tree", forbidden, raising=False)
    try:
        assert worker._acquire_session() is False
        assert attempts == []
        assert releases == [True]
        assert stopped == []
        assert worker._stats["unmanaged_endpoint_rejections"] == 1
    finally:
        worker._executor.shutdown(wait=True, cancel_futures=True)


def test_background_worker_rejects_endpoint_borrowed_during_start(tmp_path):
    from local_ai_hub.background_gpu import IdleGPUWorker

    releases, prepared, stopped = [], [], []
    scheduler = SimpleNamespace(acquire_background_gpu=lambda _: True, release_background_gpu=lambda: releases.append(True),
                                foreground_busy=lambda: False)
    config = {"server": {"state_dir": str(tmp_path)}, "models": {"background_code": "test-model"},
              "background_gpu": {"enabled": True, "idle_seconds": 0}}
    worker = IdleGPUWorker(config, scheduler)
    worker.runtime = SimpleNamespace(is_online=lambda: False, ensure_running=lambda: True,
        managed_profile_status=lambda: {"managed": False}, prepare_model=lambda *a, **k: prepared.append(True),
        stop_managed_server=lambda: stopped.append(True))
    try:
        assert worker._acquire_session() is False
        assert prepared == [] and stopped == []
        assert releases == [True]
        assert worker._stats["unmanaged_endpoint_rejections"] == 1
    finally:
        worker._executor.shutdown(wait=True, cancel_futures=True)


def test_cpu_worker_rejects_endpoint_borrowed_during_start(tmp_path):
    from local_ai_hub.background_gpu import IdleGPUWorker

    prepared, stopped = [], []
    config = {"server": {"state_dir": str(tmp_path)}, "models": {"background_code": "test-model"},
              "background_gpu": {"enabled": True, "cpu_fallback_enabled": True}}
    worker = IdleGPUWorker(config, SimpleNamespace())
    worker.cpu_runtime = SimpleNamespace(is_online=lambda: False, ensure_running=lambda: True,
        managed_profile_status=lambda: {"managed": False}, prepare_model=lambda *a, **k: prepared.append(True),
        stop_managed_server=lambda: stopped.append(True))
    try:
        assert worker._acquire_cpu_session() is False
        assert prepared == [] and stopped == []
    finally:
        worker._executor.shutdown(wait=True, cancel_futures=True)


def test_background_worker_accepts_verified_managed_endpoint(tmp_path):
    from local_ai_hub.background_gpu import IdleGPUWorker

    prepared = []
    scheduler = SimpleNamespace(acquire_background_gpu=lambda _: True, release_background_gpu=lambda: None,
                                foreground_busy=lambda: False)
    config = {"server": {"state_dir": str(tmp_path)}, "models": {"background_code": "test-model"},
              "background_gpu": {"enabled": True, "idle_seconds": 0}}
    worker = IdleGPUWorker(config, scheduler)
    worker.runtime = SimpleNamespace(is_online=lambda: True, ensure_running=lambda: True,
        managed_profile_status=lambda: {"managed": True}, prepare_model=lambda *a, **k: prepared.append(True),
        loaded_model_details=lambda: [{"name": "test-model", "cpu_offload_fraction": 0}])
    try:
        assert worker._acquire_session() is True
        assert prepared == [True]
    finally:
        worker._executor.shutdown(wait=True, cancel_futures=True)


def test_external_reservation_fences_background_and_idle_unload(tmp_path):
    runtime = SimpleNamespace(loaded_model_details=lambda: [])
    scheduler = AffinityScheduler(runtime, {"server": {"state_dir": str(tmp_path)}, "scheduler": {"idle_timeout_seconds": 1}})
    try:
        token = scheduler.reserve_external_gpu()
        assert isinstance(token, str) and token
        assert scheduler.reserve_external_gpu() is None
        assert scheduler.foreground_busy()
        assert not scheduler.background_allowed()
        assert not scheduler.acquire_background_gpu(0)
        with scheduler._cond:
            scheduler._active_model = "model"
            scheduler._idle_owned_model = "model"
            scheduler._last_model_activity = time.monotonic() - 10
            assert scheduler._claim_idle_unload(time.monotonic()) is None
            scheduler._active_model = None
        assert not scheduler.release_external_gpu("not-the-token")
        assert not scheduler.release_external_gpu("ž")
        assert not scheduler.acquire_background_gpu(0)
        assert scheduler.release_external_gpu(token)
        assert not scheduler.release_external_gpu(token)
    finally:
        scheduler.close()


def test_scheduler_does_not_dispatch_internal_work_during_external_reservation(tmp_path):
    runtime = SimpleNamespace(loaded_model_details=lambda: [])
    scheduler = AffinityScheduler(runtime, {"server": {"state_dir": str(tmp_path)}})
    called = threading.Event()
    try:
        token = scheduler.reserve_external_gpu()
        assert token
        with pytest.raises(TimeoutError):
            scheduler.submit("model", source="test", execute=lambda: called.set() or {"success": True}, wait_timeout=0.15)
        assert not called.is_set()
        assert scheduler.release_external_gpu(token)
    finally:
        scheduler.close()


def test_external_reservation_is_atomic_between_competing_clients(tmp_path):
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server": {"state_dir": str(tmp_path)}})
    barrier = threading.Barrier(3)
    results = []
    def reserve():
        barrier.wait(timeout=2)
        results.append(scheduler.reserve_external_gpu())
    threads = [threading.Thread(target=reserve) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        barrier.wait(timeout=2)
        for thread in threads:
            thread.join(timeout=2)
            assert not thread.is_alive()
        assert sum(token is not None for token in results) == 1
        assert scheduler.release_external_gpu(next(token for token in results if token))
    finally:
        scheduler.close()


def test_external_reservation_survives_scheduler_restart(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [])
    first = AffinityScheduler(runtime, config)
    token = first.reserve_external_gpu()
    assert token
    first.close()
    second = AffinityScheduler(runtime, config)
    try:
        assert second.foreground_busy()
        assert second.reserve_external_gpu() is None
        assert not second.acquire_background_gpu(0)
        assert not second.release_external_gpu("wrong-token")
        assert second.release_external_gpu(token)
    finally:
        second.close()


def test_corrupt_external_reservation_fails_closed(tmp_path):
    (tmp_path / "external-gpu-reservation").write_text("incomplete", encoding="ascii")
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server": {"state_dir": str(tmp_path)}})
    try:
        assert scheduler.foreground_busy()
        assert scheduler.reserve_external_gpu() is None
        assert not scheduler.release_external_gpu("anything")
        assert not scheduler.acquire_background_gpu(0)
    finally:
        scheduler.close()


def test_reservation_sync_failure_keeps_fence_after_restart(tmp_path, monkeypatch):
    from local_ai_hub import scheduler as scheduler_module

    config = {"server": {"state_dir": str(tmp_path)}}
    runtime = SimpleNamespace(loaded_model_details=lambda: [])
    scheduler = AffinityScheduler(runtime, config)
    try:
        def fail_sync(_fd):
            raise OSError("sync failed")
        monkeypatch.setattr(scheduler_module.os, "fsync", fail_sync)
        assert scheduler.reserve_external_gpu() is None
        assert scheduler.foreground_busy()
    finally:
        scheduler.close()
    restarted = AffinityScheduler(runtime, config)
    try:
        assert restarted.foreground_busy()
        assert restarted.reserve_external_gpu() is None
    finally:
        restarted.close()


def test_external_reservation_requires_persistent_state_directory():
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {})
    try:
        assert scheduler.reserve_external_gpu() is None
    finally:
        scheduler.close()


def test_reservation_survives_abrupt_process_exit(tmp_path):
    script = '''
import os, sys
from types import SimpleNamespace
from local_ai_hub.scheduler import AffinityScheduler
s=AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server":{"state_dir":sys.argv[1]}})
if len(sys.argv)==2:
    print(s.reserve_external_gpu(), flush=True)
    os._exit(0)
assert s.foreground_busy() and s.reserve_external_gpu() is None
assert s.release_external_gpu(sys.argv[2])
s.close()
'''
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    first = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True, timeout=10, creationflags=flags, check=True)
    token = first.stdout.strip()
    assert token and token != "None"
    subprocess.run([sys.executable, "-c", script, str(tmp_path), token], capture_output=True, text=True, timeout=10, creationflags=flags, check=True)


@pytest.mark.parametrize("field,value", [("_inflight", 1), ("_switching", True), ("_background_gpu_lease", True)])
def test_external_reservation_rejects_existing_gpu_work(field, value, tmp_path):
    scheduler = AffinityScheduler(SimpleNamespace(loaded_model_details=lambda: []), {"server": {"state_dir": str(tmp_path)}})
    try:
        with scheduler._cond:
            original = getattr(scheduler, field)
            setattr(scheduler, field, value)
            assert scheduler.reserve_external_gpu() is None
            setattr(scheduler, field, original)
    finally:
        scheduler.close()
