from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import local_ai_hub.services as services_module
from local_ai_hub.services import LocalAIServices

_SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
assert Path(services_module.__file__).resolve().is_relative_to(_SOURCE_ROOT)


class _RagBackend:
    def __init__(self, device: str) -> None:
        self.reranker = SimpleNamespace(active_device=device)
        self.search_calls: list[dict[str, object]] = []

    def search(self, query: str, tenant: str, workspace: str, **kwargs: object) -> dict[str, object]:
        self.search_calls.append(dict(kwargs))
        return {
            "success": True,
            "results": [
                {
                    "path": "rag-deadline.md",
                    "text": "RAG result retained under the adaptive context deadline.",
                    "score": 0.95,
                    "chunk_no": 0,
                }
            ],
        }


class _DeadlinePool:
    def __init__(self, backend: _RagBackend) -> None:
        self.backend = backend

    def submit(self, function, *args, **kwargs) -> Future:
        future = Future()
        if kwargs.get("use_reranker") and self.backend.reranker.active_device == "cpu":
            # Model slow CPU cross-encoder expiry without sleeping or loading a model.
            return future
        future.set_result(function(*args, **kwargs))
        return future


def test_adaptive_context_retains_rag_when_cpu_reranking_would_miss_deadline(
    tmp_path, monkeypatch
):
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {
        "features": {"rag": True},
        "rag": {"use_reranker": True},
        "search": {
            "context_backend_timeout_seconds": 0.05,
            "context_rag_timeout_seconds": 0.05,
        },
    }
    services.learner = None
    services.deterministic = None
    services.code_index = None
    services.evidence_store = None
    services.external_tools = None
    services.reranker = None
    services.rag = _RagBackend("cpu")
    monkeypatch.setitem(
        services_module._CONTEXT_BACKEND_POOLS,
        "rag",
        _DeadlinePool(services.rag),
    )
    monkeypatch.setattr(
        services_module,
        "wait",
        lambda futures, timeout=None: (set(futures), set()),
    )

    result = services._hybrid_context_uncached(
        str(tmp_path), "deadline query", "tenant", "workspace", 512,
        quality_first=True,
    )

    assert services.rag.search_calls == [{"top_k": 10, "use_reranker": False}]
    assert result["retrieval"]["backend_states"]["rag"] == "used"
    assert "RAG result retained under the adaptive context deadline." in result["context"]


def test_adaptive_context_keeps_gpu_reranking_and_explicit_disable(
    tmp_path, monkeypatch
):
    for device, enabled, expected in (("cuda:0", True, True), ("cuda:0", False, False)):
        services = LocalAIServices.__new__(LocalAIServices)
        services.config = {
            "features": {"rag": True},
            "rag": {"use_reranker": enabled},
            "search": {
                "context_backend_timeout_seconds": 0.05,
                "context_rag_timeout_seconds": 0.05,
            },
        }
        services.learner = None
        services.deterministic = None
        services.code_index = None
        services.evidence_store = None
        services.external_tools = None
        services.reranker = None
        services.rag = _RagBackend(device)
        monkeypatch.setitem(
            services_module._CONTEXT_BACKEND_POOLS,
            "rag",
            _DeadlinePool(services.rag),
        )
        monkeypatch.setattr(
            services_module,
            "wait",
            lambda futures, timeout=None: (set(futures), set()),
        )

        result = services._hybrid_context_uncached(
            str(tmp_path), "deadline query", "tenant", "workspace", 512,
            quality_first=True,
        )

        assert services.rag.search_calls == [
            {"top_k": 10, "use_reranker": expected}
        ]
        assert result["retrieval"]["backend_states"]["rag"] == "used"
        assert any(item.get("path") == "rag-deadline.md" for item in result["evidence"])
