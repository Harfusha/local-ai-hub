from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from local_ai_hub.external_gpu_reservation import ExternalGpuReservationStore
from local_ai_hub.operation_contracts import operation_contract, validate_operation_arguments


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def test_default_reservation_ttl_is_bounded_and_idle_state(tmp_path):
    store = ExternalGpuReservationStore(tmp_path / "external-gpu-reservation", clock=lambda: 100.0)

    lease = store.reserve(_digest("owner-token"), owner="external-session")

    assert lease is not None
    assert lease["schema_version"] == 1
    assert lease["generation"]
    assert lease["owner"] == "external-session"
    assert lease["state"] == "idle"
    assert lease["expires_at"] == 160.0


def test_reserve_reaps_expired_legacy_fence_before_new_owner_claims(tmp_path):
    now = [100.0]
    path = tmp_path / "external-gpu-reservation"
    path.write_text(_digest("legacy-owner"), encoding="ascii")
    os.utime(path, (80.0, 80.0))
    store = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])
    now[0] = 111.0

    replacement = store.reserve(_digest("new-owner"), owner="new-owner")

    assert replacement is not None
    assert replacement["owner"] == "new-owner"
    assert store.read() == replacement


def test_internal_claim_reaps_expired_legacy_fence(tmp_path):
    now = [111.0]
    path = tmp_path / "external-gpu-reservation"
    path.write_text(_digest("legacy-owner"), encoding="ascii")
    os.utime(path, (80.0, 80.0))
    store = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])
    current_digest = _digest("internal-owner")

    assert store.claim_internal(current_digest) is True
    assert path.read_text(encoding="ascii") == current_digest


@pytest.mark.parametrize("contents", ["not-a-digest", "g" * 64])
def test_malformed_legacy_fence_never_reaps_by_age(tmp_path, contents):
    now = [100.0]
    path = tmp_path / "external-gpu-reservation"
    path.write_text(contents, encoding="ascii")
    os.utime(path, (80.0, 80.0))
    store = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])

    assert store.reap_expired() is False
    assert path.exists()


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


def test_active_lease_heartbeat_prevents_expiry_until_owner_finishes(tmp_path, monkeypatch):
    path = tmp_path / "external-gpu-reservation"
    now = [100.0]

    def clock():
        now[0] += 0.01
        return now[0]

    store = ExternalGpuReservationStore(path, ttl_seconds=0.12, clock=clock)
    lease = store.reserve(_digest("long-running-owner"), owner="embedding:123:456")
    assert lease is not None
    assert store.renew(_digest("long-running-owner"), lease["generation"], state="active")
    initial_expiry = store.read()["expires_at"]

    original_renew = store.renew
    renewals = 0
    heartbeat_seen = threading.Event()

    def observe_renewal(token_digest, generation, *, state="idle"):
        nonlocal renewals
        renewed = original_renew(token_digest, generation, state=state)
        if renewed:
            renewals += 1
            if renewals >= 2:
                heartbeat_seen.set()
        return renewed

    monkeypatch.setattr(store, "renew", observe_renewal)

    with store.keepalive(_digest("long-running-owner"), lease["generation"], state="active"):
        assert heartbeat_seen.wait(timeout=5)
        renewed = store.read()
        assert renewed is not None
        assert renewed["generation"] == lease["generation"]
        assert renewed["expires_at"] > initial_expiry

    now[0] = renewed["expires_at"] + 1
    assert store.reap_expired() is True
    assert store.read() is None


