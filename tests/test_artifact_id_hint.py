import sqlite3
import hashlib
from contextlib import closing

import pytest

from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub import mcp_server


@pytest.mark.parametrize("method", ["get", "get_slices"])
def test_missing_id_hint_does_not_guess_or_change_normal_errors(tmp_path, method):
    store = ArtifactStore(tmp_path)
    actual_id = store.put("private content", kind="text")

    def read(artifact_id):
        if method == "get":
            return store.get(artifact_id)
        return store.get_slices(artifact_id, slices=[{"offset": 0, "max_chars": 100}])

    malformed = read(actual_id + "4c")
    assert malformed["success"] is False
    assert "copy the exact ID" in malformed["error"]
    assert "private content" not in str(malformed)
    assert actual_id not in malformed["error"]
    assert read("art_" + "0" * 24)["error"] == "artifact not found or expired"
    assert read(actual_id)["success"] is True


def test_existing_legacy_id_remains_accessible(tmp_path):
    store = ArtifactStore(tmp_path)
    artifact_id = store.put("legacy content", kind="text")
    legacy_id = "art_legacy"
    with closing(sqlite3.connect(tmp_path / "artifacts.sqlite3")) as con:
        with con:
            con.execute("UPDATE artifacts SET artifact_id=? WHERE artifact_id=?", (legacy_id, artifact_id))
            metadata = con.execute("SELECT section_json FROM artifact_paging_metadata WHERE artifact_id=?", (artifact_id,)).fetchone()[0]
            metadata = metadata.replace(artifact_id, legacy_id)
            checksum = hashlib.sha256(metadata.encode("utf-8")).hexdigest()
            con.execute("UPDATE artifact_paging_metadata SET artifact_id=?, section_json=?, section_checksum=? WHERE artifact_id=?", (legacy_id, metadata, checksum, artifact_id))
    result = store.get(legacy_id)
    assert result.get("text") == "legacy content", result
    assert store.get_slices(legacy_id, slices=[{"offset": 0, "max_chars": 100}])["success"] is True


@pytest.mark.parametrize("action", ["get", "slice"])
def test_mcp_retains_exact_copy_hint(tmp_path, monkeypatch, action):
    store = ArtifactStore(tmp_path)
    actual_id = store.put("private content", kind="text")

    def post(path, payload, **kwargs):
        if "slices" in payload:
            return store.get_slices(payload["artifact_id"], slices=payload["slices"])
        return store.get(payload["artifact_id"])

    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    options = {"slices": [{"offset": 0, "max_chars": 100}]} if action == "slice" else {}
    result = mcp_server.local_ai_artifact(action=action, artifact_id=actual_id + "4c", **options)
    assert result["success"] is False
    assert "copy the exact ID" in result["error"]
    assert "private content" not in str(result)
