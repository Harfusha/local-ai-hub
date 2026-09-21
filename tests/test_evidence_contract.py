from local_ai_hub.evidence_contract import evidence_meta


def test_evidence_meta_is_bounded_and_does_not_store_payload():
    result = evidence_meta(
        source="repo.search", repository_revision="abc123", evidence_ids=["E1"],
        stale=False, status="success", payload={"text": "secret source"},
    )
    assert result == {
        "source": "repo.search", "repository_revision": "abc123",
        "evidence_ids": ["E1"], "stale": False, "status": "success",
    }


def test_stale_evidence_cannot_claim_verified():
    result = evidence_meta("repo.search", "abc123", ["E1"], True, "success")
    assert result["status"] == "stale"
    assert result["stale"] is True
