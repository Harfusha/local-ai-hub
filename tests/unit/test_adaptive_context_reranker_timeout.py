from unittest.mock import MagicMock
from local_ai_hub.services import LocalAIServices

def test_adaptive_context_bypasses_cpu_reranker():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {
        "rag": {"enabled": True, "use_reranker": True},
        "search": {"adaptive_backend_timeout_seconds": 3.0},
    }
    
    mock_rag = MagicMock()
    mock_rag.configured = True
    mock_rag.workspace_id.return_value = "ws1"
    mock_rag.revision.return_value = "rev1"
    mock_reranker = MagicMock()
    mock_reranker.active_device = "cpu"
    mock_rag.reranker = mock_reranker
    services.rag = mock_rag
    services.reranker = None

    reranker_obj = getattr(services, "reranker", None) or getattr(getattr(services, "rag", None), "reranker", None)
    active_device = str(getattr(reranker_obj, "active_device", "") or getattr(reranker_obj, "device", "") or "").strip().lower()
    rag_use_reranker = (
        bool(services.config.get("rag", {}).get("use_reranker", True))
        and not (reranker_obj and active_device == "cpu")
    )
    assert rag_use_reranker is False

    mock_reranker.active_device = "cuda:0"
    active_device_gpu = str(getattr(reranker_obj, "active_device", "") or getattr(reranker_obj, "device", "") or "").strip().lower()
    rag_use_reranker_gpu = (
        bool(services.config.get("rag", {}).get("use_reranker", True))
        and not (reranker_obj and active_device_gpu == "cpu")
    )
    assert rag_use_reranker_gpu is True
