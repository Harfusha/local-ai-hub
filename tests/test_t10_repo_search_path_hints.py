from __future__ import annotations

import pytest
from pathlib import Path

from local_ai_hub.project_config import PathHint
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices
from local_ai_hub.tool_agent import ToolAwareLocalAgent


class _CandidatePreprocessor:
    def __init__(self, paths: list[str]):
        self.paths = paths

    def candidate_paths(self, _root: str, _query: str, limit: int) -> list[str]:
        return self.paths[:limit]


def _search_service(tmp_path: Path, preprocessor: object) -> LocalAIServices:
    config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "rag": {"extensions": [".php", ".py"]},
        "search": {
            "prefer_git_files": False,
            "use_git_grep_fallback": False,
            "use_ripgrep_if_available": False,
            "max_files": 50,
            "max_hits": 20,
        },
    }
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = config
    services.learner = None
    services.deterministic = None
    services.code_index = None
    services.preprocessor = preprocessor
    services.repo_tools = RepositoryTools(config)
    services.evidence_store = None
    services._repo_cache_state = lambda _root: {"fingerprint": "rev-1", "kind": "test"}
    services._repo_cached = lambda _operation, _root, _params, compute: compute()
    return services


def test_repo_search_prioritizes_request_and_config_hints_without_narrowing(tmp_path: Path) -> None:
    (tmp_path / "templates" / "element").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "secret").mkdir()
    (tmp_path / "templates" / "element" / "button.php").write_text("button\n", encoding="utf-8")
    (tmp_path / "src" / "button.py").write_text("button\n", encoding="utf-8")
    (tmp_path / "secret" / "button.php").write_text("button\n", encoding="utf-8")
    (tmp_path / ".local-ai.toml").write_text(
        'entry_points = ["templates/element"]\n'
        'exclude_paths = ["secret/**"]\n'
        '[path_overrides]\n'
        '"templates/element/**" = "include"\n'
        '"secret/**" = "include"\n',
        encoding="utf-8",
    )
    services = _search_service(tmp_path, _CandidatePreprocessor(["templates/element/button.php"]))
    request_hint = PathHint(
        path="src",
        purpose="repository_search",
        scope="task",
        repository_revision="rev-1",
    )

    result = services.repo_search(
        str(tmp_path), "button", top_k=2, path_hints=[request_hint], scope="task"
    )

    assert [item["path"] for item in result["results"]] == [
        "src/button.py",
        "templates/element/button.php",
    ]
    assert result["preprocessed_hit"] is True
    assert "secret/button.php" not in {item["path"] for item in result["results"]}

    configured = services.repo_search(
        str(tmp_path), "button", top_k=2, scope="task"
    )
    assert [item["path"] for item in configured["results"]] == [
        "templates/element/button.php",
        "src/button.py",
    ]


def test_repo_search_default_scope_applies_public_repository_search_hint(tmp_path: Path) -> None:
    (tmp_path / "templates" / "element").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "templates" / "element" / "button.php").write_text(
        "button\n", encoding="utf-8"
    )
    (tmp_path / "src" / "button.py").write_text("button\n", encoding="utf-8")
    services = _search_service(tmp_path, None)

    result = services.repo_search(
        str(tmp_path),
        "button",
        top_k=2,
        path_hints=[
            PathHint(
                path="templates/element",
                purpose="repository_search",
                scope="repo_search",
            )
        ],
    )

    assert result["success"] is True
    assert [hit["path"] for hit in result["results"]] == [
        "templates/element/button.php",
        "src/button.py",
    ]


def test_repo_search_hints_cannot_restore_excluded_or_outside_results(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "secret").mkdir()
    (tmp_path / "src" / "allowed.php").write_text("needle\n", encoding="utf-8")
    (tmp_path / "src" / "quarantined.php").write_text("needle\n", encoding="utf-8")
    (tmp_path / "secret" / "blocked.php").write_text("needle\n", encoding="utf-8")
    (tmp_path / ".local-ai.toml").write_text(
        'exclude_paths = ["secret/**"]\n'
        '[path_overrides]\n'
        '"secret/**" = "include"\n',
        encoding="utf-8",
    )
    services = _search_service(tmp_path, None)
    outside = tmp_path.parent / "outside.php"
    outside.write_text("needle\n", encoding="utf-8")
    monkeypatch.setattr(
        services.repo_tools,
        "search",
        lambda *_args, **_kwargs: {
            "success": True,
            "root": str(tmp_path),
            "results": [
                {"path": "src/allowed.php", "start_line": 1},
                {"path": "src/quarantined.php", "start_line": 1, "hard_denied": True},
                {"path": "secret/blocked.php", "start_line": 1},
                {"path": "../outside.php", "start_line": 1},
            ],
            "engine": "fixture",
        },
    )

    result = services.repo_search(
        str(tmp_path),
        "needle",
        top_k=5,
        path_hints=[
            PathHint("secret/blocked.php", "repository_search", "task"),
            PathHint("src/quarantined.php", "repository_search", "task"),
            PathHint("../outside.php", "repository_search", "task"),
        ],
        scope="task",
    )

    assert [item["path"] for item in result["results"]] == ["src/allowed.php"]


def test_repo_search_uses_path_override_include_only_as_priority(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "templates" / "element").mkdir(parents=True)
    (tmp_path / "src" / "button.py").write_text("button\n", encoding="utf-8")
    (tmp_path / "templates" / "element" / "button.php").write_text(
        "button\n", encoding="utf-8"
    )
    (tmp_path / ".local-ai.toml").write_text(
        '[path_overrides]\n"templates/element/**" = "include"\n',
        encoding="utf-8",
    )
    services = _search_service(tmp_path, None)

    result = services.repo_search(str(tmp_path), "button", top_k=2)

    assert [item["path"] for item in result["results"]] == [
        "templates/element/button.php",
        "src/button.py",
    ]


