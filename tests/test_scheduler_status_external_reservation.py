from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore
from local_ai_hub.scheduler import AffinityScheduler


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
