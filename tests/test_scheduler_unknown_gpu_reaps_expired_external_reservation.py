from __future__ import annotations
import pytest

import os
import threading
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
    scheduler._cond = threading.Condition()
    scheduler._inflight = set()
    scheduler._switching = False
    scheduler._gpu_prepare_in_progress = False
    scheduler._background_gpu_lease = None
    scheduler._external_gpu_store = store
    scheduler._external_gpu_generation = None
    scheduler._internal_gpu_uncertain = True

    assert scheduler._external_gpu_reserved() is True
    assert not reservation_path.exists()


def test_expired_unknown_internal_state_clears_when_lease_was_already_reaped(tmp_path):
    reservation_path = tmp_path / "external-gpu-reservation"
    store = ExternalGpuReservationStore(reservation_path, ttl_seconds=1)

    scheduler = object.__new__(AffinityScheduler)
    scheduler._cond = threading.Condition()
    scheduler._inflight = set()
    scheduler._switching = False
    scheduler._gpu_prepare_in_progress = False
    scheduler._background_gpu_lease = None
    scheduler._external_gpu_store = store
    scheduler._external_gpu_path = reservation_path
    scheduler._external_gpu_generation = None
    scheduler._internal_gpu_uncertain = True
    scheduler._internal_gpu_uncertain_since = time.monotonic() - 2
    scheduler._internal_gpu_digest = "a" * 64

    assert scheduler._external_gpu_reserved() is False
    assert scheduler._internal_gpu_uncertain is False
    assert scheduler._internal_gpu_digest is None


pytestmark = pytest.mark.slow