def test_tool_repo_search_routes_request_hints_through_complete_service() -> None:
    class _Services:
        def __init__(self) -> None:
            self.call: tuple[object, ...] | None = None

        def repo_search(self, root, query, top_k, *, path_hints, scope):
            self.call = (root, query, top_k, path_hints, scope)
            return {"success": True, "results": [{"path": "all-candidates-kept"}]}

    class _Preprocessor:
        def candidate_paths(self, *_args, **_kwargs):
            raise AssertionError("tool route must not restrict search to preprocessor candidates")

    services = _Services()
    agent = ToolAwareLocalAgent.__new__(ToolAwareLocalAgent)
    agent.services = services
    agent.preprocessor = _Preprocessor()
    agent.evidence = None
    request_hints = [{"path": "templates/element", "purpose": "repository_search", "scope": "task"}]

    result = agent._execute_tool(
        "repo_search",
        {"query": "button", "top_k": 4, "path_hints": request_hints, "scope": "task"},
        "/tmp/repo",
        "tenant",
        "workspace",
    )

    assert result["results"] == [{"path": "all-candidates-kept"}]
    assert services.call == ("/tmp/repo", "button", 4, request_hints, "task")


def test_repo_search_logs_preprocessor_candidate_failure_and_keeps_exact_fallback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class FailingPreprocessor:
        @staticmethod
        def candidate_paths(*_args, **_kwargs):
            raise PermissionError(f"private path: {tmp_path}")

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "button.py").write_text("needle button\n", encoding="utf-8")
    services = _search_service(tmp_path, FailingPreprocessor())

    with caplog.at_level("DEBUG", logger="local_ai_hub.services"):
        result = services.repo_search(str(tmp_path), "needle", top_k=5, scope="task")

    assert result["success"] is True
    assert "src/button.py" in {item["path"] for item in result["results"]}
    messages = [record.getMessage() for record in caplog.records]
    assert any("Preprocessor candidate search skipped (PermissionError)" in message for message in messages)
    assert all(str(tmp_path) not in message for message in messages)


def test_repo_search_logs_deterministic_candidate_failure_and_keeps_exact_fallback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class FailingDeterministicIndex:
        @staticmethod
        def related_paths(*_args, **_kwargs):
            raise PermissionError(f"private path: {tmp_path}")

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "button.py").write_text("needle button\n", encoding="utf-8")
    services = _search_service(tmp_path, _CandidatePreprocessor([]))
    services.deterministic = FailingDeterministicIndex()

    with caplog.at_level("DEBUG", logger="local_ai_hub.services"):
        result = services.repo_search(str(tmp_path), "needle", top_k=5, scope="task")

    assert result["success"] is True
    assert "src/button.py" in {item["path"] for item in result["results"]}
    messages = [record.getMessage() for record in caplog.records]
    assert any("Deterministic candidate search skipped (PermissionError)" in message for message in messages)
    assert all(str(tmp_path) not in message for message in messages)


def test_repo_search_logs_code_index_candidate_failure_and_keeps_exact_fallback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class FailingCodeIndex:
        @staticmethod
        def related_paths(*_args, **_kwargs):
            raise PermissionError(f"private path: {tmp_path}")

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "button.py").write_text("needle button\n", encoding="utf-8")
    services = _search_service(tmp_path, _CandidatePreprocessor([]))
    services.code_index = FailingCodeIndex()

    with caplog.at_level("DEBUG", logger="local_ai_hub.services"):
        result = services.repo_search(str(tmp_path), "needle", top_k=5, scope="task")

    assert result["success"] is True
    assert "src/button.py" in {item["path"] for item in result["results"]}
    messages = [record.getMessage() for record in caplog.records]
    assert any("CodeIndex candidate search skipped (PermissionError)" in message for message in messages)
    assert all(str(tmp_path) not in message for message in messages)


def test_repo_search_does_not_claim_progressive_disclosure_without_receipts(tmp_path: Path) -> None:
    class IncompleteEvidenceStore:
        @staticmethod
        def put_many(_root: str, hits: list[dict]) -> list[dict]:
            return [dict(hit) for hit in hits]

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "button.py").write_text("needle button\n", encoding="utf-8")
    services = _search_service(tmp_path, _CandidatePreprocessor([]))
    services.evidence_store = IncompleteEvidenceStore()

    result = services.repo_search(str(tmp_path), "needle", top_k=5, scope="task")

    assert result["success"] is True
    assert result["progressive_disclosure"] is False
    assert "needle button" in result["results"][0]["text"]


def test_tool_repo_search_preserves_text_without_evidence_receipt() -> None:
    class Services:
        @staticmethod
        def repo_search(_root, _query, _top_k, *, path_hints, scope):
            return {
                "success": True,
                "results": [{"path": "src/button.py", "text": "needle button", "file_sha256": "hash"}],
            }

    class IncompleteEvidenceStore:
        @staticmethod
        def put_many(_root, hits):
            return [dict(hit) for hit in hits]

    agent = ToolAwareLocalAgent.__new__(ToolAwareLocalAgent)
    agent.services = Services()
    agent.preprocessor = object()
    agent.evidence = IncompleteEvidenceStore()

    result = agent._execute_tool(
        "repo_search",
        {"query": "needle", "top_k": 1},
        "/tmp/repo",
        "tenant",
        "workspace",
    )

    assert result["results"][0]["text"] == "needle button"
    assert result["progressive_disclosure"] is False
