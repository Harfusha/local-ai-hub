from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import uuid
from contextlib import closing
from pathlib import Path
import pytest

from local_ai_hub.repo_knowledge import RepoKnowledgeStore
from local_ai_hub.agent_state_migration import (
    migrate_runtime_task_scopes_on_update,
    migrate_project_state_on_update,
)
from local_ai_hub.agent_incidents import _incident_scope_key
from local_ai_hub.project_identity import project_scope_id
from local_ai_hub.repo_plan.schema_validation import RepoPlanValidationError


def _setup_migration_env(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".local-ai-hub").mkdir()
    project = "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    (root / ".local-ai-hub/project.json").write_text(json.dumps({
        "schema_version": 1, "project_id": project, "mode": "shared",
    }), encoding="utf-8")
    store = RepoKnowledgeStore(root)

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    db = state_dir / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE agent_tasks_projection (task_id TEXT PRIMARY KEY, status TEXT, contract TEXT, checkpoint TEXT, context TEXT, owner TEXT, lease_id TEXT, receipts TEXT, created_at REAL, updated_at REAL, heartbeat_expires_at REAL)")
        con.execute("CREATE TABLE agent_memory_records (record_id TEXT PRIMARY KEY, kind TEXT, scope TEXT, key TEXT, value TEXT, confidence REAL, source TEXT, sensitivity TEXT, quarantine_reason TEXT, created_at REAL, updated_at REAL, scope_id TEXT, provenance TEXT, evidence_ids TEXT, contradicts_record_id TEXT, supersedes_record_id TEXT, expires_at REAL, status TEXT)")
        con.execute("CREATE TABLE agent_incidents (incident_id TEXT PRIMARY KEY, operation_class TEXT, error_class TEXT, signature_hash TEXT, resolved INTEGER, redacted_message TEXT, root_cause TEXT, verified_fix TEXT, confidence REAL, affected_paths TEXT, created_at REAL, updated_at REAL, state_revision INTEGER, attempts INTEGER, evidence_ids TEXT, repository_key TEXT, ignored INTEGER, expires_at REAL)")

        # Seed task with v2 scope
        chk = json.dumps({"phase": "done", "next_action": "", "blockers": [], "affected_paths": [], "state_data": {"_agent_task_scope": {"version": 2, "repo_root": str(root)}}})
        contract = json.dumps({"goal": "Migrate task", "description": "", "acceptance_criteria": ["done"], "non_goals": [], "constraints": [], "risk_profile": "normal"})
        con.execute("INSERT INTO agent_tasks_projection VALUES ('task-mig-1', 'completed', ?, ?, '{}', 'local-user', '', '[]', 100, 200, 0)", (contract, chk))

        # Seed memory
        provenance = json.dumps({"root": str(root)})
        con.execute("INSERT INTO agent_memory_records VALUES ('mem-mig-1', 'fact', 'project', 'deploy_target', '\"cloud-run\"', 1.0, 'ci', 'internal', '', 100, 200, '', ?, '[]', '', '', 0, 'active')", (provenance,))
        con.execute("INSERT INTO agent_memory_records VALUES ('mem-other-project', 'fact', 'project', 'private', '\"other-project-secret\"', 1.0, 'ci', 'internal', '', 100, 200, '', ?, '[]', '', '', 0, 'active')", (json.dumps({"root": str(root.parent / "other")}),))

        # Seed incident
        repository_key = _incident_scope_key("repository", str(root))
        con.execute("INSERT INTO agent_incidents VALUES ('inc-mig-1', 'command', 'TimeoutError', 'cafebabecafebabe', 1, 'build timeout', 'slow network', 'cached docker layers in runner', 1.0, '[\"Dockerfile\"]', 100, 200, 1, 0, '[]', ?, 0, 0)", (repository_key,))
        other_repository_key = _incident_scope_key("repository", str(root.parent / "other"))
        con.execute("INSERT INTO agent_incidents VALUES ('inc-other-project', 'command', 'ValueError', 'deadbeefdeadbeef', 1, 'other project', 'private', 'other-project-secret', 1.0, '[]', 100, 200, 1, 0, '[]', ?, 0, 0)", (other_repository_key,))
        con.commit()

    return root, store, state_dir


