from __future__ import annotations

import io
import json
import time
import zipfile
from dataclasses import replace
from pathlib import Path
import pytest

from local_ai_hub.app import LocalAIApp, BundleValidationError
from local_ai_hub.agent_context import ContextRequest
from local_ai_hub.agent_tasks import GoalContract, TaskStatus
from local_ai_hub.agent_identity import AgentScope, ScopeContext
from local_ai_hub.agent_memory import MemoryRecord, MemoryKind, MemoryStatus
from local_ai_hub.agent_incidents import IncidentRecord, IncidentFingerprint


def app_with_agent_state(tmp_path: Path) -> LocalAIApp:
    tmp_path.mkdir(parents=True, exist_ok=True)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(f"""
[server]
bind = "127.0.0.1"
port = 11488
state_dir = "{tmp_path.as_posix()}/state"

[agent_state]
enabled = true
retention_days = 14
""", encoding="utf-8")
    return LocalAIApp(str(cfg_path))


def active_contract() -> GoalContract:
    return GoalContract(goal="Active Operator Task")


def task_context() -> ScopeContext:
    return ScopeContext(task_id="task-active-1")


def create_expired_incident(app: LocalAIApp) -> IncidentRecord:
    now = time.time()
    rec = IncidentRecord(
        incident_id="inc-expired-1",
        fingerprint=IncidentFingerprint(
            error_class="CommandError",
            operation_class="run",
            signature_hash="sig123",
        ),
        operation_class="run",
        error_class="CommandError",
        redacted_message="command failed",
        state_revision="rev-1",
        attempts=1,
        evidence_ids=(),
        resolved=True,
        created_at=now - 100,
        updated_at=now - 50,
        expires_at=now - 10,
    )
    app.agent_incidents._save_record(rec)
    return rec


def global_unapproved_record(app: LocalAIApp) -> MemoryRecord:
    rec = MemoryRecord.create(
        kind=MemoryKind.CONVENTION,
        scope=AgentScope.GLOBAL,
        key="global_unapproved_key",
        value="unapproved_value",
        scope_id="global",
        status=MemoryStatus.CANDIDATE,
    )
    return app.agent_memory.record(rec, actor="agent")


def test_cleanup_removes_expired_terminal_records_but_never_active_task(tmp_path: Path):
    with app_with_agent_state(tmp_path) as app:
        created = app.agent_tasks.create(active_contract(), task_context())
        active = app.agent_tasks.transition(created.task_id, TaskStatus.ACTIVE, reason="start", actor="operator", idempotency_key="tx-1")
        expired = create_expired_incident(app)
        assert app.agent_state_cleanup(now=expired.expires_at + 1) == 1
        assert app.agent_tasks.get(active.task_id).status is TaskStatus.ACTIVE


def test_selective_export_rejects_record_with_disallowed_scope(tmp_path: Path):
    with app_with_agent_state(tmp_path) as app:
        with pytest.raises(BundleValidationError):
            app.export_bundle(agent_state_record_ids=[global_unapproved_record(app).record_id])


def test_selective_export_and_import_valid_records(tmp_path: Path):
    with app_with_agent_state(tmp_path / "app1") as app1:
        rec = MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="repo_fact",
            value={"architecture": "modular"},
            scope_id="repo1",
            status=MemoryStatus.CONFIRMED,
        )
        saved = app1.agent_memory.record(rec, actor="user")
        bundle_bytes = app1.export_bundle(agent_state_record_ids=[saved.record_id])
        assert isinstance(bundle_bytes, bytes)
        assert len(bundle_bytes) > 0

    with app_with_agent_state(tmp_path / "app2") as app2:
        res = app2.import_bundle(bundle_bytes)
        assert res["success"] is True
        assert res["restored_records"] == 1
        found = app2.agent_memory.find(key="repo_fact")
        assert len(found) == 1
        assert found[0].value == {"architecture": "modular"}


