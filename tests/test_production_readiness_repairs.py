from __future__ import annotations

import json
from pathlib import Path

from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_identity import AgentScope
from local_ai_hub.agent_memory import MemoryKind, MemoryRecord, MemoryStore
from local_ai_hub.commands import CommandBroker
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.services import is_retryable_local_backend_error


def test_memory_http_contract_can_round_trip_repository_identity(tmp_path: Path) -> None:
    store = MemoryStore(AgentStateStore(tmp_path / "state.db", enabled=True))
    root = tmp_path / "repo"
    root.mkdir()
    record = MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        key="root-fact",
        value="kept",
        provenance={"root": str(root), "repository_id": "repo-1"},
    )
    saved = store.record(record)
    loaded = store.get(saved.record_id, root=str(root), repository_id="repo-1")
    assert loaded is not None
    assert loaded.value == "kept"


def test_memory_record_find_delete_and_restart_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    first = MemoryStore(AgentStateStore(db_path, enabled=True))
    saved = first.record(MemoryRecord.create(
        kind=MemoryKind.FACT,
        scope=AgentScope.REPOSITORY,
        key="restart-fact",
        value="persisted",
        provenance={"root": str(tmp_path)},
    ))
    assert first.find(scope=AgentScope.REPOSITORY, key="restart-fact", root=str(tmp_path), semantic=False)

    reopened = MemoryStore(AgentStateStore(db_path, enabled=True))
    loaded = reopened.get(saved.record_id, root=str(tmp_path))
    assert loaded is not None and loaded.value == "persisted"
    assert reopened.delete(saved.record_id) is True
    assert reopened.get(saved.record_id) is None


def test_relation_traverse_deduplicates_bidirectional_edge(tmp_path: Path) -> None:
    store = MemoryStore(AgentStateStore(tmp_path / "state.db", enabled=True))
    store.record_relation("a", "depends_on", "b")
    result = store.traverse_graph("a", max_depth=2)
    assert result["total_edges"] == 1
    assert len(result["edges"]) == 1


def test_package_audit_accepts_pyproject_manifest(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\ndependencies=['requests==2.25.1', 'safe-lib>=1']\n",
        encoding="utf-8",
    )
    result = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}}).package_audit(str(tmp_path))
    assert result["success"] is True
    assert result["manifest_only"] is True
    assert result["packages_scanned"] == 2
    assert any(item["package"] == "requests" for item in result["vulnerabilities"])


def test_test_matrix_filters_fixture_json_from_stale_index(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_real.py").write_text("def test_real(): pass\n", encoding="utf-8")
    (tmp_path / "tests" / "fixture.json").write_text(json.dumps({"not": "a test"}), encoding="utf-8")
    result = DeterministicEngine({"server": {"state_dir": str(tmp_path / "state")}}).test_matrix(str(tmp_path))
    paths = [item["path"] for item in result["test_files"]]
    assert "tests/test_real.py" in paths
    assert "tests/fixture.json" not in paths


def test_command_broker_does_not_greenlight_compileall_missing_target(tmp_path: Path) -> None:
    broker = CommandBroker({"server": {"state_dir": str(tmp_path / "state")}})
    result = broker.run("python -m compileall definitely_missing_package", str(tmp_path), "test", timeout=30, force=True)
    assert result["success"] is False
    assert result["target_missing"] is True
    assert result["allowed"] is True
    assert result["class"] == "validation"


def test_backend_transport_failures_remain_retryable() -> None:
    assert is_retryable_local_backend_error("[WinError 10054] connection reset by peer")
    assert is_retryable_local_backend_error("[WinError 10061] connection refused")
