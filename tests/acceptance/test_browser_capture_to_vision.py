from __future__ import annotations

import base64
import hashlib
import json

import pytest

from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.browser_bridge import capture_to_artifacts
from local_ai_hub.vision_inputs import VisionInputs, prepare_vision_inputs


def _capture_payload(*, screenshot: bytes = b"png-fixture", html: str = "<main>fixture</main>") -> dict:
    return {
        "origin": "chrome-extension://acceptance",
        "privacy_mode": "full_local_capture",
        "privacy_notice_acknowledged": True,
        "full_capture_acknowledged": True,
        "screenshot_redaction": "none",
        "redaction_manifest": {},
        "tab_id": 7,
        "window_id": 3,
        "url": "https://fixture.test/checkout",
        "target_origin": "https://fixture.test",
        "title": "Checkout",
        "captured_at": "2026-11-13T10:00:00.000Z",
        "capture_identity": {
            "initial": {"url": "https://fixture.test/checkout", "target_origin": "https://fixture.test", "document_token": "doc:1", "document_state_token": "state:1", "relevant_state_token": "sha256:" + "a" * 64, "relevant_state_complete": True, "history_state_token": "b" * 64, "viewport_token": "1280x720@1", "interaction_observed": True},
            "final": {"url": "https://fixture.test/checkout", "target_origin": "https://fixture.test", "document_token": "doc:1", "document_state_token": "state:1", "relevant_state_token": "sha256:" + "a" * 64, "relevant_state_complete": True, "history_state_token": "b" * 64, "viewport_token": "1280x720@1", "interaction_observed": True},
        },
        "screenshot": "data:image/png;base64," + base64.b64encode(screenshot).decode("ascii"),
        "dom": {"redaction": "none", "html": html, "elements": [], "snapshot_digest": "sha256:" + hashlib.sha256(html.encode()).hexdigest()},
        "accessibility": {"snapshot": []},
        "computed_styles": {},
        "runtime": {},
        "viewport": {"width": 1280, "height": 720},
    }


def _large_capture_config() -> dict:
    return {"browser_bridge": {"max_payload_bytes": 12_000_000, "max_dom_chars": 2_000_000, "max_elements": 512, "max_screenshot_bytes": 8_000_000}}


def _read_full_artifact(store: ArtifactStore, artifact_id: str) -> str:
    offset = 0
    chunks = []
    while True:
        page = store.get(artifact_id, offset=offset, max_chars=50_000)
        assert page["success"] is True
        chunks.append(page["text"])
        if page["next_offset"] is None:
            return "".join(chunks)
        offset = page["next_offset"]


def test_browser_capture_artifacts_reach_vision_with_privacy_provenance(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    html = "<main><h1>Checkout</h1><button>Pay</button></main>"
    payload = {
        "origin": "chrome-extension://acceptance",
        "privacy_mode": "privacy_redacted",
        "privacy_notice_acknowledged": True,
        "full_capture_acknowledged": False,
        "screenshot_redaction": "opaque_region_mask",
        "screenshot_redaction_regions": 1,
        "redaction_manifest": {"credential": 1, "screenshot_regions": 1},
        "tab_id": 7,
        "window_id": 3,
        "url": "https://fixture.test/checkout",
        "target_origin": "https://fixture.test",
        "title": "Checkout",
        "captured_at": "2026-11-13T10:00:00.000Z",
        "capture_identity": {
            "initial": {"url": "https://fixture.test/checkout", "target_origin": "https://fixture.test", "document_token": "doc:1", "document_state_token": "state:1", "relevant_state_token": "sha256:" + "a" * 64, "relevant_state_complete": True, "history_state_token": "b" * 64, "viewport_token": "1280x720@1", "interaction_observed": True},
            "final": {"url": "https://fixture.test/checkout", "target_origin": "https://fixture.test", "document_token": "doc:1", "document_state_token": "state:1", "relevant_state_token": "sha256:" + "a" * 64, "relevant_state_complete": True, "history_state_token": "b" * 64, "viewport_token": "1280x720@1", "interaction_observed": True},
        },
        "screenshot": "data:image/png;base64," + base64.b64encode(b"png-fixture").decode("ascii"),
        "dom": {"redaction": "deterministic", "html": html, "elements": [], "snapshot_digest": "sha256:" + hashlib.sha256(html.encode()).hexdigest()},
        "accessibility": {"snapshot": []},
        "computed_styles": {},
        "runtime": {},
        "viewport": {"width": 1280, "height": 720},
    }
    config = {"browser_bridge": {"max_payload_bytes": 200_000, "max_dom_chars": 20_000, "max_elements": 16, "max_screenshot_bytes": 20_000}}

    capture = capture_to_artifacts(payload, artifacts=store, config=config)
    assert capture["success"] is True
    prepared = prepare_vision_inputs(
        args={"bundle_artifact_id": capture["bundle_artifact_id"]},
        image_path="",
        prompt="Review visible checkout layout.",
        artifacts=store,
    )

    assert isinstance(prepared, VisionInputs)
    assert prepared.frontend_bundle["dom"]["review_completeness"] == "complete"
    bundle = json.loads(store.get(capture["bundle_artifact_id"])["text"])
    assert bundle["privacy"]["mode"] == "privacy_redacted"
    assert bundle["privacy"]["redaction_manifest"] == payload["redaction_manifest"]
    image = store.get_binary(capture["screenshot_artifact_id"])
    assert image["success"] is True and image["kind"] == "browser-screenshot"


@pytest.mark.parametrize(("image_size", "review_ready"), [(3_900_000, True), (4_100_000, False), (7_000_000, False)])
def test_capture_screenshot_size_boundary_preserves_origin_and_reports_recovery(tmp_path, image_size, review_ready) -> None:
    store = ArtifactStore(tmp_path)
    image_bytes = b"P" + (b"x" * (image_size - 1))

    capture = capture_to_artifacts(_capture_payload(screenshot=image_bytes), artifacts=store, config=_large_capture_config())

    assert capture.get("success") is True, capture
    assert capture["capture_success"] is True
    assert capture["review_ready"] is review_ready
    image = store.get_binary(capture["screenshot_artifact_id"])
    assert image["success"] is True
    assert image["size_bytes"] == image_size
    assert image["data_base64"] == base64.b64encode(image_bytes).decode("ascii")
    if review_ready:
        assert capture["review_not_ready_reasons"] == []
        assert capture["review_recovery"] == []
    else:
        assert "screenshot_exceeds_vision_image_limit" in capture["review_not_ready_reasons"]
        assert capture["review_recovery"] == ["recapture_at_smaller_viewport_or_image_scale"]


@pytest.mark.parametrize("html_size", [8_000, 14_000, 500_000, 1_900_000])
def test_dom_projection_reports_loss_and_retains_raw_capture(tmp_path, html_size) -> None:
    store = ArtifactStore(tmp_path)
    html = "<main>" + ("x" * (html_size - 13)) + "</main>"

    capture = capture_to_artifacts(_capture_payload(html=html), artifacts=store, config=_large_capture_config())

    assert capture["capture_success"] is True
    raw = json.loads(_read_full_artifact(store, capture["raw_dom_artifact_id"]))
    projection = json.loads(_read_full_artifact(store, capture["review_dom_projection_id"]))
    assert raw["html"] == html
    assert len(projection["html"]) <= 6_000
    assert projection["projection_truncated"] is True
    assert projection["review_completeness"] == "partial"
    assert capture["review_completeness"] == "partial"
