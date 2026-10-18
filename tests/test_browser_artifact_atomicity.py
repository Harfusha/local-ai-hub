from __future__ import annotations

import base64
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.artifacts import ArtifactStore
from local_ai_hub.browser_bridge import capture_to_artifacts


def _config() -> dict:
    return {"browser_bridge": {"max_payload_bytes": 200_000, "max_dom_chars": 20_000, "max_elements": 16,
                               "max_screenshot_bytes": 20_000}}


def _payload() -> dict:
    return {
        "origin": "chrome-extension://fixture",
        "tab_id": 7,
        "window_id": 3,
        "url": "https://fixture.test/checkout",
        "target_origin": "https://fixture.test",
        "title": "Checkout",
        "captured_at": "2026-09-18T10:20:30.123Z",
        "capture_identity": {"initial": {
            "url": "https://fixture.test/checkout", "target_origin": "https://fixture.test",
            "document_token": "doc:1", "document_state_token": "state:1",
        }, "final": {
            "url": "https://fixture.test/checkout", "target_origin": "https://fixture.test",
            "document_token": "doc:1", "document_state_token": "state:1",
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


@pytest.mark.parametrize("fail_insert", range(1, 7))
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


def test_capture_batch_is_readable_and_deduplicated(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    first = capture_to_artifacts(_payload(), artifacts=store, config=_config())
    replay = capture_to_artifacts(_payload(), artifacts=store, config=_config())

    assert first["success"] is replay["success"] is True
    assert first["bundle_artifact_id"] == replay["bundle_artifact_id"]
    bundle = store.get(first["bundle_artifact_id"])
    assert bundle["success"] is True
    bundle_value = json.loads(bundle["text"])
    assert store.get(bundle_value["dom"]["artifact_id"])["success"] is True


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