def test_selective_bundle_roundtrips_memory_metadata(tmp_path: Path):
    expiry = time.time() + 3600
    provenance = {
        "root": str(tmp_path / "repo"),
        "repository_revision": "rev-7",
        "path_refs": ["src/parser.py"],
        "symbol_refs": ["Parser.parse"],
        "related_task": "task-7",
    }
    with app_with_agent_state(tmp_path / "source") as app1:
        record = replace(
            MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope=AgentScope.REPOSITORY,
                key="metadata-rich",
                value={"answer": 42},
                scope_id="repo-7",
                confidence=0.63,
                status=MemoryStatus.CONFIRMED,
                source="reviewer",
                evidence_ids=("evidence-1", "evidence-2"),
                sensitivity="sensitive",
                provenance=provenance,
                expires_at=expiry,
            ),
            contradicts_record_id="record-old",
            supersedes_record_id="record-older",
        )
        saved = app1.agent_memory.record(record, actor="user")
        bundle_bytes = app1.export_bundle(agent_state_record_ids=[saved.record_id])

    with app_with_agent_state(tmp_path / "target") as app2:
        result = app2.import_bundle(bundle_bytes)
        assert result["success"] is True
        restored = app2.agent_memory.get(saved.record_id)
        assert restored is not None
        assert restored.provenance == provenance
        assert restored.confidence == 0.63
        assert restored.evidence_ids == ("evidence-1", "evidence-2")
        assert restored.source == "reviewer"
        assert restored.sensitivity == "sensitive"
        assert restored.expires_at == expiry
        assert restored.status is MemoryStatus.CONFIRMED
        assert restored.contradicts_record_id == "record-old"
        assert restored.supersedes_record_id == "record-older"


def test_project_bundle_roundtrips_agent_state_memory_metadata(tmp_path: Path):
    source_repo = tmp_path / "source-repo"
    target_repo = tmp_path / "target-repo"
    source_repo.mkdir()
    target_repo.mkdir()
    expiry = time.time() + 3600
    provenance = {
        "root": str(source_repo),
        "repository_revision": "rev-project",
        "path_refs": ["src/project.py"],
        "symbol_refs": ["Project.run"],
        "related_task": "task-project",
    }
    with app_with_agent_state(tmp_path / "source-app") as app1:
        record = replace(
            MemoryRecord.create(
                kind=MemoryKind.CONTRACT_MAPPING,
                scope=AgentScope.REPOSITORY,
                key="project-metadata",
                value={"contract": "preserve"},
                scope_id="repo-project",
                confidence=0.71,
                status=MemoryStatus.CONFIRMED,
                source="project-reviewer",
                evidence_ids=("project-evidence",),
                sensitivity="sensitive",
                provenance=provenance,
                expires_at=expiry,
            ),
            contradicts_record_id="project-old",
            supersedes_record_id="project-older",
        )
        saved = app1.agent_memory.record(record, actor="user")
        bundle_bytes = app1.export_bundle(str(source_repo), agent_state_record_ids=[saved.record_id])

    with app_with_agent_state(tmp_path / "target-app") as app2:
        result = app2.import_bundle(bundle_bytes, str(target_repo))
        assert result["success"] is True
        restored = app2.agent_memory.get(saved.record_id)
        assert restored is not None
        expected_provenance = dict(provenance)
        expected_provenance["root"] = target_repo.as_posix()
        expected_provenance["source_root"] = str(source_repo)
        assert restored.provenance == expected_provenance
        assert restored.confidence == 0.71
        assert restored.evidence_ids == ("project-evidence",)
        assert restored.source == "project-reviewer"
        assert restored.sensitivity == "sensitive"
        assert restored.expires_at == expiry
        assert restored.status is MemoryStatus.CONFIRMED
        assert restored.contradicts_record_id == "project-old"
        assert restored.supersedes_record_id == "project-older"
        context = app2.agent_context.compile(
            ContextRequest(task_id="task-project", root=str(target_repo), token_budget=400)
        )
        assert saved.record_id in {element.element_id for element in context.elements}


