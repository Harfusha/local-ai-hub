from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from local_ai_hub import project_config
from local_ai_hub.services import LocalAIServices


@pytest.mark.parametrize(("changed_path", "expected"), [
    (".hidden.py", ".hidden.py"), ("./.hidden.py", ".hidden.py"),
    ("././.hidden.py", ".hidden.py"), ("src/example.py", "src/example.py"),
])
def test_affected_graph_preserves_hidden_prefix(tmp_path, monkeypatch, changed_path, expected):
    context = SimpleNamespace(
        config_digest="fixture", settings=SimpleNamespace(affected_tests_mapping={}),
        prioritize_paths=lambda *_args, **_kwargs: SimpleNamespace(
            paths=[], hint_used=False, fallback_used=False, hint_helped=False),
    )
    monkeypatch.setattr(project_config, "resolve_project_context", lambda *_args: context)
    service = object.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path)}}
    service._repository_test_impact_service = lambda: SimpleNamespace(affected_tests=lambda *_args: {
        "success": True, "framework": "pytest", "changed_files": [".hidden.py"],
        "test_files": [], "workspace_cache": {},
    })
    impact = Mock(return_value={"success": True, "confidence": 1.0, "indexed_changed_files": 1,
                                "changed_files_count": 1, "likely_dependents": [], "suggested_tests": []})
    service.code_index = SimpleNamespace(impact=impact)

    result = service.affected_tests(str(tmp_path), changed_paths=[changed_path])

    assert result["success"] is True
    assert impact.call_args.args[1] == [expected]
