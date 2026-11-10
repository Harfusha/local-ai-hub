from __future__ import annotations

import threading
import time

from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore
from local_ai_hub.scheduler import AffinityScheduler


def test_uncertain_internal_gpu_fence_expires_and_scheduler_recovers_when_idle(tmp_path):
    path = tmp_path / "external-gpu-reservation"
    store = ExternalGpuReservationStore(path, ttl_seconds=0.12)
    digest = "a" * 64
    assert store.claim_internal(digest)

    scheduler = AffinityScheduler.__new__(AffinityScheduler)
    scheduler._cond = threading.Condition()
    scheduler._internal_gpu_digest = digest
    scheduler._internal_gpu_uncertain = False
    scheduler._internal_gpu_uncertain_since = None
    scheduler._external_gpu_path = path
    scheduler._external_gpu_store = store
    scheduler._external_gpu_token = None
    scheduler._external_gpu_owned = False
    scheduler._external_gpu_generation = None
    scheduler._external_gpu_expiry_monotonic = None
    scheduler._external_gpu_operator_release_marker = None
    scheduler._inflight = 0
    scheduler._switching = False
    scheduler._gpu_prepare_in_progress = False
    scheduler._background_gpu_lease = False
    scheduler._running = True
    scheduler._start_internal_gpu_heartbeat(digest, store)
    heartbeat_stop = scheduler._internal_gpu_heartbeat_stop

    try:
        with scheduler._cond:
            scheduler._mark_internal_gpu_uncertain_locked()
        time.sleep(0.45)

        assert store.reap_expired() is True
        assert scheduler._external_gpu_reserved() is False
        assert scheduler._internal_gpu_uncertain is False
        assert scheduler._internal_gpu_digest is None
    finally:
        scheduler._running = False
        heartbeat_stop.set()
        store.release_internal(digest)
