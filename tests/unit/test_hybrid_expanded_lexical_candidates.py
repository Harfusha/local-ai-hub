from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.search_modes import expand_semantic_query
from local_ai_hub.services import LocalAIServices


def test_hybrid_uses_expanded_query_for_bounded_lexical_candidates(monkeypatch):
    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": False}}
    service._repo_rag_search = lambda _root, query, _top_k: (
        [{"path": "docs/agent-evaluation/results.md", "text": "index budget"}],
        {"success": True, "index_state": "current", "degraded": False},
    )
    service.preprocessor = type(
        "Preprocessor",
        (),
        {"candidate_paths": lambda _self, _root, _query, _limit: ["docs/CODE_INDEX.md"]},
    )()
    lexical_calls = []
    service._repo_search_lexical = lambda _root, query, *_args, **kwargs: (
        lexical_calls.append((query, kwargs))
        or {
            "success": True,
            "results": [
                {"path": "docs/CODE_INDEX.md", "text": "code index size limit"},
                {"path": "docs/CODE_INDEX.md", "text": "duplicate matching line"},
                {"path": "src/local_ai_hub/code_index.py", "text": "budget eviction"},
            ],
            "total_matches": None,
            "count_exact": False,
        }
    )

    result = service.repo_search(
        "C:/repo",
        "Jak omezit velikost code indexu?",
        search_mode="hybrid",
        limit=10,
    )

    assert lexical_calls[0][0] == "Jak omezit velikost code indexu?"
    assert lexical_calls[0][1]["exact_count"] is False
    assert lexical_calls[0][1]["candidate_paths"] == ("docs/CODE_INDEX.md",)
    assert lexical_calls[0][1]["candidate_query"].startswith(
        "Jak omezit velikost code indexu? "
    )
    assert lexical_calls[0][1]["candidate_query"] == expand_semantic_query(
        "Jak omezit velikost code indexu?"
    )[0]
    assert lexical_calls[0][1]["installation_intent_priority"] is True
    assert result["query_expansion_applied"] is True
    assert result["lexical_count_exact"] is False
    assert result["results"][0]["path"] == "docs/CODE_INDEX.md"


def test_repository_search_matches_expanded_terms_but_keeps_original_phrase(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "CODE_INDEX.md").write_text(
        "Set max_index_bytes to bound code_index storage and eviction.\n",
        encoding="utf-8",
    )

    result = RepositoryTools({}).search(
        str(tmp_path),
        "Jak omezit velikost code indexu?",
        candidate_paths=["docs/CODE_INDEX.md"],
        candidate_query="code_index max_index_bytes eviction",
        limit=5,
        exact_count=False,
    )

    assert result["success"] is True
    assert result["results"]
    assert result["results"][0]["path"] == "docs/CODE_INDEX.md"
    assert "jak" not in result["terms"]
    assert "omezit" not in result["terms"]
    assert "indexu" not in result["terms"]
    assert "max_index_bytes" in result["terms"]


def test_hybrid_degrades_to_bounded_expanded_candidates_when_rag_is_stale(monkeypatch):
    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": True}}
    service._repo_rag_search = lambda _root, _query, _top_k: (
        [],
        {
            "success": False,
            "reason": "embedding_space_mismatch",
            "index_state": "stale",
        },
    )
    candidate_limits = []

    def candidate_paths(_self, _root, _query, limit):
        candidate_limits.append(limit)
        return ["docs/CODE_INDEX.md"]

    service.preprocessor = type(
        "Preprocessor",
        (),
        {"candidate_paths": candidate_paths},
    )()
    lexical_calls = []
    service._repo_search_lexical = lambda _root, query, *_args, **kwargs: (
        lexical_calls.append((query, kwargs))
        or {
            "success": True,
            "results": [
                {"path": "docs/CODE_INDEX.md", "text": "code index size limit"},
                {"path": "docs/CODE_INDEX.md", "text": "duplicate matching line"},
                {"path": "src/local_ai_hub/code_index.py", "text": "budget eviction"},
            ],
            "candidate_count": 3,
            "total_matches": None,
            "count_exact": False,
        }
    )

    result = service.repo_search(
        "C:/repo",
        "Jak omezit velikost code indexu?",
        search_mode="hybrid",
        limit=10,
    )

    assert lexical_calls[0][0] == "Jak omezit velikost code indexu?"
    assert lexical_calls[0][1]["candidate_query"].startswith(
        "Jak omezit velikost code indexu? "
    )
    assert lexical_calls[0][1]["candidate_query"].endswith(
        "code_index max_index_bytes eviction byte budget"
    )
    assert candidate_limits == [128]
    assert result["success"] is True
    assert result["result_source"] == "lexical_fallback"
    assert result["degraded"] is True
    assert result["degradation_reason"] == "embedding_space_mismatch"
    assert result["coverage_complete"] is False
    assert result["count_exact"] is False
    assert result["total_matches"] is None
    assert result["results"][0]["path"] == "docs/CODE_INDEX.md"
    assert [item["path"] for item in result["results"]] == [
        "docs/CODE_INDEX.md", "src/local_ai_hub/code_index.py",
    ]


