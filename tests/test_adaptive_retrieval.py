from __future__ import annotations

import threading
import time
from pathlib import Path

from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.retrieval import fuse_ranked_paths
from local_ai_hub.evidence import EvidenceStore
from local_ai_hub.services import LocalAIServices


def test_fusion_prefers_agreement_and_keeps_file_diversity() -> None:
    groups = {
        "deterministic": ["src/authority.py", "tests/test_authority.py"],
        "serena": ["src/authority.py", "src/routes.py"],
        "lexical": ["docs/old_notes.md", "src/routes.py"],
    }

    result = fuse_ranked_paths(groups, limit=3, max_per_path=1)

    assert result[0][0] == "src/authority.py"
    assert len({path for path, _score in result}) == 3
    assert all(score > 0 for _path, score in result)


def test_project_retrieval_weights_tune_sources_but_preserve_authority() -> None:
    groups = {
        "deterministic": ["src/authority.py"],
        "code_index": ["src/indexed.py"],
        "lexical": ["docs/only-lexical.md", "src/authority.py"],
        "serena": ["src/routes.py", "docs/only-lexical.md"],
    }

    baseline = dict(fuse_ranked_paths(groups, limit=8))
    tuned = dict(fuse_ranked_paths(
        groups, limit=8,
        source_weights={"lexical": 0.25, "deterministic": 0.0, "code_index": 0.0},
    ))

    assert tuned["src/authority.py"] >= 1.25 / 61
    assert tuned["src/indexed.py"] >= round(1.20 / 61, 6)
    assert tuned["docs/only-lexical.md"] < baseline["docs/only-lexical.md"]
    assert set(tuned) == set(baseline)


def test_pinned_project_hint_survives_fusion_cap_but_remains_policy_checked(tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    deterministic_paths = [f"det-{index % 5}/file-{index}.py" for index in range(28)]
    indexed_paths = [f"index-{index % 5}/file-{index}.py" for index in range(24)]
    preprocessed_paths = [f"prep-{index % 5}/file-{index}.py" for index in range(20)]

    class FakeRepoTools:
        @staticmethod
        def iter_files(_root):
            return []

        @staticmethod
        def context_pack_paths(root, query, paths, **kwargs):
            captured["paths"] = tuple(paths)
            captured["kwargs"] = kwargs
            return {
                "success": True, "root": root, "query": query,
                "context": "safe evidence",
                "evidence": [{
                    "path": paths[0], "start_line": 1, "end_line": 1,
                    "text": "safe evidence", "content_hash": "hash-1",
                }],
                "scanned_files": 1,
            }

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"search": {}, "features": {"rag": False}, "preprocessing": {}}
    services.learner = None
    services.repo_tools = FakeRepoTools()
    services.deterministic = type("Deterministic", (), {
        "related_paths": lambda *_args, **_kwargs: deterministic_paths,
    })()
    services.code_index = type("CodeIndex", (), {
        "related_paths": lambda *_args, **_kwargs: indexed_paths,
    })()
    services.preprocessor = type("Preprocessor", (), {
        "candidate_paths": lambda *_args, **_kwargs: preprocessed_paths,
    })()
    services.external_tools = None
    services.evidence_store = None
    services.rag = None
    services._external_context_candidates = lambda *_args, **_kwargs: ({}, [], {})

    result = services._hybrid_context_uncached(
        str(tmp_path), "context", "tenant", None, 400,
        quality_first=True,
        path_hints=(
            {"path": "docs/pinned.md", "provenance": "project_config:pinned_context"},
            {"path": "private/blocked.md", "provenance": "project_config:pinned_context"},
        ),
        exclude_paths=("private",),
    )

    assert result["success"] is True
    assert "docs/pinned.md" in captured["paths"]
    assert "private/blocked.md" not in captured["paths"]
    assert "docs/pinned.md" not in captured["kwargs"]["force_include_paths"]


def test_context_reader_keeps_soft_ignored_pinned_candidate_unread(tmp_path: Path) -> None:
    ignored = tmp_path / "vendor" / "pinned.md"
    ignored.parent.mkdir()
    ignored.write_text("unique-pinned-contract-marker", encoding="utf-8")
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})

    result = tools.context_pack_paths(
        str(tmp_path), "unique-pinned-contract-marker", ["vendor/pinned.md"],
    )

    assert result["success"] is True
    assert result["evidence"] == []
    assert "unique-pinned-contract-marker" not in result["context"]


def test_terms_keep_compounds_and_drop_generic_request_words(tmp_path: Path) -> None:
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "search": {"max_terms": 12},
    }
    tools = RepositoryTools(cfg)

    terms = tools.search_terms("Implement the missing host-authoritative route-repair seam")

    assert "host-authoritative" in terms
    assert "route-repair" in terms
    assert "the" not in terms
    assert "implement" not in terms
    assert "host" not in terms
    assert "route" not in terms


