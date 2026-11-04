from __future__ import annotations

import hashlib
import json
import math
from concurrent.futures import ThreadPoolExecutor

import pytest

from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore
from local_ai_hub.operation_contracts import operation_contract, validate_operation_arguments


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def test_reservation_has_generation_expiry_and_idle_state(tmp_path):
    store = ExternalGpuReservationStore(tmp_path / "external-gpu-reservation", ttl_seconds=60, clock=lambda: 100.0)

    lease = store.reserve(_digest("owner-token"), owner="opencode-session")

    assert lease is not None
    assert lease["schema_version"] == 1
    assert lease["generation"]
    assert lease["owner"] == "opencode-session"
    assert lease["state"] == "idle"
    assert lease["expires_at"] == 160.0


def test_idle_expiration_reaps_before_new_owner_reserves(tmp_path):
    now = [100.0]
    path = tmp_path / "external-gpu-reservation"
    first = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])
    old = first.reserve(_digest("first-token"), owner="first")
    assert old is not None

    now[0] = 111.0
    second = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])
    replacement = second.reserve(_digest("second-token"), owner="second")

    assert replacement is not None
    assert replacement["generation"] != old["generation"]
    assert replacement["owner"] == "second"


def test_active_reservation_does_not_auto_expire(tmp_path):
    now = [100.0]
    path = tmp_path / "external-gpu-reservation"
    store = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])
    lease = store.reserve(_digest("active-token"), owner="active-owner")
    assert lease is not None
    assert store.renew(_digest("active-token"), lease["generation"], state="active")

    now[0] = 1000.0
    other = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])
    assert other.reserve(_digest("other-token"), owner="other") is None
    assert other.read()["generation"] == lease["generation"]


def test_owner_renewal_extends_lease_without_changing_generation(tmp_path):
    now = [100.0]
    store = ExternalGpuReservationStore(tmp_path / "external-gpu-reservation", ttl_seconds=10, clock=lambda: now[0])
    lease = store.reserve(_digest("owner-token"), owner="session")
    assert lease is not None
    now[0] = 105.0

    assert store.renew(_digest("owner-token"), lease["generation"], state="idle")
    renewed = store.read()

    assert renewed["generation"] == lease["generation"]
    assert renewed["expires_at"] == 115.0


def test_consent_release_requires_expired_idle_generation_and_audit_reason(tmp_path):
    now = [100.0]
    path = tmp_path / "external-gpu-reservation"
    owner = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])
    lease = owner.reserve(_digest("owner-token"), owner="session")
    assert lease is not None
    other = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])

    assert not other.release_with_consent(lease["generation"], consent=False, audit_reason="")
    assert not other.release_with_consent(lease["generation"], consent=True, audit_reason=" ")
    assert not other.release_with_consent("wrong-generation", consent=True, audit_reason="operator approved")
    assert not other.release_with_consent(lease["generation"], consent=True, audit_reason="operator approved")

    now[0] = 111.0
    assert other.release_with_consent(lease["generation"], consent=True, audit_reason="operator approved")
    assert other.read() is None


def test_consent_release_of_active_lease_waits_for_expiry(tmp_path):
    now = [100.0]
    path = tmp_path / "external-gpu-reservation"
    owner = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])
    lease = owner.reserve(_digest("owner-token"), owner="session")
    assert lease is not None
    assert owner.renew(_digest("owner-token"), lease["generation"], state="active")
    other = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])

    assert not other.release_with_consent(lease["generation"], consent=True, audit_reason="operator approved")
    assert other.read()["state"] == "active"
    now[0] = 111.0
    assert other.release_with_consent(lease["generation"], consent=True, audit_reason="operator confirmed owner ended")
    assert other.read() is None


def test_legacy_digest_record_stays_fail_closed(tmp_path):
    path = tmp_path / "external-gpu-reservation"
    path.write_text(_digest("old-token"), encoding="ascii")
    store = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: 10000.0)

    assert store.read() is None
    assert store.reserve(_digest("new-token"), owner="new") is None
    assert path.read_text(encoding="ascii") == _digest("old-token")


def test_corrupt_metadata_is_not_reaped_or_replaced(tmp_path):
    path = tmp_path / "external-gpu-reservation"
    path.write_text("not-a-reservation", encoding="ascii")
    store = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: 10000.0)

    assert store.read() is None
    assert store.reserve(_digest("new-token"), owner="new") is None
    assert path.read_text(encoding="ascii") == "not-a-reservation"


def test_internal_and_external_claims_share_one_atomic_fence(tmp_path):
    path = tmp_path / "external-gpu-reservation"
    store = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: 100.0)
    assert store.claim_internal(_digest("internal"))
    assert store.reserve(_digest("external"), owner="external") is None
    assert store.release_internal(_digest("internal"))
    assert store.reserve(_digest("external"), owner="external") is not None


def test_competing_external_reservations_have_one_winner(tmp_path):
    path = tmp_path / "external-gpu-reservation"
    stores = [ExternalGpuReservationStore(path) for _ in range(12)]
    with ThreadPoolExecutor(max_workers=len(stores)) as pool:
        results = list(pool.map(lambda pair: pair[1].reserve(_digest(f"token-{pair[0]}"), owner=f"owner-{pair[0]}"), enumerate(stores)))
    assert sum(result is not None for result in results) == 1


@pytest.mark.parametrize("ttl", [float("nan"), float("inf"), float("-inf"), 0, -1, True])
def test_lease_ttl_must_be_positive_finite_number(tmp_path, ttl):
    with pytest.raises(ValueError):
        ExternalGpuReservationStore(tmp_path / "reservation", ttl_seconds=ttl)


def test_coordination_mcp_contract_exposes_status_and_consented_release():
    contract = operation_contract("local_ai_coord")
    assert "gpu_reservation_status" in contract["action_order"]
    assert "gpu_reservation_release" in contract["action_order"]
    assert not validate_operation_arguments("local_ai_coord", "gpu_reservation_status", {
        "action": "gpu_reservation_status",
    })
    assert validate_operation_arguments("local_ai_coord", "gpu_reservation_release", {
        "action": "gpu_reservation_release",
    })
    assert not validate_operation_arguments("local_ai_coord", "gpu_reservation_release", {
        "action": "gpu_reservation_release",
        "generation": "generation-1",
        "consent": True,
        "audit_reason": "operator confirmed stale owner is gone",
    })

