from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.browser_bridge import capture_to_artifacts, validate_capture_payload
from local_ai_hub.vision_inputs import VisionInputs, prepare_vision_inputs


def _config() -> dict:
    return {"browser_bridge": {"max_payload_bytes": 200_000, "max_dom_chars": 20_000, "max_elements": 16,
                               "max_screenshot_bytes": 20_000}}


def _payload() -> dict:
    return {
        "origin": "chrome-extension://fixture",
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
        "captured_at": "2026-09-18T10:20:30.123Z",
        "capture_identity": {"initial": {
            "url": "https://fixture.test/checkout", "target_origin": "https://fixture.test",
            "document_token": "doc:1", "document_state_token": "state:1",
            "relevant_state_token": "sha256:" + "a" * 64, "relevant_state_complete": True,
            "history_state_token": "b" * 64, "viewport_token": "1280x720@1", "interaction_observed": True,
        }, "final": {
            "url": "https://fixture.test/checkout", "target_origin": "https://fixture.test",
            "document_token": "doc:1", "document_state_token": "state:1",
            "relevant_state_token": "sha256:" + "a" * 64, "relevant_state_complete": True,
            "history_state_token": "b" * 64, "viewport_token": "1280x720@1", "interaction_observed": True,
        }},
        "screenshot": "data:image/png;base64," + base64.b64encode(b"png-fixture").decode("ascii"),
        "dom": {"redaction": "none", "html": "<main>Pay</main>", "elements": []},
        "accessibility": {"snapshot": []},
        "computed_styles": {},
        "runtime": {},
        "viewport": {"width": 1280, "height": 720},
    }


class _FailingConnection:
    def __init__(self, connection, *, fail_insert: int | None = None, fail_commit: bool = False):
        self._connection = connection
        self._fail_insert = fail_insert
        self._fail_commit = fail_commit
        self.inserts = 0

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def execute(self, sql, parameters=()):
        if sql.lstrip().upper().startswith("INSERT OR REPLACE INTO ARTIFACTS"):
            self.inserts += 1
            if self.inserts == self._fail_insert:
                raise sqlite3.OperationalError("injected insert failure")
        return self._connection.execute(sql, parameters)

    def commit(self):
        if self._fail_commit:
            raise sqlite3.OperationalError("injected commit failure")
        return self._connection.commit()


