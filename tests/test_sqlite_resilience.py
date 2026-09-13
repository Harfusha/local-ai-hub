from __future__ import annotations

import os
import sqlite3
import time
from unittest.mock import MagicMock

import pytest

from local_ai_hub.sqlite_support import is_busy_error, retry_busy
from local_ai_hub.process_utils import (
    assign_process_to_job,
    close_job_object,
    create_sandboxed_job_object,
)
from local_ai_hub.vram_balancer import VRAMBalancer


def test_is_busy_error() -> None:
    assert is_busy_error(sqlite3.OperationalError("database is locked"))
    assert is_busy_error(sqlite3.OperationalError("database table is locked: foo"))
    assert is_busy_error(sqlite3.OperationalError("resource busy"))
    assert not is_busy_error(sqlite3.OperationalError("no such table: foo"))
    assert not is_busy_error(ValueError("busy"))


def test_retry_busy_success_after_lock() -> None:
    calls = 0

    def flaky_operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise sqlite3.OperationalError("database is locked")
        return "success"

    result = retry_busy(flaky_operation, retries=5, base_delay_seconds=0.001, jitter=True)
    assert result == "success"
    assert calls == 3


def test_retry_busy_raises_when_retries_exhausted() -> None:
    calls = 0

    def always_locked() -> None:
        nonlocal calls
        calls += 1
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        retry_busy(always_locked, retries=3, base_delay_seconds=0.001)

    assert calls == 3


def test_retry_busy_does_not_retry_unrelated_errors() -> None:
    calls = 0

    def fatal_syntax_error() -> None:
        nonlocal calls
        calls += 1
        raise sqlite3.OperationalError("syntax error near WHERE")

    with pytest.raises(sqlite3.OperationalError, match="syntax error"):
        retry_busy(fatal_syntax_error, retries=5, base_delay_seconds=0.001)

    assert calls == 1


def test_vram_model_pinning() -> None:
    balancer = VRAMBalancer()
    assert balancer.get_pinned_model() is None

    res = balancer.pin_model("qwen2.5-coder:7b", ttl_seconds=2.0)
    assert res["pinned"] is True
    assert res["model"] == "qwen2.5-coder:7b"
    assert balancer.get_pinned_model() == "qwen2.5-coder:7b"

    st = balancer.status(force=True)
    assert st["pinned_model"] is not None
    assert st["pinned_model"]["model"] == "qwen2.5-coder:7b"
    assert st["pinned_model"]["ttl_remaining_seconds"] > 0

    balancer.unpin_model()
    assert balancer.get_pinned_model() is None
    st2 = balancer.status(force=True)
    assert st2["pinned_model"] is None


def test_vram_model_pinning_expiry() -> None:
    balancer = VRAMBalancer()
    balancer.pin_model("qwen2.5-coder:7b", ttl_seconds=0.05)
    assert balancer.get_pinned_model() == "qwen2.5-coder:7b"
    time.sleep(0.06)
    assert balancer.get_pinned_model() is None


def test_job_object_lifecycle() -> None:
    if os.name != "nt":
        pytest.skip("Windows Job Object tests require Windows")

    job = create_sandboxed_job_object(memory_limit_mb=512, kill_on_close=True)
    assert job is not None
    try:
        import subprocess
        proc = subprocess.Popen(["python", "-c", "import time; time.sleep(5)"])
        try:
            ok = assign_process_to_job(job, proc.pid)
            assert isinstance(ok, bool)
        finally:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
    finally:
        close_job_object(job)
