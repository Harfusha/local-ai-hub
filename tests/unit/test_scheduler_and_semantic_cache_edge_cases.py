from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
import pytest

from local_ai_hub.scheduler import AffinityScheduler, Job
from local_ai_hub.semantic_cache import SemanticGenerationCache


class _StubEmbeddings:
    def __init__(self, dim: int = 4):
        self.dim = dim

    def encode(self, texts, **kwargs):
        return {
            "success": True,
            "embeddings": [[float(i + 1) for i in range(self.dim)] for _ in texts],
        }


def test_scheduler_init_and_submit_edge_cases():
    config = {
        "scheduler": {
            "max_parallel": float("nan"),
            "max_queue": float("inf"),
            "max_queued_per_tenant": True,
            "affinity_batch_seconds": float("nan"),
            "max_caller_wait_timeout_seconds": float("inf"),
        },
        "preprocessing": {
            "idle_grace_seconds": float("nan"),
        },
        "server": {
            "request_timeout_seconds": 10,
        },
    }
    runtime = SimpleNamespace(
        loaded_model_details=lambda: [],
        prepare_model=lambda *args, **kwargs: [],
    )
    scheduler = AffinityScheduler(runtime, config)
    try:
        assert scheduler.is_running() is True
        assert scheduler.active_model() is None
        assert scheduler.pending_count() == 0
        assert scheduler.inflight_count() == 0

        for bad in ({"tenant": None}, {"tenant": " tenant "}, {"priority": float("nan")}, {"wait_timeout": float("nan")}):
            args = dict(model="m1", tenant="tenant", source="test", execute=lambda: {"success": True})
            args.update(bad)
            with pytest.raises(ValueError):
                scheduler.submit(**args)
        res = scheduler.submit("m1", "tenant", "test", lambda: {"success": True}, wait_timeout=2.0)
        assert res["success"] is True

        # Invalid model with null byte
        with pytest.raises(ValueError, match="invalid_model"):
            scheduler.submit(
                model="bad\x00model",
                tenant="default",
                source="test",
                execute=lambda: {"success": True},
            )
    finally:
        scheduler.close()
        assert scheduler.is_running() is False


def test_semantic_cache_init_and_math_edge_cases(tmp_path: Path):
    config = {
        "server": {"state_dir": str(tmp_path)},
        "semantic_cache": {
            "threshold": float("nan"),
            "ttl_seconds": float("inf"),
            "max_entries": True,
            "min_query_chars": -5,
        },
    }
    embeddings = _StubEmbeddings(dim=4)
    cache = SemanticGenerationCache(config, embeddings)

    assert cache.is_enabled() is True
    assert cache.entry_count() == 0

    # Invalid provider vectors reject before cache writes; no legacy cosine API.
    for vector in ([1.0, float("nan")], [1.0, float("inf")], [], [True, 1.0]):
        cache.embeddings = SimpleNamespace(encode=lambda *args, vector=vector, **kwargs: {"success": True, "embeddings": [vector]})
        cache.set("bad-vector", "query with invalid vector", {"res": "bad"})
        assert cache.entry_count() == 0
    cache.embeddings = embeddings

    # Normal get/set
    cache.set("scope_1", "test query hello", {"res": "ok"})
    assert cache.entry_count() == 1

    # Scope with null byte
    val, sim = cache.get("scope\x00bad", "test query hello")
    assert val is None
    assert sim == 0.0

    # Set non-dict value
    cache.set("scope_1", "another query", "non-dict-val")  # type: ignore
    assert cache.entry_count() == 1

    # Clear
    cleared = cache.clear()
    assert cleared >= 1
    assert cache.entry_count() == 0
