from __future__ import annotations

from local_ai_hub.context_identity import (
    has_context_path_hints,
    is_valid_settings_digest,
    normalize_context_root,
)
from local_ai_hub.context_ledger import ContextLedger


def test_context_identity_root_normalization_and_helpers() -> None:
    assert normalize_context_root("   ") == ""
    assert normalize_context_root("\x00\t\n") == ""
    assert normalize_context_root(True) == ""
    assert normalize_context_root(False) == ""
    assert normalize_context_root("  C:/Repo\x00/sub  ") == normalize_context_root("C:/Repo/sub")

    assert is_valid_settings_digest("valid-digest-123") is True
    assert is_valid_settings_digest("   ") is False
    assert is_valid_settings_digest("bad\x00digest") is False
    assert is_valid_settings_digest(123) is False
    assert is_valid_settings_digest("x" * 129) is False

    assert has_context_path_hints(["docs/a.md"]) is True
    assert has_context_path_hints([]) is False
    assert has_context_path_hints(None) is False
    assert has_context_path_hints("not-a-list") is False
    assert has_context_path_hints([{"invalid_key": "val"}]) is False


def test_context_ledger_nan_inf_bool_and_null_byte_resilience() -> None:
    ledger = ContextLedger(
        max_entries=float("nan"),  # type: ignore[arg-type]
        pointer_ttl_seconds=float("inf"),  # type: ignore[arg-type]
    )
    assert ledger.entry_count() == 0

    bool_ledger = ContextLedger(
        max_entries=False,  # type: ignore[arg-type]
        pointer_ttl_seconds=False,  # type: ignore[arg-type]
    )
    assert bool_ledger._max_entries == 512
    assert bool_ledger._pointer_ttl_seconds == 300

    ledger.record(
        tool="local_ai\x00_repo",
        operation="con\x00text",
        request_tokens=15,
        response_tokens=5,
        cache_outcome="hi\x00t",
        result_id="res\x00-1",
    )
    assert ledger.entry_count() == 1

    snap_nan = ledger.snapshot(limit=float("nan"))  # type: ignore[arg-type]
    assert len(snap_nan["recent"]) == 1
    assert snap_nan["last"]["tool"] == "local_ai_repo"
    assert snap_nan["last"]["operation"] == "context"
    assert snap_nan["last"]["cache_outcome"] == "hit"
    assert snap_nan["last"]["result_id"] == "res-1"

    snap_inf = ledger.snapshot(limit=float("inf"))  # type: ignore[arg-type]
    assert len(snap_inf["recent"]) == 1

    snap_bool = ledger.snapshot(limit=False)  # type: ignore[arg-type]
    assert len(snap_bool["recent"]) == 1


def test_context_ledger_compile_single_string_evidence_and_helpers() -> None:
    ledger = ContextLedger()
    compiled_str = ledger.compile(
        task_id="task\x00-1",
        revision="rev\x00-1",
        evidence_ids="E12345",  # type: ignore[arg-type]
        context="sample context",
        root="  C:/repo\x00 ",
    )
    reuse_key = compiled_str["reuse_key"]
    assert ledger.compiled_count() == 1
    assert ledger.has_pointer(reuse_key) is True
    assert ledger.has_pointer("ctx_missing") is False

    stored = ledger._compiled[reuse_key]
    assert stored["evidence_ids"] == ["E12345"]
    assert stored["task_id"] == "task-1"
    assert stored["revision"] == "rev-1"

    compiled_none = ledger.compile(
        task_id="task-2",
        revision="rev-2",
        evidence_ids=None,  # type: ignore[arg-type]
        context="other context",
    )
    assert ledger._compiled[compiled_none["reuse_key"]]["evidence_ids"] == []
    assert ledger.compiled_count() == 2

    ledger.record(tool="t", operation="op", request_tokens=10, response_tokens=5)
    assert ledger.entry_count() == 1

    ledger.clear()
    assert ledger.entry_count() == 0
    assert ledger.compiled_count() == 0
    assert ledger.has_pointer(reuse_key) is False
    assert ledger.snapshot()["totals"] == {}
