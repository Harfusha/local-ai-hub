from __future__ import annotations

import os
import time

from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore
from local_ai_hub.scheduler import AffinityScheduler


def test_unknown_internal_gpu_state_still_reaps_expired_external_reservation(tmp_path):
    reservation_path = tmp_path / "external-gpu-reservation"
    reservation_path.write_text("a" * 64, encoding="ascii")
    expired_at = time.time() - 2
    os.utime(reservation_path, (expired_at, expired_at))
    store = ExternalGpuReservationStore(reservation_path, ttl_seconds=1)

    scheduler = object.__new__(AffinityScheduler)
    scheduler._external_gpu_store = store
    scheduler._external_gpu_generation = None
    scheduler._internal_gpu_uncertain = True

    assert scheduler._external_gpu_reserved() is True
    assert not reservation_path.exists()
