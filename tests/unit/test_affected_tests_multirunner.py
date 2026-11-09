from types import SimpleNamespace
import asyncio
from unittest.mock import Mock

import pytest

from local_ai_hub import mcp_server, project_config
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.services import LocalAIServices


def test_mixed_runner_candidates_cannot_be_reported_complete(tmp_path, monkeypatch):
    context = SimpleNamespace(
        config_digest="fixture",
        settings=SimpleNamespace(affected_tests_mapping={}),
        prioritize_paths=lambda paths, **_kwargs: SimpleNamespace(
            paths=paths, hint_used=False, fallback_used=False, hint_helped=False,
        ),
    )
    monkeypatch.setattr(project_config, "resolve_project_context", lambda *_args: context)
    monkeypatch.setattr(project_config, "path_is_allowed", lambda *_args, **_kwargs: True)
    service = object.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path)}}
    service._repository_test_impact_service = lambda: SimpleNamespace(affected_tests=lambda *_args: {
        "success": True, "framework": "pytest", "changed_files": ["src/a.py"],
        "test_files": ["tests/test_a.py", "tests/a.test.ts"],
        "selection_complete": True, "confidence": 0.95,
    })
    service.code_index = SimpleNamespace(impact=lambda *_args, **_kwargs: {
        "success": True, "confidence": 1.0, "indexed_changed_files": 1,
        "changed_files_count": 1, "likely_dependents": [], "suggested_tests": [],
    })

    result = service.affected_tests(str(tmp_path), changed_paths=["src/a.py"])

    assert result["test_files"] == ["tests/test_a.py"]
    assert result["excluded_incompatible_tests"] == ["tests/a.test.ts"]
    assert result["selection_complete"] is False
    assert result["requires_multiple_runners"] is True
    assert result["confidence"] < 0.95


def test_deterministic_mixed_runner_selection_is_not_complete(tmp_path):
    engine = object.__new__(DeterministicEngine)
    engine._root = lambda root: root
    engine.test_matrix = lambda _root: {"framework": "pytest", "test_files": []}
    engine.get_test_source_links = lambda *_args: ["tests/test_a.py", "tests/a.test.ts"]
    engine.code_index = SimpleNamespace(impact=lambda *_args: {
        "success": True, "graph_complete": True, "suggested_tests": [],
    })
    result = engine.affected_tests(str(tmp_path), changed_paths=["src/a.py"])
    assert result["test_files"] == ["tests/test_a.py"]
    assert result["excluded_incompatible_tests"] == ["tests/a.test.ts"]
    assert result["selection_complete"] is False
    assert result["requires_multiple_runners"] is True
    assert result["confidence"] < 0.95


def test_mcp_preserves_incomplete_multirunner_selection(tmp_path, monkeypatch):
    response = {
        "success": True, "framework": "pytest", "selection_complete": False,
        "requires_multiple_runners": True, "test_files": ["tests/test_a.py"],
        "excluded_incompatible_tests": ["tests/a.test.ts"],
    }
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *_args, **_kwargs: response)
    _, result = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
        "action": "affected_tests", "root": str(tmp_path), "response_profile": "compact",
    }))
    assert result["success"] is True, result
    assert result["selection_complete"] is False
    assert result["requires_multiple_runners"] is True
    assert result["excluded_incompatible_tests"] == ["tests/a.test.ts"]


@pytest.mark.parametrize(("claimed_complete", "excluded", "multiple", "matrix_extra"), [
    (False, ["tests/a.test.ts"], False, True),
    (True, ["tests/a.test.ts"], False, True),
    (True, [], True, False),
])
def test_auto_patch_verification_rejects_mixed_runner_selection(
    tmp_path, monkeypatch, claimed_complete, excluded, multiple, matrix_extra,
):
    from local_ai_hub import commands, deterministic
    from local_ai_hub.commands import CommandBroker

    root = tmp_path.resolve()
    broker = CommandBroker({"commands": {"allowed": True, "allow_unknown": True, "allow_validation": True},
                            "server": {"state_dir": str(tmp_path / "state")}})
    monkeypatch.setattr(broker, "_transaction_root_for_context", lambda _context: root)
    monkeypatch.setattr(commands, "_patch_write_paths", lambda *_args: ["note.txt"])
    monkeypatch.setattr(commands, "_snapshot_patch_targets", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(commands, "_assert_patch_root", lambda *_args: None)
    monkeypatch.setattr(commands.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr=b""))
    broker.run = Mock(return_value={"success": True, "exit_code": 0})
    fake = SimpleNamespace(
        affected_tests=lambda *_args, **_kwargs: {
            "success": True, "selection_complete": claimed_complete, "confidence": 0.95,
            "test_files": ["tests/test_a.py"], "excluded_incompatible_tests": excluded,
            "requires_multiple_runners": multiple,
        },
        test_matrix=lambda *_args: {
            "framework": "pytest", "run_all_command": "python -m pytest -q",
            "test_files": [{"path": "tests/test_a.py"}] + ([{"path": "tests/a.test.ts"}] if matrix_extra else []),
        },
    )
    monkeypatch.setattr(deterministic, "DeterministicEngine", lambda *_args, **_kwargs: fake)
    result = broker.patch_and_verify("diff --git a/note.txt b/note.txt\n", root,
                                     command="auto", _transaction_context="transaction-1")
    assert result["success"] is False, result
    assert result.get("tests_passed") is not True
    assert result["excluded_incompatible_tests"] == excluded
    broker.run.assert_not_called()
