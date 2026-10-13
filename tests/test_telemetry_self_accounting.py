import queue
import threading

from local_ai_hub.telemetry import TelemetryStore


def test_system_event_reports_whether_telemetry_queue_accepts_it(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry", enabled=True, flush_interval_seconds=0.01)
    try:
        assert store.record_system("admin.maintenance.optimize_db", success=True) is True
        assert store.flush(10) is True
    finally:
        store.close()

    disabled = TelemetryStore(tmp_path / "disabled", enabled=False)
    assert disabled.record_system("admin.maintenance.optimize_db", success=True) is False


def test_telemetry_instrumentation_is_not_recorded_as_user_tool_workload():
    store = object.__new__(TelemetryStore)
    recorded = []
    store.record = lambda **event: (recorded.append(event), True)[1]

    assert store.record_tool_accounting(
        {
            "tool": "local_ai_telemetry",
            "agent_tool_request_tokens_est": 120,
            "agent_tool_response_tokens_est": 240,
            "gross_cloud_tokens_avoided_est": 80,
        }
    ) is False
    assert store.record_tool_accounting(
        {
            "tool": "get_telemetry",
            "agent_tool_request_tokens_est": 12,
            "agent_tool_response_tokens_est": 24,
        }
    ) is True

    assert len(recorded) == 1
    assert recorded[0]["action"] == "get_telemetry"
    assert recorded[0]["tool_calls"] == 1


def test_queue_full_does_not_publish_rejected_event_to_live_feed():
    store = object.__new__(TelemetryStore)
    store.enabled = True
    store._queue = queue.Queue(maxsize=1)
    store._queue.put_nowait(("occupied", {}))
    store._stats_lock = threading.Lock()
    store._stats = {"queued": 0, "processed": 0, "written": 0, "dropped": 0, "writer_errors": 0, "batches": 0}
    store._live_lock = threading.Lock()
    store._live_events = []
    store._live_seq = 0

    assert store._enqueue("http", {"action": "/api/test", "success": True}) is False
    assert store.live()["events"] == []


def test_concurrent_queue_acceptance_keeps_live_feed_in_queue_order():
    store = object.__new__(TelemetryStore)
    store.enabled = True
    store._queue = queue.Queue()
    store._stats_lock = threading.Lock()
    store._stats = {"queued": 0, "processed": 0, "written": 0, "dropped": 0, "writer_errors": 0, "batches": 0}
    store._live_lock = threading.Lock()
    store._live_events = []
    store._live_seq = 0
    first_publish_entered = threading.Event()
    second_publish_entered = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    publish = store._publish_live

    def delayed_publish(kind, payload):
        if payload["action"] == "event-1":
            first_publish_entered.set()
            assert release_first.wait(1.0)
        publish(kind, payload)
        if payload["action"] == "event-2":
            second_publish_entered.set()

    store._publish_live = delayed_publish
    outcomes = []
    first = threading.Thread(target=lambda: outcomes.append(store._enqueue("http", {"action": "event-1"})))
    second = threading.Thread(target=lambda: (second_started.set(), outcomes.append(store._enqueue("http", {"action": "event-2"}))))

    first.start()
    assert first_publish_entered.wait(1.0)
    second.start()
    assert second_started.wait(1.0)
    second_published_early = second_publish_entered.wait(0.05)
    release_first.set()
    first.join(1.0)
    second.join(1.0)

    queued_actions = [store._queue.get_nowait()[1]["action"] for _ in range(store._queue.qsize())]
    live_actions = [event["action"] for event in store.live()["events"]]
    assert not first.is_alive() and not second.is_alive()
    assert second_published_early is False
    assert outcomes == [True, True]
    assert queued_actions == ["event-1", "event-2"]
    assert live_actions == queued_actions