@pytest.mark.parametrize("fail_insert", range(1, 8))
def test_capture_rolls_back_every_artifact_when_any_insert_fails(tmp_path: Path, monkeypatch, fail_insert: int) -> None:
    store = ArtifactStore(tmp_path)
    connect = store._connect
    monkeypatch.setattr(store, "_connect", lambda: _FailingConnection(connect(), fail_insert=fail_insert))

    result = capture_to_artifacts(_payload(), artifacts=store, config=_config())

    assert result["success"] is False
    with closing(connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0


def test_capture_rolls_back_all_artifacts_when_commit_fails(tmp_path: Path, monkeypatch) -> None:
    store = ArtifactStore(tmp_path)
    connect = store._connect
    monkeypatch.setattr(store, "_connect", lambda: _FailingConnection(connect(), fail_commit=True))

    result = capture_to_artifacts(_payload(), artifacts=store, config=_config())

    assert result["success"] is False
    with closing(connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0


def test_purge_browser_capture_by_bundle_preserves_shared_artifacts(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    first = capture_to_artifacts(_payload(), artifacts=store, config=_config())
    second = capture_to_artifacts(_payload(), artifacts=store, config=_config())

    assert first["success"] is True and second["success"] is True
    assert first["bundle_artifact_id"] != second["bundle_artifact_id"]

    purged_first = store.purge_browser_capture(first["bundle_artifact_id"])

    assert purged_first == {
        "success": True,
        "bundle_artifact_id": first["bundle_artifact_id"],
        "deleted_count": 1,
        "retained_shared_count": 6,
    }
    assert store.kind(first["bundle_artifact_id"]) is None
    assert store.kind(second["bundle_artifact_id"]) == "frontend-review-bundle"
    assert store.kind(second["screenshot_artifact_id"]) == "browser-screenshot"

    purged_second = store.purge_browser_capture(second["bundle_artifact_id"])

    assert purged_second["success"] is True
    assert purged_second["deleted_count"] == 7
    assert purged_second["retained_shared_count"] == 0


def test_purge_browser_capture_rejects_non_capture_artifacts(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    ordinary = store.put_json({"private": "value"}, kind="ordinary")

    result = store.purge_browser_capture(ordinary)

    assert result == {
        "success": False,
        "error_code": "browser_capture_not_found",
        "bundle_artifact_id": ordinary,
    }


def test_failed_batch_preserves_preexisting_shared_content_addressed_row(tmp_path: Path, monkeypatch) -> None:
    store = ArtifactStore(tmp_path)
    existing = {"redaction": "none", "html": "<main>Pay</main>", "elements": []}
    artifact_id = store.put_json(existing, kind="browser-dom")
    existing_created_at = time.time() - 60
    with closing(store._connect()) as con:
        con.execute("UPDATE artifacts SET created_at=? WHERE artifact_id=?", (existing_created_at, artifact_id))
        con.commit()
    connect = store._connect
    monkeypatch.setattr(store, "_connect", lambda: _FailingConnection(connect(), fail_insert=6))

    result = capture_to_artifacts(_payload(), artifacts=store, config=_config())

    assert result["success"] is False
    stored = store.get(artifact_id)
    assert stored["success"] is True
    assert json.loads(stored["text"]) == existing
    with closing(connect()) as con:
        assert con.execute("SELECT created_at FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()[0] == existing_created_at


def test_capture_batch_has_distinct_bundles_and_deduplicated_children(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    first = capture_to_artifacts(_payload(), artifacts=store, config=_config())
    replay = capture_to_artifacts(_payload(), artifacts=store, config=_config())

    assert first["success"] is replay["success"] is True
    assert first["bundle_artifact_id"] != replay["bundle_artifact_id"]
    bundle = store.get(first["bundle_artifact_id"])
    assert bundle["success"] is True
    bundle_value = json.loads(bundle["text"])
    assert store.get(bundle_value["dom"]["artifact_id"])["success"] is True
    assert store.get(bundle_value["dom"]["raw_dom_artifact_id"])["success"] is True
    replay_value = json.loads(store.get(replay["bundle_artifact_id"])["text"])
    assert replay_value["dom"]["artifact_id"] == bundle_value["dom"]["artifact_id"]
    assert replay_value["dom"]["raw_dom_artifact_id"] == bundle_value["dom"]["raw_dom_artifact_id"]
    assert first["review_ready"] is True


def test_capture_rejects_dom_snapshot_digest_mismatch() -> None:
    payload = _payload()
    payload["dom"]["snapshot_digest"] = "sha256:" + hashlib.sha256(b"different html").hexdigest()

    result = validate_capture_payload(payload, config=_config())

    assert result["success"] is False
    assert result["error_code"] == "dom_snapshot_digest_mismatch"


def test_capture_bundle_resolves_through_vision_review_contract(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    capture = capture_to_artifacts(_payload(), artifacts=store, config=_config())

    prepared = prepare_vision_inputs(
        args={"bundle_artifact_id": capture["bundle_artifact_id"]},
        image_path="",
        prompt="Check the checkout page for visible layout problems.",
        artifacts=store,
    )

    assert capture["review_ready"] is True
    assert isinstance(prepared, VisionInputs)
    assert prepared.frontend_bundle["dom"].get("review_completeness") == "complete", prepared.frontend_bundle["dom"]
    stored_bundle = json.loads(store.get(capture["bundle_artifact_id"])["text"])
    assert stored_bundle["dom"]["raw_dom_artifact_id"] == capture["raw_dom_artifact_id"]
    assert stored_bundle["privacy"]["mode"] == "full_local_capture"
    assert stored_bundle["privacy"]["redaction"] == "none"
    assert stored_bundle["privacy"]["retention_seconds"] == store.ttl_seconds


def test_partial_capture_prompt_restricts_review_scope(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    payload = _payload()
    payload["dom"]["html"] = "<main>" + ("x" * 20_000) + "</main>"
    capture = capture_to_artifacts(
        payload, artifacts=store,
        config={"browser_bridge": {"max_payload_bytes": 200_000, "max_dom_chars": 30_000,
                                   "max_elements": 16, "max_screenshot_bytes": 20_000}},
    )

    prepared = prepare_vision_inputs(
        args={"bundle_artifact_id": capture["bundle_artifact_id"]},
        image_path="",
        prompt="Review the page.",
        artifacts=store,
    )

    assert isinstance(prepared, VisionInputs)
    assert prepared.model_context.prompt.startswith("Review the page.")
    assert "partial projection" in prepared.model_context.prompt
    assert "do not infer that omitted page content is absent" in prepared.model_context.prompt


def test_privacy_redacted_capture_preserves_manifest_and_mode(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    payload = _payload()
    payload.update({
        "privacy_mode": "privacy_redacted",
        "privacy_notice_acknowledged": True,
        "screenshot_redaction": "opaque_region_mask",
        "screenshot_redaction_regions": 2,
        "full_capture_acknowledged": False,
        "redaction_manifest": {"credential": 1, "form_field": 1, "screenshot_regions": 2},
    })
    payload["dom"] = {"redaction": "deterministic", "html": "<main>[REDACTED]</main>", "elements": [],
                      "snapshot_digest": "sha256:" + hashlib.sha256(b"<main>[REDACTED]</main>").hexdigest()}

    checked = validate_capture_payload(payload, config=_config())
    capture = capture_to_artifacts(payload, artifacts=store, config=_config())

    assert checked["success"] is True
    assert capture["success"] is True
    bundle = json.loads(store.get(capture["bundle_artifact_id"])["text"])
    assert bundle["privacy"]["mode"] == "privacy_redacted"
    assert bundle["privacy"]["redaction"] == "deterministic"
    assert bundle["privacy"]["redaction_manifest"] == payload["redaction_manifest"]
    assert bundle["privacy"]["screenshot_redaction"] == "opaque_region_mask"
    prepared = prepare_vision_inputs(
        args={"bundle_artifact_id": capture["bundle_artifact_id"]},
        image_path="",
        prompt="Review this page.",
        artifacts=store,
    )
    assert isinstance(prepared, VisionInputs)
    assert "masked values are unknown" in prepared.model_context.prompt.lower()


def test_screenshot_only_capture_stores_no_page_content(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    payload = _payload()
    payload.update({"privacy_mode": "screenshot_only", "privacy_notice_acknowledged": True})
    payload["dom"] = {"redaction": "none", "html": "", "elements": []}
    payload["accessibility"] = {"snapshot": []}
    payload["computed_styles"] = {}
    payload["runtime"] = {"console_refs": [], "network_refs": []}

    capture = capture_to_artifacts(payload, artifacts=store, config=_config())

    assert capture["success"] is True
    bundle = json.loads(store.get(capture["bundle_artifact_id"])["text"])
    assert bundle["privacy"]["mode"] == "screenshot_only"
    assert bundle["privacy"]["payload_includes"] == ["screenshot"]
    assert store.get(bundle["dom"]["raw_dom_artifact_id"])["success"] is True
    assert json.loads(store.get(bundle["dom"]["raw_dom_artifact_id"])["text"])["html"] == ""
    unsafe = dict(payload)
    unsafe["accessibility"] = {"snapshot": [{"name": "private account number"}]}
    assert validate_capture_payload(unsafe, config=_config())["error_code"] == "screenshot_only_contains_dom"


def test_capture_bundle_masks_secret_path_segments_and_queries(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    payload = _payload()
    secret = "AbCdEf0123456789AbCdEf0123456789"
    url = f"https://fixture.test/reset/{secret}?access_token=query-secret"
    payload["url"] = url
    payload["capture_identity"]["initial"]["url"] = url
    payload["capture_identity"]["final"]["url"] = url

    capture = capture_to_artifacts(payload, artifacts=store, config=_config())

    assert capture["success"] is True
    bundle = json.loads(store.get(capture["bundle_artifact_id"])["text"])
    assert bundle["page"]["url"] == "https://fixture.test/reset/~redacted~"
    assert secret not in bundle["page"]["url"]
    assert "query-secret" not in bundle["page"]["url"]


def test_large_raw_capture_keeps_origin_and_marks_vision_limit(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, max_binary_bytes=8_000_000)
    payload = _payload()
    screenshot_bytes = b"x" * 4_100_000
    payload["screenshot"] = "data:image/png;base64," + base64.b64encode(screenshot_bytes).decode("ascii")
    config = {"browser_bridge": {"max_payload_bytes": 8_000_000, "max_dom_chars": 2_000_000,
                                  "max_elements": 256, "max_screenshot_bytes": 8_000_000}}

    result = capture_to_artifacts(payload, artifacts=store, config=config)

    assert result["success"] is True, result
    assert result["capture_success"] is True
    assert result["review_ready"] is False
    assert "screenshot_exceeds_vision_image_limit" in result["review_not_ready_reasons"]
    assert store.get_binary(result["screenshot_artifact_id"])["size_bytes"] == len(screenshot_bytes)
    review = prepare_vision_inputs(
        args={"bundle_artifact_id": result["bundle_artifact_id"]}, image_path="", prompt="Review", artifacts=store,
    )
    assert review["error_code"] == "vision_review_not_ready"
    assert review["reasons"] == result["review_not_ready_reasons"]


def test_large_dom_keeps_raw_and_emits_bounded_partial_projection(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, max_inline_chars=20_000)
    payload = _payload()
    payload["dom"]["html"] = "<main>" + ("x" * 20_000) + "</main>"

    result = capture_to_artifacts(payload, artifacts=store, config={"browser_bridge": {"max_payload_bytes": 200_000,
        "max_dom_chars": 30_000, "max_elements": 16, "max_screenshot_bytes": 20_000}})

    assert result["success"] is True, result
    assert result["review_ready"] is True
    bundle = json.loads(store.get(result["bundle_artifact_id"])["text"])
    projection_result = store.get(bundle["dom"]["artifact_id"], max_chars=20_000)
    raw_result = store.get(result["raw_dom_artifact_id"], max_chars=30_000)
    assert projection_result["success"] is True, projection_result
    assert raw_result["success"] is True, raw_result
    projection = json.loads(projection_result["text"])
    raw = json.loads(raw_result["text"])
    assert raw["html"] == payload["dom"]["html"]
    assert projection["projection_truncated"] is True
    assert bundle["dom"]["review_completeness"] == "partial"
    assert len(json.dumps(projection, ensure_ascii=False)) <= 12_000


def test_capture_cancellation_during_batch_rolls_back(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    checks = 0

    def cancel_after_some_inserts() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    result = capture_to_artifacts(
        _payload(), artifacts=store, config=_config(), cancel_check=cancel_after_some_inserts
    )

    assert result["success"] is False
    assert result["error_code"] == "capture_cancelled"
    with closing(store._connect()) as con:
        assert con.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0
