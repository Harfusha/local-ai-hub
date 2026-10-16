from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import pytest

from local_ai_hub.adoption_metrics import (
    AdoptionMetricsStore,
    _duration_bucket,
    _output_bucket,
)


def test_duration_and_output_bucket_nan_inf_and_invalid_handling() -> None:
    # NaN, Inf, non-numeric strings must not raise ValueError or OverflowError
    assert _duration_bucket(float("nan")) is None
    assert _duration_bucket(float("inf")) is None
    assert _duration_bucket(float("-inf")) is None
    assert _duration_bucket("invalid") is None  # type: ignore[arg-type]

    assert _output_bucket(float("nan")) is None
    assert _output_bucket(float("inf")) is None
    assert _output_bucket(float("-inf")) is None
    assert _output_bucket("invalid") is None  # type: ignore[arg-type]


def test_record_with_nan_and_inf_metrics(tmp_path: Path) -> None:
    store = AdoptionMetricsStore(tmp_path)
    now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)

    # Must not raise when recording nan/inf durations or sizes
    store.record(
        "local_ai_repo",
        "search",
        "repository",
        "used",
        duration_ms=float("nan"),
        output_size=float("inf"),  # type: ignore[arg-type]
        now=now,
    )
    report = store.report(days=1, now=now)
    assert report["totals"]["used"] == 1


def test_report_resilient_to_unexpected_day_and_outcome(tmp_path: Path) -> None:
    store = AdoptionMetricsStore(tmp_path)
    now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)

    # Insert a future day and unknown outcome directly into DB
    with closing(store._connect()) as con:
        con.execute(
            "INSERT INTO daily_adoption(day, tool, action, intent, outcome, reason, latency_bucket, output_bucket, count) "
            "VALUES ('2026-09-25', 'local_ai_repo', 'search', 'repository', 'custom_outcome', '', '', '', 2)"
        )
        con.commit()

    # report() must not raise KeyError: '2026-09-25' or KeyError: 'custom_outcome'
    rep = store.report(days=7, now=now)
    assert isinstance(rep, dict)
    assert "daily" in rep


def test_state_dir_validation() -> None:
    with pytest.raises(ValueError, match="state_dir cannot be blank"):
        AdoptionMetricsStore("")

    with pytest.raises(ValueError, match="state_dir cannot be blank"):
        AdoptionMetricsStore("   ")

    with pytest.raises(ValueError, match="NUL character"):
        AdoptionMetricsStore("/tmp\x00/state")


def test_report_rejects_invalid_days_and_clamps_negative_days(tmp_path: Path) -> None:
    store = AdoptionMetricsStore(tmp_path)
    now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="days must be an integer"):
        store.report(days="invalid", now=now)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="days must be an integer"):
        store.report(days=True, now=now)  # type: ignore[arg-type]

    r2 = store.report(days=-10, now=now)
    assert r2["days"] == 1
