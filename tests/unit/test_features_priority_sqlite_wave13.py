from __future__ import annotations

import sqlite3
import pytest

from local_ai_hub.features import FeatureSet, rollout_feature_enabled
from local_ai_hub.priority_gate import CooperativePriorityGate
from local_ai_hub.sqlite_support import connect_sqlite
from local_ai_hub.sqlite_counts import (
    global_row_counts,
    get_table_count,
    is_row_counts_initialized,
)


def test_feature_set_malformed_config() -> None:
    # FeatureSet with None in sub-tables should not raise AttributeError
    fs = FeatureSet({"features": None, "server": None, "models": None, "commands": None, "artifacts": None})
    assert fs.status is True
    assert fs.repo is True
    assert fs.fast_model != ""

    # rollout_feature_enabled with None config
    assert rollout_feature_enabled(None, "batch_replacement") is False  # type: ignore[arg-type]


def test_priority_gate_bool_and_timeout() -> None:
    with pytest.raises(ValueError):
        CooperativePriorityGate(True)
    gate = CooperativePriorityGate(3)
    with pytest.raises(ValueError):
        gate.try_acquire(priority=False)
    with pytest.raises(ValueError):
        with gate.slot(priority=True, timeout=True):
            pytest.fail("invalid priority acquired gate")
    assert gate.try_acquire(priority=3) is True
    assert gate.is_active is True
    gate.release()
    with gate.slot(priority=3, timeout=1.0):
        assert gate.is_active is True
    assert gate.is_active is False


def test_sqlite_support_connect_hardening() -> None:
    # Null byte path rejected cleanly
    with pytest.raises((ValueError, sqlite3.OperationalError)):
        connect_sqlite("bad\0db.sqlite")

    # NaN and bool timeout handling
    con1 = connect_sqlite(":memory:", timeout_seconds=float("nan"))
    con1.close()

    con2 = connect_sqlite(":memory:", timeout_seconds=True)  # type: ignore[arg-type]
    con2.close()


def test_sqlite_counts_hardening() -> None:
    # Closed connection should not raise unhandled ProgrammingError
    con = sqlite3.connect(":memory:")
    con.close()

    with pytest.raises(sqlite3.DatabaseError):
        global_row_counts(con, ("test",))

    assert get_table_count(con, "test") is None
    assert is_row_counts_initialized(con, ("test",)) is False
