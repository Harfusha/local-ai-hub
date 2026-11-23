import pytest
from src.local_ai_hub.laya_crosslingual_reranker import (
    LayaCrossLingualReranker,
    DocumentCandidate,
)


def test_crosslingual_query_expansion():
    reranker = LayaCrossLingualReranker()

    # Pure Czech query
    res_cs = reranker.expand_query("Kde je sdílená paměť a správa paměti?")
    assert res_cs.detected_language == "cs"
    assert "ipc" in res_cs.expanded_terms or "shm" in res_cs.expanded_terms
    assert "buffer" in res_cs.expanded_terms or "allocation" in res_cs.expanded_terms
    assert "memory" in res_cs.composite_query

    # English query
    res_en = reranker.expand_query("Where is the connection pool?")
    assert res_en.detected_language == "en"


def test_crosslingual_reranking():
    reranker = LayaCrossLingualReranker()

    candidates = [
        DocumentCandidate(
            doc_id="doc_ui",
            path="src/ui/dashboard.py",
            text="Interactive React dashboard components and charts rendering",
        ),
        DocumentCandidate(
            doc_id="doc_ipc",
            path="src/local_ai_hub/shared_memory_ipc.py",
            text="Windows kernel zero-copy shared memory buffer and IPC channels",
        ),
        DocumentCandidate(
            doc_id="doc_db",
            path="src/local_ai_hub/sqlite_fts_cdc.py",
            text="SQLite FTS5 full-text search change data capture tables",
        ),
    ]

    # Czech query: "Najdi sdílená paměť v systému"
    ranked = reranker.rerank("Najdi sdílená paměť v systému", candidates)

    assert len(ranked) == 3
    # doc_ipc should rank first due to cross-lingual expansion: sdílená -> shared, paměť -> memory
    assert ranked[0].doc_id == "doc_ipc"
    assert ranked[0].score > ranked[1].score
    assert "shared" in ranked[0].matched_terms or "memory" in ranked[0].matched_terms
