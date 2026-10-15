"""Deferred bundle regression source; all SQLite state belongs to tmp_path."""
import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.static_exports import named_export_status


@pytest.mark.parametrize("source,language,name,valid", [
    ("def exists():\n    pass\n", "python", "missing", False),
    ("class Outer:\n    def method(self): pass\n", "python", "method", False),
    ("__all__ = []\ndef named(): pass\n", "python", "named", True),
    ("class Hidden {}", "typescript", "Hidden", False),
    ("export class Visible {}", "typescript", "Visible", True),
    ("class Local {}\nexport { Local as Visible };", "typescript", "Visible", True),
    ("export default class OnlyDefault {}", "javascript", "OnlyDefault", False),
    ("const text = 'export class Fake {}';", "javascript", "Fake", False),
    ("// export class Fake {}\nclass Hidden {}", "javascript", "Fake", False),
    ("export { Missing } from './unknown';", "javascript", "Missing", False),
    ("const pattern = /export class Fake/;", "javascript", "Fake", False),
])
def test_static_named_exports_do_not_invent_importable_symbols(source, language, name, valid):
    assert named_export_status(source, language, name)[0] is valid


def test_existing_module_missing_and_stale_symbols_are_not_suggested(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "module.py"
    source.write_text("def exists():\n    pass\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}, "rag": {"extensions": [".py"]}}
    tools = RepositoryTools(config)
    index = CodeIndex(config, tools)
    monkeypatch.setattr(index, "_parse_file_content", lambda *_args, **_kwargs: ([{
        "name": "exists", "name_path": "exists", "kind": "function", "line": 1, "end_line": 2,
    }], [], []))
    engine = DeterministicEngine(config, tools, code_index=index)
    try:
        assert index.update_file(str(root), "module.py")["success"]
        result = engine.resolve_imports(str(root), ["exists", "missing"], "python")
        assert result["resolved_count"] == 1
        assert result["unresolved_symbols"] == ["missing"]
        assert result["resolved_imports"][0]["export_validation"] == "top_level_python_declaration"
        source.write_text("def removed():\n    pass\n", encoding="utf-8")
        stale = engine.resolve_imports(str(root), ["exists"], "python")
        assert stale["resolved_count"] == 0
        assert stale["unresolved_symbols"] == ["exists"]
        assert stale["rejected_candidates"][0]["reason"] == "stale_indexed_declaration"
    finally:
        index.close()
        observer = getattr(engine, "_cache_observer", None)
        if observer is not None:
            observer.close()