def test_hybrid_stale_rag_uses_expanded_current_source_scan_without_index_paths(monkeypatch):
    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": True}}
    service._repo_rag_search = lambda _root, _query, _top_k: (
        [],
        {"success": False, "reason": "embedding_space_mismatch", "index_state": "stale"},
    )
    service.preprocessor = type(
        "Preprocessor", (), {"candidate_paths": lambda _self, _root, _query, _limit: []},
    )()
    lexical_calls = []
    service._repo_search_lexical = lambda _root, query, *_args, **kwargs: (
        lexical_calls.append((query, kwargs))
        or {
            "success": True,
            "results": [{"path": "docs/INSTALLATION.md", "text": "install setup"}],
            "candidate_count": 1,
            "total_matches": None,
            "count_exact": False,
        }
    )

    result = service.repo_search(
        "C:/repo", "Local AI Hub installation", search_mode="hybrid", limit=5,
    )

    assert lexical_calls[0][0] == "Local AI Hub installation"
    assert lexical_calls[0][1]["candidate_query"].startswith("Local AI Hub installation ")
    assert lexical_calls[0][1]["candidate_query"] == expand_semantic_query(
        "Local AI Hub installation"
    )[0]
    assert lexical_calls[0][1]["candidate_paths"] is None
    assert lexical_calls[0][1]["exact_count"] is False
    assert result["lexical_candidate_source"] == "current_source_scan"
    assert result["lexical_preprocessed_candidate_count"] == 0
    assert result["count_exact"] is False


def test_hybrid_empty_degraded_rag_uses_the_same_expanded_fallback(monkeypatch):
    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": True}}
    service._repo_rag_search = lambda _root, _query, _top_k: (
        [],
        {
            "success": True,
            "degraded": True,
            "degradation_reason": "embedding_space_mismatch",
            "index_state": "stale",
        },
    )
    service.preprocessor = type(
        "Preprocessor", (), {"candidate_paths": lambda _self, _root, _query, _limit: []},
    )()
    lexical_calls = []
    service._repo_search_lexical = lambda _root, query, *_args, **kwargs: (
        lexical_calls.append((query, kwargs))
        or {
            "success": True,
            "results": [{"path": "docs/INSTALLATION.md", "text": "install setup"}],
            "candidate_count": 1,
            "total_matches": None,
            "count_exact": False,
        }
    )

    result = service.repo_search(
        "C:/repo", "Local AI Hub installation", search_mode="hybrid", limit=5,
    )

    assert lexical_calls[0][1]["candidate_query"].startswith("Local AI Hub installation ")
    assert lexical_calls[0][1]["candidate_query"] == expand_semantic_query(
        "Local AI Hub installation"
    )[0]
    assert lexical_calls[0][1]["exact_count"] is False
    assert result["result_source"] == "lexical_fallback"
    assert result["query_expansion_applied"] is True
    assert result["degraded"] is True
    assert result["count_exact"] is False
    assert result["total_matches"] is None