@pytest.mark.skipif(shutil.which("git") is None, reason="Git unavailable")
def test_update_bootstraps_same_identity_in_independent_old_checkouts(tmp_path: Path):
    first = tmp_path / "old-checkout-a"
    first.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(first)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(first), "config", "user.name", "Fixture"], check=True)
    subprocess.run(["git", "-C", str(first), "config", "user.email", "fixture@example.invalid"], check=True)
    (first / "README.md").write_text("old checkout\n", encoding="utf-8")
    (first / ".gitignore").write_text(".local-ai-hub/local/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(first), "add", "README.md", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(first), "commit", "-m", "old checkout"], check=True, capture_output=True)

    origin = "https://example.invalid/local-ai-hub/repository.git"
    subprocess.run(["git", "-C", str(first), "remote", "add", "origin", origin], check=True)
    second = tmp_path / "old-checkout-b"
    subprocess.run(["git", "clone", str(first), str(second)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(second), "remote", "set-url", "origin", origin], check=True)

    identities = []
    for index, checkout in enumerate((first, second), start=1):
        assert not (checkout / ".local-ai-hub/project.json").exists()
        state_dir = tmp_path / f"state-{index}"
        state_dir.mkdir()

        result = migrate_project_state_on_update(state_dir, checkout)

        assert result["status"] == "no_legacy_state"
        identities.append(project_scope_id(checkout))

    assert identities[0] == identities[1]


def test_update_migration_publishes_portable_records_once(tmp_path: Path):
    root, store, state_dir = _setup_migration_env(tmp_path)
    first = migrate_project_state_on_update(state_dir, root)
    assert first["status"] == "migrated"
    assert first["records"] == {"task": 1, "memory": 1, "incident": 1}
    assert (root / ".local-ai-hub/agent-os/tasks/task-mig-1.json").is_file()
    assert (root / ".local-ai-hub/agent-os/memory/mem-mig-1.json").is_file()
    assert (root / ".local-ai-hub/agent-os/incidents/inc-mig-1.json").is_file()
    assert not (root / ".local-ai-hub/agent-os/memory/mem-other-project.json").exists()
    assert not (root / ".local-ai-hub/agent-os/incidents/inc-other-project.json").exists()
    again = migrate_project_state_on_update(state_dir, root)
    assert again["status"] == "already_migrated"
    assert again["records"] == 0


def test_update_migration_resumes_after_a_late_blocker(tmp_path: Path):
    root, _, state_dir = _setup_migration_env(tmp_path)
    db = state_dir / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("UPDATE agent_incidents SET verified_fix='password=private' WHERE incident_id='inc-mig-1'")
        con.commit()

    with pytest.raises(RepoPlanValidationError):
        migrate_project_state_on_update(state_dir, root)
    assert (root / ".local-ai-hub/agent-os/tasks/task-mig-1.json").is_file()
    assert (root / ".local-ai-hub/agent-os/memory/mem-mig-1.json").is_file()
    assert not (state_dir / "project_state_migration_v1.json").exists()

    with closing(sqlite3.connect(db)) as con:
        con.execute("UPDATE agent_incidents SET verified_fix='cached docker layers in runner' WHERE incident_id='inc-mig-1'")
        con.commit()
    resumed = migrate_project_state_on_update(state_dir, root)
    assert resumed["status"] == "migrated"
    assert resumed["records"] == {"task": 0, "memory": 0, "incident": 1}


def test_update_migration_rejects_source_change_between_record_kinds(tmp_path: Path, monkeypatch):
    root, _, state_dir = _setup_migration_env(tmp_path)
    import local_ai_hub.agent_state_migration as migration
    import local_ai_hub.repo_knowledge_batch as knowledge_batch

    # Force the cheap stat identity to stay constant: migration must bind its
    # pages to the complete SQLite content digest, not only file metadata.
    monkeypatch.setattr(migration, "_identity", lambda _path: (1, 2, 3, 4, 5))

    original_apply = knowledge_batch.apply_knowledge_batch
    changed = False

    def mutate_legacy_db_after_first_kind(*args, **kwargs):
        nonlocal changed
        result = original_apply(*args, **kwargs)
        if not changed:
            changed = True
            with closing(sqlite3.connect(state_dir / "agent_state.sqlite")) as con:
                con.execute("UPDATE agent_incidents SET attempts=attempts+1 WHERE incident_id='inc-mig-1'")
                con.commit()
        return result

    monkeypatch.setattr(knowledge_batch, "apply_knowledge_batch", mutate_legacy_db_after_first_kind)
    with pytest.raises(RepoPlanValidationError, match="snapshot changed"):
        migrate_project_state_on_update(state_dir, root)

    assert not (state_dir / "project_state_migration_v1.json").exists()
    assert (root / ".local-ai-hub/agent-os/tasks/task-mig-1.json").is_file()
    assert not (root / ".local-ai-hub/agent-os/memory/mem-mig-1.json").exists()
    assert not (root / ".local-ai-hub/agent-os/incidents/inc-mig-1.json").exists()


def test_legacy_database_snapshot_hashes_only_bounded_migration_inputs(tmp_path: Path, monkeypatch):
    import local_ai_hub.agent_state_migration as migration

    db = tmp_path / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        con.execute("CREATE TABLE agent_memory_records(record_id TEXT PRIMARY KEY, payload BLOB)")
        con.execute("CREATE TABLE unrelated_cache(payload BLOB)")
        con.execute("INSERT INTO agent_memory_records VALUES('memory-a', 'first')")
        con.execute("INSERT INTO unrelated_cache VALUES('unrelated')")
        con.commit()

    first = migration._database_snapshot(db)
    with closing(sqlite3.connect(db)) as con:
        con.execute("UPDATE unrelated_cache SET payload='different'")
        con.commit()
    assert migration._database_snapshot(db) == first

    with closing(sqlite3.connect(db)) as con:
        con.execute("UPDATE agent_memory_records SET payload='other'")
        con.commit()
    assert migration._database_snapshot(db) != first

    monkeypatch.setattr(migration, "_MAX_DATABASE_BYTES", 1)
    with pytest.raises(RepoPlanValidationError, match="512 MiB content limit"):
        migration._database_snapshot(db)


def test_update_migrates_old_runtime_task_scope_once_and_fences_active_attempt(tmp_path: Path):
    root, _, state_dir = _setup_migration_env(tmp_path)
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", ".local-ai-hub/project.json"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "project identity"], check=True, capture_output=True)
    db = state_dir / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        row = con.execute("SELECT checkpoint FROM agent_tasks_projection WHERE task_id='task-mig-1'").fetchone()
        checkpoint = json.loads(row[0])
        checkpoint["state_data"]["_agent_task_scope"]["version"] = 3
        con.execute(
            "UPDATE agent_tasks_projection SET status='active',lease_id='old-lease',heartbeat_expires_at=9999999999,checkpoint=? WHERE task_id='task-mig-1'",
            (json.dumps(checkpoint),),
        )
        con.commit()

    first = migrate_runtime_task_scopes_on_update(state_dir)
    assert first == {"status": "migrated", "converted": 1, "retired": 0}
    with closing(sqlite3.connect(db)) as con:
        status, lease_id, heartbeat, checkpoint_raw = con.execute(
            "SELECT status,lease_id,heartbeat_expires_at,checkpoint FROM agent_tasks_projection WHERE task_id='task-mig-1'"
        ).fetchone()
    migrated = json.loads(checkpoint_raw)["state_data"]["_agent_task_scope"]
    assert status == "blocked"
    assert not lease_id and heartbeat == 0
    assert migrated["version"] == 4
    assert migrated["project_id"] == "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb"
    assert migrated["snapshot_id"]
    assert "re-review" in json.loads(checkpoint_raw)["blockers"][-1]
    assert migrate_runtime_task_scopes_on_update(state_dir) == {
        "status": "already_migrated", "converted": 0, "retired": 0,
    }


def test_update_retires_runtime_scope_when_old_checkout_is_gone(tmp_path: Path):
    root, _, state_dir = _setup_migration_env(tmp_path)
    old_root = tmp_path / "removed-checkout"
    db = state_dir / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        row = con.execute("SELECT checkpoint FROM agent_tasks_projection WHERE task_id='task-mig-1'").fetchone()
        checkpoint = json.loads(row[0])
        checkpoint["state_data"]["_agent_task_scope"]["version"] = 3
        checkpoint["state_data"]["_agent_task_scope"]["repo_root"] = str(old_root)
        con.execute(
            "UPDATE agent_tasks_projection SET status='active',lease_id='old-lease',heartbeat_expires_at=9999999999,checkpoint=? WHERE task_id='task-mig-1'",
            (json.dumps(checkpoint),),
        )
        con.commit()

    result = migrate_runtime_task_scopes_on_update(state_dir)
    assert result == {"status": "migrated", "converted": 0, "retired": 1}
    with closing(sqlite3.connect(db)) as con:
        status, lease_id, heartbeat, checkpoint_raw = con.execute(
            "SELECT status,lease_id,heartbeat_expires_at,checkpoint FROM agent_tasks_projection WHERE task_id='task-mig-1'"
        ).fetchone()
    retired = json.loads(checkpoint_raw)["state_data"]
    assert status == "abandoned"
    assert not lease_id and heartbeat == 0
    assert "_agent_task_scope" not in retired
    assert len(retired["_retired_repository_scope"]) == 64


def test_update_migration_recognizes_registered_linked_worktree_roots(tmp_path: Path):
    root, _, state_dir = _setup_migration_env(tmp_path)
    linked = tmp_path / "linked"
    (root / ".gitignore").write_text(".local-ai-hub/local/\n", encoding="utf-8")
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", ".gitignore", ".local-ai-hub/project.json"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "project identity"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-b", "linked-test", str(linked)], check=True, capture_output=True)

    db = state_dir / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        task_row = con.execute("SELECT checkpoint FROM agent_tasks_projection WHERE task_id='task-mig-1'").fetchone()
        checkpoint = json.loads(task_row[0])
        checkpoint["state_data"]["_agent_task_scope"]["repo_root"] = str(linked)
        con.execute("UPDATE agent_tasks_projection SET checkpoint=? WHERE task_id='task-mig-1'", (json.dumps(checkpoint),))
        con.execute("UPDATE agent_memory_records SET provenance=? WHERE record_id='mem-mig-1'", (json.dumps({"root": str(linked)}),))
        con.execute("UPDATE agent_incidents SET repository_key=? WHERE incident_id='inc-mig-1'", (_incident_scope_key("repository", str(linked)),))
        con.commit()

    result = migrate_project_state_on_update(state_dir, root)
    assert result["records"] == {"task": 1, "memory": 1, "incident": 1}


