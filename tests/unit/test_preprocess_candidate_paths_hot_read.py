from types import SimpleNamespace
from unittest.mock import Mock

import local_ai_hub.preprocess as preprocess_module
from local_ai_hub.preprocess import ProjectPreprocessor


def test_empty_candidate_lookup_skips_unused_project_configuration(tmp_path, monkeypatch):
    project_settings = Mock(return_value=None)
    resolve_context = Mock()
    monkeypatch.setattr(preprocess_module, "resolve_project_context", resolve_context)

    preprocessor = object.__new__(ProjectPreprocessor)
    preprocessor.config = {"server": {"state_dir": str(tmp_path / "state")}}
    preprocessor.state_dir = tmp_path / "state"
    preprocessor.repo_tools = SimpleNamespace(_terms=lambda _query: [])
    preprocessor._root = lambda root: str(root)
    preprocessor._project_settings = project_settings

    assert preprocessor.candidate_paths(
        str(tmp_path), "no lexical terms", include_semantic=False,
    ) == []
    project_settings.assert_not_called()
    resolve_context.assert_not_called()
