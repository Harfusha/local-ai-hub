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
