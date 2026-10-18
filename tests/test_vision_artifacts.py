from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import threading
import urllib.request
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.artifacts import ArtifactStore, UnsupportedArtifactSchema


PNG = b"\x89PNG\r\n\x1a\n\x00\x01"


def test_binary_transport_is_available_without_changing_text_transport(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    assert callable(getattr(store, "put_bytes", None))
    artifact_id = store.put("plain text", kind="text")

    result = store.get(artifact_id)
    assert result["success"] is True
    assert result["text"] == "plain text"


def test_binary_image_round_trips_with_complete_identity_metadata(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    artifact_id = store.put_bytes(PNG, kind="vision-image", mime_type="image/png")
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
        "identity": {
            "artifact_id": artifact_id,
            "kind": "vision-image",
            "mime_type": "image/png",
            "encoding": "base64",
            "size_bytes": len(PNG),
            "checksum": hashlib.sha256(PNG).hexdigest(),
        },
        "data_base64": base64.b64encode(PNG).decode("ascii"),
    }


def test_artifacts_are_owner_global_and_same_content_is_idempotent(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    first_id = store.put("same response", kind="vision-output")
    second_id = store.put("same response", kind="vision-output")
    first_image_id = store.put_bytes(PNG, kind="vision-image", mime_type="image/png")
    second_image_id = store.put_bytes(PNG, kind="vision-image", mime_type="image/png")

    assert first_id == second_id
    assert first_image_id == second_image_id
    assert store.get(first_id)["text"] == "same response"
    assert store.get_binary(first_image_id)["data_base64"] == base64.b64encode(PNG).decode("ascii")
    with pytest.raises(TypeError):
        store.get(first_id, tenant="retired")
    with pytest.raises(TypeError):
        store.get_binary(first_image_id, tenant="retired")


@pytest.mark.parametrize("operation", ["put", "get", "get_binary", "list"])
def test_artifact_operations_reject_retired_tenant_selectors(tmp_path: Path, operation: str) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(TypeError):
        if operation == "put":
            store.put("payload", tenant="retired", kind="text")
        elif operation == "get":
            store.get("art_missing", tenant="retired")
        elif operation == "get_binary":
            store.get_binary("art_missing", tenant="retired")
        else:
            store.list(tenant="retired")


@pytest.mark.parametrize("tenant", [None, "", False, 0])
def test_artifact_list_rejects_falsey_retired_tenant_selectors(tmp_path: Path, tenant: object) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(TypeError):
        store.list(tenant=tenant)  # type: ignore[arg-type]


@pytest.mark.parametrize("limit", [True, False, 0, -1, "20", 20.0])
def test_artifact_list_rejects_noncanonical_limits(tmp_path: Path, limit: object) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(ValueError, match="limit"):
        store.list(limit=limit)  # type: ignore[arg-type]


def test_pre_paging_schema_fails_closed_without_mutating_database(tmp_path: Path) -> None:
    tenant = "tenant-valid-v1"
    tenant_digest = hashlib.sha256(tenant.encode("utf-8")).hexdigest()
    db_path = tmp_path / "artifacts.sqlite3"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            "CREATE TABLE artifacts (artifact_id TEXT PRIMARY KEY, created_at REAL NOT NULL, tenant TEXT NOT NULL, tenant_identity TEXT, kind TEXT NOT NULL, text TEXT NOT NULL DEFAULT '', mime_type TEXT, encoding TEXT, blob BLOB, size_bytes INTEGER, checksum TEXT, identity_json TEXT)"
        )
        connection.execute("CREATE TABLE artifact_schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO artifacts(artifact_id, created_at, tenant, tenant_identity, kind, text) VALUES (?, ?, ?, ?, ?, ?)",
            ("art_v1", 9_999_999_999, tenant_digest, tenant_digest, "text", "stable"),
        )
        connection.execute("INSERT INTO artifact_schema_meta VALUES (?, ?)", ("tenant_storage", "sha256-v1"))
        connection.commit()

    original_database = db_path.read_bytes()
    with pytest.raises(UnsupportedArtifactSchema, match="unsupported artifact database schema"):
        ArtifactStore(tmp_path)
    assert db_path.read_bytes() == original_database

    current_store = ArtifactStore(tmp_path / "fresh")
    artifact_id = current_store.put("current schema", kind="text")
    assert current_store.get(artifact_id)["text"] == "current schema"


def test_binary_integrity_rejects_non_numeric_stored_size(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    artifact_id = store.put_bytes(PNG, kind="vision-image", mime_type="image/png")

    with closing(sqlite3.connect(store.path)) as connection:
        connection.execute("UPDATE artifacts SET size_bytes=? WHERE artifact_id=?", ("not-a-number", artifact_id))
        connection.commit()

    assert store.get_binary(artifact_id) == {
        "success": False,
        "error": "artifact integrity check failed",
    }


def test_binary_transport_rejects_non_images_and_oversized_images(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, max_binary_bytes=len(PNG))

    with pytest.raises(ValueError, match="image MIME"):
        store.put_bytes(PNG, kind="not-an-image", mime_type="application/json")
    with pytest.raises(ValueError, match="size"):
        store.put_bytes(PNG + b"x", kind="vision-image", mime_type="image/png")


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

    artifact_id = store.put_json(bundle, kind="frontend_review_bundle")
    result = store.get(artifact_id, section="json:dom")

    assert result["success"] is True
    assert json.loads(store.get(artifact_id)["text"]) == bundle
    assert json.loads(result["text"]) == bundle["dom"]


def test_binary_reads_never_return_partial_payloads(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    artifact_id = store.put_bytes(PNG, kind="vision-image", mime_type="image/png")

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


def test_binary_metadata_does_not_echo_credentials_or_payload(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    artifact_id = store.put_bytes(PNG, kind="vision-image", mime_type="image/png")
    result = store.get_binary(artifact_id)

    encoded = json.dumps(result)
    assert "authorization" not in encoded.lower()
    assert "cookie" not in encoded.lower()
    assert "network_body" not in encoded.lower()


def test_new_artifacts_use_tenantless_schema_and_preserve_content(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    text_id = store.put("response", kind="vision-output")
    image_id = store.put_bytes(PNG, kind="vision-image", mime_type="image/png")

    with closing(sqlite3.connect(store.path)) as connection:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(artifacts)")}
    assert not {"tenant", "tenant_identity"}.intersection(columns)
    assert {"artifact_id", "kind", "text", "mime_type", "blob"}.issubset(columns)

    reopened = ArtifactStore(tmp_path)
    assert reopened.get(text_id)["text"] == "response"
    assert base64.b64decode(reopened.get_binary(image_id)["data_base64"]) == PNG


@pytest.mark.parametrize("column,value", [
    ("mime_type", "text/plain"),
    ("size_bytes", 999),
    ("checksum", "0" * 64),
    ("identity_json", '{"artifact_id":"art_wrong","kind":"vision-image"}'),
])
def test_binary_integrity_rejects_mismatched_stored_identity(tmp_path: Path, column: str, value: object) -> None:
    store = ArtifactStore(tmp_path)
    artifact_id = store.put_bytes(PNG, kind="vision-image", mime_type="image/png")

    with closing(sqlite3.connect(store.path)) as connection:
        connection.execute(f"UPDATE artifacts SET {column}=? WHERE artifact_id=?", (value, artifact_id))
        connection.commit()

    result = store.get_binary(artifact_id)
    assert result == {"success": False, "error": "artifact integrity check failed"}


def test_http_binary_artifact_get_is_owner_global_and_complete(tmp_path: Path) -> None:
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{state_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    artifact_id = app.artifacts.put_bytes(PNG, kind="vision-image", mime_type="image/png")
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/artifact/get",
            data=json.dumps({"artifact_id": artifact_id, "binary": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["success"] is True
        assert base64.b64decode(payload["data_base64"]) == PNG

        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/artifact/get",
            data=json.dumps({"artifact_id": artifact_id, "binary": True}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-LocalAI-Request-ID": "owner-global-artifact-request",
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            owner_global_payload = json.loads(response.read().decode("utf-8"))
        assert owner_global_payload["success"] is True
        assert base64.b64decode(owner_global_payload["data_base64"]) == PNG
    finally:
        server.shutdown()
        server.server_close()
        http_server.APP = previous_app
        app.close()


def test_mcp_binary_artifact_response_is_metadata_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from local_ai_hub import mcp_server

    monkeypatch.setattr(
        mcp_server.CLIENT,
        "post",
        lambda *_args, **_kwargs: {
            "success": True,
            "artifact_id": "art_image",
            "mime_type": "image/png",
            "size_bytes": len(PNG),
            "data_base64": base64.b64encode(PNG).decode("ascii"),
        },
    )

    result = mcp_server.local_ai_artifact(action="get", artifact_id="art_image", binary=True)

    assert result["success"] is True
    assert "data_base64" not in result
    assert result["binary_payload"] == "available through /api/artifact/get with binary=true"


def test_json_bundle_size_is_bounded(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, max_json_bytes=32)

    with pytest.raises(ValueError, match="size"):
        store.put_json({"dom": "x" * 100}, kind="frontend_review_bundle")
