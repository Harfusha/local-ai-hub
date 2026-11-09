from __future__ import annotations

import threading
import pytest

from local_ai_hub import vram_balancer


def test_status_returns_while_gpu_probe_is_blocked_and_coalesces_callers(monkeypatch):
    entered, release, finished, returned = (threading.Event() for _ in range(4))
    calls = []
    def probe():
        calls.append(1)
        entered.set()
        try:
            release.wait(3)
            return {'available': False}
        finally:
            finished.set()
    monkeypatch.setattr(vram_balancer, 'get_gpu_telemetry', probe)
    balancer = vram_balancer.VRAMBalancer()
    results = []
    def status():
        results.append(balancer.status())
        returned.set()
    caller = threading.Thread(target=status)
    caller.start()
    try:
        assert entered.wait(1)
        assert returned.wait(0.2), 'status waited for the hardware probe'
        assert results[0]['telemetry_stale'] is True
        assert results[0]['telemetry_wait_timed_out'] is False
        assert results[0]['throttle_background'] is True
        for _ in range(10):
            assert balancer.status()['telemetry_stale'] is True
        assert len(calls) == 1
    finally:
        release.set()
        caller.join(2)
        assert finished.wait(2)
        with balancer._condition:
            balancer._condition.wait_for(lambda: not balancer._sampling, timeout=2)
    assert not caller.is_alive()


def test_fresh_cached_status_does_not_start_another_probe(monkeypatch):
    calls = []
    def probe():
        calls.append(1)
        return {'available': True, 'vram_total_mb': 16384, 'vram_used_mb': 1024}
    monkeypatch.setattr(vram_balancer, 'get_gpu_telemetry', probe)
    balancer = vram_balancer.VRAMBalancer()
    fresh = balancer.status(force=True)
    assert fresh['available'] is True
    assert balancer.status() == fresh
    assert calls == [1]


def test_completed_unavailable_sample_is_not_cached_as_still_sampling(monkeypatch):
    monkeypatch.setattr(vram_balancer, 'get_gpu_telemetry', lambda: {'available': False})
    balancer = vram_balancer.VRAMBalancer()

    result = balancer.status(force=True)

    assert result['telemetry_error'] == 'sample_unavailable'
    assert result['telemetry_sampling'] is False
    assert result['telemetry_active_probes'] == 0


def test_nonblocking_status_reports_a_sampler_that_exceeded_its_wait_budget(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def probe():
        entered.set()
        release.wait(2)
        return {'available': False}

    monkeypatch.setattr(vram_balancer, 'get_gpu_telemetry', probe)
    balancer = vram_balancer.VRAMBalancer()
    balancer._sample_wait_timeout_seconds = 0.01
    try:
        first = balancer.status(force=True)
        assert entered.is_set()
        assert first['telemetry_error'] == 'sample_wait_timeout'
        assert first['telemetry_wait_timed_out'] is True

        pending = balancer.status()
        assert pending['telemetry_error'] == 'sample_wait_timeout'
        assert pending['telemetry_wait_timed_out'] is True
        assert pending['telemetry_sampling'] is True
    finally:
        release.set()
        with balancer._condition:
            assert balancer._condition.wait_for(lambda: not balancer._sampling, timeout=2)


def test_stalled_sampler_is_replaced_and_late_result_cannot_overwrite_fresh_sample(monkeypatch):
    first_entered, release_first, first_finished, second_finished = (
        threading.Event() for _ in range(4)
    )
    calls = []

    def probe():
        calls.append(1)
        if len(calls) == 1:
            first_entered.set()
            try:
                release_first.wait(2)
                return {'available': True, 'vram_total_mb': 8192, 'vram_used_mb': 7000}
            finally:
                first_finished.set()
        second_finished.set()
        return {'available': True, 'vram_total_mb': 16384, 'vram_used_mb': 1024}

    monkeypatch.setattr(vram_balancer, 'get_gpu_telemetry', probe)
    balancer = vram_balancer.VRAMBalancer()
    balancer._sample_wait_timeout_seconds = 0.01
    try:
        timed_out = balancer.status(force=True)
        assert first_entered.is_set()
        assert timed_out['telemetry_wait_timed_out'] is True

        retrying = balancer.status()
        assert retrying['telemetry_error'] == 'sample_wait_timeout'
        assert second_finished.wait(1)
        with balancer._condition:
            assert balancer._condition.wait_for(lambda: not balancer._sampling, timeout=1)
        fresh = balancer.status()
        assert fresh['available'] is True
        assert fresh['vram_total_mb'] == 16384

        release_first.set()
        assert first_finished.wait(1)
        assert balancer.status()['vram_total_mb'] == 16384
        assert calls == [1, 1]
    finally:
        release_first.set()


def test_stalled_sampler_retries_are_capped_at_two_workers(monkeypatch):
    release = threading.Event()
    first_entered, second_entered = threading.Event(), threading.Event()
    calls = []

    def probe():
        calls.append(1)
        (first_entered if len(calls) == 1 else second_entered).set()
        release.wait(2)
        return {'available': False}

    monkeypatch.setattr(vram_balancer, 'get_gpu_telemetry', probe)
    balancer = vram_balancer.VRAMBalancer()
    balancer._sample_wait_timeout_seconds = 0.01
    try:
        assert balancer.status(force=True)['telemetry_wait_timed_out'] is True
        assert first_entered.is_set()
        balancer.status()
        assert second_entered.wait(1)
        with balancer._condition:
            balancer._sampling_started_at = 0.0

        exhausted = balancer.status()
        assert exhausted['telemetry_error'] == 'sample_wait_timeout'
        assert exhausted['telemetry_active_probes'] == 2
        assert balancer.status()['telemetry_error'] == 'sample_wait_timeout'
        assert calls == [1, 1]
    finally:
        release.set()
        with balancer._condition:
            assert balancer._condition.wait_for(lambda: not balancer._sampling_workers, timeout=2)


@pytest.mark.parametrize('force', [False, True])
def test_sampler_start_failure_does_not_wedge_singleflight(monkeypatch, force):
    def fail_start(self):
        raise RuntimeError('thread unavailable')
    monkeypatch.setattr(threading.Thread, 'start', fail_start)
    balancer = vram_balancer.VRAMBalancer()
    result = balancer.status(force=force)
    assert result['available'] is False
    assert result['telemetry_error'] == 'sample_start_failed'
    assert result['telemetry_wait_timed_out'] is False
    assert balancer._sampling is False
