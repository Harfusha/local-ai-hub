from __future__ import annotations

from pathlib import Path

import pytest

from local_ai_hub.resilience import RecoveryJournal


def test_registration_call_shape_replays_identical_completed_request(tmp_path: Path) -> None:
    journal = RecoveryJournal(tmp_path / "state")
    payload = {"query": "same registration"}

    owner = journal.begin(
        "request-1",
        "tenant",
        "/api/search",
        identity="agent-a",
        payload=payload,
    )
    response = {"success": True, "value": "saved"}
    journal.finish("request-1", True, status_code=200, response=response)

    replay = journal.begin(
        "request-1",
        "tenant",
        "/api/search",
        identity="agent-a",
        payload=payload,
    )

    assert owner["claimed"] is True
    assert replay["claimed"] is False
    assert replay["state"] == "done"
    assert replay["status_code"] == 200
    assert replay["response"] == response
    assert replay["payload_fingerprint"] == owner["payload_fingerprint"]


@pytest.mark.parametrize(
    ("identity", "payload_fingerprint"),
    [
        ("agent-b", None),
        ("agent-a", "different-fingerprint"),
    ],
)
def test_wait_for_rejects_registration_identity_or_fingerprint_conflict(
    tmp_path: Path,
    identity: str,
    payload_fingerprint: str | None,
) -> None:
    journal = RecoveryJournal(tmp_path / "state")
    owner = journal.begin(
        "request-1",
        "tenant",
        "/api/search",
        identity="agent-a",
        payload={"query": "owner payload"},
    )

    replay = journal.wait_for(
        "request-1",
        "tenant",
        "/api/search",
        timeout_seconds=0,
        identity=identity,
        payload_fingerprint=payload_fingerprint or owner["payload_fingerprint"],
    )

    assert replay == {
        "state": "conflict",
        "error": "request id already belongs to a different identity, operation, or payload",
    }