def test_lexical_command_is_path_bounded(tmp_path: Path) -> None:
    cfg = {
        "server": {"state_dir": str(tmp_path / "state")},
        "search": {"use_git_grep_fallback": True},
        "rag": {
            "extensions": [".py", ".cs"],
            "ignore_dirs": ["Library", "node_modules"],
        },
    }
    tools = RepositoryTools(cfg)

    command = tools._git_grep_command(tmp_path, ["host-authoritative", "seam"], 24)

    assert command[:5] == ["git", "-C", str(tmp_path), "grep", "-n"]
    assert "-m" in command
    assert "--untracked" in command
    assert "--" in command
    assert "*.py" in command
    assert "*.cs" in command
    assert ":(exclude)library/**" in command
    assert ":(exclude)node_modules/**" in command


def test_adaptive_external_context_queries_serena_without_keyword_gates(tmp_path: Path) -> None:
    source = tmp_path / "src" / "authority.py"
    source.parent.mkdir()
    source.write_text("class Authority: pass\n", encoding="utf-8")

    calls: list[tuple[str, str]] = []

    class FakeRepoTools:
        @staticmethod
        def search_terms(_query: str) -> list[str]:
            return ["host-authoritative", "route-repair"]

    class FakeExternalTools:
        def query(self, _root: str, _query: str, *, backend: str, action: str, limit: int) -> dict:
            calls.append((backend, action))
            return {"success": True, "results": [{"path": "src/authority.py"}], "backend": backend}

    services = LocalAIServices.__new__(LocalAIServices)
    services.repo_tools = FakeRepoTools()
    services.external_tools = FakeExternalTools()

    groups, warnings, states = services._external_context_candidates(str(tmp_path), "Explain the architecture")

    assert warnings == []
    assert {backend for backend, _action in calls} == {"serena"}
    assert all(action == "search" for _backend, action in calls)
    assert groups["serena"] == ["src/authority.py"]
    assert states == {"serena": "used"}


def test_external_context_accepts_normalized_mcp_result_wrapper(tmp_path: Path) -> None:
    source = tmp_path / "src" / "authority.py"
    source.parent.mkdir()
    source.write_text("class Authority: pass\n", encoding="utf-8")

    class FakeRepoTools:
        @staticmethod
        def search_terms(_query: str) -> list[str]:
            return ["Authority"]

    class FakeExternalTools:
        def query(self, _root: str, _query: str, *, backend: str, action: str, limit: int) -> dict:
            return {"success": True, "backend": backend, "result": {"matches": [{"file_path": "src/authority.py"}]}}

    services = LocalAIServices.__new__(LocalAIServices)
    services.repo_tools = FakeRepoTools()
    services.external_tools = FakeExternalTools()
    services.config = {"search": {"context_backend_timeout_seconds": 1}}

    groups, warnings, states = services._external_context_candidates(str(tmp_path), "Find Authority")

    assert warnings == []
    assert groups == {"serena": ["src/authority.py"]}
    assert states == {"serena": "used"}


def test_external_candidate_extractor_accepts_nested_backend_payload(tmp_path: Path) -> None:
    source = tmp_path / "src" / "routes.py"
    source.parent.mkdir()
    source.write_text("def route(): pass\n", encoding="utf-8")

    payload = {"data": {"matches": [{"file_path": "src/routes.py"}]}}

    result = LocalAIServices._external_candidate_paths(str(tmp_path), payload)

    assert result == ["src/routes.py"]


