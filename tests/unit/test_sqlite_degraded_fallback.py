import sqlite3
import pytest
from unittest.mock import MagicMock
from local_ai_hub.sqlite_support import retry_busy, with_degraded_fallback, connect_sqlite

def test_retry_busy_raises_on_persistent_lock_when_fallback_disabled():
    counter = {"calls": 0}
    def failing_op():
        counter["calls"] += 1
        raise sqlite3.OperationalError("database is locked")
    
    with pytest.raises(sqlite3.OperationalError):
        retry_busy(failing_op, retries=2, base_delay_seconds=0.001)
    assert counter["calls"] == 2

def test_retry_busy_returns_degraded_dict_when_fallback_enabled():
    counter = {"calls": 0}
    def failing_op():
        counter["calls"] += 1
        raise sqlite3.OperationalError("database is locked")
    
    result = retry_busy(failing_op, retries=3, base_delay_seconds=0.001, fallback_degraded=True)
    assert counter["calls"] == 3
    assert result == {
        "success": False,
        "degraded": True,
        "error": "database_locked",
        "error_code": "database_locked",
    }

def test_retry_busy_returns_custom_degraded_value():
    def failing_op():
        raise sqlite3.OperationalError("database table is busy")
    
    custom_fallback = {"items": [], "cached": True, "degraded": True}
    result = retry_busy(
        failing_op,
        retries=2,
        base_delay_seconds=0.001,
        fallback_degraded=True,
        degraded_value=custom_fallback,
    )
    assert result == custom_fallback

def test_with_degraded_fallback_convenience_function():
    def failing_op():
        raise sqlite3.OperationalError("database is locked")
    
    res = with_degraded_fallback(failing_op, retries=2, base_delay_seconds=0.001)
    assert res["success"] is False
    assert res["degraded"] is True
    assert res["error"] == "database_locked"

def test_with_degraded_fallback_succeeds_when_operation_succeeds():
    assert with_degraded_fallback(lambda: {"data": 42}) == {"data": 42}