def test_expired_legacy_digest_fence_reaps_by_mtime_and_audits(tmp_path):
    now = [100.0]
    path = tmp_path / "external-gpu-reservation"
    path.write_text(_digest("legacy-owner"), encoding="ascii")
    os.utime(path, (95.0, 95.0))
    store = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])

    assert store.reap_expired() is False
    assert path.exists()

    now[0] = 111.0
    assert store.reap_expired() is True
    assert not path.exists()
    events = [
        json.loads(line)
        for line in store.audit_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["action"] == "legacy_fence_expired"
    assert events[-1]["owner"] == "unknown"


def test_consented_release_current_removes_active_reservation_without_owner_probe(tmp_path, monkeypatch):
    from local_ai_hub import process_utils

    path = tmp_path / "external-gpu-reservation"
    store = ExternalGpuReservationStore(path, ttl_seconds=900, clock=lambda: 100.0)
    lease = store.reserve(_digest("active-owner"), owner="embedding:424242:17")
    assert lease is not None

    def unexpected_owner_probe(_pid):
        raise AssertionError("consented release must not probe owner liveness")

    monkeypatch.setattr(process_utils, "process_is_alive", unexpected_owner_probe)
    assert store.release_current_with_consent(
        consent=True,
        audit_reason="operator authorized release without owner inspection",
    )
    assert store.read() is None
    event = json.loads(store.audit_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["action"] == "consented_release_current_reservation"
    assert event["generation"] == lease["generation"]
    assert event["owner"] == "embedding:424242:17"


def test_consented_release_current_clears_unknown_legacy_fence_and_audits(tmp_path):
    path = tmp_path / "external-gpu-reservation"
    path.write_text(_digest("legacy-owner"), encoding="ascii")
    store = ExternalGpuReservationStore(path, ttl_seconds=900)

    assert store.read() is None
    assert store.release_current_with_consent(
        consent=True,
        audit_reason="operator authorized cleanup of stale legacy reservation",
    )
    assert not path.exists()
    events = [
        json.loads(line)
        for line in store.audit_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["action"] == "consented_release_current_legacy_fence"
    assert events[-1]["owner"] == "unknown"
    assert events[-1]["reason"] == "operator authorized cleanup of stale legacy reservation"


def test_consented_release_current_rejects_malformed_metadata(tmp_path):
    path = tmp_path / "external-gpu-reservation"
    store = ExternalGpuReservationStore(path, ttl_seconds=900)
    active = store.reserve(_digest("active-owner"), owner="embedding:123:456")

    assert active is not None
    assert store.read() == active

    metadata_path = path.with_name(path.name + ".lease.json")
    metadata_path.write_text("malformed", encoding="utf-8")
    assert not store.release_current_with_consent(
        consent=True, audit_reason="operator authorized reservation cleanup",
    )
    assert path.exists()
    assert metadata_path.exists()


def test_expired_active_reservation_reaps_before_new_owner_reserves(tmp_path):
    now = [100.0]
    path = tmp_path / "external-gpu-reservation"
    store = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])
    lease = store.reserve(_digest("active-token"), owner="active-owner")
    assert lease is not None
    assert store.renew(_digest("active-token"), lease["generation"], state="active")

    now[0] = 111.0
    other = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])
    assert other.reap_expired()
    assert other.read() is None
    replacement = other.reserve(_digest("other-token"), owner="other")
    assert replacement is not None
    assert replacement["generation"] != lease["generation"]
    assert replacement["owner"] == "other"


def test_expired_active_reservation_allows_internal_gpu_claim(tmp_path):
    now = [100.0]
    path = tmp_path / "external-gpu-reservation"
    external = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])
    lease = external.reserve(_digest("active-token"), owner="active-owner")
    assert lease is not None
    assert external.renew(_digest("active-token"), lease["generation"], state="active")

    now[0] = 111.0
    internal = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: now[0])
    internal_digest = _digest("internal-token")
    assert internal.claim_internal(internal_digest)
    assert not internal.metadata_path.exists()
    assert internal.path.read_text(encoding="ascii") == internal_digest
    assert internal.release_internal(internal_digest)


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


def test_consent_release_allows_confirmed_dead_embedding_owner(tmp_path, monkeypatch):
    store = ExternalGpuReservationStore(
        tmp_path / "external-gpu-reservation", ttl_seconds=60, clock=lambda: 100.0
    )
    lease = store.reserve(_digest("embedding-token"), owner="embedding:12345:67890")
    assert lease is not None
    monkeypatch.setattr("local_ai_hub.process_utils.process_is_alive", lambda pid: False)

    assert store.release_with_consent(
        lease["generation"], consent=True, audit_reason="confirmed owner process exited"
    )
    assert store.read() is None
    events = [
        json.loads(line)
        for line in store.audit_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["action"] == "consented_release_dead_owner"
    assert events[-1]["owner"] == "embedding:12345:67890"


def test_consent_release_recovers_metadata_orphan_after_partial_cleanup(tmp_path, monkeypatch):
    now = [100.0]
    store = ExternalGpuReservationStore(
        tmp_path / "external-gpu-reservation", ttl_seconds=10, clock=lambda: now[0]
    )
    lease = store.reserve(_digest("owner-token"), owner="session")
    assert lease is not None
    now[0] = 111.0

    original_unlink = Path.unlink
    failed = [False]

    def fail_metadata_unlink_once(path, *args, **kwargs):
        if path == store.metadata_path and not failed[0]:
            failed[0] = True
            raise OSError("simulated crash window after digest removal")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_metadata_unlink_once)
    assert not store.release_with_consent(
        lease["generation"], consent=True, audit_reason="operator approved"
    )
    assert not store.path.exists()
    assert store.metadata_path.exists()

    monkeypatch.setattr(Path, "unlink", original_unlink)
    assert store.release_with_consent(
        lease["generation"], consent=True, audit_reason="recover interrupted release"
    )
    assert not store.metadata_path.exists()


