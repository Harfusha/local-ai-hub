import pytest

from local_ai_hub.agent_memory import MemoryRecord


@pytest.mark.parametrize("field,value", [
    ("contradicts_record_id", "previous-contradiction"),
    ("supersedes_record_id", "previous-version"),
    ("quarantine_reason", "awaiting-source-verification"),
])
def test_memory_factory_preserves_correction_and_quarantine_provenance(field, value):
    record = MemoryRecord.create(
        kind="fact", scope="global", key="confirmed-learning", value="bounded fact",
        source="verified-test", provenance={"evidence_id": "verified-evidence"},
        **{field: value},
    )

    restored = MemoryRecord.from_dict(record.to_dict())

    assert getattr(record, field) == value
    assert getattr(restored, field) == value
    assert restored.record_id == record.record_id
    assert restored.source == "verified-test"
    assert restored.provenance == record.provenance


def test_memory_factory_omitted_relationships_stay_empty():
    record = MemoryRecord.create(kind="fact", scope="global", key="confirmed-learning")

    assert record.contradicts_record_id is None
    assert record.supersedes_record_id is None
    assert record.quarantine_reason is None