def test_external_candidate_extractor_accepts_serena_path_key_mapping(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "slash.py").write_text("def slash(): pass\n", encoding="utf-8")
    (source_dir / "backslash.py").write_text("def backslash(): pass\n", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside.write_text("def outside(): pass\n", encoding="utf-8")

    payload = {
        "result": {
            "src/slash.py": ["slash match"],
            r"src\backslash.py": ["backslash match"],
            str(outside): ["outside match"],
        }
    }

    result = LocalAIServices._external_candidate_paths(str(tmp_path), payload)

    assert result == ["src/slash.py", "src/backslash.py"]


def test_external_context_preserves_query_case_for_serena(tmp_path: Path) -> None:
    source = tmp_path / "src" / "probe.py"
    source.parent.mkdir()
    source.write_text("class SerenaLiveTarget: pass\n", encoding="utf-8")

    class FakeRepoTools:
        @staticmethod
        def search_terms(_query: str) -> list[str]:
            return ["serenalivetarget"]

    class FakeExternalTools:
        @staticmethod
        def query(_root: str, query: str, *, backend: str, action: str, limit: int, timeout: float | None = None) -> dict:
            matches = {"src/probe.py": ["SerenaLiveTarget"]} if query == "SerenaLiveTarget" else {}
            return {"success": True, "backend": backend, "result": matches}

    services = LocalAIServices.__new__(LocalAIServices)
    services.repo_tools = FakeRepoTools()
    services.external_tools = FakeExternalTools()
    services.config = {"search": {"context_backend_timeout_seconds": 1}}

    groups, warnings, states = services._external_context_candidates(str(tmp_path), "SerenaLiveTarget")

    assert groups == {"serena": ["src/probe.py"]}
    assert warnings == []
    assert states == {"serena": "used"}


def test_external_context_backend_timeout_isolated_and_reported(tmp_path: Path) -> None:
    source = tmp_path / "src" / "routes.py"
    source.parent.mkdir()
    source.write_text("def route(): pass\n", encoding="utf-8")
    release = threading.Event()

    class FakeRepoTools:
        @staticmethod
        def search_terms(_query: str) -> list[str]:
            return ["route-repair"]

    class FakeExternalTools:
        def query(self, _root: str, _query: str, *, backend: str, action: str, limit: int) -> dict:
            if backend == "serena":
                release.wait(1)
            return {"success": True, "results": [{"path": "src/routes.py"}]}

    services = LocalAIServices.__new__(LocalAIServices)
    services.repo_tools = FakeRepoTools()
    services.external_tools = FakeExternalTools()
    services.config = {"search": {"context_backend_timeout_seconds": 0.2}}

    started = time.monotonic()
    groups, warnings, states = services._external_context_candidates(str(tmp_path), "route-repair")
    elapsed = time.monotonic() - started
    release.set()

    assert elapsed < 0.6
    assert any("serena" in warning and "timeout" in warning.lower() for warning in warnings)
    assert states == {"serena": "degraded"}


def test_concurrent_context_requests_bound_serena_workers(tmp_path: Path) -> None:
    release = threading.Event()
    gate = threading.Barrier(3)
    lock = threading.Lock()
    active = {"serena": 0}
    maximum = {"serena": 0}

    class FakeRepoTools:
        @staticmethod
        def search_terms(_query: str) -> list[str]:
            return ["route"]

    class FakeExternalTools:
        def query(self, _root: str, _query: str, *, backend: str, action: str, limit: int) -> dict:
            with lock:
                active[backend] += 1
                maximum[backend] = max(maximum[backend], active[backend])
            try:
                if backend == "serena":
                    release.wait(1)
                return {"success": True, "results": [{"path": "src/routes.py"}]}
            finally:
                with lock:
                    active[backend] -= 1

    services = LocalAIServices.__new__(LocalAIServices)
    services.repo_tools = FakeRepoTools()
    services.external_tools = FakeExternalTools()
    services.config = {"search": {"context_backend_timeout_seconds": 0.08}}
    outputs = []

    def retrieve() -> None:
        gate.wait()
        outputs.append(services._external_context_candidates(str(tmp_path), "route"))

    workers = [threading.Thread(target=retrieve) for _ in range(2)]
    for worker in workers:
        worker.start()
    gate.wait()
    for worker in workers:
        worker.join(0.5)
    release.set()
    for worker in workers:
        worker.join(0.5)

    assert len(outputs) == 2
    assert maximum["serena"] == 1
    assert all(result[2]["serena"] == "degraded" for result in outputs)


def test_external_context_malformed_backend_response_is_reported(tmp_path: Path) -> None:
    source = tmp_path / "src" / "routes.py"
    source.parent.mkdir()
    source.write_text("def route(): pass\n", encoding="utf-8")
    class FakeRepoTools:
        @staticmethod
        def search_terms(_query: str) -> list[str]:
            return ["route-repair"]

    class FakeExternalTools:
        def query(self, _root: str, _query: str, *, backend: str, action: str, limit: int) -> dict:
            if backend == "serena":
                return {"success": True, "results": "not-a-list"}
            return {"success": True, "results": [{"path": "src/routes.py"}]}

    services = LocalAIServices.__new__(LocalAIServices)
    services.repo_tools = FakeRepoTools()
    services.external_tools = FakeExternalTools()

    groups, warnings, states = services._external_context_candidates(str(tmp_path), "route-repair")

    assert any("serena" in warning and "malformed" in warning.lower() for warning in warnings)
    assert states == {"serena": "degraded"}


def test_external_context_backend_crash_is_isolated_and_redacted(tmp_path: Path) -> None:
    class FakeRepoTools:
        @staticmethod
        def search_terms(_query: str) -> list[str]:
            return ["route"]

    class CrashingExternalTools:
        @staticmethod
        def query(_root: str, _query: str, *, backend: str, action: str, limit: int) -> dict:
            raise RuntimeError("private backend token")

    services = LocalAIServices.__new__(LocalAIServices)
    services.repo_tools = FakeRepoTools()
    services.external_tools = CrashingExternalTools()
    services.config = {"search": {"context_backend_timeout_seconds": 0.2}}

    groups, warnings, states = services._external_context_candidates(str(tmp_path), "route")

    assert groups == {}
    assert states == {"serena": "degraded"}
    assert warnings == ["serena degraded: RuntimeError"]
    assert "private backend token" not in " ".join(warnings)


def test_rag_exception_degrades_and_keeps_evidence_traceable(tmp_path: Path) -> None:
    source = tmp_path / "src" / "routes.py"
    source.parent.mkdir()
    source.write_text("def route(): pass\n", encoding="utf-8")

    class FakeRepoTools:
        @staticmethod
        def search_terms(_query: str) -> list[str]:
            return ["route"]

        @staticmethod
        def context_pack(root: str, query: str, *, max_tokens: int, top_k: int) -> dict:
            return {
                "success": True, "root": root, "query": query, "context": "route evidence",
                "evidence": [{"path": "src/routes.py", "start_line": 1, "end_line": 1, "text": "def route(): pass"}],
                "scanned_files": 1,
            }

        @staticmethod
        def context_pack_paths(
            root: str, query: str, _paths: list[str], *, max_tokens: int, top_k: int,
        ) -> dict:
            return FakeRepoTools.context_pack(root, query, max_tokens=max_tokens, top_k=top_k)

    class FakeRag:
        @staticmethod
        def workspace_id(_root: str) -> str:
            return "workspace-1"

        @staticmethod
        def list_workspaces(_tenant: str) -> list[dict]:
            return [{"workspace": "workspace-1"}]

        @staticmethod
        def search(*_args, **_kwargs):
            raise RuntimeError("database unavailable")

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"search": {}, "features": {"rag": True}, "preprocessing": {}}
    services.learner = None
    services.repo_tools = FakeRepoTools()
    services.deterministic = type("Deterministic", (), {"related_paths": lambda *_args, **_kwargs: ["src/routes.py"]})()
    services.code_index = None
    services.preprocessor = None
    services.external_tools = None
    services.evidence_store = None
    services.rag = FakeRag()

    result = services._hybrid_context_uncached(
        str(tmp_path), "route", "tenant", None, 400, quality_first=True
    )

    assert result["success"] is True
    assert result["retrieval"]["backend_states"]["rag"] == "degraded"
    assert any("rag degraded" in warning for warning in result["retrieval"]["warnings"])
    assert result["evidence"][0]["evidence_id"]


