from __future__ import annotations

from tools import profile_evidence_collector


def test_profile_evidence_collector_schema_and_verdicts():
    evidence = profile_evidence_collector.collect_all_evidence()
    assert evidence["schema_version"] == "performance_profile_evidence.v1"
    assert len(evidence["profiles"]) == 4

    findings = {p["finding"] for p in evidence["profiles"]}
    assert findings == {"F17", "F18", "F19", "F22"}

    for p in evidence["profiles"]:
        assert p["verdict"] == "do_not_rewrite"
        assert len(p["verdict_reason"]) > 10
