from pathlib import Path

from local_ai_hub.telemetry import TelemetryStore


def _store_without_writer(tmp_path: Path) -> TelemetryStore:
    store = TelemetryStore(tmp_path / "telemetry", enabled=False, queue_size=100)
    store.enabled = True
    return store


def test_overflow_is_rejected_without_counting_as_accepted(tmp_path: Path) -> None:
    store = _store_without_writer(tmp_path)
    for index in range(100):
        assert store._enqueue("test", {"index": index}) is True
    assert store._enqueue("test", {"index": 100}) is False

    writer = store._writer_snapshot()

    assert writer["attempted"] == 101
    assert writer["accepted"] == writer["queued"] == 100
    assert writer["rejected_overflow"] == 1
    assert writer["lost_after_acceptance"] == 0
    assert writer["pending"] == 100
    assert writer["accounting_balanced"] is True
    assert writer["scope"] == "current_process"


def test_writer_abandonment_is_separate_from_enqueue_rejection(tmp_path: Path) -> None:
    store = _store_without_writer(tmp_path)
    for index in range(3):
        assert store._enqueue("test", {"index": index}) is True

    store._queue.get_nowait()
    store._queue.get_nowait()
    store._record_writer_abandonment(2)
    writer = store._writer_snapshot()

    assert writer["accepted"] == 3
    assert writer["processed"] == 2
    assert writer["lost_after_acceptance"] == writer["dropped"] == 2
    assert writer["pending"] == 1
    assert writer["rejected_overflow"] == 0
    assert writer["writer_errors_unit"].startswith("caught writer exception attempts")
    assert writer["accounting_balanced"] is True


def test_zero_attempts_have_null_rates_and_unobserved_activity(tmp_path: Path) -> None:
    writer = _store_without_writer(tmp_path)._writer_snapshot()

    assert writer["attempted"] == 0
    assert writer["activity_observed"] is False
    assert writer["accepted_rate"] is None
    assert writer["overflow_rejection_rate"] is None
    assert writer["post_acceptance_loss_rate"] is None
    assert writer["interval_seconds"] >= 0
    assert writer["process_started_at"] <= writer["snapshot_end_at"]
    detail = _store_without_writer(tmp_path / "detail")._detail_status(
        truncated=False, flush_complete=True, writer=writer
    )
    assert detail["status"] == "incomplete"
    assert "writer_activity_unobserved" in detail["omitted_sections"]


def test_cached_summary_refreshes_writer_and_marks_new_rejection_incomplete(tmp_path: Path) -> None:
    store = _store_without_writer(tmp_path)
    with store._stats_lock:
        store._stats.update(attempted=1, accepted=1, queued=1, processed=1, written=1)
    previous = store._writer_snapshot()
    data = {
        "detail": store._detail_status(truncated=False, flush_complete=True, writer=previous),
        "decision_grade": {"detail": {}},
    }
    for index in range(100):
        store._queue.put_nowait(("test", {"index": index}))
    assert store._enqueue("test", {"overflow": True}) is False

    refreshed = store._refresh_cached_writer_status(data, previous)

    assert refreshed["writer"]["rejected_overflow"] == 1
    assert refreshed["summary_cache_stale"] is True
    assert refreshed["detail"]["status"] == "incomplete"
    assert "cached_summary_data" in refreshed["detail"]["omitted_sections"]
    assert refreshed["decision_grade"]["detail"] == refreshed["detail"]