def test_rag_malformed_chunk_is_skipped_without_failing_context(tmp_path: Path) -> None:
    source = tmp_path / "src" / "routes.py"
    source.parent.mkdir()
    source.write_text("def route(): pass\n", encoding="utf-8")

    class FakeRepoTools:
        @staticmethod
        def search_terms(_query: str) -> list[str]:
            return ["route"]

        @staticmethod
        def context_pack(root: str, query: str, *, max_tokens: int, top_k: int) -> dict:
            return {"success": True, "root": root, "query": query, "context": "route evidence", "evidence": [], "scanned_files": 1}

    class FakeRag:
        @staticmethod
        def workspace_id(_root: str) -> str:
            return "workspace-1"

        @staticmethod
        def list_workspaces(_tenant: str) -> list[dict]:
            return [{"workspace": "workspace-1"}]

        @staticmethod
        def search(*_args, **_kwargs):
            return {"success": True, "revision": "r1", "results": [{"path": "src/routes.py", "chunk_no": "broken", "text": "bad"}]}

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"search": {}, "features": {"rag": True}, "preprocessing": {}}
    services.learner = None
    services.repo_tools = FakeRepoTools()
    services.deterministic = type("Deterministic", (), {"related_paths": lambda *_args, **_kwargs: ["src/routes.py"]})()
    services.code_index = None
    services.preprocessor = None
    services.external_tools = None
    services.evidence_store = None
    services.rag = FakeRag()

    result = services._hybrid_context_uncached(str(tmp_path), "route", "tenant", None, 400, quality_first=True)

    assert result["success"] is True
    assert result["retrieval"]["backend_states"]["rag"] == "degraded"
    assert any("malformed result entries" in warning for warning in result["retrieval"]["warnings"])


