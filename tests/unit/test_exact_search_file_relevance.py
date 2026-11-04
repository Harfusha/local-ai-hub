from local_ai_hub.repo_tools import RepositoryTools


def test_search_prioritizes_distinct_terms_across_file_over_repetition(tmp_path):
    (tmp_path / "a_noise.py").write_text("# retry retry retry\n", encoding="utf-8")
    (tmp_path / "z_target.py").write_text("def retry():\n    # transaction\n    pass\n", encoding="utf-8")
    tools = RepositoryTools({"rag": {"extensions": [".py"]}})

    result = tools.search(str(tmp_path), "retry transaction", exact_count=True)

    assert result["success"] is True
    assert result["results"][0]["path"] == "z_target.py"
    assert {item["path"] for item in result["results"]} == {"a_noise.py", "z_target.py"}


def test_identifier_search_prioritizes_definition_over_import(tmp_path):
    (tmp_path / "a_import.py").write_text("from z_definition import pagination_bounds_error\n", encoding="utf-8")
    (tmp_path / "z_definition.py").write_text("def pagination_bounds_error(value):\n    return None\n", encoding="utf-8")
    tools = RepositoryTools({"rag": {"extensions": [".py"]}})

    result = tools.search(str(tmp_path), "pagination_bounds_error", exact_count=True)

    assert result["success"] is True
    assert [item["path"] for item in result["results"]] == ["z_definition.py", "a_import.py"]
