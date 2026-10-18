"""Retired selectors are checked in control envelopes, not domain payloads."""

import pytest

from local_ai_hub.conversations import Conversation
from local_ai_hub.telemetry import TelemetryStore, _retired_tenant_field


def test_conversation_preserves_retired_words_in_message_content_and_nested_domain_data():
    domain = {"model_output": {"tenant": "user-provided value"}}
    content = {"captured": ["tenant", {"tenant_key": "literal data"}]}
    conversation = Conversation(
        conversation_id="conversation-1",
        settings={"metadata": {"source": "user"}},
        messages=[{"role": "assistant", "content": content, "domain": domain}],
    )

    assert conversation.messages[0]["content"] is content
    assert conversation.messages[0]["domain"] is domain


@pytest.mark.parametrize("field", ["tenant", "tenant_id", "tenant_key", "tenant_scope"])
@pytest.mark.parametrize("value", [None, False, ""])
def test_conversation_rejects_retired_fields_in_declared_control_envelopes(field, value):
    with pytest.raises(ValueError, match="retired"):
        Conversation(conversation_id="conversation-1", settings={"metadata": {field: value}})
    with pytest.raises(ValueError, match="retired"):
        Conversation(
            conversation_id="conversation-1", settings={},
            messages=[{"role": "assistant", "metadata": {field: value}}],
        )


def test_conversation_does_not_scan_nested_or_content_domain_mappings():
    conversation = Conversation(
        conversation_id="conversation-1",
        settings={"metadata": {"domain": {"tenant": "domain field"}}},
        messages=[{"role": "assistant", "content": {"tenant": "quoted data"}}],
    )
    assert conversation.messages[0]["content"] == {"tenant": "quoted data"}


def test_telemetry_checks_only_event_and_one_direct_metadata_dictionary():
    assert _retired_tenant_field({"metadata": {"tenant": "retired control"}})
    assert not _retired_tenant_field({"context": {"domain": {"tenant": "opaque output"}}})
    assert not _retired_tenant_field({"response": {"metadata": {"tenant": "domain output"}}})
    assert _retired_tenant_field([{"scope": {"tenant_key": False}}])


def test_telemetry_clean_event_accepts_tenant_text_inside_domain_result():
    cleaned = TelemetryStore._clean_event({
        "event_type": "inference",
        "context": {"model_result": {"tenant": "captured user data"}},
    })
    assert cleaned["event_type"] == "inference"


@pytest.mark.parametrize("field", ["tenant", "tenant_id", "tenant_key", "tenant_scope"])
@pytest.mark.parametrize("value", [None, False, ""])
def test_telemetry_rejects_retired_fields_at_event_or_direct_metadata(field, value):
    assert _retired_tenant_field({field: value})
    assert _retired_tenant_field({"provenance": {field: value}})
