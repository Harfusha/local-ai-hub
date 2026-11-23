"""Tests for Failure Fingerprinting and Proactive Negative Knowledge Advisory."""

from src.local_ai_hub.incident_intelligence import (
    FailureFingerprinter,
    ProactiveNegativeKnowledgeAdvisory,
)


def test_failure_fingerprint_normalization():
    trace_1 = """
Traceback (most recent call last):
  File "C:\\Users\\Adam\\AppData\\Local\\Temp\\tmpa_j9_xha.jsonl", line 45, in <module>
    open(path, 'r')
PermissionError: [Errno 13] Permission denied: 'C:\\Users\\Adam\\AppData\\Local\\Temp\\tmpa_j9_xha.jsonl'
"""
    trace_2 = """
Traceback (most recent call last):
  File "C:\\Users\\Adam\\AppData\\Local\\Temp\\tmpb_k8_yza.jsonl", line 89, in <module>
    open(path, 'r')
PermissionError: [Errno 13] Permission denied: 'C:\\Users\\Adam\\AppData\\Local\\Temp\\tmpb_k8_yza.jsonl'
"""
    fp1 = FailureFingerprinter.extract_fingerprint(trace_1, exit_code=1)
    fp2 = FailureFingerprinter.extract_fingerprint(trace_2, exit_code=1)

    assert fp1.failure_class == "FILE_LOCK_PERMISSION_DENIED"
    assert fp2.failure_class == "FILE_LOCK_PERMISSION_DENIED"
    # Even though file names and line numbers differ, normalized canonical signature matches!
    assert fp1.canonical_signature == fp2.canonical_signature


def test_proactive_negative_knowledge_warning():
    # Dangerous bare pytest
    w1 = ProactiveNegativeKnowledgeAdvisory.audit_command("pytest")
    assert w1 is not None
    assert w1.warning_code == "UNCONSTRAINED_BARE_PYTEST"
    assert "Specify targeted test file" in w1.recommended_alternative

    # Destructive git command
    w2 = ProactiveNegativeKnowledgeAdvisory.audit_command("git reset --hard HEAD")
    assert w2 is not None
    assert w2.warning_code == "DESTRUCTIVE_GIT_RESET"

    # Safe targeted command -> No warning
    w3 = ProactiveNegativeKnowledgeAdvisory.audit_command("pytest tests/test_my_feature.py -q")
    assert w3 is None