def test_expanded_candidate_search_prefers_matching_document_path(tmp_path: Path):
    docs = tmp_path / "docs"
    tests = tmp_path / "tests" / "unit"
    docs.mkdir()
    tests.mkdir(parents=True)
    (docs / "INSTALLATION.md").write_text(
        "Install and set up the Local AI Hub by following this guide.\n",
        encoding="utf-8",
    )
    (tests / "test_rag_semantic_only.py").write_text(
        '"Jak nainstalovat a spustit Local AI Hub? install installation setup '
        'bootstrap getting started"\n',
        encoding="utf-8",
    )

    result = RepositoryTools({}).search(
        str(tmp_path),
        "Jak nainstalovat a spustit Local AI Hub",
        candidate_paths=["tests/unit/test_rag_semantic_only.py", "docs/INSTALLATION.md"],
        candidate_query=(
            "Jak nainstalovat a spustit Local AI Hub install installation "
            "setup bootstrap getting started"
        ),
        limit=5,
        exact_count=False,
    )

    assert result["success"] is True
    assert result["results"][0]["path"] == "docs/INSTALLATION.md"

    lexical = RepositoryTools({}).search(
        str(tmp_path),
        "Jak nainstalovat a spustit Local AI Hub",
        candidate_paths=["tests/unit/test_rag_semantic_only.py", "docs/INSTALLATION.md"],
        limit=5,
        exact_count=False,
        installation_intent_priority=False,
    )

    assert lexical["success"] is True
    assert lexical["results"][0]["path"] == "tests/unit/test_rag_semantic_only.py"

    hybrid_lexical_candidates = RepositoryTools({}).search(
        str(tmp_path),
        "Jak nainstalovat a spustit Local AI Hub",
        candidate_paths=["tests/unit/test_rag_semantic_only.py", "docs/INSTALLATION.md"],
        limit=5,
        exact_count=False,
        installation_intent_priority=True,
    )

    assert hybrid_lexical_candidates["success"] is True
    assert hybrid_lexical_candidates["results"][0]["path"] == "docs/INSTALLATION.md"


def test_bounded_hybrid_candidates_do_not_let_many_early_lines_hide_install_docs(tmp_path: Path, monkeypatch):
    noise = tmp_path / "a_noise"
    docs = tmp_path / "docs"
    noise.mkdir()
    docs.mkdir()
    noise_lines = "Local AI Hub install setup getting started bootstrap\n" * 9
    candidate_rows = []
    for index in range(40):
        relative = f"a_noise/{index:02}.txt"
        (tmp_path / relative).write_text(noise_lines, encoding="utf-8")
        candidate_rows.extend((relative, line_no) for line_no in range(1, 10))
    target = docs / "INSTALLATION.md"
    target.write_text(
        "# Installation\nInstall and set up the Local AI Hub with this guide.\n",
        encoding="utf-8",
    )
    candidate_rows.extend([
        ("docs/INSTALLATION.md", 1),
        ("docs/INSTALLATION.md", 2),
    ])
    tools = RepositoryTools({})

    def bounded_ripgrep(_base, _terms, max_matches, *, candidate_paths=None, **_kwargs):
        rows = candidate_rows
        if candidate_paths is not None:
            allowed = {path.relative_to(tmp_path).as_posix() for path in candidate_paths}
            rows = [row for row in candidate_rows if row[0] in allowed]
        return rows[:max_matches], False

    monkeypatch.setattr(
        tools, "_ripgrep_candidates", bounded_ripgrep,
    )

    result = tools.search(
        str(tmp_path),
        "Local AI Hub installation",
        candidate_query="Local AI Hub installation install setup getting started bootstrap",
        candidate_paths=[*(f"a_noise/{index:02}.txt" for index in range(40)), "docs/INSTALLATION.md"],
        limit=10,
        exact_count=False,
        installation_intent_priority=True,
    )

    assert result["success"] is True
    assert result["results"][0]["path"] == "docs/INSTALLATION.md"
    assert result["scanned_files"] <= 64


def test_project_search_caps_candidate_paths_and_reports_partial_coverage(tmp_path: Path, monkeypatch):
    tools = RepositoryTools({})
    project_paths = [tmp_path / f"module_{index:04}.py" for index in range(700)]
    monkeypatch.setattr(
        tools, "_iter_project_search_files",
        lambda *_args, **_kwargs: iter(project_paths),
    )
    received_paths = []

    def empty_ripgrep(_base, _terms, _max_matches, *, candidate_paths=None, **_kwargs):
        received_paths.append(candidate_paths)
        return [], False

    monkeypatch.setattr(tools, "_ripgrep_candidates", empty_ripgrep)
    settings = SimpleNamespace(exclude_paths=[], pinned_context=[], entry_points=[])

    result = tools.search(
        str(tmp_path), "natural installation setup", limit=10,
        exact_count=False, project_settings=settings,
    )

    assert result["success"] is True
    assert len(received_paths) == 1
    assert len(received_paths[0]) == 320
    assert result["truncated"] is True
    assert "candidate_file_limit" in result["truncation_reasons"]
