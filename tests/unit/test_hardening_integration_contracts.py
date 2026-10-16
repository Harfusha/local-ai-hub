"""Integration regressions: malformed identities must not gain default authority."""
from pathlib import Path

import pytest

from local_ai_hub.agent_events import AgentEvent
from local_ai_hub.process_utils import canonical_root
from local_ai_hub.preprocess import _project_git_identity
from local_ai_hub.scheduler import AffinityScheduler
from local_ai_hub.semantic_cache import SemanticGenerationCache


@pytest.mark.parametrize("root", [None, False, 3, "", "bad\x00root"])
def test_canonical_root_rejects_invalid_identity(root):
    with pytest.raises((TypeError, ValueError)):
        canonical_root(root)


def test_valid_root_keeps_its_repository_identity(tmp_path: Path):
    assert canonical_root(tmp_path) == str(tmp_path.resolve())
    assert _project_git_identity(str(tmp_path)) == (str(tmp_path.resolve()), False)


@pytest.mark.parametrize("root", [None, False, "", "bad\x00root"])
def test_preprocessing_does_not_sanitize_invalid_git_identity(root):
    assert _project_git_identity(root) == ("", False)


@pytest.mark.parametrize("scope", [False, 0, [], {}, "bad\x00scope"])
def test_invalid_cache_scope_rejects_before_opening_database(scope):
    cache = object.__new__(SemanticGenerationCache)
    with pytest.raises(ValueError):
        cache.clear(scope)


@pytest.mark.parametrize("state_dir", [None, False, 3, "", "bad\x00path"])
def test_cache_rejects_invalid_state_path_without_database(tmp_path, monkeypatch, state_dir):
    monkeypatch.chdir(tmp_path)
    with pytest.raises((TypeError, ValueError)):
        SemanticGenerationCache({"server": {"state_dir": state_dir}}, None)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("field,value", [
    ("event_id", ""), ("stream_id", False), ("actor", "bad\x00actor"),
    ("payload", []), ("created_at", True), ("created_at", float("nan")),
    ("created_at", 10**1000), ("seq", True), ("seq", "1"),
])
def test_events_reject_corrupt_provenance(field, value):
    data = dict(event_id="evt", stream_id="stream", kind="created", payload={},
                idempotency_key="key", correlation_id="", actor="agent", created_at=0)
    data[field] = value
    with pytest.raises((TypeError, ValueError)):
        AgentEvent.from_dict(data)


def test_persisted_event_does_not_fabricate_missing_identity():
    with pytest.raises(KeyError):
        AgentEvent.from_dict({"stream_id": "stream"})


@pytest.mark.parametrize("field,value", [
    ("tenant", False), ("tenant", "bad\x00tenant"), ("source", []),
    ("priority", True), ("priority", "5"), ("wait_timeout", float("inf")),
])
def test_scheduler_rejects_invalid_caller_before_queue_access(field, value):
    scheduler = object.__new__(AffinityScheduler)
    args = dict(model="model", tenant="tenant", source="source", execute=lambda: {})
    args[field] = value
    with pytest.raises(ValueError):
        scheduler.submit(**args)
