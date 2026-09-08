from __future__ import annotations

import pytest
from local_ai_hub.http_server import Handler, RequestBodyError


def test_memory_put_validation_requires_key_and_value():
    # Empty key raises RequestBodyError
    with pytest.raises(RequestBodyError, match="key is required"):
        Handler._validate_payload("/api/memory/put", {"key": "", "value": "test"})

    # Missing key raises RequestBodyError
    with pytest.raises(RequestBodyError, match="key is required"):
        Handler._validate_payload("/api/memory/put", {"value": "test"})

    # Key exceeding 160 characters raises RequestBodyError
    with pytest.raises(RequestBodyError, match="key must be a string of at most 160 characters"):
        Handler._validate_payload("/api/memory/put", {"key": "k" * 161, "value": "test"})

    # Empty value raises RequestBodyError
    with pytest.raises(RequestBodyError, match="value is required"):
        Handler._validate_payload("/api/memory/put", {"key": "my_key", "value": ""})

    # Missing value raises RequestBodyError
    with pytest.raises(RequestBodyError, match="value is required"):
        Handler._validate_payload("/api/memory/put", {"key": "my_key"})

    # Valid payload passes
    Handler._validate_payload("/api/memory/put", {"key": "my_key", "value": "my_value"})


def test_memory_get_and_delete_validation_requires_key():
    for path in ("/api/memory/get", "/api/memory/delete"):
        with pytest.raises(RequestBodyError, match="key is required"):
            Handler._validate_payload(path, {"key": ""})

        with pytest.raises(RequestBodyError, match="key must be a string of at most 160 characters"):
            Handler._validate_payload(path, {"key": "x" * 161})

        Handler._validate_payload(path, {"key": "valid_key"})


def test_memory_store_clean_key_and_value(tmp_path):
    from local_ai_hub.memory import WorkspaceMemoryStore

    store = WorkspaceMemoryStore(tmp_path)
    with pytest.raises(ValueError, match="memo key must be 1..160 characters"):
        store.put(".", "", "val", "tenant")

    with pytest.raises(ValueError, match="memo key must be 1..160 characters"):
        store.put(".", "   ", "val", "tenant")

    with pytest.raises(ValueError, match="memo key must be 1..160 characters"):
        store.put(".", "k" * 161, "val", "tenant")

    with pytest.raises(ValueError, match="memo value must not be empty"):
        store.put(".", "valid_key", "", "tenant")

    with pytest.raises(ValueError, match="memo value must not be empty"):
        store.put(".", "valid_key", "   ", "tenant")

