from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import local_ai_hub.services as services_module
from local_ai_hub.services import LocalAIServices

_SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"
assert Path(services_module.__file__).resolve().is_relative_to(_SOURCE_ROOT)


class _RagBackend:
    def __init__(self, device: str) -> None:
        self.reranker = SimpleNamespace(active_device=device)
        self.search_calls: list[dict[str, object]] = []
        self.authorizations: list[tuple[str, str]] = []

    @staticmethod
    def workspace_id(root: str) -> str:
        return "workspace:" + str(Path(root).resolve())

    def require_workspace_root(self, *, workspace: str, root: str) -> None:
        canonical_root = str(Path(root).resolve(strict=True))
        self.authorizations.append((workspace, canonical_root))
        if workspace != self.workspace_id(canonical_root):
            raise ValueError("workspace is not bound to root")

    def search(self, query: str, *, workspace: str, **kwargs: object) -> dict[str, object]:
        self.search_calls.append({k: kwargs[k] for k in ("top_k", "use_reranker") if k in kwargs})
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


def _wait_for_completed_futures(futures, timeout=None):
    futures = set(futures)
    done = {future for future in futures if future.done()}
    return done, futures - done


def test_deadline_wait_keeps_unresolved_future_pending():
    unresolved = Future()
    resolved = Future()
    resolved.set_result("ready")

    done, pending = _wait_for_completed_futures({unresolved, resolved}, timeout=0.01)

    assert done == {resolved}
    assert pending == {unresolved}


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
    monkeypatch.setattr(services_module, "wait", _wait_for_completed_futures)

    result = services._hybrid_context_uncached(
        str(tmp_path), "deadline query", workspace="workspace", max_tokens=512,
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
        monkeypatch.setattr(services_module, "wait", _wait_for_completed_futures)

        result = services._hybrid_context_uncached(
            str(tmp_path), "deadline query", workspace="workspace", max_tokens=512,
            quality_first=True,
        )

        assert services.rag.search_calls == [
            {"top_k": 10, "use_reranker": expected}
        ]
        assert result["retrieval"]["backend_states"]["rag"] == "used"
        assert any(item.get("path") == "rag-deadline.md" for item in result["evidence"])


def test_hybrid_context_checks_workspace_binding_before_revision_or_cache(tmp_path):
    class RejectingRag(_RagBackend):
        def require_workspace_root(self, *, workspace: str, root: str) -> None:
            self.authorizations.append((workspace, root))
            raise ValueError("workspace belongs to another root")

        def revision(self, *, workspace: str) -> str:
            raise AssertionError("revision read before workspace authorization")

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"features": {"rag": True}}
    services.deterministic = None
    services.learner = None
    services.code_index = None
    services.evidence_store = None
    services.external_tools = None
    services.reranker = None
    services.rag = RejectingRag("cpu")
    services._repo_cached = Mock(return_value={"context": "cached cross-root context"})

    result = services._hybrid_context(
        str(tmp_path), "root-bound query", workspace="attacker-workspace", max_tokens=128
    )

    assert services.rag.authorizations == [("attacker-workspace", str(tmp_path.resolve()))]
    services._repo_cached.assert_not_called()
    assert result.get("context") != "cached cross-root context"