def test_missing_rag_revision_bypasses_context_cache(tmp_path: Path) -> None:
    class BrokenRevisionRag:
        @staticmethod
        def workspace_id(_root: str) -> str:
            return "workspace-1"

        @staticmethod
        def revision(*_args) -> str:
            raise RuntimeError("database unavailable")

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"features": {"rag": True}}
    services.rag = BrokenRevisionRag()
    services.deterministic = None
    services._repo_cached = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cache must be bypassed"))
    captured = {}

    def uncached(*_args, **kwargs):
        captured.update(kwargs)
        return {"success": True, "context": "fresh", "retrieval": {"warnings": []}}

    services._hybrid_context_uncached = uncached

    result = services._hybrid_context(str(tmp_path), "route", "tenant", None, 400, quality_first=True)

    assert result["context"] == "fresh"
    assert result["cache_hit"] is False
    assert result["cache_layer"] == "workspace-bypassed"
    assert captured["rag_revision_available"] is False


def test_incomplete_evidence_receipt_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "src" / "routes.py"
    source.parent.mkdir()
    source.write_text("def route(): pass\n", encoding="utf-8")

    class FakeRepoTools:
        @staticmethod
        def search_terms(_query: str) -> list[str]:
            return ["route"]

        @staticmethod
        def context_pack(root: str, query: str, *, max_tokens: int, top_k: int) -> dict:
            return {"success": True, "root": root, "query": query, "context": "route evidence", "evidence": [{"path": "src/routes.py"}], "scanned_files": 1}

    class IncompleteEvidenceStore:
        @staticmethod
        def put_many(_root: str, _evidence: list[dict]) -> list[dict]:
            return [{"path": "src/routes.py"}]

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"search": {}, "features": {"rag": False}, "preprocessing": {}}
    services.learner = None
    services.repo_tools = FakeRepoTools()
    services.deterministic = type("Deterministic", (), {"related_paths": lambda *_args, **_kwargs: ["src/routes.py"]})()
    services.code_index = None
    services.preprocessor = None
    services.external_tools = None
    services.evidence_store = IncompleteEvidenceStore()
    services.rag = None

    result = services._hybrid_context_uncached(
        str(tmp_path), "route", "tenant", None, 400, quality_first=True
    )

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["stop_code"] == "context_evidence_receipt_incomplete"


def test_evidence_store_persists_raw_context_pack_snippets(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "state")
    item = {
        "path": "src/routes.py", "start_line": 4, "end_line": 4,
        "file_sha256": "file-hash", "raw": "def route(): pass",
    }

    stored = store.put_many(str(tmp_path), [item])

    assert stored[0].get("evidence_id")
    fetched = store.get(stored[0]["evidence_id"], verify=False)
    assert fetched["success"] is True
    assert fetched["text"] == item["raw"]


def test_all_adaptive_backends_keep_multifile_evidence_and_report_coverage(tmp_path: Path) -> None:
    for name in ("routes", "handlers", "models"):
        source = tmp_path / "src" / f"{name}.py"
        source.parent.mkdir(exist_ok=True)
        source.write_text(f"def {name}(): pass\n", encoding="utf-8")

    requested_paths: list[str] = []

    class FakeRepoTools:
        @staticmethod
        def iter_files(_root):
            return [str(path) for path in tmp_path.rglob("*") if path.is_file()]

        @staticmethod
        def search_terms(_query: str) -> list[str]:
            return ["route-repair"]

        @staticmethod
        def context_pack_paths(root: str, query: str, paths: list[str], *, max_tokens: int, top_k: int, **_kwargs) -> dict:
            requested_paths.extend(paths)
            return {
                "success": True, "root": root, "query": query, "context": "route evidence",
                "evidence": [{"path": "src/routes.py", "start_line": 1, "end_line": 1, "text": "def routes(): pass"}],
                "scanned_files": 1,
            }

    class FakeExternal:
        @staticmethod
        def query(_root: str, _query: str, *, backend: str, action: str, limit: int) -> dict:
            path = "src/handlers.py" if backend == "serena" else "src/models.py"
            return {"success": True, "results": [{"path": path}]}

    class FakeRag:
        @staticmethod
        def workspace_id(_root: str) -> str:
            return "workspace-1"

        @staticmethod
        def list_workspaces(_tenant: str) -> list[dict]:
            return [{"workspace": "workspace-1"}]

        @staticmethod
        def search(*_args, **_kwargs) -> dict:
            return {"success": True, "results": [
                {"path": "src/handlers.py", "chunk_no": 1, "text": "handler evidence", "content_hash": "h1"},
                {"path": "src/models.py", "chunk_no": 2, "text": "model evidence", "content_hash": "h2"},
                {"path": "private/generated.py", "chunk_no": 3, "text": "must not leak", "content_hash": "h3"},
            ]}

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"search": {}, "features": {"rag": True}, "preprocessing": {}}
    services.learner = None
    services.repo_tools = FakeRepoTools()
    services.deterministic = type("Deterministic", (), {"related_paths": lambda *_args, **_kwargs: ["src/routes.py"]})()
    services.code_index = type("CodeIndex", (), {"related_paths": lambda *_args, **_kwargs: ["src/routes.py", "src/models.py"]})()
    services.preprocessor = type("Preprocessor", (), {"candidate_paths": lambda *_args, **_kwargs: ["src/handlers.py"]})()
    services.external_tools = FakeExternal()
    services.evidence_store = None
    services.rag = FakeRag()

    result = services._hybrid_context_uncached(
        str(tmp_path), "route-repair across handlers and models", "tenant", None, 900,
        quality_first=True, exclude_paths=("private/**",), force_include_paths=("private/generated.py",),
    )

    states = result["retrieval"]["backend_states"]
    assert all(states[name] == "used" for name in (
        "deterministic", "code_index", "preprocessor", "serena", "lexical", "rag"
    )), states
    assert result["retrieval"]["quality"]["file_coverage"] == 3
    assert result["retrieval"]["quality"]["cross_backend_agreement_count"] >= 1
    assert all(item.get("evidence_id") for item in result["evidence"])
    assert all(item.get("path") != "private/generated.py" for item in result["evidence"])
    assert "must not leak" not in result["context"]
    assert "private/generated.py" not in requested_paths


