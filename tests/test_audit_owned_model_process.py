import sys
import threading
import time

import pytest


@pytest.mark.parametrize(
    ("platform", "device", "mask_present", "avx512_available", "expected_mask"),
    [
        ("linux", "cuda", False, False, False),
        ("win32", "cpu", False, False, False),
        ("win32", "cuda", True, False, False),
        ("win32", "cuda:0", False, True, False),
        ("win32", "cuda:0", False, False, True),
    ],
)
def test_cuda_worker_environment_only_disables_unsupported_avx512(
    monkeypatch, platform, device, mask_present, avx512_available, expected_mask
):
    from local_ai_hub import owned_model

    monkeypatch.setattr(owned_model.sys, "platform", platform)
    monkeypatch.setattr(owned_model, "_windows_avx512_available", lambda: avx512_available)
    monkeypatch.delenv("CUBLASLT_DISABLE_CPU_INSTRUCTIONS_MASK", raising=False)
    if mask_present:
        monkeypatch.setenv("CUBLASLT_DISABLE_CPU_INSTRUCTIONS_MASK", "existing")

    result = owned_model._cuda_worker_environment({"device": device})

    assert (result is not None) is expected_mask
    if expected_mask:
        assert result["CUBLASLT_DISABLE_CPU_INSTRUCTIONS_MASK"] == "1"


def test_owned_model_stderr_reader_stops_after_stream_close():
    from types import SimpleNamespace

    from local_ai_hub.owned_model import _ModelProcess

    class ClosedStream:
        def read1(self, _size):
            raise OSError("stream closed")

        def read(self, _size):
            raise OSError("stream closed")

    process = object.__new__(_ModelProcess)
    process.process = SimpleNamespace(stderr=ClosedStream())
    process._stderr_lock = threading.Lock()
    process._stderr_tail = bytearray()

    process._read_stderr()

    assert process._stderr_tail == b""


def test_owned_model_stderr_reader_bounds_retained_tail():
    from types import SimpleNamespace

    from local_ai_hub.owned_model import _ModelProcess

    class Stream:
        chunks = iter((b"z", b""))

        def read(self, _size):
            return next(self.chunks)

    process = object.__new__(_ModelProcess)
    process.process = SimpleNamespace(stderr=Stream())
    process._stderr_lock = threading.Lock()
    process._stderr_tail = bytearray(b"x" * 8192)

    process._read_stderr()

    assert len(process._stderr_tail) == 8192
    assert process._stderr_tail[-1:] == b"z"


