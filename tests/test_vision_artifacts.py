from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.artifacts import ArtifactStore


PNG = b"\x89PNG\r\n\x1a\n\x00\x01"


def test_binary_transport_is_available_without_changing_text_transport(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    assert callable(getattr(store, "put_bytes", None))
    artifact_id = store.put("plain text", "tenant", "text")

    result = store.get(artifact_id)
    assert result["success"] is True
    assert result["text"] == "plain text"


def test_binary_image_round_trips_with_complete_identity_metadata(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    artifact_id = store.put_bytes(PNG, "tenant", "vision-image", "image/png")
    result = store.get_binary(artifact_id)

    assert result == {
        "success": True,
        "artifact_id": artifact_id,
        "kind": "vision-image",
        "mime_type": "image/png",
        "encoding": "base64",
        "size_bytes": len(PNG),
        "checksum": hashlib.sha256(PNG).hexdigest(),
        "sha256": hashlib.sha256(PNG).hexdigest(),
        "identity": {"artifact_id": artifact_id, "kind": "vision-image"},
        "data_base64": base64.b64encode(PNG).decode("ascii"),
    }


def test_binary_transport_rejects_non_images_and_oversized_images(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, max_binary_bytes=len(PNG))

    with pytest.raises(ValueError, match="image MIME"):
        store.put_bytes(PNG, "tenant", "not-an-image", "application/json")
    with pytest.raises(ValueError, match="size"):
        store.put_bytes(PNG + b"x", "tenant", "vision-image", "image/png")


def test_review_bundle_round_trips_without_semantic_dom_redaction(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    dom = '<main data-token="dom-value"><button>Save</button></main>'
    bundle = {
        "schema_version": "1",
        "source": "current_tab",
        "screenshot": {"artifact_id": "image-ref", "mime_type": "image/png"},
        "dom": {"artifact_id": "dom-ref", "format": "live-dom", "redaction": "none"},
        "accessibility": {"artifact_id": "a11y-ref"},
        "computed_styles": {"artifact_id": "styles-ref", "scope": "visible-elements"},
        "dom_payload": dom,
    }

    artifact_id = store.put_json(bundle, "tenant", "frontend_review_bundle")
    result = store.get(artifact_id, section="json:dom")

    assert result["success"] is True
    assert json.loads(store.get(artifact_id)["text"]) == bundle
    assert json.loads(result["text"]) == bundle["dom"]


def test_binary_reads_never_return_partial_payloads(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    artifact_id = store.put_bytes(PNG, "tenant", "vision-image", "image/png")

    text_result = store.get(artifact_id, offset=1, max_chars=2)
    binary_result = store.get_binary(artifact_id)

    assert text_result["success"] is False
    assert text_result["error"] == "binary artifact requires binary retrieval"
    assert binary_result["size_bytes"] == len(PNG)
    assert base64.b64decode(binary_result["data_base64"]) == PNG


def test_invalid_binary_ref_has_bounded_sanitized_failure(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    invalid_ref = r"C:\Users\secret\Cookies.sqlite"

    result = store.get_binary(invalid_ref)

    assert result == {"success": False, "error": "artifact not found or expired"}
    assert invalid_ref not in json.dumps(result)


def test_binary_metadata_does_not_echo_tenant_path_or_credentials(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    tenant_path = r"C:\Users\secret\profile"

    artifact_id = store.put_bytes(PNG, tenant_path, "vision-image", "image/png")
    result = store.get_binary(artifact_id)

    encoded = json.dumps(result)
    assert tenant_path not in encoded
    assert "authorization" not in encoded.lower()
    assert "cookie" not in encoded.lower()
    assert "network_body" not in encoded.lower()


def test_existing_text_schema_is_migrated_without_losing_text_artifacts(tmp_path: Path) -> None:
    db_path = tmp_path / "artifacts.sqlite3"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            "CREATE TABLE artifacts (artifact_id TEXT PRIMARY KEY, created_at REAL NOT NULL, tenant TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?)",
            ("art_legacy", 9_999_999_999, "tenant", "text", "legacy"),
        )
        connection.commit()

    store = ArtifactStore(tmp_path)

    result = store.get("art_legacy")
    assert result["success"] is True
    assert result["text"] == "legacy"


def test_json_bundle_size_is_bounded(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, max_json_bytes=32)

    with pytest.raises(ValueError, match="size"):
        store.put_json({"dom": "x" * 100}, "tenant", "frontend_review_bundle")
