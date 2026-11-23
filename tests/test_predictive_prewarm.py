"""Unit tests for JIT Predictive Context Pre-warming Engine."""

import time
from local_ai_hub.predictive_prewarm import PredictiveContextPrewarmer


def test_predictive_prewarm_lifecycle() -> None:
    prewarmer = PredictiveContextPrewarmer(system_prompt="Test System Instructions", max_slots=3)

    code = """import os
import sys

class Engine:
    def start(self):
        pass

def run():
    pass
"""
    # 1. Pre-warm on file modification event
    item = prewarmer.prewarm_for_file("src/core/engine.py", content=code)
    assert item.target_path == "src/core/engine.py"
    assert "class Engine" in item.prefix_text
    assert item.token_est > 0

    # 2. Instant context hit
    retrieved = prewarmer.get_prewarmed_context("src/core/engine.py")
    assert retrieved is not None
    assert retrieved.cache_key == item.cache_key

    # 3. Miss on unknown path
    miss = prewarmer.get_prewarmed_context("src/unknown.py")
    assert miss is None

    # Check stats
    stats = prewarmer.stats()
    assert stats["active_slots"] == 1
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 0.5


def test_predictive_prewarm_eviction() -> None:
    prewarmer = PredictiveContextPrewarmer(max_slots=2)

    prewarmer.prewarm_for_file("f1.py", "def a(): pass")
    time.sleep(0.01)
    prewarmer.prewarm_for_file("f2.py", "def b(): pass")
    time.sleep(0.01)
    prewarmer.prewarm_for_file("f3.py", "def c(): pass")

    # f1.py should be evicted
    assert prewarmer.get_prewarmed_context("f1.py") is None
    assert prewarmer.get_prewarmed_context("f2.py") is not None
    assert prewarmer.get_prewarmed_context("f3.py") is not None