@pytest.mark.parametrize("kind", ["embedding", "reranker"])
def test_failed_worker_cleanup_preserves_owner_for_retry(kind):
    from local_ai_hub.embeddings import EmbeddingModel
    from local_ai_hub.reranker import Reranker
    from local_ai_hub import model_lifecycle
    class Model:
        owned_process = True
        calls = 0
        def close(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("model process cleanup unconfirmed")
    owner = object.__new__(EmbeddingModel if kind == "embedding" else Reranker)
    owner._load_lock = threading.Lock()
    owner._encoder_lock = threading.Lock()
    owner._predict_lock = threading.Lock()
    owner.model_name = "fake"
    model = Model()
    owner._model = model_lifecycle.load_model(owner, uses_cuda=True, factory=lambda: model)
    owner.active_backend, owner.active_device = "torch", "cuda"
    try:
        with pytest.raises(RuntimeError, match="cleanup unconfirmed"):
            owner.release()
        assert owner._model is model
        assert owner.active_device == "cuda"
        assert owner.release() is True
    finally:
        model_lifecycle.release_model(owner, used_cuda=True)


@pytest.mark.parametrize("kind", ["embedding", "reranker"])
def test_real_owned_worker_loads_and_runs_isolated_fake_model(tmp_path, monkeypatch, kind):
    from local_ai_hub.owned_model import OwnedNLPModel
    (tmp_path / "sentence_transformers.py").write_text(
        "from types import SimpleNamespace\n"
        "class SentenceTransformer:\n"
        " def __init__(self,*args,**kwargs):\n"
        "  self.max_seq_length=128;self.prompts={'query':'q'};self.config=SimpleNamespace(_commit_hash='b'*40)\n"
        " def encode(self,items,**kwargs):return [[float(len(item)),1.0] for item in items]\n"
        "class CrossEncoder(SentenceTransformer):\n"
        " def predict(self,items,**kwargs):return [0.5 for item in items]\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    model = OwnedNLPModel(kind, "fake", {"device": "cuda"}, max_length=64)
    try:
        assert model.config._commit_hash == "b" * 40
        if kind == "embedding":
            assert model.max_seq_length == 64
            assert model.encode(["hello"], normalize_embeddings=True) == [[5.0, 1.0]]
        else:
            assert model.predict([["query", "document"]]) == [0.5]
    finally:
        model.close()
    assert model._transport.process.poll() is not None


def test_owned_worker_returns_protocol_error_for_nonfinite_model_output(tmp_path, monkeypatch):
    from local_ai_hub.owned_model import OwnedNLPModel

    (tmp_path / "sentence_transformers.py").write_text(
        "from types import SimpleNamespace\n"
        "class SentenceTransformer:\n"
        " def __init__(self,*args,**kwargs):\n"
        "  self.max_seq_length=128;self.prompts={};self.config=SimpleNamespace(_commit_hash='c'*40)\n"
        "class CrossEncoder(SentenceTransformer):\n"
        " def predict(self,items,**kwargs):return [float('nan') for item in items]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    model = OwnedNLPModel("reranker", "fake", {"device": "cuda"}, max_length=64)
    try:
        with pytest.raises(RuntimeError, match="model response is not valid JSON"):
            model.predict([["query", "document"]])
        assert model._transport.process.poll() is not None
    finally:
        model.close()


def test_owned_model_release_avoids_parent_cuda_driver(monkeypatch):
    from local_ai_hub import model_lifecycle
    class Owner:
        pass
    class Model:
        owned_process = True
        closed = False
        def close(self):
            self.closed = True
    owner, model = Owner(), Model()
    monkeypatch.setattr(model_lifecycle.gc, "collect", lambda: pytest.fail("parent touched CUDA cleanup path"))
    model_lifecycle.load_model(owner, uses_cuda=True, factory=lambda: model)
    assert model_lifecycle.release_model(owner, used_cuda=True) is True
    assert model.closed


@pytest.mark.parametrize("kind", ["embedding", "reranker"])
def test_cuda_nlp_candidate_uses_worker_without_importing_models_in_parent(monkeypatch, kind):
    from local_ai_hub import owned_model, model_lifecycle
    from local_ai_hub.embeddings import EmbeddingModel
    from local_ai_hub.reranker import Reranker
    calls = []
    class Model:
        owned_process = True
        model_name = "example"
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))
        def close(self):
            pass
    monkeypatch.setattr(owned_model, "OwnedNLPModel", Model)
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    owner = object.__new__(EmbeddingModel if kind == "embedding" else Reranker)
    owner._candidate_specs = lambda **_kwargs: [("torch", "cuda")]
    owner.model_name, owner.config = "example", {"models": {"allow_hf_downloads": False}}
    owner.trust_remote_code, owner.max_seq_length, owner.max_length = False, 512, 512
    owner._record_model_provenance = lambda *args, **kwargs: None
    try:
        assert owner._load_candidate(0) is True
        assert calls[0][0][0] == kind
        assert calls[0][1]["allow_downloads"] is False
    finally:
        model_lifecycle.release_model(owner, used_cuda=True)


def test_owned_model_timeout_reaps_actual_child():
    from local_ai_hub.owned_model import _ModelProcess
    process = _ModelProcess([sys.executable, "-u", "-c", "import sys,time;sys.stdin.readline();time.sleep(30)"])
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            process.request({"operation": "load"}, timeout=0.15)
        assert time.monotonic() - started < 4
        assert process.process.poll() is not None
    finally:
        process.close()


def test_owned_model_protocol_roundtrip_and_idempotent_close():
    from local_ai_hub.owned_model import _ModelProcess
    script = "import sys,json\nfor line in sys.stdin:\n data=json.loads(line);print(json.dumps({'success':True,'request_id':data['request_id'],'value':data}),flush=True)"
    process = _ModelProcess([sys.executable, "-u", "-c", script])
    try:
        assert process.request({"operation": "encode", "items": ["hello"]}, timeout=5)["value"]["items"] == ["hello"]
    finally:
        process.close()
        process.close()
    assert process.process.poll() is not None


def test_owned_model_rejects_oversized_input_before_pipe_write():
    from local_ai_hub.owned_model import _ModelProcess
    process = _ModelProcess([sys.executable, "-u", "-c", "import time;time.sleep(30)"])
    try:
        with pytest.raises(ValueError):
            process.request({"items": "x" * (2 * 1024 * 1024)}, timeout=1)
    finally:
        process.close()


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), True, 301])
def test_owned_model_rejects_invalid_timeout_before_transport_use(timeout):
    from local_ai_hub.owned_model import _ModelProcess

    process = _ModelProcess.__new__(_ModelProcess)
    with pytest.raises(ValueError, match="model timeout"):
        process.request({"operation": "load"}, timeout=timeout)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ("{'success': True, 'request_id': 999}", "identity mismatch"),
        ("{'success': False, 'request_id': 1, 'error': 'worker refused'}", "worker refused"),
    ],
)
def test_owned_model_rejects_bad_worker_response_and_reaps_child(response, message):
    from local_ai_hub.owned_model import _ModelProcess

    script = f"import json,sys,time;sys.stdin.readline();print(json.dumps({response}),flush=True);time.sleep(30)"
    process = _ModelProcess([sys.executable, "-u", "-c", script])
    try:
        with pytest.raises(RuntimeError, match=message):
            process.request({"operation": "load"}, timeout=5)
        assert process.process.poll() is not None
    finally:
        process.close()


def test_owned_model_reports_worker_exit_code_and_bounded_stderr():
    from local_ai_hub.owned_model import _ModelProcess

    script = "import sys;sys.stdin.readline();sys.stderr.write('fatal model worker error\\n');sys.stderr.flush();sys.exit(17)"
    process = _ModelProcess([sys.executable, "-u", "-c", script])
    try:
        with pytest.raises(RuntimeError, match="worker exit code: 17") as raised:
            process.request({"operation": "load"}, timeout=5)
        assert "fatal model worker error" in str(raised.value)
    finally:
        process.close()


def test_owned_model_timeout_reports_bounded_worker_stderr():
    from local_ai_hub.owned_model import _ModelProcess

    script = "import sys,time;sys.stdin.readline();sys.stderr.write('predict still running');sys.stderr.flush();time.sleep(5)"
    process = _ModelProcess([sys.executable, "-u", "-c", script])
    try:
        with pytest.raises(TimeoutError, match="model operation timed out") as raised:
            process.request({"operation": "predict"}, timeout=0.1)
        assert "worker stderr: predict still running" in str(raised.value)
    finally:
        process.close()


def test_owned_model_rejects_request_after_close():
    from local_ai_hub.owned_model import _ModelProcess

    process = _ModelProcess([sys.executable, "-u", "-c", "import time;time.sleep(30)"])
    process.close()
    with pytest.raises(RuntimeError, match="model process is closed"):
        process.request({"operation": "load"}, timeout=1)
