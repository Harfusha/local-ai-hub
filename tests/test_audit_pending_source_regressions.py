"""Regressions for context artifact identity and lock cleanup failures."""
from __future__ import annotations

import os

import pytest


@pytest.mark.parametrize("pointer", [None, False, 7, [], {}, "", " art_1", "art_1 ", "art_1\0"])
@pytest.mark.parametrize("location", ["top", "nested"])
def test_context_delivery_rejects_present_invalid_artifact_pointer(pointer, location):
    from local_ai_hub.context_delivery import prepare_context_delivery
    context = {"success": True, "complete": True, "text": "short exact context"}
    value = {"success": True, "task_context": context}
    if location == "top":
        value["task_context_artifact_id"] = pointer
    else:
        context["artifact_id"] = pointer
    result = prepare_context_delivery(value, 3200)
    assert result["success"] is False
    assert result["complete"] is False
    assert result["task_context"]["complete"] is False
    assert "task_context_artifact_id" not in result
    assert "artifact_id" not in result["task_context"]
    assert result.get("next_action") != "read_task_context_artifact"


def test_context_delivery_rejects_disagreeing_artifact_identities():
    from local_ai_hub.context_delivery import prepare_context_delivery
    result = prepare_context_delivery({
        "success": True, "task_context_artifact_id": "art_first",
        "task_context": {
            "success": True, "complete": True, "text": "exact",
            "artifact_id": "art_second",
        },
    }, 3200)
    assert result["success"] is False
    assert "task_context_artifact_id" not in result
    assert "artifact_id" not in result["task_context"]


@pytest.mark.parametrize("success,complete", [(False, True), (True, False), (False, False)])
def test_context_delivery_cannot_promote_incomplete_nested_context(success, complete):
    from local_ai_hub.context_delivery import prepare_context_delivery
    result = prepare_context_delivery({
        "success": True, "complete": True,
        "task_context": {"success": success, "complete": complete, "text": "partial"},
    }, 3200)
    assert result["success"] is False
    assert result["complete"] is False
    assert result["partial"] is True


def test_context_delivery_keeps_matching_real_pointer_and_exact_small_text():
    from local_ai_hub.context_delivery import prepare_context_delivery
    result = prepare_context_delivery({
        "success": True, "task_context_artifact_id": "art_same",
        "task_context": {
            "success": True, "complete": True, "text": "exact context",
            "artifact_id": "art_same",
        },
    }, 3200)
    assert result["success"] is True
    assert result["task_context"]["text"] == "exact context"
    assert result["task_context_artifact_id"] == "art_same"


def test_unlock_failure_still_closes_owned_descriptor(tmp_path, monkeypatch):
    import local_ai_hub.file_locks as module

    closed = []
    original_close = module.os.close

    def close(descriptor):
        closed.append(descriptor)
        return original_close(descriptor)

    if os.name == "nt":
        import msvcrt
        original_unlock = msvcrt.locking

        def locking(descriptor, mode, size):
            if mode == msvcrt.LK_UNLCK:
                raise OSError("injected unlock fault")
            return original_unlock(descriptor, mode, size)

        monkeypatch.setattr(msvcrt, "locking", locking)
    else:
        import fcntl
        original_unlock = fcntl.flock

        def flock(descriptor, mode):
            if mode == fcntl.LOCK_UN:
                raise OSError("injected unlock fault")
            return original_unlock(descriptor, mode)

        monkeypatch.setattr(fcntl, "flock", flock)
    monkeypatch.setattr(module.os, "close", close)
    with pytest.raises(OSError, match="injected unlock fault"):
        with module.exclusive_file_update(tmp_path / "runtime.toml"):
            pass
    assert len(closed) == 1