def test_completed_migration_does_not_read_legacy_database_again(tmp_path: Path, monkeypatch):
    import local_ai_hub.agent_state_migration as migration

    root, _, state_dir = _setup_migration_env(tmp_path)
    first = migrate_project_state_on_update(state_dir, root)
    assert first["status"] == "migrated"

    def reject_legacy_scan(*_args, **_kwargs):
        raise AssertionError("completed migration must not read legacy checkout metadata")

    monkeypatch.setattr(migration, "_database_project_roots", reject_legacy_scan)
    second = migrate_project_state_on_update(state_dir, root)
    assert second == {"status": "already_migrated", "project_id": "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb", "records": 0}


def test_update_without_legacy_database_does_not_scan_or_create_a_marker(tmp_path: Path, monkeypatch):
    import local_ai_hub.agent_state_migration as migration

    root, _, state_dir = _setup_migration_env(tmp_path)
    (state_dir / "agent_state.sqlite").unlink()

    first = migrate_project_state_on_update(state_dir, root)
    assert first["status"] == "no_legacy_state"
    assert not (state_dir / "project_state_migration_v1.json").exists()

    def reject_legacy_scan(*_args, **_kwargs):
        raise AssertionError("completed no-state migration must not scan legacy metadata")

    monkeypatch.setattr(migration, "_database_project_roots", reject_legacy_scan)
    second = migrate_project_state_on_update(state_dir, root)
    assert second == {"status": "no_legacy_state", "project_id": "41a9ce2a-d6b9-4ff0-ae6a-87e6c884f7bb", "records": 0}


