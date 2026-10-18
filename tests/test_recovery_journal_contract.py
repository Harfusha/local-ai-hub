from __future__ import annotations

from pathlib import Path

import pytest

from local_ai_hub.resilience import RecoveryJournal


def test_registration_call_shape_replays_identical_completed_request(tmp_path: Path) -> None:
    journal = RecoveryJournal(tmp_path / "state")
    payload = {"query": "same registration"}

    owner = journal.begin("request-1", action="/api/search", payload=payload)
    response = {"success": True, "value": "saved"}
    journal.finish("request-1", True, status_code=200, response=response)

    replay = journal.begin("request-1", action="/api/search", payload=payload)

    assert owner["claimed"] is True
    assert replay["claimed"] is False
    assert replay["state"] == "done"
    assert replay["status_code"] == 200
    assert replay["response"] == response
    assert replay["payload_fingerprint"] == owner["payload_fingerprint"]


@pytest.mark.parametrize(
    ("action", "payload_fingerprint"),
    [
        ("/api/other", None),
        ("/api/search", "different-fingerprint"),
    ],
)
def test_wait_for_rejects_action_or_fingerprint_conflict(
    tmp_path: Path,
    action: str,
    payload_fingerprint: str | None,
) -> None:
    journal = RecoveryJournal(tmp_path / "state")
    owner = journal.begin(
        "request-1",
        action="/api/search",
        payload={"query": "owner payload"},
    )

    replay = journal.wait_for(
        "request-1",
        action=action,
        timeout_seconds=0,
        payload_fingerprint=payload_fingerprint or owner["payload_fingerprint"],
    )

    assert replay == {
        "state": "conflict",
        "error": "request id already belongs to a different operation or payload",
    }


@pytest.mark.parametrize("retired_value", [None, "", False])
@pytest.mark.parametrize("retired_field", ["tenant", "identity"])
def test_begin_and_wait_for_reject_retired_inputs_by_presence(
    tmp_path: Path,
    retired_field: str,
    retired_value: object,
) -> None:
    journal = RecoveryJournal(tmp_path / "state")
    retired = {retired_field: retired_value}

    with pytest.raises(TypeError):
        journal.begin(
            "request-retired-begin",
            action="/api/search",
            payload={},
            **retired,
        )
    with pytest.raises(TypeError):
        journal.wait_for(
            "request-retired-wait",
            action="/api/search",
            timeout_seconds=0,
            payload_fingerprint=journal.fingerprint_payload({}),
            **retired,
        )
