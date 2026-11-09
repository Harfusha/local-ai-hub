from local_ai_hub.telemetry import _tail_latency, TelemetryStore


def test_unrecorded_queue_and_service_are_not_reported_as_measured_zero(tmp_path):
    store = TelemetryStore(tmp_path)
    try:
        store.record_http(action='/api/search', duration_ms=50, success=True)
        assert store.flush(5)
        report = store.report(days=1)
        item = next(row for row in report['http_tail_latency']['by_action'] if row['action'] == '/api/search')
        assert item['p95_duration_ms'] == 50
        assert item['p95_queue_wait_ms'] is None
        assert item['p95_service_ms'] is None
        assert item['queue_wait_measurement_complete'] is False
        assert item['service_measurement_complete'] is False
    finally:
        store.close()


def test_only_unambiguous_positive_phase_samples_support_percentiles():
    item = _tail_latency([('/api/x', 10, 1, 8, 1), ('/api/x', 20, 2, 15, 1)], 'action')[0]
    assert item['p95_queue_wait_ms'] == 2
    assert item['p95_service_ms'] == 15
    assert item['queue_wait_measurement_complete'] is True
    assert item['service_measurement_complete'] is True


def test_zero_legacy_value_prevents_claim_of_complete_phase_percentile():
    item = _tail_latency([('/api/x', 10, 0, 0, 1), ('/api/x', 20, 2, 15, 1)], 'action')[0]
    assert item['p95_queue_wait_ms'] is None
    assert item['p95_service_ms'] is None


def test_phase_completeness_is_evaluated_independently():
    item = _tail_latency([('/api/x', 10, 0, 8, 1), ('/api/x', 20, 2, 15, 1)], 'action')[0]
    assert item['p95_queue_wait_ms'] is None
    assert item['queue_wait_measurement_complete'] is False
    assert item['p95_service_ms'] == 15
    assert item['service_measurement_complete'] is True


def test_phase_ambiguity_survives_store_restart(tmp_path):
    store = TelemetryStore(tmp_path)
    store.record_http(action='/api/search', duration_ms=30, success=True, queue_wait_ms=0, service_ms=5)
    assert store.flush(5)
    store.close()
    reopened = TelemetryStore(tmp_path)
    try:
        row = next(item for item in reopened.report(days=1)['http_tail_latency']['by_action']
                   if item['action'] == '/api/search')
        assert row['p95_queue_wait_ms'] is None
        assert row['queue_wait_measurement_complete'] is False
        assert row['p95_service_ms'] == 5
        assert row['service_measurement_complete'] is True
    finally:
        reopened.close()
