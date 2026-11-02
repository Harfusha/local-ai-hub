from local_ai_hub.code_index import CodeIndex
from local_ai_hub.mcp_server import _compact
from local_ai_hub.repo_tools import RepositoryTools


def test_no_matches_distinguishes_empty_index_from_indexed_files(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "module.py").write_text("def existing_symbol():\n    return 1\n", encoding="utf-8")
    other = tmp_path / "other"
    other.mkdir()
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    index = CodeIndex(config, RepositoryTools(config))

    empty = index.query(str(root), "quasarunmatchable")
    assert empty["total_matches"] == 0
    assert empty["coverage"]["indexed_files_present"] is False
    assert empty["coverage"]["complete"] is False
    assert _compact(empty, "code_index")["coverage"]["indexed_files_present"] is False

    assert index.update_files_batch(str(root), ["module.py"])["success"] is True
    indexed = index.query(str(root), "quasarunmatchable")
    assert indexed["total_matches"] == 0
    assert indexed["coverage"]["indexed_files_present"] is True
    assert indexed["coverage"]["complete"] is False
    assert _compact(indexed, "code_index")["coverage"]["indexed_files_present"] is True
    assert index.query(str(other), "quasarunmatchable")["coverage"]["indexed_files_present"] is False
