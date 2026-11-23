from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub import rag as rag_module
from local_ai_hub.rag import RAGStore
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.scheduler import AffinityScheduler, SchedulerCancelledError, SchedulerTimeoutError
from local_ai_hub.sqlite_support import connect_sqlite
from local_ai_hub.services import LocalAIServices


@pytest.fixture
def rag_with_many_chunks(tmp_path: Path) -> tuple[RAGStore, str]:
    db_path = str(tmp_path / "rag.db")
    config = {
        "server": {"state_dir": str(tmp_path)},
        "rag": {"db_path": db_path, "search_batch_size": 32},
        "features": {"reranker": True},
    }
    rag = RAGStore(config)
    rag._init_db()

    # Pre-populate 200 chunks with dummy float embeddings
    workspace = "deadline_ws"
    dimension = 384
    import numpy as np
    dummy_vec = np.ones(dimension, dtype=np.float32).tobytes()

    with closing(connect_sqlite(rag.db_path)) as con:
        rows = [
            (
                workspace,
                f"src/file_{i}.py",
                i,
                f"def compute_task_{i}(): return {i}",
                f"hash_{i}",
                "default_space",
                dummy_vec,
            )
            for i in range(200)
        ]
        con.executemany(
            """
            INSERT INTO chunks (workspace, path, chunk_no, text, content_hash, embedding_space, embedding)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        con.commit()

    # Mock services.embed
    class DummyEmbedServices:
        def embed(self, texts, priority=3, query=True, wait_timeout=None, cancel_event=None):
            return {
                "success": True,
                "embedding_space_id": "default_space",
                "embeddings": [np.ones(dimension, dtype=np.float32).tolist()],
            }
    rag.services = DummyEmbedServices()

    return rag, workspace


def test_rag_search_aborts_immediately_on_cancel_event(rag_with_many_chunks, monkeypatch):
    rag, ws = rag_with_many_chunks
    monkeypatch.setattr(rag.services, "embed", lambda *_args, **_kwargs: pytest.fail("cancelled search must not embed"))
    cancel_event = threading.Event()
    cancel_event.set()  # Pre-cancelled

    result = rag.search("compute_task", workspace=ws, cancel_event=cancel_event)
    assert result["success"] is True
    assert "deadline_exceeded" in result.get("fallbacks", [])


def test_cancelling_rag_owner_removes_pending_ollama_embedding(rag_with_many_chunks, monkeypatch):
    rag, workspace = rag_with_many_chunks
    cancel, queued = threading.Event(), threading.Event()
    monkeypatch.setattr(AffinityScheduler, "_dispatch_loop", lambda self: None)
    runtime = SimpleNamespace(request=lambda *_args: pytest.fail("cancelled embedding dispatched"))
    config = {"models": {"embedding_backend": "ollama", "embedding": "test-embedder"}}
    scheduler = AffinityScheduler(runtime, config)
    services = object.__new__(LocalAIServices)
    services.config, services.scheduler, services.runtime = config, scheduler, runtime
    rag.services = services
    queue_job = scheduler._queue_job_locked

    def queue_embedding(*args, **kwargs):
        job = queue_job(*args, **kwargs)
        queued.set()
        return job

    monkeypatch.setattr(scheduler, "_queue_job_locked", queue_embedding)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            deadline = time.perf_counter() + 4
            future = pool.submit(rag.search, "compute_task", workspace=workspace, deadline=deadline, cancel_event=cancel)
            assert queued.wait(2)
            cancel.set()
            result = future.result(timeout=1)
            assert result["cancelled"] is True and result["operation_not_started"] is True
            assert result["retryable"] is False and result["results"] == []
            with scheduler._cond:
                assert scheduler._pending == []
    finally:
        scheduler.close()


@pytest.mark.parametrize("outcome", ["cancelled", "timed_out"])
def test_rag_preserves_uncertain_ollama_embedding_outcome(rag_with_many_chunks, monkeypatch, outcome):
    rag, workspace = rag_with_many_chunks
    parent_cancel = threading.Event()
    job = SimpleNamespace(id=17)

    def submit(*_args, cancel_event=None, **_kwargs):
        assert cancel_event is not parent_cancel
        assert cancel_event is not None
        if outcome == "cancelled":
            parent_cancel.set()
            assert cancel_event.is_set()
            raise SchedulerCancelledError(job, "running")
        cancel_event.set()
        raise SchedulerTimeoutError(job, "running", 0.05)

    services = object.__new__(LocalAIServices)
    services.config = {"models": {"embedding_backend": "ollama"}}
    services.scheduler = SimpleNamespace(submit=submit)
    rag.services = services
    monkeypatch.setattr(rag, "_search_fts_candidates", lambda *_args, **_kwargs: pytest.fail("unresolved embedding triggered fallback"))

    result = rag.search("compute_task", workspace=workspace, cancel_event=parent_cancel)

    assert result[outcome] is True and result["outcome_unknown"] is True
    assert result["retryable"] is False and result["results"] == []
    assert result["job_id"] == 17 and result["scheduler_state"] == "running"
    assert parent_cancel.is_set() is (outcome == "cancelled")


def test_cancelled_rag_waiter_leaves_shared_search_running(rag_with_many_chunks, monkeypatch):
    rag, workspace = rag_with_many_chunks
    owner_started, release_owner, cancel = (threading.Event() for _ in range(3))
    calls = []
    monkeypatch.setattr(rag, "_embedding_space_cache_identity_known", lambda: True)

    def search(*_args, **_kwargs):
        calls.append("search")
        owner_started.set()
        assert release_owner.wait(8)
        return {"success": True, "results": []}

    monkeypatch.setattr(rag, "_search_uncached", search)
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(rag.search, "shared query", workspace=workspace)
        try:
            assert owner_started.wait(3)
            waiter = pool.submit(rag.search, "shared query", workspace=workspace, cancel_event=cancel)
            wait_until = time.monotonic() + 3
            while not rag.search_flight.coalesced_waiters and time.monotonic() < wait_until:
                time.sleep(0.01)
            assert rag.search_flight.coalesced_waiters == 1
            cancel.set()
            result = waiter.result(timeout=1)
            assert result["cancelled"] is True
            assert result["success"] is False and result["retryable"] is False
            assert result["search_cache"]["coalesced"] is True
            assert not owner.done()
        finally:
            release_owner.set()
        assert owner.result(timeout=3)["success"] is True

    assert rag.search("shared query", workspace=workspace)["search_cache"]["hit"] is True
    assert calls == ["search"]


def test_coalesced_rag_waiter_keeps_unknown_outcome_without_replay(rag_with_many_chunks, monkeypatch):
    rag, workspace = rag_with_many_chunks
    owner_started, release_owner = threading.Event(), threading.Event()
    generation = 1
    calls = []
    monkeypatch.setattr(rag, "_embedding_space_cache_identity_known", lambda: True)
    monkeypatch.setattr(rag, "_workspace_index_generation", lambda *_: generation)

    def embed(*_args, **_kwargs):
        calls.append("embed")
        owner_started.set()
        assert release_owner.wait(5)
        return {"success": False, "outcome_unknown": True, "retryable": False,
                "error": "embedding still running", "job_id": 17}

    monkeypatch.setattr(rag.services, "embed", embed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(rag.search, "shared query", workspace=workspace)
        try:
            assert owner_started.wait(3)
            waiter = pool.submit(rag.search, "shared query", workspace=workspace)
            wait_until = time.monotonic() + 3
            while not rag.search_flight.coalesced_waiters and time.monotonic() < wait_until:
                time.sleep(0.01)
            assert rag.search_flight.coalesced_waiters == 1
            generation = 2
        finally:
            release_owner.set()
        owner_result, waiter_result = owner.result(timeout=3), waiter.result(timeout=3)

    assert calls == ["embed"]
    for result in (owner_result, waiter_result):
        assert result["outcome_unknown"] is True and result["retryable"] is False
        assert result["job_id"] == 17 and "_cacheable" not in result
    assert waiter_result["search_cache"]["coalesced"] is True


@pytest.mark.parametrize("outcome", ["in_progress", "outcome_unknown", "cancelled"])
def test_rag_index_change_does_not_replay_unresolved_search(rag_with_many_chunks, monkeypatch, outcome):
    rag, workspace = rag_with_many_chunks
    generations = iter((1, 2))
    monkeypatch.setattr(rag, "_workspace_index_generation", lambda *_args: next(generations))
    monkeypatch.setattr(rag, "_embedding_space_cache_identity_known", lambda: True)
    monkeypatch.setattr(rag, "_search_uncached", lambda *_args, **_kwargs: pytest.fail("shared search must not replay"))
    monkeypatch.setattr(rag.search_flight, "get_or_compute", lambda *_args: ({"success": False, outcome: True}, False, True))

    result = rag.search("shared query", workspace=workspace)

    assert result["success"] is False and result[outcome] is True
    assert result["search_cache"]["coalesced"] is True


def test_rag_search_skips_embedding_when_deadline_exceeded(rag_with_many_chunks, monkeypatch):
    rag, ws = rag_with_many_chunks
    monkeypatch.setattr(rag.services, "embed", lambda *_args, **_kwargs: pytest.fail("expired search must not embed"))

    # Pass an expired deadline
    past_deadline = time.perf_counter() - 1.0

    result = rag.search("compute_task", workspace=ws, deadline=past_deadline)
    assert result["success"] is True
    assert "deadline_exceeded" in result.get("fallbacks", [])


def test_rag_passes_short_remaining_budget_to_embedder(rag_with_many_chunks, monkeypatch):
    rag, workspace = rag_with_many_chunks
    timeouts = []

    def embed(_texts, *, wait_timeout, **_kwargs):
        timeouts.append(wait_timeout)
        return {"success": False, "error": "synthetic backend unavailable"}

    monkeypatch.setattr(rag.services, "embed", embed)
    monkeypatch.setattr(rag_module, "time", SimpleNamespace(perf_counter=lambda: 10.0))

    rag._search_uncached("compute_task", workspace, deadline=10.01, semantic_only=True)

    assert timeouts == pytest.approx([0.01])


def test_rag_skips_lexical_fallback_when_embedding_spends_budget(rag_with_many_chunks, monkeypatch):
    rag, workspace = rag_with_many_chunks
    now = 10.0

    def embed(*_args, **_kwargs):
        nonlocal now
        now = 11.0
        return {"success": False, "error": "synthetic embedding deadline"}

    monkeypatch.setattr(rag.services, "embed", embed)
    monkeypatch.setattr(rag_module, "time", SimpleNamespace(perf_counter=lambda: now))
    monkeypatch.setattr(rag, "_search_fts_candidates", lambda *_args, **_kwargs: pytest.fail("deadline must stop FTS"))

    result = rag._search_uncached("compute_task", workspace, deadline=10.5)

    assert result["fallback"] == "deadline_exceeded"


def test_rag_token_overlap_does_not_start_after_fts_uses_deadline(rag_with_many_chunks, monkeypatch):
    rag, workspace = rag_with_many_chunks
    now = 10.0

    def fts(*_args, **_kwargs):
        nonlocal now
        now = 11.0
        return {"status": "MATCHES_EMPTY", "candidates": []}

    monkeypatch.setattr(rag_module, "time", SimpleNamespace(perf_counter=lambda: now))
    monkeypatch.setattr(rag, "_search_fts_candidates", fts)
    monkeypatch.setattr(
        rag, "_search_token_overlap",
        lambda *_args, **_kwargs: pytest.fail("expired search must not start token overlap"),
    )
    result = rag._search_uncached("compute_task", workspace, deadline=10.5, lexical_only=True)

    assert result["fallback"] == "deadline_exceeded"
    assert result["results"] == []


def test_rag_cancellation_interrupts_token_overlap_without_partial_results(rag_with_many_chunks, monkeypatch):
    rag, workspace = rag_with_many_chunks
    event = threading.Event()
    original_connect = rag._connect

    def connect():
        con = original_connect()

        def trace(statement):
            if "rag_token_hits(text)" in statement or statement.startswith(
                "SELECT path, chunk_no, text, content_hash FROM chunks WHERE"
            ):
                event.set()

        con.set_trace_callback(trace)
        return con

    monkeypatch.setattr(rag, "_connect", connect)
    monkeypatch.setattr(rag, "_search_fts_candidates", lambda *_a, **_kw: {
        "status": "MATCHES_EMPTY", "candidates": [],
    })
    result = rag._search_uncached("compute_task", workspace, cancel_event=event, lexical_only=True)

    assert event.is_set()
    assert result["fallback"] == "deadline_exceeded"
    assert result["results"] == []


@pytest.mark.parametrize("fallback", ["deadline_exceeded", "reranker_deadline_skipped"])
def test_limited_rag_result_does_not_enter_cache_after_identity_change(rag_with_many_chunks, monkeypatch, fallback):
    rag, workspace = rag_with_many_chunks
    space, calls = "unloaded", []
    monkeypatch.setattr(rag, "_embedding_space_cache_identity_known", lambda: True)
    monkeypatch.setattr(rag, "_embedding_space_id", lambda: space)
    monkeypatch.setattr(rag, "_embedding_dimension_cache_identity", lambda: {"dimension": 384})

    def search(*_args, **_kwargs):
        nonlocal space
        calls.append("search")
        space = "loaded"
        if len(calls) == 1:
            return {"success": True, "degraded": True, "fallbacks": ["fts_unavailable", fallback], "results": []}
        return {"success": True, "results": [{"path": "complete.py", "text": "complete evidence"}]}

    monkeypatch.setattr(rag, "_search_uncached", search)
    partial = rag.search("same query", workspace=workspace, deadline=time.perf_counter() + 5)
    complete = rag.search("same query", workspace=workspace)
    cached = rag.search("same query", workspace=workspace)

    assert fallback in partial["fallbacks"] and partial["degraded"] is True
    assert complete["results"][0]["path"] == "complete.py"
    assert complete["search_cache"]["hit"] is False
    assert cached["search_cache"]["hit"] is True
    assert calls == ["search", "search"]


def test_rag_search_normal_without_deadline(rag_with_many_chunks: tuple[RAGStore, str]):
    rag, ws = rag_with_many_chunks

    result = rag.search("compute_task", workspace=ws)
    assert result["success"] is True
    assert len(result["results"]) > 0
    assert "deadline_exceeded" not in result.get("fallbacks", [])


@pytest.mark.parametrize("indexed", [False, True])
def test_hybrid_context_probes_only_its_rag_workspace(rag_with_many_chunks, tmp_path, monkeypatch, indexed):
    rag, workspace = rag_with_many_chunks
    target = workspace if indexed else "missing_workspace"
    queries = []

    def search(_query, *, workspace, **_kwargs):
        queries.append(workspace)
        return {"success": True, "results": [], "fallbacks": []}

    monkeypatch.setattr(rag, "workspace_id", lambda _root: target)
    monkeypatch.setattr(rag, "list_workspaces", lambda: pytest.fail("context must not list all RAG workspaces"))
    monkeypatch.setattr(rag, "search", search)
    root = tmp_path / "source"
    root.mkdir()
    services = object.__new__(LocalAIServices)
    services.config = {"features": {"rag": True}, "search": {}}
    services.repo_tools = RepositoryTools(services.config)
    services.rag = rag
    services.learner = services.deterministic = services.code_index = services.preprocessor = None
    services.external_tools = services.evidence_store = None

    result = services._hybrid_context_uncached(str(root), "find relevant source", workspace=None,
                                               max_tokens=128, quality_first=True)

    assert result["success"] is True
    assert queries == ([workspace] if indexed else [])


def test_hybrid_context_starts_optional_backend_deadline_after_sync_preparation(tmp_path: Path):
    class SlowCodeIndex:
        def related_paths(self, root, query, *, limit):
            time.sleep(0.05)
            return []

    class CapturingRAG:
        def __init__(self):
            self.remaining_at_search = None

        def search(self, query, *, workspace, top_k, use_reranker, deadline, cancel_event):
            self.remaining_at_search = deadline - time.perf_counter()
            return {"success": True, "results": [], "fallbacks": []}

    rag = CapturingRAG()
    services = object.__new__(LocalAIServices)
    services.config = {
        "features": {"rag": True},
        "rag": {"use_reranker": False},
        "search": {
            "context_backend_timeout_seconds": 0.01,
            "context_rag_timeout_seconds": 0.01,
        },
    }
    services.rag = rag
    services.reranker = None
    services.evidence_store = None
    services.learner = None
    services.deterministic = None
    services.code_index = SlowCodeIndex()
    services.preprocessor = None
    services.external_tools = None

    result = services._hybrid_context_uncached(
        str(tmp_path),
        "find relevant source",
        workspace="test-workspace",
        max_tokens=128,
        quality_first=True,
        rag_revision="revision-1",
        rag_revision_available=True,
    )

    assert rag.remaining_at_search is not None
    assert rag.remaining_at_search > 0
    assert result["retrieval"]["backend_selection"]["preparation_ms"] >= 50
