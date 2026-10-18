"""Verification authority comes from actual task/root pins, never a tenant selector."""

import pytest

from local_ai_hub.agent_verification import _receipt_evidence_matches


@pytest.mark.parametrize("value", [None, False, "", "former-tenant"])
def test_receipt_lookup_rejects_retired_trusted_tenant_before_artifact_access(value):
    with pytest.raises(TypeError, match="trusted_tenant"):
        _receipt_evidence_matches(
            None, None, expected_owner="task-writer", require_repository_revision=True,
            trusted_tenant=value,
        )
