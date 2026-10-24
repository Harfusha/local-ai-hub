from __future__ import annotations

from contextlib import closing
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.process_utils import canonical_root
import sqlite3


def _indexed_repo(tmp_path, files):
    root = tmp_path / "repository"
    root.mkdir()
    for relative, source in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}, "rag": {"extensions": [".py"]}}
    repo_tools = RepositoryTools(config)
    index = CodeIndex(config, repo_tools)
    result = index.update_files_batch(str(root), list(files))
    assert result["success"] is True, result
    return root, index


def _query(root, index, query):
    result = index.query(str(root), query, limit=30, verify_freshness=True)
    assert result["success"] is True, result
    return result["symbols"]


def test_old_parser_metadata_is_stale_until_normal_reindex(tmp_path):
    root, index = _indexed_repo(tmp_path, {"src/worker.py": "def execute_worker():\n    return True\n"})
    try:
        with closing(sqlite3.connect(index.db_path)) as connection:
            connection.execute("UPDATE files SET analyzer_version=? WHERE root=?", ("old-parser-contract", canonical_root(str(root))))
            connection.commit()
        stale = index.query(str(root), "execute_worker", verify_freshness=True)
        assert stale["stale"] is True
        assert stale["freshness"]["status"] == "stale_candidates"
        assert stale["freshness"]["stale_paths"] == ["src/worker.py"]
        refreshed = index.update_files_batch(str(root), ["src/worker.py"])
        assert refreshed["success"] is True
        assert index.query(str(root), "execute_worker", verify_freshness=True)["stale"] is False
    finally:
        index.close()


def test_tool_registration_evidence_beats_identical_helper_documentation(tmp_path):
    source = 'def execute_request():\n    """Public tool entrypoint for request execution."""\n    return True\n'
    root, index = _indexed_repo(tmp_path, {
        "a_plain.py": source,
        "z_registered.py": "@registry.tool()\n" + source,
    })
    try:
        result = _query(root, index, "public tool entrypoints request execution")
        assert result[0]["path"] == "z_registered.py"
        assert result[0]["line"] == 2
        assert {item["path"] for item in result} == {"a_plain.py", "z_registered.py"}
        (root / "z_registered.py").write_text(source, encoding="utf-8")
        assert index.update_files_batch(str(root), ["z_registered.py"])["success"] is True
        updated = _query(root, index, "public tool entrypoints request execution")
        assert updated[0]["path"] == "a_plain.py"
        assert updated[0]["score"] == updated[1]["score"]
    finally:
        index.close()


def test_nested_function_method_and_class_kinds_keep_lexical_scope(tmp_path):
    root, index = _indexed_repo(tmp_path, {
        "src/nesting.py": '''class Container:
    def operate(self):
        def nested_worker():
            return True
        return nested_worker()

    class NestedComponent:
        def execute(self):
            return False
''',
    })
    try:
        nested = _query(root, index, "nested_worker")
        method = _query(root, index, "operate")
        outer_class = _query(root, index, "Container")
        nested_class = _query(root, index, "NestedComponent")

        assert nested[0]["kind"] == "function"
        assert nested[0]["line"] == 3
        assert method[0]["kind"] == "method"
        assert method[0]["line"] == 2
        assert outer_class[0]["kind"] == "class"
        assert outer_class[0]["line"] == 1
        assert nested_class[0]["kind"] == "class"
        assert nested_class[0]["line"] == 7
    finally:
        index.close()


def test_default_architecture_search_prefers_production_but_explicit_tests_remain(tmp_path):
    root, index = _indexed_repo(tmp_path, {
        "zsrc/pipeline.py": '''class EventPipeline:
    """Coordinates the event stream architecture and pipeline ownership."""
    def dispatch(self):
        return None
''',
        "tests/test_pipeline.py": '''class EventPipeline:
    """Tests the event stream architecture and pipeline behavior."""
    def test_identifier(self):
        return True

    def pytest_fixture(self):
        return True
''',
    })
    try:
        default = _query(root, index, "event stream architecture pipeline")
        assert default
        assert default[0]["path"] == "zsrc/pipeline.py"

        for query, expected_name in (
            ("test", "test_identifier"),
            ("pytest", "pytest_fixture"),
            ("test_identifier", "test_identifier"),
        ):
            symbols = _query(root, index, query)
            assert any(item["path"].startswith("tests/") for item in symbols), query
            assert any(item["name"] == expected_name and item["path"].startswith("tests/") for item in symbols), query
    finally:
        index.close()


def test_architecture_words_retrieve_class_from_documentation_not_camel_case(tmp_path):
    root, index = _indexed_repo(tmp_path, {
        "src/control.py": '''class ControlPlane:
    """Owns the dependency graph for delayed message fanout and bounded retry decisions."""
    def reconcile(self):
        """Applies graph updates after delivery."""
        return None
''',
    })
    try:
        symbols = _query(root, index, "dependency graph delayed message fanout bounded retry")
        assert symbols
        assert any(item["name"] == "ControlPlane" and item["kind"] == "class" for item in symbols)
    finally:
        index.close()


def test_public_mcp_tool_entrypoint_ranks_above_same_name_fallback_and_helper(tmp_path):
    root, index = _indexed_repo(tmp_path, {
        "a_fallback.py": '''@fallback.tool
def lookup_asset():
    """Fallback route for looking up an asset."""
    return None
''',
        "b_internal.py": '''def lookup_asset():
    """Internal helper for looking up an asset."""
    return None
''',
        "z_public.py": '''@mcp.tool
def lookup_asset():
    """Public tool entrypoint for looking up an asset."""
    return None
''',
    })
    try:
        symbols = _query(root, index, "public mcp tool lookup asset entrypoint")
        assert symbols
        assert symbols[0]["name"] == "lookup_asset"
        assert symbols[0]["path"] == "z_public.py"
        assert symbols[0]["kind"] == "function"
        assert symbols[0]["line"] == 2
        same_named = [item for item in symbols if item["name"] == "lookup_asset"]
        assert {item["path"] for item in same_named} == {"a_fallback.py", "b_internal.py", "z_public.py"}
    finally:
        index.close()
