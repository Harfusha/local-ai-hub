from __future__ import annotations

import threading

from local_ai_hub.rag import RAGStore, _fragment_hash


class _Services:
    def __init__(self, block: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = block

    def embed(self, texts, _tenant, **_kwargs):
        batch = list(texts)
        self.calls.append(batch)
        self.started.set()
        if self.block:
            assert self.release.wait(2)
        return {"success": True, "embeddings": [[float(len(text)), 1.0] for text in batch]}


class _Reranker:
    pass


def _store(tmp_path, services: _Services) -> RAGStore:
    return RAGStore(
        {
            "server": {"state_dir": str(tmp_path / "state")},
            "models": {},
            "cpu_retrieval": {},
            "workspace_cache": {},
            "rag": {"extensions": [".py"], "ignore_dirs": [], "chunk_chars": 4096, "chunk_overlap_chars": 0},
            "resilience": {"singleflight_wait_timeout_seconds": 2},
        },
        services,
        _Reranker(),
    )


def test_fragment_hash_reuses_crlf_and_lf_content():
    assert _fragment_hash("def same():\r\n    return 1\r\n") == _fragment_hash("def same():\n    return 1\n")


def test_postprocess_keeps_highest_ranked_unique_evidence():
    payload = {
        "success": True,
        "results": [
            {"content_hash": "same", "text": "first"},
            {"content_hash": "same", "text": "duplicate"},
            {"content_hash": "other", "text": "second"},
            {"content_hash": "third", "text": "trimmed"},
        ],
    }

    result = RAGStore._postprocess_search_payload(payload, 2)

    assert [row["text"] for row in result["results"]] == ["first", "second"]
    assert result["deterministic_postprocess"] == {"deduplicated": 2}


def test_index_embeds_identical_fragments_once(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    source = "def same():\n    return 1\n"
    (root / "one.py").write_text(source, encoding="utf-8")
    (root / "two.py").write_text(source, encoding="utf-8")
    services = _Services()

    result = _store(tmp_path, services).index(str(root), "tenant")

    assert result["success"] is True
    assert len(services.calls) == 1
    assert [_fragment_hash(text) for text in services.calls[0]] == [_fragment_hash(source)]


def test_index_coalesces_identical_concurrent_requests(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "one.py").write_text("def same():\n    return 1\n", encoding="utf-8")
    services = _Services(block=True)
    store = _store(tmp_path, services)
    first: dict[str, object] = {}
    second: dict[str, object] = {}

    first_thread = threading.Thread(target=lambda: first.update(store.index(str(root), "tenant")))
    second_thread = threading.Thread(target=lambda: second.update(store.index(str(root), "tenant")))
    first_thread.start()
    assert services.started.wait(2)
    second_thread.start()
    services.release.set()
    first_thread.join(2)
    second_thread.join(2)

    assert first["success"] is True
    assert second["success"] is True
    assert second["coalesced"] is True
    assert len(services.calls) == 1
