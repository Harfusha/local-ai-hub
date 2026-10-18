from local_ai_hub.artifacts import ArtifactStore


def test_json_section_pagination_uses_requested_offset(tmp_path):
    payload = "A" * 256 + "B" * 256 + "C" * 128
    store = ArtifactStore(tmp_path)
    artifact_id = store.put_json(
        {"payload": payload}, kind="test-json"
    )

    first = store.get(
        artifact_id,
        offset=0,
        max_chars=256,
        section="json:payload",
    )
    second = store.get(
        artifact_id,
        offset=first["next_offset"],
        max_chars=256,
        section="json:payload",
    )
    third = store.get(
        artifact_id,
        offset=second["next_offset"],
        max_chars=256,
        section="json:payload",
    )

    assert first["text"] == payload[:256]
    assert second["text"] == payload[256:512]
    assert third["text"] == payload[512:]
    assert first["next_offset"] == 256
    assert second["next_offset"] == 512
    assert third["next_offset"] is None
    assert first["text"] + second["text"] + third["text"] == payload


def test_json_section_pagination_stops_at_exact_end_of_second_page(tmp_path):
    payload = "A" * 256 + "B" * 256
    store = ArtifactStore(tmp_path)
    artifact_id = store.put_json(
        {"payload": payload}, kind="test-json"
    )

    first = store.get(
        artifact_id,
        offset=0,
        max_chars=256,
        section="json:payload",
    )
    second = store.get(
        artifact_id,
        offset=first["next_offset"],
        max_chars=256,
        section="json:payload",
    )
    at_end = store.get(
        artifact_id,
        offset=512,
        max_chars=256,
        section="json:payload",
    )

    assert first["text"] == payload[:256]
    assert second["text"] == payload[256:512]
    assert second["next_offset"] is None
    assert at_end["text"] == ""
    assert at_end["next_offset"] is None