def test_external_context_candidates_skips_when_empty_query(tmp_path: Path) -> None:
    services = LocalAIServices.__new__(LocalAIServices)
    called = []

    class FakeExternal:
        call_timeout = 20.0
        def query(self, *args, **kwargs):
            called.append((args, kwargs))
            return {"success": True}

    services.external_tools = FakeExternal()
    services.repo_tools = RepositoryTools({"search": {"max_terms": 8}})

    groups, warnings, states = services._external_context_candidates(str(tmp_path), "")
    assert groups == {}
    assert states == {"serena": "skipped"}
    assert called == []

    groups, warnings, states = services._external_context_candidates(str(tmp_path), "   ")
    assert groups == {}
    assert states == {"serena": "skipped"}
    assert called == []


def test_external_context_candidates_skips_disabled_serena(tmp_path: Path) -> None:
    services = LocalAIServices.__new__(LocalAIServices)
    called = []

    class DisabledExternal:
        serena_enabled = False

        def query(self, *args, **kwargs):
            called.append((args, kwargs))
            raise AssertionError("disabled Serena must not be queried")

    services.external_tools = DisabledExternal()
    services.repo_tools = RepositoryTools({"search": {"max_terms": 8}})

    groups, warnings, states = services._external_context_candidates(str(tmp_path), "FindProjectRoute")

    assert groups == {}
    assert warnings == []
    assert states == {"serena": "skipped"}
    assert called == []


def test_adaptive_selection_excludes_disabled_serena(tmp_path: Path) -> None:
    services = LocalAIServices.__new__(LocalAIServices)

    class DisabledExternal:
        serena_enabled = False

        @staticmethod
        def query(*_args, **_kwargs):
            raise AssertionError("disabled Serena must not be queried")

    services.config = {"search": {"context_backend_timeout_seconds": 0.2}, "features": {"rag": False}, "preprocessing": {}}
    services.learner = None
    services.repo_tools = RepositoryTools({"search": {"max_terms": 8}})
    services.deterministic = None
    services.code_index = None
    services.preprocessor = None
    services.external_tools = DisabledExternal()
    services.evidence_store = None
    services.rag = None
    root = tmp_path / "repo"
    root.mkdir()
    (root / "routes.py").write_text("def project_route():\n    return True\n", encoding="utf-8")

    result = services._hybrid_context_uncached(
        str(root), "Find project route", "tenant", None, 200, quality_first=True,
    )

    selection = result["retrieval"]["backend_selection"]
    assert selection["selected_backends"] == []
    assert selection["decision"] == "no_optional_backend_available"
    assert result["retrieval"]["backend_states"]["serena"] == "skipped"