def test_update_migration_recognizes_existing_relocated_checkout_by_project_id(tmp_path: Path):
    root, _, state_dir = _setup_migration_env(tmp_path)
    old_checkout = tmp_path / "old-checkout"
    (old_checkout / ".local-ai-hub").mkdir(parents=True)
    (old_checkout / ".local-ai-hub/project.json").write_bytes((root / ".local-ai-hub/project.json").read_bytes())
    db = state_dir / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        task_row = con.execute("SELECT checkpoint FROM agent_tasks_projection WHERE task_id='task-mig-1'").fetchone()
        checkpoint = json.loads(task_row[0])
        checkpoint["state_data"]["_agent_task_scope"]["repo_root"] = str(old_checkout)
        con.execute("UPDATE agent_tasks_projection SET checkpoint=? WHERE task_id='task-mig-1'", (json.dumps(checkpoint),))
        con.execute("UPDATE agent_memory_records SET provenance=? WHERE record_id='mem-mig-1'", (json.dumps({"root": str(old_checkout)}),))
        con.execute("UPDATE agent_incidents SET repository_key=? WHERE incident_id='inc-mig-1'", (_incident_scope_key("repository", str(old_checkout)),))
        con.commit()

    result = migrate_project_state_on_update(state_dir, root)
    assert result["records"] == {"task": 1, "memory": 1, "incident": 1}


