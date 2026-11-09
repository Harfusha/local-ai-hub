import pytest

from local_ai_hub.repo_tools import RepositoryTools


@pytest.mark.parametrize("query", ["the", "C++", "x"])
@pytest.mark.parametrize("exact_count", [False, True])
def test_search_finds_literal_query_without_search_terms(tmp_path, query, exact_count):
    (tmp_path / "sample.py").write_text(f"value = {query!r}\n", encoding="utf-8")
    tools = RepositoryTools({"rag": {"extensions": [".py"]}, "search": {"use_ripgrep_if_available": False}})

    result = tools.search(str(tmp_path), query, exact_count=exact_count)

    assert result["success"] is True
    assert [item["path"] for item in result["results"]] == ["sample.py"]


def test_ripgrep_candidates_treat_compound_as_literal(tmp_path):
    tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    if not tools._rg:
        pytest.skip("ripgrep unavailable")
    (tmp_path / "sample.py").write_text("fooXbar\nfoo.bar\n", encoding="utf-8")

    candidates, failed = tools._ripgrep_candidates(tmp_path, ["foo.bar"], 10)

    assert failed is False
    assert candidates == [("sample.py", 2)]


def test_git_grep_uses_literal_patterns(tmp_path):
    tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    assert "-F" in tools._git_grep_command(tmp_path, ["foo.bar"], 10)