def test_adaptive_context_reports_lexical_quality_and_fallback(tmp_path: Path) -> None:
    evidence = {
        "evidence_id": "ev-1", "path": "src/routes.py", "start_line": 1,
        "end_line": 1, "text": "def route(): pass", "file_sha256": "sha256-route",
    }
    lexical_quality = {
        "coverage": {"scope": "search_candidates", "candidate_count": 2, "included_evidence_count": 1, "complete": False},
        "freshness": {"scope": "included_evidence", "status": "snapshot_identity_checked", "checked_files": 1, "complete": False},
        "truncated": True,
        "truncation": {"budget_chars": 512, "truncated_snippet_count": 1},
    }

    class FakeRepoTools:
        @staticmethod
        def search_terms(_query: str) -> list[str]:
            return ["ProjectRoute"]

        @staticmethod
        def context_pack(*_args, **_kwargs) -> dict:
            return {"success": True, "root": str(tmp_path), "context": evidence["text"], "evidence": [evidence], "scanned_files": 2, **lexical_quality}

        @staticmethod
        def context_pack_paths(*_args, **_kwargs) -> dict:
            return FakeRepoTools.context_pack()

    class CrashingExternal:
        serena_enabled = True

        @staticmethod
        def query(*_args, **_kwargs):
            raise RuntimeError("external backend failed")

    class FakeRag:
        @staticmethod
        def search(*_args, **_kwargs):
            return {
                "success": True,
                "revision": "r1",
                "truncated": True,
                "coverage": {"complete": False},
                "results": [
                    {
                        "evidence_id": "rag-1", "path": "src/routes.py", "chunk_no": 1,
                        "text": "a" * 500, "content_hash": "hash-1", "revision": "r1",
                    },
                    {
                        "evidence_id": "rag-2", "path": "src/routes.py", "chunk_no": 2,
                        "text": "b" * 500, "content_hash": "hash-2", "revision": "r1",
                    },
                ],
            }

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"search": {"context_backend_timeout_seconds": 0.2}, "features": {"rag": True}, "preprocessing": {}}
    services.learner = None
    services.repo_tools = FakeRepoTools()
    services.deterministic = None
    services.code_index = None
    services.preprocessor = None
    services.external_tools = CrashingExternal()
    services.evidence_store = None
    services.rag = FakeRag()

    result = services._hybrid_context_uncached(
        str(tmp_path), "Find ProjectRoute implementation", "tenant", "workspace-1", 200,
        quality_first=True, rag_revision="r1", rag_revision_available=True,
    )

    retrieval = result["retrieval"]
    assert retrieval["backend_states"]["serena"] == "degraded"
    assert retrieval["lexical"] == lexical_quality
    assert retrieval["fallbacks"] == [{"backend": "serena", "fallback": "lexical"}]
    assert retrieval["semantic"]["coverage"]["candidate_count"] == 2
    assert retrieval["semantic"]["coverage"]["complete"] is False
    assert retrieval["semantic"]["coverage"]["omitted_chunk_count"] == 1
    assert retrieval["semantic"]["freshness"]["status"] == "not_checked"
    assert retrieval["semantic"]["freshness"]["declared_hash_chunks"] == 1
    assert retrieval["semantic"]["truncated"] is True
    assert retrieval["semantic"]["truncation"]["backend_reported_truncated"] is True


def test_semantic_coverage_preserves_incomplete_backend_receipt(tmp_path: Path) -> None:
    class FakeRepoTools:
        @staticmethod
        def search_terms(_query: str) -> list[str]:
            return ["ProjectRoute"]

        @staticmethod
        def context_pack(*_args, **_kwargs) -> dict:
            return {"success": True, "root": str(tmp_path), "context": "", "evidence": [], "scanned_files": 1}

        @staticmethod
        def context_pack_paths(*_args, **_kwargs) -> dict:
            return FakeRepoTools.context_pack()

    class FakeRag:
        @staticmethod
        def search(*_args, **_kwargs):
            return {
                "success": True,
                "revision": "r1",
                "truncated": False,
                "coverage": {"complete": False},
                "results": [{
                    "evidence_id": "rag-1", "path": "src/routes.py", "chunk_no": 1,
                    "text": "def route(): pass", "content_hash": "hash-1", "revision": "r1",
                }],
            }

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"search": {"context_backend_timeout_seconds": 0.2}, "features": {"rag": True}, "preprocessing": {}}
    services.learner = None
    services.repo_tools = FakeRepoTools()
    services.deterministic = None
    services.code_index = None
    services.preprocessor = None
    services.external_tools = None
    services.evidence_store = None
    services.rag = FakeRag()

    result = services._hybrid_context_uncached(
        str(tmp_path), "ProjectRoute", "tenant", "workspace-1", 400,
        quality_first=True, rag_revision="r1", rag_revision_available=True,
    )

    semantic = result["retrieval"]["semantic"]
    assert semantic["coverage"]["complete"] is False
    assert semantic["truncated"] is True
    assert semantic["truncation"]["backend_coverage_complete"] is False
    assert semantic["truncation"]["complete"] is False


