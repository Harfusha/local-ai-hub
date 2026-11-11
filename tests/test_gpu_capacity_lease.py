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
