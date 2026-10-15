"""Test isolated worker subprocess execution for Tree-sitter on Windows Python 3.13."""
import sys
import threading
from concurrent.futures.process import BrokenProcessPool
from unittest.mock import MagicMock

import pytest
from local_ai_hub import treesitter_parser as module


@pytest.fixture(autouse=True)
def reset_worker_circuit_breaker(monkeypatch):
    monkeypatch.setattr(module, "_WORKER_DISABLED_CAUSE", None)
    monkeypatch.setattr(module, "_WORKER_POOL", None)


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


def test_worker_crash_disables_all_later_submissions(monkeypatch):
    mock_pool = MagicMock()
    mock_future = MagicMock()
    mock_future.result.side_effect = BrokenProcessPool("worker exited")
    mock_pool.submit.return_value = mock_future
    monkeypatch.setattr(module, "_get_worker_pool", lambda: mock_pool)
    monkeypatch.setattr(module, "_use_isolated_worker", lambda: True)

    first = module.parse_treesitter_with_status("def first(): pass", "python")
    later = module.parse_treesitter_with_status("def later(): pass", "python")

    assert first["fallback_reason"] == "worker_crash"
    assert later["fallback_reason"] == "worker_disabled"
    assert later["worker_disabled_cause"].startswith("worker_crash:")
    assert mock_pool.submit.call_count == 1


def test_cleanup_failure_does_not_reenable_worker(monkeypatch):
    mock_pool = MagicMock()
    mock_future = MagicMock()
    mock_future.result.side_effect = TimeoutError("worker stalled")
    mock_pool.submit.return_value = mock_future
    monkeypatch.setattr(module, "_get_worker_pool", lambda: mock_pool)
    monkeypatch.setattr(module, "_reset_worker_pool", lambda: False)
    monkeypatch.setattr(module, "_use_isolated_worker", lambda: True)

    first = module.parse_treesitter_with_status("def first(): pass", "python")
    later = module.parse_treesitter_with_status("def later(): pass", "python")

    assert first["fallback_reason"] == "worker_timeout"
    assert first["worker_cleanup_confirmed"] is False
    assert later["fallback_reason"] == "worker_disabled"
    assert mock_pool.submit.call_count == 1


@pytest.mark.parametrize(
    "worker_outcome",
    [ValueError("worker result failed"), {"result": None, "status": "failed", "fallback_reason": "worker_error", "error_type": "ValueError"}],
)
def test_worker_execution_error_trips_process_lifetime_breaker(monkeypatch, worker_outcome):
    mock_pool = MagicMock()
    mock_future = MagicMock()
    if isinstance(worker_outcome, Exception):
        mock_future.result.side_effect = worker_outcome
    else:
        mock_future.result.return_value = worker_outcome
    mock_pool.submit.return_value = mock_future
    monkeypatch.setattr(module, "_get_worker_pool", lambda: mock_pool)
    monkeypatch.setattr(module, "_use_isolated_worker", lambda: True)

    first = module.parse_treesitter_with_status("def first(): pass", "python")
    later = module.parse_treesitter_with_status("def later(): pass", "python")

    assert first["fallback_reason"] == "worker_error"
    assert later["fallback_reason"] == "worker_disabled"
    assert later["worker_disabled_cause"] == "worker_error:ValueError"
    assert mock_pool.submit.call_count == 1


def test_concurrent_waiter_observes_breaker_without_recreating_pool(monkeypatch):
    mock_pool = MagicMock()
    mock_future = MagicMock()
    entered = threading.Event()
    release = threading.Event()

    def fail_after_release(timeout=None):
        entered.set()
        assert release.wait(timeout=2)
        raise BrokenProcessPool("worker exited")

    mock_future.result.side_effect = fail_after_release
    mock_pool.submit.return_value = mock_future
    monkeypatch.setattr(module, "_get_worker_pool", lambda: mock_pool)
    monkeypatch.setattr(module, "_use_isolated_worker", lambda: True)
    results = {}

    first = threading.Thread(
        target=lambda: results.setdefault("first", module.parse_treesitter_with_status("def first(): pass", "python"))
    )
    second = threading.Thread(
        target=lambda: results.setdefault("second", module.parse_treesitter_with_status("def second(): pass", "python"))
    )
    first.start()
    assert entered.wait(timeout=2)
    second.start()
    release.set()
    first.join(timeout=3)
    second.join(timeout=3)

    assert not first.is_alive()
    assert not second.is_alive()
    assert results["first"]["fallback_reason"] == "worker_crash"
    assert results["second"]["fallback_reason"] == "worker_disabled"
    assert mock_pool.submit.call_count == 1
