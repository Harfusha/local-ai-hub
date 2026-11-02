import json

import pytest

from local_ai_hub import mcp_server
from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.token_accounting import json_tokens


@pytest.mark.parametrize("limit", [128, 256, 512, 1024, 4096])
def test_artifact_get_is_exact_or_explicitly_rejected(tmp_path, monkeypatch, limit):
    store = ArtifactStore(tmp_path)
    content = "ž🙂\\x\n" * 900
    artifact_id = store.put(content, kind="text")
    def post(path, payload, **kwargs):
        return store.get(payload["artifact_id"], offset=payload.get("offset", 0),
                         max_chars=payload.get("max_chars", 4000))
    monkeypatch.setattr(mcp_server.CLIENT, "post", post)
    result = mcp_server.local_ai_artifact(action="get", artifact_id=artifact_id, max_response_tokens=limit)
    if limit == 4096:
        assert result["success"] is True
    if result["success"]:
        assert result["text"] == content[:4000]
        assert result["next_offset"] == 4000
    else:
        assert result.get("status_code") != 500
        assert "output contract failed" not in result["error"]


@pytest.mark.parametrize("limit", [128, 256, 1024, 4096])
def test_wire_projection_never_silently_corrupts_page(tmp_path, limit):
    store = ArtifactStore(tmp_path)
    artifact_id = store.put("ž🙂\\x\n" * 900, kind="text")
    page = store.get(artifact_id, max_chars=4000)
    content, result = mcp_server._mcp_budget_payload(
        "local_ai_artifact", {"action": "get", "max_response_tokens": limit}, page,
    )
    if result.get("success"):
        assert result["text"] == page["text"]
        assert result["next_offset"] == page["next_offset"]
        assert json.loads(content[0].text)["text"] == page["text"]
    else:
        assert result.get("status_code") != 500
    wire = {"content": [item.model_dump(mode="json", exclude_none=True) for item in content],
            "structuredContent": result, "isError": False}
    assert json_tokens(wire) <= limit


def test_small_page_succeeds_and_offset_tracks_exact_text(tmp_path, monkeypatch):
    store = ArtifactStore(tmp_path)
    text = "ž🙂" * 200
    artifact_id = store.put(text, kind="text")
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda path, payload, **kwargs: store.get(
        payload["artifact_id"], offset=payload.get("offset", 0), max_chars=payload.get("max_chars", 4000)))
    result = mcp_server.local_ai_artifact(action="get", artifact_id=artifact_id,
                                          offset=10, max_chars=40, max_response_tokens=1024)
    assert result["success"] is True
    assert result["text"] == text[10:50]
    assert result["next_offset"] == 50


@pytest.mark.parametrize("limit", [128, 256, 1024, 4096])
def test_multi_slice_is_exact_or_rejected(tmp_path, monkeypatch, limit):
    store = ArtifactStore(tmp_path)
    text = "abcž🙂" * 600
    artifact_id = store.put(text, kind="text")
    requested = [{"offset": 0, "max_chars": 800}, {"offset": 1000, "max_chars": 800}]
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda path, payload, **kwargs: store.get_slices(
        payload["artifact_id"], slices=payload["slices"]))
    result = mcp_server.local_ai_artifact(action="slice", artifact_id=artifact_id,
                                          slices=requested, max_response_tokens=limit)
    if result.get("success"):
        assert result["slices"] == [{"offset": 0, "text": text[:800]},
                                     {"offset": 1000, "text": text[1000:1800]}]
    else:
        assert result.get("status_code") != 500
        assert "output contract failed" not in result["error"]
