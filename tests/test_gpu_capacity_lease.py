from __future__ import annotations

import hashlib
import json
import time

from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore


def _digest(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _write_legacy_reservation(store: ExternalGpuReservationStore, token_digest: str) -> None:
    now = time.time()
    store.path.write_text(token_digest, encoding="ascii")
    store.metadata_path.write_text(json.dumps({
        "schema_version": 1,
        "generation": "legacy-generation",
        "token_digest": token_digest,
        "owner": "legacy-owner",
        "state": "active",
        "created_at": now,
        "updated_at": now,
        "expires_at": now + 900,
    }), encoding="utf-8")


def test_legacy_reservation_without_budget_admits_measured_capacity(tmp_path):
    store = ExternalGpuReservationStore(tmp_path / "gpu")
    _write_legacy_reservation(store, _digest("owner"))

    assert store.read()["generation"] == "legacy-generation"
    lease = store.acquire_capacity_lease(
        owner="laya:task-1",
        requested_bytes=4 * 1024**3,
        total_bytes=16 * 1024**3,
        available_bytes=8 * 1024**3,
    )
    assert lease is not None
    assert lease["reservation_generation"] == "legacy-generation"
    assert store.read() is not None


def test_budgeted_reservation_admits_capacity_lease_without_releasing_fence(tmp_path):
    store = ExternalGpuReservationStore(tmp_path / "gpu")
    reservation = store.reserve(
        _digest("owner"), owner="external-owner", owner_vram_budget_bytes=16 * 1024**3,
    )

    lease = store.acquire_capacity_lease(
        owner="laya:task-1",
        requested_bytes=4 * 1024**3,
        total_bytes=16 * 1024**3,
        available_bytes=4 * 1024**3,
    )

    assert reservation is not None
    assert lease is not None
    assert lease["reservation_generation"] == reservation["generation"]
    assert store.read()["generation"] == reservation["generation"]
    assert not store.release(reservation["token_digest"], reservation["generation"])


def test_capacity_lease_rejects_stale_generation_and_insufficient_capacity(tmp_path):
    store = ExternalGpuReservationStore(tmp_path / "gpu")
    store.reserve(_digest("owner"), owner="external-owner", owner_vram_budget_bytes=12 * 1024**3)

    assert store.acquire_capacity_lease(
        owner="laya:task-1", requested_bytes=4 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=8 * 1024**3,
        expected_reservation_generation="stale-generation",
    ) is None
    assert store.acquire_capacity_lease(
        owner="laya:task-1", requested_bytes=4 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=3 * 1024**3,
    ) is None
    admitted = store.acquire_capacity_lease(
        owner="laya:task-1", requested_bytes=5 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=8 * 1024**3,
    )
    assert admitted is not None


def test_capacity_lease_releases_only_for_matching_owner_and_generation(tmp_path):
    store = ExternalGpuReservationStore(tmp_path / "gpu")
    store.reserve(_digest("owner"), owner="external-owner", owner_vram_budget_bytes=8 * 1024**3)
    lease = store.acquire_capacity_lease(
        owner="laya:task-1", requested_bytes=4 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=5 * 1024**3,
    )

    assert lease is not None
    assert not store.release_capacity_lease(lease["lease_id"], "other-owner", lease["generation"])
    assert not store.release_capacity_lease(lease["lease_id"], lease["owner"], "stale-generation")
    assert store.release_capacity_lease(lease["lease_id"], lease["owner"], lease["generation"])


def test_capacity_lease_release_clears_idle_embedding_reservation(tmp_path):
    store = ExternalGpuReservationStore(tmp_path / "gpu")
    reservation = store.reserve(
        _digest("embedding"), owner="embedding:123:456", owner_vram_budget_bytes=8 * 1024**3,
    )
    lease = store.acquire_capacity_lease(
        owner="hub:request", requested_bytes=2 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=8 * 1024**3,
        expected_reservation_generation=reservation["generation"],
    )
    second_lease = store.acquire_capacity_lease(
        owner="hub:second-request", requested_bytes=2 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=8 * 1024**3,
        expected_reservation_generation=reservation["generation"],
    )

    assert reservation is not None and lease is not None and second_lease is not None
    assert store.renew(reservation["token_digest"], reservation["generation"], state="idle")
    assert not store.release(reservation["token_digest"], reservation["generation"])

    assert store.release_capacity_lease(lease["lease_id"], lease["owner"], lease["generation"])
    assert store.read()["generation"] == reservation["generation"]
    assert store.capacity_snapshot()["leases"] == [second_lease]
    assert store.release_capacity_lease(
        second_lease["lease_id"], second_lease["owner"], second_lease["generation"],
    )
    assert store.read() is None


def test_capacity_lease_release_preserves_idle_external_reservation(tmp_path):
    store = ExternalGpuReservationStore(tmp_path / "gpu")
    reservation = store.reserve(
        _digest("external"), owner="external-owner", owner_vram_budget_bytes=8 * 1024**3,
    )
    lease = store.acquire_capacity_lease(
        owner="hub:request", requested_bytes=2 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=8 * 1024**3,
        expected_reservation_generation=reservation["generation"],
    )

    assert reservation is not None and lease is not None
    assert store.renew(reservation["token_digest"], reservation["generation"], state="idle")
    assert not store.release(reservation["token_digest"], reservation["generation"])

    assert store.release_capacity_lease(lease["lease_id"], lease["owner"], lease["generation"])
    assert store.read()["generation"] == reservation["generation"]
    assert store.capacity_snapshot()["leases"] == []


def test_authorized_orphaned_laya_capacity_lease_release_requires_dead_owner_and_null_reservation(
    tmp_path, monkeypatch,
):
    from local_ai_hub import process_utils

    store = ExternalGpuReservationStore(tmp_path / "gpu")
    dead = store.acquire_capacity_lease(
        owner="laya-runtime:12345:deadbeef", requested_bytes=2 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=16 * 1024**3,
    )
    active = store.acquire_capacity_lease(
        owner="laya-runtime:12346:deadbeef", requested_bytes=2 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=16 * 1024**3,
    )
    assert dead is not None and active is not None
    monkeypatch.setattr(process_utils, "process_is_alive", lambda pid: pid == 12346)

    assert not store.release_orphaned_laya_capacity_lease(
        dead["lease_id"], dead["owner"], "stale-generation",
        consent=True, audit_reason="operator approved exact stale lease",
    )
    assert not store.release_orphaned_laya_capacity_lease(
        dead["lease_id"], dead["owner"], dead["generation"],
        consent=False, audit_reason="operator approved exact stale lease",
    )
    assert store.release_orphaned_laya_capacity_lease(
        dead["lease_id"], dead["owner"], dead["generation"],
        consent=True, audit_reason="operator approved exact stale lease",
    )
    assert not store.release_orphaned_laya_capacity_lease(
        active["lease_id"], active["owner"], active["generation"],
        consent=True, audit_reason="operator approved exact stale lease",
    )
    assert [item["lease_id"] for item in store.capacity_snapshot()["leases"]] == [active["lease_id"]]
    event = json.loads(store.audit_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["action"] == "consented_capacity_lease_release_dead_laya_owner"
    assert event["lease_id"] == dead["lease_id"]
    assert event["reservation_generation"] is None


def test_orphaned_laya_release_does_not_audit_when_capacity_write_fails(tmp_path, monkeypatch):
    from local_ai_hub import process_utils

    store = ExternalGpuReservationStore(tmp_path / "gpu")
    lease = store.acquire_capacity_lease(
        owner="laya-runtime:12345:deadbeef", requested_bytes=2 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=16 * 1024**3,
    )
    assert lease is not None
    monkeypatch.setattr(process_utils, "process_is_alive", lambda _pid: False)
    monkeypatch.setattr(store, "_write_capacity_leases", lambda _payload: False)

    assert not store.release_orphaned_laya_capacity_lease(
        lease["lease_id"], lease["owner"], lease["generation"],
        consent=True, audit_reason="operator approved exact stale lease",
    )
    assert store._read_capacity_leases_unlocked()["leases"] == [lease]
    events = [
        json.loads(line) for line in store.audit_path.read_text(encoding="utf-8").splitlines()
    ] if store.audit_path.exists() else []
    assert not any(event["action"] == "consented_capacity_lease_release_dead_laya_owner" for event in events)


def test_orphaned_laya_release_rolls_back_when_audit_fails(tmp_path, monkeypatch):
    from local_ai_hub import process_utils

    store = ExternalGpuReservationStore(tmp_path / "gpu")
    lease = store.acquire_capacity_lease(
        owner="laya-runtime:12345:deadbeef", requested_bytes=2 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=16 * 1024**3,
    )
    assert lease is not None
    monkeypatch.setattr(process_utils, "process_is_alive", lambda _pid: False)

    def fail_after_capacity_change(_event):
        assert store._read_capacity_leases_unlocked()["leases"] == []
        raise OSError("audit unavailable")

    monkeypatch.setattr(store, "_append_audit", fail_after_capacity_change)

    assert not store.release_orphaned_laya_capacity_lease(
        lease["lease_id"], lease["owner"], lease["generation"],
        consent=True, audit_reason="operator approved exact stale lease",
    )
    assert store._read_capacity_leases_unlocked()["leases"] == [lease]


def test_scheduler_dispatches_exact_orphaned_laya_capacity_release(tmp_path, monkeypatch):
    from local_ai_hub import process_utils
    from local_ai_hub.scheduler import AffinityScheduler

    store = ExternalGpuReservationStore(tmp_path / "gpu")
    lease = store.acquire_capacity_lease(
        owner="laya-runtime:12345:deadbeef", requested_bytes=2 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=16 * 1024**3,
    )
    assert lease is not None
    monkeypatch.setattr(process_utils, "process_is_alive", lambda pid: False)
    scheduler = object.__new__(AffinityScheduler)
    scheduler._external_gpu_store = store

    result = scheduler.gpu_reservation_operation(
        action="release_laya_capacity_lease", lease_id=lease["lease_id"],
        owner=lease["owner"], generation=lease["generation"], consent=True,
        audit_reason="operator approved exact stale lease",
    )

    assert result["success"] and result["mutation_applied"]
    assert result["lease_id"] == lease["lease_id"]
    assert store.capacity_snapshot()["leases"] == []


def test_scheduler_capacity_release_requires_exact_prestart_job_lease(tmp_path, monkeypatch):
    store = ExternalGpuReservationStore(tmp_path / "gpu")
    created_at = time.time()
    monkeypatch.setattr(store, "_clock", lambda: created_at)
    lease = store.acquire_capacity_lease(
        owner="scheduler-job:7", requested_bytes=2 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=16 * 1024**3,
    )
    assert lease is not None

    assert store.release_orphaned_scheduler_capacity_lease(
        lease["lease_id"], lease["owner"], lease["generation"],
        created_before=created_at + 1, consent=True, audit_reason="operator approved exact stale scheduler lease",
    )
    assert store.capacity_snapshot()["leases"] == []
    event = json.loads(store.audit_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["action"] == "consented_scheduler_capacity_lease_release_no_runner"
    assert event["lease_id"] == lease["lease_id"]


def test_scheduler_capacity_release_rejects_current_or_reservation_bound_lease(tmp_path):
    store = ExternalGpuReservationStore(tmp_path / "gpu")
    created_at = time.time()
    store._clock = lambda: created_at
    reservation = store.reserve(_digest("owner"), owner="external-owner", owner_vram_budget_bytes=8 * 1024**3)
    lease = store.acquire_capacity_lease(
        owner="scheduler-job:7", requested_bytes=2 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=8 * 1024**3,
    )
    assert reservation is not None and lease is not None

    assert not store.release_orphaned_scheduler_capacity_lease(
        lease["lease_id"], lease["owner"], lease["generation"],
        created_before=created_at + 1, consent=True, audit_reason="operator approved exact stale scheduler lease",
    )
    assert store.capacity_snapshot()["leases"] == [lease]


def test_scheduler_releases_old_job_lease_only_without_live_job_or_ollama_runner(tmp_path):
    import threading
    from types import SimpleNamespace

    from local_ai_hub.scheduler import AffinityScheduler

    store = ExternalGpuReservationStore(tmp_path / "gpu")
    created_at = time.time()
    store._clock = lambda: created_at
    lease = store.acquire_capacity_lease(
        owner="scheduler-job:7", requested_bytes=2 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=16 * 1024**3,
    )
    assert lease is not None
    scheduler = object.__new__(AffinityScheduler)
    scheduler._external_gpu_store = store
    scheduler._cond = threading.Condition()
    scheduler._pending = [SimpleNamespace(id=7)]
    scheduler._inflight_jobs = {}
    scheduler._started_at = created_at + 1

    def release(probe):
        return scheduler.gpu_reservation_operation(
            action="release_scheduler_capacity_lease", lease_id=lease["lease_id"],
            owner=lease["owner"], generation=lease["generation"], consent=True,
            audit_reason="operator approved exact stale scheduler lease",
            ollama_runner_probe=probe,
        )

    assert not release(lambda: False)["success"]
    scheduler._pending = []
    assert not release(lambda: True)["success"]
    assert store.capacity_snapshot()["leases"] == [lease]

    result = release(lambda: False)
    assert result["success"] and result["mutation_applied"]
    assert store.capacity_snapshot()["leases"] == []


def test_ollama_runner_probe_requires_a_valid_bounded_api_ps_response(monkeypatch):
    from local_ai_hub import http_server

    class Response:
        def __init__(self, value):
            self.body = json.dumps(value).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size):
            assert size == 262145
            return self.body[:size]

    seen = {}

    def open_url(request, timeout):
        seen.update(url=request.full_url, timeout=timeout)
        return Response({"models": []})

    monkeypatch.setattr(http_server.urllib.request, "urlopen", open_url)
    assert http_server._ollama_runner_present({"ollama": {"url": "http://ollama:11434/"}}) is False
    assert seen == {"url": "http://ollama:11434/api/ps", "timeout": 2}

    monkeypatch.setattr(http_server.urllib.request, "urlopen", lambda *_args, **_kwargs: Response({"models": [{"name": "model"}]}))
    assert http_server._ollama_runner_present({}) is True

    monkeypatch.setattr(http_server.urllib.request, "urlopen", lambda *_args, **_kwargs: Response({"unexpected": []}))
    try:
        http_server._ollama_runner_present({})
    except ValueError:
        pass
    else:
        raise AssertionError("malformed Ollama runner state must fail closed")


def test_authorized_orphaned_laya_capacity_lease_release_rejects_reservation_bound_lease(
    tmp_path, monkeypatch,
):
    from local_ai_hub import process_utils

    store = ExternalGpuReservationStore(tmp_path / "gpu")
    reservation = store.reserve(_digest("owner"), owner="external-owner", owner_vram_budget_bytes=8 * 1024**3)
    lease = store.acquire_capacity_lease(
        owner="laya-runtime:12345:deadbeef", requested_bytes=2 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=8 * 1024**3,
    )
    assert reservation is not None and lease is not None
    monkeypatch.setattr(process_utils, "process_is_alive", lambda pid: False)

    assert not store.release_orphaned_laya_capacity_lease(
        lease["lease_id"], lease["owner"], lease["generation"],
        consent=True, audit_reason="operator approved exact stale lease",
    )
    assert store.capacity_snapshot()["leases"] == [lease]


def test_capacity_lease_aggregates_multiple_owners(tmp_path):
    store = ExternalGpuReservationStore(tmp_path / "gpu")
    store.reserve(_digest("owner"), owner="external-owner", owner_vram_budget_bytes=4 * 1024**3)

    first = store.acquire_capacity_lease(
        owner="laya:resident", requested_bytes=4 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=8 * 1024**3,
    )
    second = store.acquire_capacity_lease(
        owner="hub:request", requested_bytes=4 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=8 * 1024**3,
    )

    assert first is not None and second is not None
    assert store.capacity_snapshot()["leases"] == [first, second]
    assert store.acquire_capacity_lease(
        owner="overflow", requested_bytes=5 * 1024**3,
        total_bytes=12 * 1024**3, available_bytes=8 * 1024**3,
    ) is None


def test_internal_digest_fence_allows_generation_bound_capacity_lease(tmp_path):
    store = ExternalGpuReservationStore(tmp_path / "gpu")
    digest = _digest("scheduler-internal")
    assert store.claim_internal(digest)

    assert store.capacity_snapshot(expected_internal_digest=digest) == {
        "reservation": None, "leases": [], "internal_fence_digest": digest,
    }
    assert store.acquire_capacity_lease(
        owner="laya:resident", requested_bytes=4 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=8 * 1024**3,
        expected_internal_digest=_digest("wrong-owner"),
    ) is None
    lease = store.acquire_capacity_lease(
        owner="laya:resident", requested_bytes=4 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=8 * 1024**3,
        expected_internal_digest=digest,
    )

    assert lease is not None
    assert lease["reservation_generation"] == f"internal:{digest}"
    assert store.capacity_snapshot(expected_internal_digest=digest)["leases"] == [lease]
    assert store.capacity_snapshot() is None
    assert not store.release_internal(digest)
    assert store.path.read_text(encoding="ascii") == digest
    assert store.release_capacity_lease(lease["lease_id"], lease["owner"], lease["generation"])
    assert store.release_internal(digest)


def test_internal_digest_capacity_admission_fails_closed_for_foreign_or_malformed_fence(tmp_path):
    store = ExternalGpuReservationStore(tmp_path / "gpu")
    foreign_digest = _digest("foreign-internal")
    store.path.write_text(foreign_digest, encoding="ascii")

    assert store.acquire_capacity_lease(
        owner="laya:resident", requested_bytes=4 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=8 * 1024**3,
        expected_internal_digest=_digest("scheduler-internal"),
    ) is None
    assert store.capacity_snapshot(expected_internal_digest=_digest("scheduler-internal")) is None

    store.path.write_text("malformed", encoding="ascii")
    assert store.acquire_capacity_lease(
        owner="laya:resident", requested_bytes=4 * 1024**3,
        total_bytes=16 * 1024**3, available_bytes=8 * 1024**3,
        expected_internal_digest=_digest("scheduler-internal"),
    ) is None
