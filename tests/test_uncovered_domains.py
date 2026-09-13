from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
from local_ai_hub.services import LocalAIServices
from local_ai_hub.rag import RAGStore
from local_ai_hub.telemetry import TelemetryStore


def test_vision_service(tmp_path: Path) -> None:
    img_file = tmp_path / "test.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\nfakeimagebytes")

    runtime = MagicMock()
    runtime.request = MagicMock(return_value={
        "response": "A screenshot showing a dashboard with token metrics.",
    })

    services = LocalAIServices(
        config={"server": {"state_dir": str(tmp_path)}, "models": {"vision": "llava"}},
        runtime=runtime,
        scheduler=MagicMock(),
        embeddings=MagicMock(),
        artifacts=MagicMock(),
        telemetry=MagicMock(),
        repo_tools=MagicMock(),
        deterministic=None,
    )

    res = services.vision(
        {
            "image": str(img_file),
            "prompt": "What is in this image?",
        },
        tenant="test",
    )

    assert res["success"] is True
    assert "A screenshot showing" in res["response"]
    assert runtime.request.called
    req_payload = runtime.request.call_args[0][1]
    assert len(req_payload["images"]) == 1
    assert req_payload["prompt"] == "What is in this image?"


def test_docset_rag(tmp_path: Path) -> None:
    config = {
        "server": {"state_dir": str(tmp_path)},
        "rag": {"chunk_chars": 500, "chunk_overlap_chars": 50},
    }
    rag = RAGStore(config=config)
    rag.index = MagicMock(return_value={"success": True, "indexed": 5, "workspace": "docset:pandas"})
    rag.search = MagicMock(return_value={"success": True, "results": [{"path": "api.md", "text": "DataFrame"}]})

    idx_res = rag.docset_index("pandas", str(tmp_path))
    assert idx_res["success"] is True
    rag.index.assert_called_once_with(str(tmp_path), "docset", workspace="docset:pandas")

    search_res = rag.docset_search("pandas", "DataFrame")
    assert search_res["success"] is True
    rag.search.assert_called_once_with("DataFrame", "docset", "docset:pandas", top_k=8, use_reranker=True)


def test_telemetry_timeline(tmp_path: Path) -> None:
    telemetry = TelemetryStore(
        state_dir=tmp_path,
        flush_interval_seconds=0.01,
        max_events=100,
    )
    try:
        # Record some events
        telemetry.record_http(
            request_id="req-1",
            agent="agent-a",
            tenant="tenant-1",
            action="local_ai_command",
            status_code=200,
            duration_ms=45.2,
            success=True,
        )
        telemetry.record_http(
            request_id="req-2",
            agent="agent-b",
            tenant="tenant-1",
            action="local_ai_repo",
            status_code=200,
            duration_ms=12.5,
            success=True,
        )
        telemetry.flush(timeout=0.5)

        timeline = telemetry.get_timeline(limit=10)
        assert len(timeline) >= 2
        actions = [item["action"] for item in timeline]
        assert "local_ai_command" in actions
        assert "local_ai_repo" in actions
        assert timeline[0]["timestamp"] > 0
    finally:
        telemetry.close()