def test_reserve_does_not_replace_metadata_orphan_after_cleanup_failure(tmp_path, monkeypatch):
    now = [100.0]
    store = ExternalGpuReservationStore(
        tmp_path / "external-gpu-reservation", ttl_seconds=10, clock=lambda: now[0]
    )
    old_lease = store.reserve(_digest("old-owner-token"), owner="old-session")
    assert old_lease is not None
    now[0] = 111.0

    original_unlink = Path.unlink
    failed = [False]

    def fail_metadata_unlink_once(path, *args, **kwargs):
        if path == store.metadata_path and not failed[0]:
            failed[0] = True
            raise OSError("simulated metadata cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_metadata_unlink_once)
    assert store.reserve(_digest("new-owner-token"), owner="new-session") is None
    assert not store.path.exists()
    assert store.metadata_path.exists()
    assert store.read() is None
    assert not store.claim_internal(_digest("internal-owner-token"))

    monkeypatch.setattr(Path, "unlink", original_unlink)
    assert store.release_with_consent(
        old_lease["generation"], consent=True, audit_reason="recover interrupted reserve cleanup"
    )
    assert not store.path.exists()
    assert not store.metadata_path.exists()
    assert store.reserve(_digest("new-owner-token"), owner="new-session") is not None


def test_reserve_keeps_expired_generation_when_digest_cleanup_fails(tmp_path, monkeypatch):
    now = [100.0]
    store = ExternalGpuReservationStore(
        tmp_path / "external-gpu-reservation", ttl_seconds=10, clock=lambda: now[0]
    )
    old_lease = store.reserve(_digest("old-owner-token"), owner="old-session")
    assert old_lease is not None
    now[0] = 111.0

    original_unlink = Path.unlink

    def fail_digest_unlink(path, *args, **kwargs):
        if path == store.path:
            raise OSError("simulated digest cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_digest_unlink)
    assert store.reserve(_digest("new-owner-token"), owner="new-session") is None
    assert store.path.exists()
    assert store.metadata_path.exists()
    assert store.read()["generation"] == old_lease["generation"]
    assert not store.claim_internal(_digest("internal-owner-token"))

    monkeypatch.setattr(Path, "unlink", original_unlink)
    assert store.release_with_consent(
        old_lease["generation"], consent=True, audit_reason="recover failed digest cleanup"
    )
    assert not store.path.exists()
    assert not store.metadata_path.exists()
    assert store.reserve(_digest("new-owner-token"), owner="new-session") is not None


def test_expired_release_retries_transient_metadata_sharing_violation(tmp_path, monkeypatch):
    now = [100.0]
    store = ExternalGpuReservationStore(
        tmp_path / "external-gpu-reservation", ttl_seconds=10, clock=lambda: now[0]
    )
    lease = store.reserve(_digest("owner-token"), owner="session")
    assert lease is not None
    now[0] = 111.0

    original_unlink = Path.unlink
    attempts = 0

    def fail_once_on_metadata(path, *args, **kwargs):
        nonlocal attempts
        if path == store.metadata_path and attempts == 0:
            attempts += 1
            error = OSError("simulated metadata sharing violation")
            error.winerror = 32
            raise error
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_once_on_metadata)
    assert store.reap_expired() is True
    assert attempts == 1
    assert not store.path.exists()
    assert not store.metadata_path.exists()
    assert store.reserve(_digest("new-owner-token"), owner="new-session") is not None


def test_consent_release_recovers_metadata_orphan_after_unlink_failure(tmp_path, monkeypatch):
    now = [100.0]
    store = ExternalGpuReservationStore(
        tmp_path / "external-gpu-reservation", ttl_seconds=10, clock=lambda: now[0]
    )
    lease = store.reserve(_digest("owner-token"), owner="session")
    assert lease is not None
    now[0] = 111.0

    original_unlink = Path.unlink
    failed = False

    def fail_first_metadata_unlink(path, *args, **kwargs):
        nonlocal failed
        if path == store.metadata_path and not failed:
            failed = True
            raise OSError("simulated metadata cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_first_metadata_unlink)
    assert not store.reap_expired()
    assert not store.path.exists()
    assert store.metadata_path.exists()
    assert store.read() is None

    assert store.release_with_consent(
        lease["generation"], consent=True, audit_reason="recover metadata cleanup"
    )
    assert not store.path.exists()
    assert not store.metadata_path.exists()
    audit = [json.loads(line) for line in store.audit_path.read_text(encoding="utf-8").splitlines()]
    assert audit[-1]["action"] == "consented_release_recovery"
    assert audit[-1]["generation"] == lease["generation"]


def test_consent_release_keeps_malformed_metadata_orphan_fail_closed(tmp_path):
    now = [100.0]
    store = ExternalGpuReservationStore(
        tmp_path / "external-gpu-reservation", ttl_seconds=10, clock=lambda: now[0]
    )
    lease = store.reserve(_digest("owner-token"), owner="session")
    assert lease is not None
    store.path.unlink()
    store.metadata_path.write_text("{malformed", encoding="utf-8")
    now[0] = 111.0

    assert not store.release_with_consent(
        lease["generation"], consent=True, audit_reason="operator approved"
    )
    assert store.metadata_path.exists()


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


def test_consent_release_removes_active_reservation_when_owner_process_is_gone(tmp_path, monkeypatch):
    now = [100.0]
    path = tmp_path / "external-gpu-reservation"
    store = ExternalGpuReservationStore(path, ttl_seconds=900, clock=lambda: now[0])
    lease = store.reserve(_digest("owner-token"), owner="reranker:424242:17")
    assert lease is not None
    assert store.renew(_digest("owner-token"), lease["generation"], state="active")
    monkeypatch.setattr("local_ai_hub.process_utils.process_is_alive", lambda pid: False)

    assert store.release_with_consent(
        lease["generation"], consent=True, audit_reason="operator approved after owner process exited"
    )
    assert store.read() is None


def test_consent_release_removes_active_embedding_reservation_when_owner_process_is_gone(tmp_path, monkeypatch):
    now = [100.0]
    path = tmp_path / "external-gpu-reservation"
    store = ExternalGpuReservationStore(path, ttl_seconds=900, clock=lambda: now[0])
    lease = store.reserve(_digest("embedding-owner-token"), owner="embedding:424242:17")
    assert lease is not None
    assert store.renew(_digest("embedding-owner-token"), lease["generation"], state="active")
    monkeypatch.setattr("local_ai_hub.process_utils.process_is_alive", lambda pid: False)

    assert store.release_with_consent(
        lease["generation"], consent=True, audit_reason="operator approved after embedding owner exited"
    )
    assert store.read() is None


def test_consent_release_keeps_unknown_owner_type_fail_closed(tmp_path, monkeypatch):
    store = ExternalGpuReservationStore(tmp_path / "external-gpu-reservation", ttl_seconds=900, clock=lambda: 100.0)
    lease = store.reserve(_digest("unknown-owner-token"), owner="unknown-worker:424242:17")
    assert lease is not None
    assert store.renew(_digest("unknown-owner-token"), lease["generation"], state="active")
    monkeypatch.setattr("local_ai_hub.process_utils.process_is_alive", lambda pid: False)

    assert not store.release_with_consent(
        lease["generation"], consent=True, audit_reason="unknown owner type remains fail-closed"
    )
    assert store.read() is not None


def test_consent_release_keeps_active_reservation_when_process_liveness_is_unknown(tmp_path, monkeypatch):
    now = [100.0]
    path = tmp_path / "external-gpu-reservation"
    store = ExternalGpuReservationStore(path, ttl_seconds=900, clock=lambda: now[0])
    lease = store.reserve(_digest("owner-token"), owner="reranker:424242:17")
    assert lease is not None
    assert store.renew(_digest("owner-token"), lease["generation"], state="active")
    monkeypatch.setattr("local_ai_hub.process_utils.process_is_alive", lambda pid: None)

    assert not store.release_with_consent(
        lease["generation"], consent=True, audit_reason="owner status is unknown"
    )
    assert store.read() is not None


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


def test_internal_release_retries_windows_sharing_violation(tmp_path, monkeypatch):
    path = tmp_path / "external-gpu-reservation"
    store = ExternalGpuReservationStore(path, ttl_seconds=10, clock=lambda: 100.0)
    digest = _digest("internal")
    assert store.claim_internal(digest)
    original_unlink = Path.unlink
    attempts = 0

    def unlink_with_transient_sharing_violation(candidate, *args, **kwargs):
        nonlocal attempts
        if candidate == path and attempts == 0:
            attempts += 1
            error = OSError("simulated Windows sharing violation")
            error.winerror = 32
            raise error
        if candidate == path:
            attempts += 1
        return original_unlink(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink_with_transient_sharing_violation)

    assert store.release_internal(digest) is True
    assert attempts == 2
    assert not path.exists()


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
    assert "gpu_reservation_release_authorized" in contract["action_order"]
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
    assert not validate_operation_arguments("local_ai_coord", "gpu_reservation_release_authorized", {
        "action": "gpu_reservation_release_authorized",
        "consent": True,
        "audit_reason": "operator authorized release without owner inspection",
    })
    assert validate_operation_arguments("local_ai_coord", "gpu_reservation_release_authorized", {
        "action": "gpu_reservation_release_authorized",
    })


pytestmark = pytest.mark.slow
