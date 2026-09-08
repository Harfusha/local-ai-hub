from __future__ import annotations

from contextlib import closing
from pathlib import Path

from local_ai_hub import __version__
from local_ai_hub.agent_context import ContextCompiler, ContextRequest
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore
from local_ai_hub.agent_memory import MemoryStore
from local_ai_hub.agent_tasks import TaskStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.process_utils import is_rooted_path
from local_ai_hub.sqlite_support import connect_sqlite
from tools.release_check import _iter_release_hygiene_violations


def test_v2_version() -> None:
    assert __version__ == "2.4.0"


def test_rooted_path_detection_is_host_independent() -> None:
    assert is_rooted_path("C:\\repo\\project") is True
    assert is_rooted_path("D:/repo/project") is True
    assert is_rooted_path("\\\\server\\share\\repo") is True
    assert is_rooted_path("/srv/repo") is True
    assert is_rooted_path("src/module.py") is False


def test_shared_sqlite_connections_enable_foreign_keys(tmp_path: Path) -> None:
    with closing(connect_sqlite(tmp_path / "state.sqlite3")) as con:
        enabled = con.execute("PRAGMA foreign_keys").fetchone()[0]
    assert enabled == 1


def test_agent_state_hot_path_indexes_are_created(tmp_path: Path) -> None:
    store = AgentStateStore(tmp_path / "agent_state.sqlite3", enabled=True)
    TaskStore(store)
    MemoryStore(store)
    IncidentStore(store)
    VerificationStore(store)

    with closing(connect_sqlite(store.db_path)) as con:
        indexes = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}

    assert {
        "idx_agent_tasks_updated",
        "idx_agent_tasks_status_updated",
        "idx_agent_memory_expires",
        "idx_agent_incidents_lookup",
        "idx_agent_incidents_recent",
        "idx_agent_verif_task_observed",
    } <= indexes


def test_context_compile_includes_leases_and_invalidates_changed_links(tmp_path: Path) -> None:
    state = AgentStateStore(tmp_path / "agent_state.sqlite3", enabled=True)
    leases = ScopeLeaseStore(tmp_path / "state")
    repo = tmp_path / "repo"
    repo.mkdir()
    claimed = leases.claim("other-agent", str(repo), ["src/core.py"], purpose="refactor")
    assert claimed["success"] is True

    compiler = ContextCompiler(state, lease_store=leases)
    compiler.link("source", "target", "implements", path="src/core.py")
    compiled = compiler.compile(
        ContextRequest(
            task_id="task-v2",
            token_budget=512,
            include_kinds=("active_lease",),
            changed_paths=("src/core.py",),
            root=str(repo),
            tenant="current-agent",
        )
    )

    assert compiler.get_active_links("src/core.py") == []
    assert compiled.elements
    assert {el.source_kind for el in compiled.elements} == {"active_lease"}
    assert "src/core.py" in compiled.text()
    assert "other-agent" in compiled.text()


def test_release_hygiene_detector_rejects_local_payloads(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("[server]\n", encoding="utf-8")
    (tmp_path / "cache.sqlite3").write_bytes(b"sqlite")
    (tmp_path / ".agents").mkdir()
    (tmp_path / ".agents" / "progress.md").write_text("local", encoding="utf-8")
    (tmp_path / "generated").mkdir()
    (tmp_path / "generated" / "local.json").write_text("{}", encoding="utf-8")

    violations = list(_iter_release_hygiene_violations(tmp_path))
    joined = "\n".join(violations)
    assert "config.toml" in joined
    assert "cache.sqlite3" in joined
    assert ".agents" in joined
    assert "generated/local.json" in joined
