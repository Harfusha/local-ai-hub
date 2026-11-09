from local_ai_hub.services import LocalAIServices
from local_ai_hub.embeddings import EmbeddingModel


class _EmbeddingModel:
    def __init__(self) -> None:
        self.calls = []

    def encode(self, texts, *, query=False, priority=3):
        self.calls.append((list(texts), query, priority))
        return {
            "success": True,
            "backend": "sentence-transformers",
            "device": "cuda:0",
            "embeddings": [[0.25, 0.75]],
        }


class _Runtime:
    def __init__(self) -> None:
        self.requests = []

    def request(self, endpoint, payload):
        self.requests.append((endpoint, payload))
        return {"success": False, "error": "model not found in Ollama"}


class _Scheduler:
    def __init__(self) -> None:
        self.calls = []

    def submit(self, model, *, execute, **kwargs):
        self.calls.append((model, kwargs))
        return execute()


def _service(backend: str) -> tuple[LocalAIServices, _EmbeddingModel, _Runtime, _Scheduler]:
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {
        "models": {
            "embedding": "BAAI/bge-small-en-v1.5",
            "embedding_backend": backend,
        },
        "rag": {"embedding_batch_size": 12},
    }
    embeddings, runtime, scheduler = _EmbeddingModel(), _Runtime(), _Scheduler()
    service.embeddings = embeddings
    service.runtime = runtime
    service.scheduler = scheduler
    return service, embeddings, runtime, scheduler


def test_auto_embedding_backend_uses_accelerator_embedding_model() -> None:
    service, embeddings, runtime, scheduler = _service("auto")

    result = service.embed(["indexed source"], priority=1)

    assert result["success"] is True
    assert result["device"] == "cuda:0"
    assert embeddings.calls == [(["indexed source"], False, 1)]
    assert runtime.requests == []
    assert scheduler.calls == []


def test_explicit_ollama_embedding_backend_keeps_ollama_path() -> None:
    service, embeddings, runtime, scheduler = _service("ollama")

    result = service.embed(["indexed source"], priority=1)

    assert result["success"] is False
    assert embeddings.calls == []
    assert len(runtime.requests) == 1
    assert len(scheduler.calls) == 1


def test_auto_huggingface_model_skips_ollama_before_device_candidates(tmp_path, monkeypatch) -> None:
    model = EmbeddingModel({
        "server": {"state_dir": str(tmp_path)},
        "models": {
            "embedding": "BAAI/bge-small-en-v1.5",
            "embedding_backend": "auto",
            "embedding_device": "cpu",
            "allow_hf_downloads": False,
        },
        "features": {"rag": True},
        "cache": {"embeddings": False},
    })
    ollama_calls = []
    device_calls = []

    def ollama(texts):
        ollama_calls.append(list(texts))
        return None

    def encode_device(texts, *, query, priority):
        device_calls.append((list(texts), query, priority))
        return [[0.25, 0.75] for _ in texts], "sentence-transformers"

    monkeypatch.setattr(model, "_encode_ollama", ollama)
    monkeypatch.setattr(model, "_encode_st_batch", encode_device)

    result = model.encode(["HF-cached preprocessing input"], priority=1)

    assert result["success"] is True
    assert result["backend"] == "sentence-transformers"
    assert ollama_calls == []
    assert device_calls == [(["HF-cached preprocessing input"], False, 1)]