def test_path_hints_rank_context_evidence_without_narrowing_lexical_search(tmp_path: Path) -> None:
    class FakeRepoTools:
        targeted_calls = 0
        full_calls = 0

        @staticmethod
        def search_terms(_query: str) -> list[str]:
            return ["unique"]

        def context_pack_paths(self, root: str, query: str, paths: list[str], *, max_tokens: int, top_k: int) -> dict:
            self.targeted_calls += 1
            return {
                "success": True, "root": root, "query": query, "context": "hinted only",
                "evidence": [{"path": "src/hinted.py", "start_line": 1, "end_line": 1, "raw": "unique"}],
                "scanned_files": len(paths),
            }

        def context_pack(self, root: str, query: str, *, max_tokens: int, top_k: int) -> dict:
            self.full_calls += 1
            return {
                "success": True, "root": root, "query": query, "context": "all candidates",
                "evidence": [
                    {"path": "src/hinted.py", "start_line": 1, "end_line": 1, "raw": "unique"},
                    {"path": "src/unhinted.py", "start_line": 1, "end_line": 1, "raw": "unique"},
                ],
                "scanned_files": 2,
            }

    class FakeDeterministic:
        @staticmethod
        def related_paths(_root: str, _query: str, *, limit: int) -> list[str]:
            return ["src/hinted.py"]

    repo_tools = FakeRepoTools()
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"search": {}, "features": {"rag": False}, "preprocessing": {}}
    services.learner = None
    services.repo_tools = repo_tools
    services.deterministic = FakeDeterministic()
    services.code_index = None
    services.preprocessor = None
    services.external_tools = None
    services.evidence_store = None
    services.rag = None

    result = services._hybrid_context_uncached(
        str(tmp_path), "unique source", "tenant", None, 400, quality_first=True
    )

    paths = [item["path"] for item in result["evidence"]]
    assert paths == ["src/hinted.py", "src/unhinted.py"]
    assert repo_tools.full_calls == 1
    assert repo_tools.targeted_calls == 0


def test_explicit_path_hint_cannot_read_configured_ignored_directory(tmp_path: Path) -> None:
    private = tmp_path / "node_modules" / "private.py"
    private.parent.mkdir()
    private.write_text("unique_secret_marker = True\n", encoding="utf-8")
    tools = RepositoryTools({"rag": {"extensions": [".py"], "ignore_dirs": ["node_modules"]}})

    result = tools.search_paths(str(tmp_path), "unique_secret_marker", ["node_modules/private.py"])

    assert result["success"] is True
    assert result["scanned_files"] == 0
    assert result["results"] == []


def test_ignored_directory_is_filtered_from_accelerated_search(monkeypatch, tmp_path: Path) -> None:
    private = tmp_path / "node_modules" / "private.py"
    private.parent.mkdir()
    private.write_text("unique_secret_marker = True\n", encoding="utf-8")
    tools = RepositoryTools({"rag": {"extensions": [".py"], "ignore_dirs": ["node_modules"]}})
    monkeypatch.setattr(
        tools,
        "_ripgrep_candidates",
        lambda _base, _terms, _limit: ([("node_modules/private.py", 1)], False),
    )

    result = tools.search(str(tmp_path), "unique_secret_marker")

    assert result["success"] is True
    assert result["scanned_files"] == 0
    assert result["results"] == []


def test_accelerated_search_rejects_candidates_outside_repository(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "private.py"
    outside.write_text("unique_secret_marker = True\n", encoding="utf-8")
    tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    monkeypatch.setattr(
        tools,
        "_ripgrep_candidates",
        lambda _base, _terms, _limit: ([("../private.py", 1)], False),
    )

    result = tools.search(str(root), "unique_secret_marker")

    assert result["success"] is True
    assert result["scanned_files"] == 0
    assert result["results"] == []


def test_explicit_path_hint_cannot_read_configured_ignored_extension(tmp_path: Path) -> None:
    private = tmp_path / "private.secret"
    private.write_text("unique_secret_marker = True\n", encoding="utf-8")
    tools = RepositoryTools({"rag": {"extensions": [".secret"], "ignore_extensions": [".secret"]}})

    result = tools.search_paths(str(tmp_path), "unique_secret_marker", ["private.secret"])

    assert result["success"] is True
    assert result["scanned_files"] == 0
    assert result["results"] == []


def test_explicit_path_hint_cannot_read_extension_outside_allowlist(tmp_path: Path) -> None:
    private = tmp_path / "private.txt"
    private.write_text("unique_secret_marker = True\n", encoding="utf-8")
    tools = RepositoryTools({"rag": {"extensions": [".py"], "ignore_extensions": []}})

    result = tools.search_paths(str(tmp_path), "unique_secret_marker", ["private.txt"])

    assert result["success"] is True
    assert result["scanned_files"] == 0
    assert result["results"] == []


def test_explicit_path_hint_cannot_escape_repository_root(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    private = tmp_path / "private.py"
    private.write_text("unique_secret_marker = True\n", encoding="utf-8")
    tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    monkeypatch.setattr(tools, "_read_snapshot", lambda path: pytest.fail("unsafe hint reached source reading"))

    result = tools.search_paths(str(root), "unique_secret_marker", ["../private.py"])

    assert result["success"] is False
    assert "repository-relative" in result["error"]
    assert "unique_secret_marker" not in str(result)

