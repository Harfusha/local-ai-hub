import multiprocessing

import pytest

from local_ai_hub.config import ConfigError, validate_config
from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore
from local_ai_hub.scheduler import AffinityScheduler


def _candidate_scheduler_gpu_state(config, result_queue):
    scheduler = AffinityScheduler(object(), config)
    try:
        snapshot = scheduler._external_gpu_store.capacity_snapshot()
        result_queue.put({
            "admission": scheduler.status()["gpu_admission_state"],
            "lease_ids": [row["lease_id"] for row in snapshot["leases"]] if isinstance(snapshot, dict) else [],
        })
    finally:
        scheduler.close()


def test_scheduler_status_tracks_external_reservation_fence(tmp_path):
    config = {"server": {"state_dir": str(tmp_path)}}
    scheduler = AffinityScheduler(object(), config)
    external_store = ExternalGpuReservationStore(tmp_path / "external-gpu-reservation")
    digest = "a" * 64
    try:
        assert scheduler.status()["gpu_admission_state"] == "available"
        assert external_store.claim_internal(digest) is True
        assert scheduler.status()["gpu_admission_state"] == "external_reservation"
    finally:
        external_store.release_internal(digest)
        scheduler.close()


def test_isolated_scheduler_can_share_hub_gpu_fence_with_separate_state(tmp_path):
    primary_state = tmp_path / "primary"
    candidate_state = tmp_path / "candidate"
    primary_state.mkdir()
    candidate_state.mkdir()
    primary = AffinityScheduler(object(), {"server": {"state_dir": str(primary_state)}})
    candidate_config = {
        "server": {"state_dir": str(candidate_state)},
        "scheduler": {
            "external_gpu_reservation_path": str(primary_state / "external-gpu-reservation"),
        },
    }
    digest = "b" * 64
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = None
    reservation = None
    lease = None
    try:
        reservation = primary._external_gpu_store.reserve(
            digest, owner="primary-test", owner_vram_budget_bytes=4 * 1024**3,
        )
        assert reservation is not None
        lease = primary._external_gpu_store.acquire_capacity_lease(
            owner="scheduler-job:test", requested_bytes=1024**3,
            total_bytes=16 * 1024**3, available_bytes=8 * 1024**3,
            expected_reservation_generation=reservation["generation"],
        )
        assert lease is not None
        process = context.Process(target=_candidate_scheduler_gpu_state, args=(candidate_config, result_queue))
        process.start()
        assert result_queue.get(timeout=15) == {
            "admission": "available", "lease_ids": [lease["lease_id"]],
        }
        process.join(timeout=15)
        assert process.exitcode == 0
    finally:
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=5)
        result_queue.close()
        if lease is not None:
            primary._external_gpu_store.release_capacity_lease(lease["lease_id"], lease["owner"], lease["generation"])
        if reservation is not None:
            primary._external_gpu_store.release(reservation["token_digest"], reservation["generation"])
        primary.close()


@pytest.mark.parametrize("path", ["relative/external-gpu-reservation", "C:/temp/wrong-name"])
def test_config_rejects_noncanonical_shared_gpu_fence_path(path):
    with pytest.raises(ConfigError, match="external_gpu_reservation_path"):
        validate_config({"scheduler": {"external_gpu_reservation_path": path}})
