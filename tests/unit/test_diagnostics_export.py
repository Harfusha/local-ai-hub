from __future__ import annotations

import json
import os
import sqlite3

import pyzipper
import pytest

from local_ai_hub.diagnostics_export import create_diagnostics_archive


def _database(path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE diagnostics (project_root TEXT, payload TEXT)")
        connection.executemany("INSERT INTO diagnostics VALUES (?, ?)", rows)
        connection.commit()
    finally:
        connection.close()


def _source_tree(root):
    (root / "src" / "local_ai_hub").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "docs").mkdir()
    (root / "src" / "local_ai_hub" / "app.py").write_text("hub source", encoding="utf-8")
    (root / "tests" / "test_app.py").write_text("hub test", encoding="utf-8")
    (root / "docs" / "INSTALL_PROMPT.md").write_text("hub prompt", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='local-ai-hub'", encoding="utf-8")
    (root / "other-project").mkdir()
    (root / "other-project" / "private.py").write_text("other project", encoding="utf-8")
    (root / "models").mkdir()
    (root / "models" / "weights.gguf").write_bytes(b"model weights")
    (root / ".env").write_text("API_TOKEN=do-not-copy", encoding="utf-8")


def test_support_archive_streams_global_state_source_and_redacted_config(tmp_path):
    state_dir = tmp_path / "state"
    _database(state_dir / "telemetry.sqlite3", [("project-a", "event-a"), ("project-b", "event-b")])
    _database(state_dir / "agent_state.sqlite3", [("project-a", "task and memory state")])
    _database(state_dir / "projects" / "project-b" / "rag.sqlite3", [("project-b", "retrieval state")])
    (state_dir / "logs" / "service").mkdir(parents=True)
    (state_dir / "logs" / "service" / "hub.log").write_text("hub diagnostic", encoding="utf-8")
    (state_dir / "logs" / "service" / "hub.log.1").write_text("rotated diagnostic", encoding="utf-8")
    source_root = tmp_path / "hub"
    _source_tree(source_root)

    with create_diagnostics_archive(
        state_dir,
        config={"server": {"bind": "127.0.0.1", "api_key": "secret-value"}, "models": {"default": "qwen"}},
        source_root=source_root,
        temp_dir=tmp_path,
    ) as export:
        assert export.path.is_file()
        assert export.size == export.path.stat().st_size
        assert export.size > 0
        with pyzipper.AESZipFile(export.path) as archive:
            archive.setpassword(export.password.encode("ascii"))
            names = set(archive.namelist())
            assert {
                "state/telemetry.sqlite3",
                "state/agent_state.sqlite3",
                "state/projects/project-b/rag.sqlite3",
                "state/logs/service/hub.log",
                "state/logs/service/hub.log.1",
                "hub/src/local_ai_hub/app.py",
                "hub/tests/test_app.py",
                "hub/docs/INSTALL_PROMPT.md",
                "hub/pyproject.toml",
                "config/effective_config.redacted.json",
                "manifest.json",
                "README.txt",
            } <= names
            assert "hub/other-project/private.py" not in names
            assert "hub/models/weights.gguf" not in names
            assert "hub/.env" not in names
            assert archive.getinfo("state/telemetry.sqlite3").wz_aes_strength == 3
            assert archive.getinfo("state/telemetry.sqlite3").compress_type == pyzipper.ZIP_BZIP2
            config = json.loads(archive.read("config/effective_config.redacted.json"))
            assert config["server"]["api_key"] == "[REDACTED]"
            assert archive.getinfo("state/telemetry.sqlite3").extract_version >= 45
            config = json.loads(archive.read("config/effective_config.redacted.json"))
            assert config["server"]["bind"] == "127.0.0.1"
            assert config["server"]["api_key"] == "[REDACTED]"
            assert config["models"]["default"] == "qwen"
            exported_manifest = json.loads(archive.read("manifest.json"))
            assert exported_manifest["scope"] == "installation_all_projects"
            assert exported_manifest["redacted_config"] is True
            assert exported_manifest["source_files"] >= 4
            assert exported_manifest["excluded_categories"] == ["environment secrets", "model weights", "other project source"]
            db = sqlite3.connect(":memory:")
            db.deserialize(archive.read("state/telemetry.sqlite3"))
            assert db.execute("SELECT project_root, payload FROM diagnostics ORDER BY project_root").fetchall() == [
                ("project-a", "event-a"),
                ("project-b", "event-b"),
            ]
            db.close()
        archive_path = export.path
        assert len(export.password) >= 40

    assert not archive_path.exists()


def test_support_archive_uses_fresh_password_and_enforces_configured_limits(tmp_path):
    state_dir = tmp_path / "state"
    (state_dir / "logs").mkdir(parents=True)
    (state_dir / "logs" / "hub.log").write_bytes(os.urandom(8192))

    no_source = tmp_path / "no-source"
    with create_diagnostics_archive(state_dir, source_root=no_source, temp_dir=tmp_path) as first:
        first_password = first.password
    with create_diagnostics_archive(state_dir, source_root=no_source, temp_dir=tmp_path) as second:
        assert second.password != first_password

    with pytest.raises(ValueError, match="source data exceeds configured source limit"):
        create_diagnostics_archive(state_dir, source_root=no_source, max_source_bytes=1024, temp_dir=tmp_path)

    with pytest.raises(ValueError, match="archive exceeds configured limit"):
        create_diagnostics_archive(state_dir, source_root=no_source, max_archive_bytes=1024, temp_dir=tmp_path)


def test_support_archive_cancellation_removes_temporary_files(tmp_path):
    state_dir = tmp_path / "state"
    (state_dir / "logs").mkdir(parents=True)
    (state_dir / "logs" / "hub.log").write_bytes(b"diagnostic" * 2048)

    with pytest.raises(RuntimeError, match="export cancelled"):
        create_diagnostics_archive(
            state_dir,
            source_root=tmp_path / "no-source",
            temp_dir=tmp_path,
            cancelled=lambda: True,
        )

    assert list(tmp_path.glob("local-ai-hub-export-*")) == []
