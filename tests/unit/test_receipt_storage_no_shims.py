import json
import pytest
from local_ai_hub.agent_verification import _stored_receipt, VERIFICATION_RECEIPT_METADATA_SCHEMA


def receipt_row(details, passed=1):
    return ("receipt", "task", "criterion", "", "evidence", "command", "revision", 10.0, None, passed, json.dumps(details))


def metadata(**changes):
    result = {"schema": VERIFICATION_RECEIPT_METADATA_SCHEMA, "owner": "agent", "mutation_generation": 2, "evidence_type": "test"}
    result.update(changes)
    return {"_verification_receipt": result, "note": {"tenant": "opaque project text"}}


def test_stored_receipt_preserves_current_proof_and_opaque_details():
    receipt = _stored_receipt(receipt_row(metadata()))
    assert receipt.owner == "agent" and receipt.mutation_generation == 2
    assert receipt.passed is True
    assert receipt.details == {"note": {"tenant": "opaque project text"}}


@pytest.mark.parametrize("details", [{}, [], {"_verification_receipt": {}}, metadata(schema=""), metadata(schema="unsupported")])
def test_legacy_receipt_metadata_is_not_promoted(details):
    with pytest.raises(ValueError):
        _stored_receipt(receipt_row(details))


@pytest.mark.parametrize("generation", [None, False, "2", -1])
def test_stored_generations_are_not_coerced(generation):
    with pytest.raises(ValueError):
        _stored_receipt(receipt_row(metadata(mutation_generation=generation)))


@pytest.mark.parametrize("passed", [None, True, "1", 2, -1])
def test_stored_passed_flags_reject_invalid_values(passed):
    with pytest.raises(ValueError):
        _stored_receipt(receipt_row(metadata(), passed=passed))
