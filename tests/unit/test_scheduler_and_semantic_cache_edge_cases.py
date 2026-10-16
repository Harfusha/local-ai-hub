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

        # Submit with NaN priority and NaN wait_timeout
        res = scheduler.submit(
            model="m1",
            tenant=None,  # type: ignore
            source="test",
            execute=lambda: {"success": True},
            priority=float("nan"),  # type: ignore
            wait_timeout=float("nan"),
        )
        assert res.get("success") is True

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

    # Math cosine edge cases: NaN, Inf, length mismatch
    assert cache._cos([1.0, float("nan")], [1.0, 2.0]) == -1.0
    assert cache._cos([1.0, float("inf")], [1.0, 2.0]) == -1.0
    assert cache._cos([], [1.0]) == -1.0
    assert cache._cos([1.0], [1.0, 2.0]) == -1.0

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
