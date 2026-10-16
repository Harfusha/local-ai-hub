import pytest
from pathlib import Path

from local_ai_hub.state_paths import (
    _clean_dir_candidate,
    get_fallback_state_dir,
    cleanup_fallback_state_dir,
)
from local_ai_hub.artifacts import ArtifactStore


def test_state_paths_clean_candidate():
    assert _clean_dir_candidate(True) is None
    assert _clean_dir_candidate(False) is None
    assert _clean_dir_candidate(None) is None
    assert _clean_dir_candidate("") is None
    assert _clean_dir_candidate("   ") is None
    with pytest.raises(ValueError):
        _clean_dir_candidate("path\x00bad")

    candidate = _clean_dir_candidate("valid/path")
    assert isinstance(candidate, Path)


def test_state_paths_fallback_dir_boolean_guard():
    assert get_fallback_state_dir(True) is None
    assert get_fallback_state_dir(False) is None
    assert cleanup_fallback_state_dir(True) is False
    assert cleanup_fallback_state_dir(False) is False


def test_artifacts_store_null_state_dir():
    with pytest.raises(ValueError, match="invalid state_dir"):
        ArtifactStore("bad\x00path")


def test_artifacts_tenant_identity_null_byte():
    with pytest.raises(ValueError, match="null byte"):
        ArtifactStore._tenant_identity("bad\x00tenant")


def test_artifacts_get_and_binary_invalid_id(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")

    # Invalid artifact_id in get
    res_get = store.get("")
    assert res_get["success"] is False
    assert "invalid artifact_id" in res_get["error"]

    res_get_null = store.get("art\x00id")
    assert res_get_null["success"] is False
    assert "invalid artifact_id" in res_get_null["error"]

    # Invalid artifact_id in get_binary
    res_bin = store.get_binary("")
    assert res_bin["success"] is False
    assert "invalid artifact_id" in res_bin["error"]

    res_bin_null = store.get_binary("art\x00id")
    assert res_bin_null["success"] is False
    assert "invalid artifact_id" in res_bin_null["error"]
