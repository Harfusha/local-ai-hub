import threading
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore
from local_ai_hub.scheduler import AffinityScheduler


def _scheduler(store):
    scheduler = AffinityScheduler.__new__(AffinityScheduler)
    scheduler._external_gpu_store = store
    scheduler._cond = threading.Condition()
    scheduler._internal_gpu_digest = None
    scheduler._internal_gpu_uncertain = False
    return scheduler


def test_status_does_not_mix_absent_record_with_a_new_owner(tmp_path, monkeypatch):
    store = ExternalGpuReservationStore(tmp_path / 'gpu')
    old_read = store.read

    def interleaved_read():
        record = old_read()
        assert record is None
        store.reserve('a' * 64, owner_vram_budget_bytes=16 * 1024**3, owner='new-owner')
        return record

    monkeypatch.setattr(store, 'read', interleaved_read)
    result = _scheduler(store).gpu_reservation_operation(action='status')
    assert result['state'] in {'free', 'active', 'idle'}
    assert result.get('manual_intervention_required') is not True


def test_status_keeps_malformed_reservation_fail_closed(tmp_path):
    store = ExternalGpuReservationStore(tmp_path / 'gpu')
    store.path.write_text('invalid', encoding='utf-8')
    result = _scheduler(store).gpu_reservation_operation(action='status')
    assert result['state'] == 'unknown'
    assert result['reservation_present'] is True
    assert result['manual_intervention_required'] is True
    assert result['reason_code'] == 'reservation_fence_unreadable'
    assert store.path.read_text(encoding='utf-8') == 'invalid'


def test_status_explains_valid_legacy_fence_without_releasing_it(tmp_path):
    store = ExternalGpuReservationStore(tmp_path / 'gpu')
    digest = 'd' * 64
    store.path.write_text(digest, encoding='ascii')

    result = _scheduler(store).gpu_reservation_operation(action='status')

    assert result['state'] == 'unknown'
    assert result['reason_code'] == 'legacy_digest_only_fence'
    assert store.path.read_text(encoding='ascii') == digest


def test_status_reports_when_it_reaps_an_expired_reservation(tmp_path):
    now = [1000.0]
    store = ExternalGpuReservationStore(
        tmp_path / 'gpu', ttl_seconds=1, clock=lambda: now[0]
    )
    store.reserve('e' * 64, owner_vram_budget_bytes=16 * 1024**3, owner='expired-owner')
    now[0] += 2

    result = _scheduler(store).gpu_reservation_operation(action='status')

    assert result['state'] == 'free'
    assert result['reaped'] is True
    assert not store.path.exists()


def test_status_snapshot_and_competing_reservation_are_serialized(tmp_path, monkeypatch):
    store = ExternalGpuReservationStore(tmp_path / 'gpu')
    scheduler = _scheduler(store)
    reading, attempted, allow_read = threading.Event(), threading.Event(), threading.Event()
    old_read = store._read_unlocked

    def held_read():
        reading.set()
        assert allow_read.wait(5)
        return old_read()

    monkeypatch.setattr(store, 'reap_expired', lambda: False)
    monkeypatch.setattr(store, '_read_unlocked', held_read)
    with ThreadPoolExecutor(max_workers=2) as pool:
        status_future = pool.submit(scheduler.gpu_reservation_operation, action='status')
        assert reading.wait(5)

        def reserve():
            attempted.set()
            return store.reserve('b' * 64, owner_vram_budget_bytes=16 * 1024**3, owner='new-owner')

        reserve_future = pool.submit(reserve)
        assert attempted.wait(5)
        allow_read.set()
        status = status_future.result(timeout=5)
        reservation = reserve_future.result(timeout=5)

    assert status['state'] == 'free' and status['reservation_present'] is False
    assert reservation['owner'] == 'new-owner'


def test_scheduler_gpu_check_reads_store_under_one_cross_process_lock(tmp_path, monkeypatch):
    store = ExternalGpuReservationStore(tmp_path / 'gpu')
    store.reserve('c' * 64, owner_vram_budget_bytes=16 * 1024**3, owner='another-scheduler')
    scheduler = _scheduler(store)
    scheduler._external_gpu_path = store.path

    lock_count = 0
    original_locked = store._locked

    @contextmanager
    def counted_locked():
        nonlocal lock_count
        lock_count += 1
        with original_locked():
            yield

    monkeypatch.setattr(store, '_locked', counted_locked)

    assert scheduler._external_gpu_reserved() is True
    assert lock_count == 1
