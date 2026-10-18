from __future__ import annotations

import pytest

from local_ai_hub.async_jobs import AsyncJobManager


@pytest.mark.parametrize("field", ["answer", "result", "data", "value", "text", "request", "response", "captured_request", "captured_response"])
def test_async_result_domain_content_remains_opaque(field):
    value = {field: {"nested": {"tenant": "domain content"}}}
    AsyncJobManager._validate_persisted_result_fields(value)


@pytest.mark.parametrize("field", ["control", "metadata", "provenance"])
def test_async_result_declared_envelope_fields_reject_retired_keys(field):
    with pytest.raises(RuntimeError, match="async result envelope"):
        AsyncJobManager._validate_persisted_result_fields({field: {"tenant_key": "retired"}})


def test_async_result_top_level_retired_control_rejects():
    with pytest.raises(RuntimeError, match="async result envelope"):
        AsyncJobManager._validate_persisted_result_fields({"tenant_scope": "retired", "answer": "opaque"})


def test_async_payload_retired_root_and_nested_batch_fields_still_reject():
    with pytest.raises(RuntimeError, match="async job payload"):
        AsyncJobManager._validate_persisted_payload_fields({"tenant": "retired"})
    with pytest.raises(ValueError, match="retired async job field"):
        AsyncJobManager._validate_persisted_payload_fields({"tasks": [{"tenant_id": "retired"}]})


def test_async_payload_nested_domain_content_remains_opaque():
    AsyncJobManager._validate_persisted_payload_fields({"request": {"tenant": "captured user content"}})