def test_project_bundle_rejects_tampered_agent_state_records(tmp_path: Path):
    source_repo = tmp_path / "source-repo"
    target_repo = tmp_path / "target-repo"
    source_repo.mkdir()
    target_repo.mkdir()
    with app_with_agent_state(tmp_path / "source-app") as app1:
        record = app1.agent_memory.record(
            MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope=AgentScope.REPOSITORY,
                key="tamper-check",
                value="original",
                scope_id="repo-tamper",
                status=MemoryStatus.CONFIRMED,
                provenance={"root": str(source_repo), "path_refs": ["src/tamper.py"]},
            ),
            actor="user",
        )
        raw = app1.export_bundle(str(source_repo), agent_state_record_ids=[record.record_id])

    with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
        payload = json.loads(zf.read("bundle.json"))
    payload["agent_state_records"][0]["data"]["value"] = "tampered"
    modified = io.BytesIO()
    with zipfile.ZipFile(modified, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bundle.json", json.dumps(payload, separators=(",", ":")))

    with app_with_agent_state(tmp_path / "target-app") as app2:
        result = app2.import_bundle(modified.getvalue(), str(target_repo))
        assert result["success"] is False
        assert result["error"] == "bundle integrity check failed"
        assert app2.agent_memory.get(record.record_id) is None


@pytest.mark.parametrize("removed_key", ["agent_state_records", "agent_state_records_sha256", "both"])
def test_project_bundle_rejects_removed_agent_state_integrity_data(tmp_path: Path, removed_key: str):
    source_repo = tmp_path / "source-repo"
    target_repo = tmp_path / "target-repo"
    source_repo.mkdir()
    target_repo.mkdir()
    with app_with_agent_state(tmp_path / "source-app") as app1:
        record = app1.agent_memory.record(
            MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope=AgentScope.REPOSITORY,
                key="removal-check",
                value="original",
                status=MemoryStatus.CONFIRMED,
                provenance={"root": str(source_repo)},
            ),
            actor="user",
        )
        raw = app1.export_bundle(str(source_repo), agent_state_record_ids=[record.record_id])

    with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
        payload = json.loads(zf.read("bundle.json"))
    if removed_key == "both":
        payload.pop("agent_state_records")
        payload.pop("agent_state_records_sha256")
    else:
        payload.pop(removed_key)
    modified = io.BytesIO()
    with zipfile.ZipFile(modified, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bundle.json", json.dumps(payload, separators=(",", ":")))

    with app_with_agent_state(tmp_path / f"target-app-{removed_key}") as app2:
        result = app2.import_bundle(modified.getvalue(), str(target_repo))
        assert result["success"] is False
        assert result["error"] == "bundle integrity check failed"


def test_standalone_bundle_honors_json_and_compressed_limits(tmp_path: Path, monkeypatch):
    with app_with_agent_state(tmp_path / "source") as app:
        record = app.agent_memory.record(
            MemoryRecord.create(
                kind=MemoryKind.FINDING,
                scope=AgentScope.TASK,
                key="limited",
                value="payload",
                scope_id="task-limited",
            ),
            actor="user",
        )
        monkeypatch.setattr(app, "_bundle_limits", lambda: (1024 * 1024, 1, 10))
        with pytest.raises(ValueError, match="bundle.json exceeds configured limit"):
            app.export_bundle(agent_state_record_ids=[record.record_id])

        monkeypatch.setattr(app, "_bundle_limits", lambda: (1, 1024 * 1024, 10))
        with pytest.raises(ValueError, match="bundle exceeds configured compressed limit"):
            app.export_bundle(agent_state_record_ids=[record.record_id])



def test_bundle_requires_exact_current_application_version(tmp_path: Path):
    with app_with_agent_state(tmp_path / "source") as app:
        rec = MemoryRecord.create(
            kind=MemoryKind.FACT,
            scope=AgentScope.REPOSITORY,
            key="version_contract",
            value="current-only",
            scope_id="repo1",
            status=MemoryStatus.CONFIRMED,
        )
        saved = app.agent_memory.record(rec, actor="user")
        raw = app.export_bundle(agent_state_record_ids=[saved.record_id])

    source = io.BytesIO(raw)
    with zipfile.ZipFile(source, "r") as zf:
        payload = json.loads(zf.read("bundle.json"))
    payload["version"] = "not-current"
    modified = io.BytesIO()
    with zipfile.ZipFile(modified, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bundle.json", json.dumps(payload, separators=(",", ":")))

    with app_with_agent_state(tmp_path / "target") as app:
        result = app.import_bundle(modified.getvalue())
        assert result["success"] is False
        assert "must match Local AI Hub" in result["error"]

def test_app_status_includes_agent_state_summary(tmp_path: Path):
    with app_with_agent_state(tmp_path) as app:
        status = app.status()
        assert status["success"] is True
        assert status["agent_state"]["enabled"] is True
        created = app.agent_tasks.create(active_contract(), task_context())
        app.agent_tasks.transition(created.task_id, TaskStatus.ACTIVE, reason="start", actor="operator", idempotency_key="tx-status")
        status = app.status()
        assert "agent_state" in status
        ag_stat = status["agent_state"]
        assert ag_stat["enabled"] is True
        assert ag_stat["status"] == "healthy"
        assert ag_stat["active_tasks_count"] == 1
        assert ag_stat["tasks_count"] == 1
        assert ag_stat["retention_days"] == 14
