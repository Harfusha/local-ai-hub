"""Test isolated worker subprocess execution for Tree-sitter on Windows Python 3.13."""
import sys
from concurrent.futures.process import BrokenProcessPool
from unittest.mock import MagicMock

import pytest
from local_ai_hub import treesitter_parser as module


def test_treesitter_worker_isolated_execution():
    """Verify tree-sitter runs via isolated worker without crashing main process."""
    source = "def example_func(x: int) -> int:\n    return x + 1\n"
    # When worker is invoked, it should return parsed symbols
    result = module._worker_parse(source, "python")
    assert result["status"] == "ok"
    assert result["result"] is not None
    symbols, references, _ = result["result"]
    assert any(sym["name"] == "example_func" for sym in symbols)


def test_treesitter_isolated_worker_handles_crash_gracefully(monkeypatch):
    """If the worker subprocess crashes (e.g. access violation / BrokenProcessPool),

    parse_treesitter_with_status must catch the error, keep main process alive,
    and return a graceful fallback status.
    """
    mock_pool = MagicMock()
    mock_future = MagicMock()
    mock_future.result.side_effect = BrokenProcessPool("Worker process terminated abruptly with access violation")
    mock_pool.submit.return_value = mock_future

    monkeypatch.setattr(module, "_get_worker_pool", lambda: mock_pool)
    monkeypatch.setattr(module, "_use_isolated_worker", lambda: True)

    result = module.parse_treesitter_with_status("def crash(): pass", "python")
    assert result["result"] is None
    assert result["status"] in ("failed", "unavailable")
    assert result["fallback_reason"] in ("worker_crash", "worker_error")


def test_treesitter_isolated_worker_handles_timeout_gracefully(monkeypatch):
    """If the worker subprocess hangs/times out, parse_treesitter_with_status

    must return graceful fallback within timeout bounds.
    """
    mock_pool = MagicMock()
    mock_future = MagicMock()
    mock_future.result.side_effect = TimeoutError("Tree-sitter parse job timed out")
    mock_pool.submit.return_value = mock_future

    monkeypatch.setattr(module, "_get_worker_pool", lambda: mock_pool)
    monkeypatch.setattr(module, "_use_isolated_worker", lambda: True)

    result = module.parse_treesitter_with_status("def hang(): pass", "python")
    assert result["result"] is None
    assert result["status"] in ("failed", "unavailable")
    assert result["fallback_reason"] in ("worker_timeout", "worker_error")
