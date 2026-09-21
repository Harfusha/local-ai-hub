from __future__ import annotations

from contextlib import closing
from pathlib import Path

from local_ai_hub import __version__
from local_ai_hub.agent_context import ContextCompiler, ContextRequest
from local_ai_hub.agent_consistency import AdaptiveContextPack, GuardWarning
from local_ai_hub.agent_events import AgentStateStore
from local_ai_hub.agent_incidents import IncidentStore
from local_ai_hub.agent_memory import MemoryStore
from local_ai_hub.agent_tasks import TaskStore
from local_ai_hub.agent_verification import VerificationStore
from local_ai_hub.leases import ScopeLeaseStore
from local_ai_hub.process_utils import is_rooted_path
from local_ai_hub.sqlite_support import connect_sqlite
from local_ai_hub.services import LocalAIServices
from tools.release_check import _iter_release_hygiene_violations
import local_ai_hub.mcp_server as mcp_mod


def test_release_version() -> None:
    assert __version__ == "4.0.0"


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
            task_id="task-current",
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


def test_deterministic_fast_fallback_remains_useful_and_explicit() -> None:
    class Deterministic:
        def context_pack(self, _root, _query, *, max_chars, max_raw_evidence):
            assert max_chars > 0 and max_raw_evidence > 0
            return {
                "success": True,
                "context": "verified route evidence",
                "evidence": [{"evidence_id": "det-route", "path": "src/routes.py"}],
            }

    services = LocalAIServices.__new__(LocalAIServices)
    services.deterministic = Deterministic()
    services.config = {"deterministic": {"context_max_chars": 5200, "context_raw_evidence": 5}}
    services._repo_cached = lambda _op, _root, _params, compute: compute()

    result = services.fast_context("C:/repo", "route", 512)

    assert result["success"] is True
    assert result["context"] == "verified route evidence"
    assert result["evidence"][0]["evidence_id"] == "det-route"
    assert result["degraded"] is True
    assert result["continuation"] == {
        "available": True,
        "mode": "full",
        "hint": "Request context mode=full only when deterministic-fast context is insufficient.",
    }


def test_unavailable_code_intelligence_keeps_lexical_context_useful() -> None:
    class RepoTools:
        def context_pack(self, _root, _query, *, max_tokens, top_k):
            assert max_tokens > 0 and top_k > 0
            return {
                "success": True,
                "root": "C:/repo",
                "context": "lexical route evidence",
                "evidence": [{"evidence_id": "lex-route", "path": "src/routes.py"}],
            }

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"features": {"rag": False}, "search": {"context_top_k": 14, "max_snippets_per_file": 3}}
    services.repo_tools = RepoTools()
    services.deterministic = None
    services.code_index = None
    services.preprocessor = None
    services.rag = None
    services.learner = None
    services.evidence_store = None

    result = services._hybrid_context_uncached("C:/repo", "route", "tenant", None, 512)

    assert result["success"] is True
    assert result["context"] == "lexical route evidence"
    assert result["evidence"][0]["evidence_id"] == "lex-route"
    assert result["semantic_used"] is False


def test_context_projection_keeps_deterministic_warning_and_evidence_authoritative() -> None:
    response = {
        "success": True,
        "context": "verified route evidence",
        "warnings": [{"code": "model_claim", "message": "discard me"}],
        "evidence_ids": ["model-evidence"],
        "adaptive_context_pack": {
            "warnings": [{
                "severity": "warning",
                "code": "preload_missing_file",
                "message": "optional preload omitted",
                "evidence_ids": [],
                "affected_paths": ["docs/missing.md"],
                "recommended_action": "continue with indexed context",
                "requires_approval": False,
            }],
            "evidence": [{"evidence_id": "det-route", "path": "src/routes.py"}],
            "repo_revision": "rev-1",
            "changed_paths": [],
        },
        "guarded": True,
        "degraded": True,
    }

    projected = mcp_mod._context_pack_projection(response)

    assert projected["context"] == "verified route evidence"
    assert projected["evidence_ids"] == ["det-route"]
    assert projected["warnings"][0]["code"] == "preload_missing_file"
    assert projected["repo_revision"] == "rev-1"
    assert projected["degraded"] is True


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