@pytest.mark.parametrize("same_origin", [True, False])
def test_update_migration_maps_unmanifested_old_clone_only_by_matching_origin(tmp_path: Path, same_origin: bool):
    root, _, state_dir = _setup_migration_env(tmp_path)
    project_manifest = root / ".local-ai-hub/project.json"
    project_data = project_manifest.read_bytes()
    project_manifest.unlink()
    (root / ".gitignore").write_text(".local-ai-hub/local/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "old checkout"], check=True, capture_output=True)
    old_checkout = tmp_path / "old-checkout"
    subprocess.run(["git", "clone", str(root), str(old_checkout)], check=True, capture_output=True)
    project_manifest.parent.mkdir(parents=True, exist_ok=True)
    project_manifest.write_bytes(project_data)
    subprocess.run(["git", "-C", str(root), "add", ".local-ai-hub/project.json"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "bootstrap project identity"], check=True, capture_output=True)
    shared_origin = "https://example.invalid/org/project.git"
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", shared_origin], check=True)
    old_origin = shared_origin if same_origin else "https://example.invalid/org/unrelated.git"
    subprocess.run(["git", "-C", str(old_checkout), "remote", "set-url", "origin", old_origin], check=True)

    db = state_dir / "agent_state.sqlite"
    with closing(sqlite3.connect(db)) as con:
        task_row = con.execute("SELECT checkpoint FROM agent_tasks_projection WHERE task_id='task-mig-1'").fetchone()
        checkpoint = json.loads(task_row[0])
        checkpoint["state_data"]["_agent_task_scope"]["repo_root"] = str(old_checkout)
        con.execute("UPDATE agent_tasks_projection SET checkpoint=? WHERE task_id='task-mig-1'", (json.dumps(checkpoint),))
        con.execute("UPDATE agent_memory_records SET provenance=? WHERE record_id='mem-mig-1'", (json.dumps({"root": str(old_checkout)}),))
        con.execute("UPDATE agent_incidents SET repository_key=? WHERE incident_id='inc-mig-1'", (_incident_scope_key("repository", str(old_checkout)),))
        con.commit()

    result = migrate_project_state_on_update(state_dir, root)

    expected = 1 if same_origin else 0
    assert result["records"] == {"task": expected, "memory": expected, "incident": expected}


def test_release_update_invokes_project_cutover_once(tmp_path: Path, monkeypatch):
    root, _, state_dir = _setup_migration_env(tmp_path)
    (root / "pyproject.toml").write_text('[project]\nversion = "8.2.1"\n', encoding="utf-8")
    from tools import setup as setup_module

    monkeypatch.setattr(setup_module, "SOURCE_ROOT", root)
    monkeypatch.setattr(setup_module, "run_state_migrations", lambda *args, **kwargs: {"status": "current", "backups": []})
    monkeypatch.setattr(setup_module, "apply_embedding_reset", lambda *args, **kwargs: {"status": "not_required"})
    monkeypatch.setattr(setup_module, "discard_stale_migration_artifacts", lambda *args, **kwargs: [])

    result = setup_module.migrate_release_state(state_dir)
    assert result["project_state_migration"]["status"] == "migrated"
    assert (root / ".local-ai-hub/agent-os/tasks/task-mig-1.json").is_file()
    assert (state_dir / "project_state_migration_v1.json").is_file()


def test_release_update_bootstraps_missing_identity_for_old_git_checkout(tmp_path: Path, monkeypatch):
    root, _, state_dir = _setup_migration_env(tmp_path)
    (root / ".local-ai-hub/project.json").unlink()
    with closing(sqlite3.connect(state_dir / "agent_state.sqlite")) as con:
        con.execute(
            "UPDATE agent_incidents SET repository_key=? WHERE incident_id='inc-mig-1'",
            (_incident_scope_key("repository", str(root)),),
        )
        con.commit()
    (root / ".gitignore").write_text(".local-ai-hub/local/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "add", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "--quiet", "-m", "old checkout"], check=True, capture_output=True)
    old_clone = tmp_path / "old-clone"
    subprocess.run(["git", "clone", "--quiet", str(root), str(old_clone)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(old_clone), "remote", "set-url", "origin",
         "https://clone-user:clone-secret@example.invalid/org/project.git?token=clone-secret"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "remote", "add", "origin",
         "https://user:secret@example.invalid/org/project.git?token=secret"],
        check=True,
    )
    (root / "pyproject.toml").write_text('[project]\nversion = "8.2.1"\n', encoding="utf-8")
    from tools import setup as setup_module

    monkeypatch.setattr(setup_module, "SOURCE_ROOT", root)
    monkeypatch.setattr(setup_module, "run_state_migrations", lambda *args, **kwargs: {"status": "current", "backups": []})
    monkeypatch.setattr(setup_module, "apply_embedding_reset", lambda *args, **kwargs: {"status": "not_required"})
    monkeypatch.setattr(setup_module, "discard_stale_migration_artifacts", lambda *args, **kwargs: [])

    result = setup_module.migrate_release_state(state_dir)
    manifest = json.loads((root / ".local-ai-hub/project.json").read_text(encoding="utf-8"))
    assert "secret" not in json.dumps(manifest)
    assert str(uuid.UUID(manifest["project_id"])) == manifest["project_id"]
    assert manifest["mode"] == "shared"
    assert result["project_state_migration"]["status"] == "migrated"
    assert result["project_state_migration"]["records"] == {"task": 1, "memory": 1, "incident": 1}
    assert (root / ".local-ai-hub/agent-os/tasks/task-mig-1.json").is_file()

    clone_state = tmp_path / "clone-state"
    clone_state.mkdir()
    clone_result = migrate_project_state_on_update(clone_state, old_clone)
    clone_manifest = json.loads((old_clone / ".local-ai-hub/project.json").read_text(encoding="utf-8"))
    assert clone_result["status"] == "no_legacy_state"
    assert clone_manifest["project_id"] == manifest["project_id"]

    repeated = setup_module.migrate_release_state(state_dir)
    assert repeated["project_state_migration"]["status"] == "already_migrated"
    assert json.loads((root / ".local-ai-hub/project.json").read_text(encoding="utf-8"))["project_id"] == manifest["project_id"]


def test_release_update_rejects_old_checkout_without_stable_origin(tmp_path: Path, monkeypatch):
    root, _, state_dir = _setup_migration_env(tmp_path)
    (root / ".local-ai-hub/project.json").unlink()
    (root / ".gitignore").write_text(".local-ai-hub/local/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "add", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "--quiet", "-m", "old checkout"], check=True, capture_output=True)
    from tools import setup as setup_module

    migration_calls = []
    monkeypatch.setattr(setup_module, "SOURCE_ROOT", root)
    monkeypatch.setattr(setup_module, "run_state_migrations", lambda *args, **kwargs: migration_calls.append(args) or {"status": "current", "backups": []})
    monkeypatch.setattr(setup_module, "apply_embedding_reset", lambda *args, **kwargs: {"status": "not_required"})
    monkeypatch.setattr(setup_module, "discard_stale_migration_artifacts", lambda *args, **kwargs: [])

    with pytest.raises(RepoPlanValidationError, match="credential-free Git origin"):
        setup_module.migrate_release_state(state_dir)
    assert migration_calls == []
    assert not (root / ".local-ai-hub/project.json").exists()
    assert not (state_dir / "project_state_migration_v1.json").exists()


def test_real_repository_update_hook_has_a_published_project_identity(tmp_path: Path, monkeypatch):
    from tools import setup as setup_module

    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(setup_module, "SOURCE_ROOT", repository_root)

    result = setup_module.migrate_release_state(tmp_path, create_backup=False)

    assert result["project_state_migration"]["status"] == "no_legacy_state"
