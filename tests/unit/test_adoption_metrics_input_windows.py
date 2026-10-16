from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from local_ai_hub import adoption_metrics


@pytest.mark.parametrize(
    "value_factory",
    [
        lambda: float("nan"),
        lambda: float("inf"),
        lambda: float("-inf"),
        lambda: True,
        lambda: -1,
        lambda: "12",
        lambda: object(),
    ],
    ids=["nan", "infinity", "negative-infinity", "bool", "negative", "string", "nonnumeric"],
)
def test_metric_buckets_report_invalid_values_as_unknown(value_factory):
    value = value_factory()

    assert adoption_metrics._duration_bucket(value) is None
    assert adoption_metrics._output_bucket(value) is None


def test_metric_buckets_handle_huge_integer_without_float_conversion():
    value = 10**10000

    assert adoption_metrics._duration_bucket(value) == "2s+"
    assert adoption_metrics._output_bucket(value) == "4KiB+"


@pytest.mark.parametrize(
    ("state_dir", "error_type"),
    [
        (None, TypeError),
        ("", ValueError),
        ("   ", ValueError),
        (True, TypeError),
        (12, TypeError),
        (b"state", TypeError),
        ("bad\x00path", ValueError),
    ],
    ids=["none", "empty", "blank", "bool", "numeric", "bytes", "nul"],
)
def test_store_rejects_invalid_state_dir_before_filesystem_changes(
    state_dir, error_type, monkeypatch
):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("invalid constructor input reached filesystem or database")

    monkeypatch.setattr(Path, "mkdir", fail_if_called)
    monkeypatch.setattr(adoption_metrics, "connect_sqlite", fail_if_called)

    with pytest.raises(error_type):
        adoption_metrics.AdoptionMetricsStore(state_dir)


@pytest.mark.parametrize(
    "options",
    [{"retention_days": "invalid"}, {"max_actions": "invalid"}],
    ids=["retention-days", "max-actions"],
)
def test_store_validates_numeric_limits_before_creating_state_dir(tmp_path, options, monkeypatch):
    state_dir = tmp_path / "not-created"

    def fail_if_called(*args, **kwargs):
        raise AssertionError("invalid constructor input reached filesystem or database")

    monkeypatch.setattr(Path, "mkdir", fail_if_called)
    monkeypatch.setattr(adoption_metrics, "connect_sqlite", fail_if_called)

    with pytest.raises(TypeError):
        adoption_metrics.AdoptionMetricsStore(state_dir, **options)


def test_store_preserves_literal_spaces_in_valid_state_dir(tmp_path):
    state_dir = tmp_path / "  state directory"

    store = adoption_metrics.AdoptionMetricsStore(state_dir)

    assert store.path == state_dir / "adoption_metrics.sqlite3"
    assert state_dir.is_dir()


def test_record_prune_and_report_use_the_same_utc_day(tmp_path):
    store = adoption_metrics.AdoptionMetricsStore(tmp_path / "state", retention_days=2)
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO daily_adoption(day, tool, action, intent, outcome, reason, latency_bucket, output_bucket, count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2024-12-31", "local_ai_task", "delegate", "route", "used", "", "", "", 1),
        )
        con.commit()

    record_now = datetime(2025, 1, 2, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    store.record("local_ai_task", "delegate", "route", "used", now=record_now)

    with closing(store._connect()) as con:
        retained = con.execute(
            "SELECT count FROM daily_adoption WHERE day = ?", ("2024-12-31",)
        ).fetchone()
    report_now = datetime(2025, 1, 2, 0, 30, tzinfo=timezone(timedelta(hours=1)))
    report = store.report(days=1, now=report_now)

    assert retained == (1,)
    assert report["daily"][0]["day"] == "2025-01-01"
    assert report["daily"][0]["used"] == 1


def test_report_excludes_future_recorded_activity(tmp_path):
    store = adoption_metrics.AdoptionMetricsStore(tmp_path / "state")
    store.record(
        "local_ai_task",
        "delegate",
        "route",
        "used",
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    report = store.report(days=1, now=datetime(2025, 1, 1, tzinfo=timezone.utc))

    assert report["daily"][0]["day"] == "2025-01-01"
    assert report["daily"][0]["used"] == 0
    assert report["totals"]["used"] == 0
