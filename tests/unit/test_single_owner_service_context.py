"""Retired service identity inputs reject before inference or filesystem work."""

import threading

import pytest

from local_ai_hub.services import LocalAIServices


@pytest.mark.parametrize("value", [None, False, "", "old-owner"])
def test_generation_rejects_tenant_before_model_admission(value):
    services = LocalAIServices.__new__(LocalAIServices)
    with pytest.raises(TypeError, match="tenant"):
        services._generate("model", "prompt", "system", 128, 0.0,
                           source="reason", priority=4, tenant=value)


def test_generation_rejects_former_positional_identity():
    with pytest.raises(TypeError):
        LocalAIServices.__new__(LocalAIServices)._generate(
            "model", "prompt", "system", 128, 0.0, "old-owner", "reason", 4,
        )


@pytest.mark.parametrize("method", ["_hybrid_context", "_hybrid_context_uncached"])
@pytest.mark.parametrize("value", [None, False, "", "old-owner"])
def test_hybrid_context_has_no_identity_slot(method, value):
    operation = getattr(LocalAIServices.__new__(LocalAIServices), method)
    with pytest.raises(TypeError, match="tenant"):
        operation("root", "question", workspace="project-index", max_tokens=128, tenant=value)
    with pytest.raises(TypeError):
        operation("root", "question", value, "project-index", 128)


def query_service():
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {}
    service._focus_lock = threading.Lock()
    service._recent_focus_symbols = {}
    return service


def test_query_focus_retains_repository_and_session_separation(tmp_path):
    service = query_service()
    repository = tmp_path / "repository"
    other = tmp_path / "other"
    repository.mkdir()
    other.mkdir()
    service.expand_query("Inspect SecretSymbol", root=str(repository), session_id="chat-one")
    assert "SecretSymbol" in service.expand_query("find it", root=str(repository), session_id="chat-one")
    assert "SecretSymbol" not in service.expand_query("find it", root=str(other), session_id="chat-one")
    assert "SecretSymbol" not in service.expand_query("find it", root=str(repository), session_id="chat-two")
    assert "SecretSymbol" not in service.expand_query("find it")


def test_query_owner_global_focus_has_no_manufactured_identity():
    service = query_service()
    service.expand_query("Inspect SharedSymbol")
    assert "SharedSymbol" in service.expand_query("find it")
    with pytest.raises(TypeError, match="tenant"):
        service.expand_query("find it", tenant=None)


@pytest.mark.parametrize("field,value", [("root", None), ("root", " bad "),
                                         ("session_id", False), ("session_id", "chat\x00one")])
def test_query_scope_inputs_do_not_coerce(field, value):
    with pytest.raises(ValueError):
        query_service().expand_query("find it", **{field: value})


@pytest.mark.parametrize("method", ["delegate", "delegate_profile", "continue_conversation",
                                   "reason", "review", "second_opinion"])
@pytest.mark.parametrize("field", ["tenant", "tenant_key", "tenant_id", "tenant_scope"])
@pytest.mark.parametrize("value", [None, False, ""])
def test_semantic_service_payloads_reject_retired_identity_before_resources(method, field, value):
    operation = getattr(LocalAIServices.__new__(LocalAIServices), method)
    with pytest.raises(ValueError, match="retired"):
        operation({field: value})
