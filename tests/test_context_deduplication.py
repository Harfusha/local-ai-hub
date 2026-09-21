from local_ai_hub.context_ledger import ContextLedger


def test_same_revision_and_evidence_returns_pointer_not_full_context():
    ledger = ContextLedger()
    first = ledger.compile("task-1", revision="r1", evidence_ids=["E1"], context="facts")
    second = ledger.compile("task-1", revision="r1", evidence_ids=["E1"], context="facts")
    assert first["status"] == "materialized"
    assert second["status"] == "unchanged"
    assert second["context"] is None
    assert second["reuse_key"] == first["reuse_key"]


def test_new_evidence_returns_only_delta():
    ledger = ContextLedger()
    ledger.compile("task-1", "r1", ["E1"], "facts")
    result = ledger.compile("task-1", "r1", ["E1", "E2"], "facts plus new")
    assert result["status"] == "delta"
    assert result["added_evidence_ids"] == ["E2"]
