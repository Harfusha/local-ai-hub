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


def test_artifacts_are_tenant_scoped_and_same_content_cannot_overwrite(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    first_id = store.put("same response", "tenant-a", "vision-output")
    second_id = store.put("same response", "tenant-b", "vision-output")
    first_image_id = store.put_bytes(PNG, "tenant-a", "vision-image", "image/png")
    second_image_id = store.put_bytes(PNG, "tenant-b", "vision-image", "image/png")

    assert first_id != second_id
    assert first_image_id != second_image_id
    assert store.get(first_id, tenant="tenant-a")["success"] is True
    assert store.get(first_id, tenant="tenant-b") == {
        "success": False,
        "error": "artifact not found or expired",
        "artifact_id": first_id,
    }
    assert store.get_binary(first_image_id, tenant="tenant-a")["success"] is True
    assert store.get_binary(first_image_id, tenant="tenant-b") == {
        "success": False,
        "error": "artifact not found or expired",
    }


def test_artifact_schema_uses_additive_release_compatible_tables(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "src" / "local_ai_hub" / "artifacts.py"
    assert "ALTER TABLE" not in source.read_text(encoding="utf-8").upper()

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
    with closing(sqlite3.connect(db_path)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "artifacts_v2" in tables
    assert store.get("art_legacy", tenant="tenant")["text"] == "legacy"


def test_legacy_migration_hashes_raw_64_hex_tenant_tokens(tmp_path: Path) -> None:
    raw_token = "a" * 64
    db_path = tmp_path / "artifacts.sqlite3"
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            "CREATE TABLE artifacts (artifact_id TEXT PRIMARY KEY, created_at REAL NOT NULL, tenant TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?)",
            ("art_hex_legacy", 9_999_999_999, raw_token, "text", "legacy"),
        )
        connection.commit()

    store = ArtifactStore(tmp_path)
    expected_digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with closing(sqlite3.connect(db_path)) as connection:
        old_tenant = connection.execute("SELECT tenant FROM artifacts").fetchone()[0]
        migrated_tenant = connection.execute("SELECT tenant FROM artifacts_v2").fetchone()[0]
        database_values = "\n".join(connection.iterdump())

    assert old_tenant == expected_digest
    assert migrated_tenant == expected_digest
    assert raw_token not in database_values
    assert store.get("art_hex_legacy", tenant=raw_token)["success"] is True

    ArtifactStore(tmp_path)
    with closing(sqlite3.connect(db_path)) as connection:
        assert connection.execute("SELECT tenant FROM artifacts").fetchone()[0] == expected_digest


def test_binary_integrity_rejects_non_numeric_stored_size(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    artifact_id = store.put_bytes(PNG, "tenant", "vision-image", "image/png")

    with closing(sqlite3.connect(store.path)) as connection:
        connection.execute("UPDATE artifacts SET size_bytes=? WHERE artifact_id=?", ("not-a-number", artifact_id))
        connection.commit()

    assert store.get_binary(artifact_id, tenant="tenant") == {
        "success": False,
        "error": "artifact integrity check failed",
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

    with closing(sqlite3.connect(db_path)) as connection:
        stored_tenant = connection.execute("SELECT tenant FROM artifacts WHERE artifact_id=?", ("art_legacy",)).fetchone()[0]
    assert stored_tenant != "tenant"
    assert len(stored_tenant) == 64


def test_new_text_and_binary_artifacts_store_only_tenant_identity(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    sensitive_tenant = r"C:\Users\secret\auth-profile"

    text_id = store.put("response", sensitive_tenant, "vision-output")
    image_id = store.put_bytes(PNG, sensitive_tenant, "vision-image", "image/png")

    with closing(sqlite3.connect(store.path)) as connection:
        rows = connection.execute(
            "SELECT tenant, tenant_identity FROM artifacts WHERE artifact_id IN (?, ?) ORDER BY artifact_id",
            (text_id, image_id),
        ).fetchall()
    stored_tenants = [str(row[0]) for row in rows]
    stored_values = [str(value) for row in rows for value in row]
    assert sensitive_tenant not in json.dumps(stored_values)
    assert all(len(value) == 64 for value in stored_values)
    assert all(value == hashlib.sha256(sensitive_tenant.encode()).hexdigest() for value in stored_values)

    ArtifactStore(tmp_path)
    with closing(sqlite3.connect(store.path)) as connection:
        reopened_values = [row[0] for row in connection.execute("SELECT tenant FROM artifacts").fetchall()]
    assert reopened_values == stored_tenants


@pytest.mark.parametrize("column,value", [
    ("mime_type", "text/plain"),
    ("size_bytes", 999),
    ("checksum", "0" * 64),
    ("identity_json", '{"artifact_id":"art_wrong","kind":"vision-image"}'),
])
def test_binary_integrity_rejects_mismatched_stored_identity(tmp_path: Path, column: str, value: object) -> None:
    store = ArtifactStore(tmp_path)
    artifact_id = store.put_bytes(PNG, "tenant", "vision-image", "image/png")

    with closing(sqlite3.connect(store.path)) as connection:
        connection.execute(f"UPDATE artifacts SET {column}=? WHERE artifact_id=?", (value, artifact_id))
        connection.commit()

    result = store.get_binary(artifact_id)
    assert result == {"success": False, "error": "artifact integrity check failed"}


def test_http_binary_artifact_get_returns_complete_payload(tmp_path: Path) -> None:
    from local_ai_hub import http_server
    from local_ai_hub.app import LocalAIApp

    state_dir = tmp_path / "state"
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = 11498\nstate_dir = "{state_dir.as_posix()}"\n',
        encoding="utf-8",
    )
    app = LocalAIApp(str(config_path))
    artifact_id = app.artifacts.put_bytes(PNG, "tenant", "vision-image", "image/png")
    previous_app = http_server.APP
    http_server.APP = app
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/artifact/get",
            data=json.dumps({"artifact_id": artifact_id, "binary": True}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-LocalAI-Tenant": "tenant"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["success"] is True
        assert base64.b64decode(payload["data_base64"]) == PNG

        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/artifact/get",
            data=json.dumps({"artifact_id": artifact_id, "binary": True}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-LocalAI-Tenant": "other-tenant"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            cross_tenant_payload = json.loads(response.read().decode("utf-8"))
        assert cross_tenant_payload == {"success": False, "error": "artifact not found or expired"}
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

    result = mcp_server.local_ai_artifact("art_image", binary=True)

    assert result["success"] is True
    assert "data_base64" not in result
    assert result["binary_payload"] == "available through /api/artifact/get with binary=true"


def test_json_bundle_size_is_bounded(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, max_json_bytes=32)

    with pytest.raises(ValueError, match="size"):
        store.put_json({"dom": "x" * 100}, "tenant", "frontend_review_bundle")
