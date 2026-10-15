from pathlib import Path

import pytest

from local_ai_hub.repo_tools import RepositoryTools


@pytest.mark.parametrize("field,value", [
    ("limit", True), ("limit", "2"), ("limit", None),
    ("limit", 0), ("limit", -1), ("offset", True),
    ("offset", "2"), ("offset", None), ("offset", -1),
])
def test_invalid_bounds_reject_before_query_work(tmp_path: Path, monkeypatch, field, value):
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})

    def unexpected_terms(*args, **kwargs):
        pytest.fail("invalid bounds reached query processing")

    monkeypatch.setattr(tools, "_terms", unexpected_terms)
    result = tools.search(str(tmp_path), "needle", **{field: value})
    assert result["success"] is False
    assert result["status_code"] == 400
    assert result["terminal"] is True
    assert result["retryable"] is False


def test_retired_top_k_keyword_rejected(tmp_path: Path):
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    with pytest.raises(TypeError, match="top_k"):
        tools.search(str(tmp_path), "needle", top_k=2)


def test_empty_query_preserves_canonical_bounds(tmp_path: Path):
    tools = RepositoryTools({"server": {"state_dir": str(tmp_path / "state")}})
    result = tools.search(str(tmp_path), "", limit=3, offset=7)
    assert result["success"] is True
    assert result["limit"] == 3
    assert result["offset"] == 7
    assert result["results"] == []
