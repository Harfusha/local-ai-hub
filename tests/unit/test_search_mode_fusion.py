from __future__ import annotations

import pytest

from local_ai_hub.search_modes import (
    default_agent_search_mode,
    default_search_mode,
    expand_lexical_fallback_query,
    expand_semantic_query,
    fuse_search_results,
    lexical_precision_query,
    prefers_lexical_precision,
)
from local_ai_hub.services import LocalAIServices
from local_ai_hub.repo_tools import RepositoryTools


def _service(monkeypatch, rag_rows=None, rag_meta=None):
    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True}}
    rows = rag_rows or []
    meta = rag_meta or {"success": True, "index_state": "partial_or_candidate_bounded"}
    monkeypatch.setattr(service, "_repo_rag_search", lambda root, query, top_k: (rows, meta))
    return service


@pytest.mark.parametrize(
    "rag_meta",
    [
        {"success": False, "reason": "embedding_backend", "index_state": "unavailable"},
        {
            "success": True,
            "degraded": True,
            "degradation_reason": "embedding_backend",
            "index_state": "stale",
        },
    ],
)
def test_hybrid_lexical_fallback_does_not_compute_or_claim_exact_counts(monkeypatch, rag_meta):
    service = _service(monkeypatch, rag_meta=rag_meta)
    lexical_calls = []

    def lexical(root, query, *args, **kwargs):
        lexical_calls.append(kwargs)
        return {
            "success": True,
            "root": root,
            "results": [{"path": "docs/INSTALLATION.md", "text": "installation guide"}],
            "total_matches": 1,
            "count_exact": False,
            "has_more": False,
        }

    monkeypatch.setattr(service, "_repo_search_lexical", lexical)

    result = service.repo_search(
        ".", "Local AI Hub installation", search_mode="hybrid", limit=5,
    )

    assert lexical_calls[0]["exact_count"] is False
    assert result["result_source"] == "lexical_fallback"
    assert result["coverage_complete"] is False
    assert result["total_matches"] is None
    assert result["count_exact"] is False
    assert result["lexical_total_matches"] is None
    assert result["lexical_count_exact"] is False
    assert result["has_more"] is None
    assert len(result["results"]) == 1


def test_hybrid_bounded_fallback_finds_matches_after_unrelated_path_prefix(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    noise = root / "aaa_noise"
    target = root / "src" / "access.py"
    noise.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    for index in range(48):
        (noise / f"file_{index:03d}.py").write_text("value = 1\n", encoding="utf-8")
    target.write_text("def renew_access_key():\n    return True\n", encoding="utf-8")

    tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    tools.max_hits = 8
    service = object.__new__(LocalAIServices)
    service.config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "features": {"rag": True},
    }
    service.repo_tools = tools
    service.learner = service.deterministic = service.code_index = None
    service.preprocessor = service.evidence_store = None
    service._repo_cache_state = lambda _root: {}
    monkeypatch.setattr(
        service, "_repo_rag_search",
        lambda _root, _query, _top_k: ([], {"success": False, "reason": "embedding_backend"}),
    )

    result = service.repo_search(
        str(root), "renew access key", search_mode="hybrid", limit=5,
    )

    assert result["success"] is True
    assert result["result_source"] == "lexical_fallback"
    assert result["coverage_complete"] is False
    assert result["count_exact"] is False
    assert [row["path"] for row in result["results"]] == ["src/access.py"]


def test_hybrid_fallback_prioritizes_pinned_context_before_noisy_candidates(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    noise = root / "aaa_noise"
    docs = root / "docs"
    noise.mkdir(parents=True)
    docs.mkdir(parents=True)
    (root / ".local-ai.toml").write_text(
        'project_type = "python"\npinned_context = ["docs/INSTALLATION.md"]\n',
        encoding="utf-8",
    )
    target = docs / "INSTALLATION.md"
    target.write_text("Local AI Hub installation guide\n", encoding="utf-8")
    for index in range(80):
        (noise / f"file_{index:03d}.py").write_text(
            "Local AI Hub agent\n", encoding="utf-8",
        )

    tools = RepositoryTools({})
    tools.max_hits = 8
    inventory_calls = []
    monkeypatch.setattr(
        tools, "_git_files", lambda _root: inventory_calls.append(True) or None,
    )
    service = object.__new__(LocalAIServices)
    service.config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "features": {"rag": True},
    }
    service.repo_tools = tools
    service.learner = service.deterministic = service.code_index = None
    service.preprocessor = service.evidence_store = None
    service._repo_cache_state = lambda _root: {}
    monkeypatch.setattr(
        service, "_repo_rag_search",
        lambda _root, _query, _top_k: ([], {"success": False, "reason": "embedding_backend"}),
    )

    result = service.repo_search(
        str(root), "Local AI Hub installation", search_mode="hybrid", limit=5,
    )

    assert result["success"] is True
    assert result["result_source"] == "lexical_fallback"
    assert "docs/INSTALLATION.md" in {row["path"] for row in result["results"]}
    assert inventory_calls == [True]


def test_hybrid_fallback_uses_expansion_and_entry_points_for_code_index_queries(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    noise = root / "src" / "aaa_noise"
    source = root / "src" / "local_ai_hub"
    noise.mkdir(parents=True)
    source.mkdir(parents=True)
    (root / ".local-ai.toml").write_text(
        'project_type = "python"\nentry_points = ["src"]\n',
        encoding="utf-8",
    )
    target = source / "code_index.py"
    target.write_text(
        "".join("code_index = True\n" for _ in range(20)) + "max_index_bytes = 512\n",
        encoding="utf-8",
    )
    for index in range(300):
        (noise / f"file_{index:03d}.py").write_text(
            "max_index_bytes = 64\n", encoding="utf-8",
        )

    tools = RepositoryTools({})
    tools.max_hits = 1
    service = object.__new__(LocalAIServices)
    service.config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "features": {"rag": True},
    }
    service.repo_tools = tools
    service.learner = service.deterministic = service.code_index = None
    service.preprocessor = service.evidence_store = None
    service._repo_cache_state = lambda _root: {}
    monkeypatch.setattr(
        service, "_repo_rag_search",
        lambda _root, _query, _top_k: ([], {"success": False, "reason": "embedding_backend"}),
    )

    result = service.repo_search(
        str(root), "Jak nastavit limit code indexu?", search_mode="hybrid", limit=5,
    )

    assert result["success"] is True
    assert result["result_source"] == "lexical_fallback"
    target_result = next(
        row for row in result["results"]
        if row["path"] == "src/local_ai_hub/code_index.py"
    )
    assert "max_index_bytes = 512" in target_result["text"]


def test_hybrid_candidate_budget_scales_with_requested_page(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    source = root / "src"
    source.mkdir(parents=True)
    (root / ".local-ai.toml").write_text(
        'project_type = "python"\nentry_points = ["src"]\n',
        encoding="utf-8",
    )
    (source / "setup.py").write_text("installation = True\n", encoding="utf-8")

    tools = RepositoryTools({})
    tools.max_hits = 160
    budgets = []
    monkeypatch.setattr(
        tools, "_ripgrep_candidates",
        lambda _base, _terms, max_matches, *, candidate_paths=None: (
            budgets.append(max_matches) or [], False,
        ),
    )
    service = object.__new__(LocalAIServices)
    service.config = {
        "server": {"state_dir": str(tmp_path / "state")},
        "features": {"rag": True},
    }
    service.repo_tools = tools
    service.learner = service.deterministic = service.code_index = None
    service.preprocessor = service.evidence_store = None
    service._repo_cache_state = lambda _root: {}
    monkeypatch.setattr(
        service, "_repo_rag_search",
        lambda _root, _query, _top_k: ([], {"success": False, "reason": "embedding_backend"}),
    )

    service.repo_search(
        str(root), "Local AI Hub installation", search_mode="hybrid", limit=10,
    )

    assert budgets
    assert max(budgets) <= 81


def test_repository_search_defaults_to_hybrid_for_natural_language(monkeypatch):
    service = _service(monkeypatch, [{"path": "docs/semantic-only.md", "text": "semantic"}])
    rag_calls = []
    lexical_calls = []
    monkeypatch.setattr(
        service,
        "_repo_rag_search",
        lambda root, query, top_k: (rag_calls.append(query) or [], {"success": True}),
    )
    monkeypatch.setattr(
        service,
        "_repo_search_lexical",
        lambda root, query, *args, **kwargs: (
            lexical_calls.append(query)
            or {"success": True, "results": [], "count_exact": True, "total_matches": 0}
        ),
    )

    result = service.repo_search(".", "natural language query")

    assert result["search_mode"] == "hybrid"
    assert lexical_calls == ["natural language query"]
    assert rag_calls == ["natural language query"]


@pytest.mark.parametrize("query", ["repo_search", "C++"])
def test_repository_search_defaults_to_lexical_for_exact_identifiers(monkeypatch, query):
    service = _service(monkeypatch, [{"path": "docs/semantic-only.md", "text": "semantic"}])
    rag_calls = []
    lexical_calls = []
    monkeypatch.setattr(
        service,
        "_repo_rag_search",
        lambda root, query, top_k: (rag_calls.append(query) or [], {"success": True}),
    )
    monkeypatch.setattr(
        service,
        "_repo_search_lexical",
        lambda root, query, *args, **kwargs: (
            lexical_calls.append(query)
            or {"success": True, "results": [], "count_exact": True, "total_matches": 0}
        ),
    )

    result = service.repo_search(".", query)

    assert result["search_mode"] == "lexical"
    assert lexical_calls == [query]
    assert rag_calls == []


@pytest.mark.parametrize(("query", "expected"), [
    ("Local AI Hub installation", "hybrid"),
    ("repo_search", "lexical"),
    ("C++", "lexical"),
    ("How do I find repo_search?", "lexical"),
    ("How do I train a dragon to parse violet_heron_20261106?", "lexical"),
])
def test_default_agent_search_mode_selects_agent_safe_mode(query, expected):
    assert default_agent_search_mode(query) == expected


@pytest.mark.parametrize(("query", "expected"), [
    ("How do I find repo_search?", "repo_search"),
    ("How do I install C++?", "C++"),
    ("Local AI Hub installation", "Local AI Hub installation"),
])
def test_lexical_precision_query_extracts_only_embedded_symbol(query, expected):
    assert lexical_precision_query(query) == expected


def test_hybrid_query_with_embedded_identifier_uses_exact_lexical_path(monkeypatch):
    service = _service(monkeypatch, rag_rows=[{"path": "unrelated.md", "text": "unrelated"}])
    lexical_calls = []
    rag_calls = []

    def lexical(root, query, *args, **kwargs):
        lexical_calls.append(query)
        return {
            "success": True,
            "root": root,
            "results": [],
            "total_matches": 0,
            "count_exact": True,
            "has_more": False,
        }

    def rag(root, query, top_k):
        rag_calls.append(query)
        return [{"path": "unrelated.md", "text": "unrelated"}], {
            "success": True,
            "index_state": "current",
        }

    monkeypatch.setattr(service, "_repo_search_lexical", lexical)
    monkeypatch.setattr(service, "_repo_rag_search", rag)

    result = service.repo_search(
        ".",
        "How do I train a dragon to parse violet_heron_20261106?",
        search_mode="hybrid",
    )

    assert lexical_calls == ["violet_heron_20261106"]
    assert rag_calls == []
    assert result["result_source"] == "lexical"
    assert result["count_exact"] is True
    assert result["total_matches"] == 0


def test_lexical_mode_prioritizes_intent_docs_but_keeps_symbol_queries_exact(monkeypatch):
    service = _service(monkeypatch)
    calls = []

    def lexical(root, query, *args, **kwargs):
        calls.append((query, kwargs))
        return {"success": True, "results": [], "count_exact": True, "total_matches": 0}

    monkeypatch.setattr(service, "_repo_search_lexical", lexical)
    service.repo_search(".", "Local AI Hub installation", search_mode="lexical")
    service.repo_search(".", "repo_search", search_mode="lexical")

    assert calls[0][1]["installation_intent_priority"] is True
    assert calls[1][1]["installation_intent_priority"] is False


def test_hybrid_fusion_deduplicates_files_and_rewards_backend_agreement():
    lexical = [
        {"path": "src/setup.py", "start_line": 10, "score": 9.0, "text": "setup"},
        {"path": "src/setup.py", "start_line": 30, "score": 8.0, "text": "duplicate file"},
        {"path": "docs/install.md", "start_line": 4, "score": 7.0, "text": "install"},
    ]
    rag = [
        {"path": "docs\\install.md", "chunk_no": 2, "embedding_score": 0.91, "text": "install"},
        {"path": "src/other.py", "chunk_no": 0, "embedding_score": 0.82, "text": "other"},
    ]

    fused, metadata = fuse_search_results(lexical, rag, limit=10, offset=0)

    assert [item["path"] for item in fused] == ["docs/install.md", "src/setup.py", "src/other.py"]
    assert fused[0]["sources"] == ["lexical", "rag"]
    assert fused[1]["sources"] == ["lexical"]
    assert fused[2]["sources"] == ["rag"]
    assert metadata["candidate_count"] == 3
    assert metadata["count_exact"] is False


def test_hybrid_fusion_paging_is_stable_and_semantic_counts_are_not_lexical_counts():
    lexical = [{"path": f"src/{name}.py", "start_line": 1} for name in ("a", "b", "c")]
    rag = [{"path": f"docs/{name}.md", "chunk_no": 0} for name in ("d", "e", "f")]

    page_one, first = fuse_search_results(lexical, rag, limit=2, offset=0)
    page_two, second = fuse_search_results(lexical, rag, limit=2, offset=2)
    all_results, _ = fuse_search_results(lexical, rag, limit=20, offset=0)

    assert page_one + page_two == all_results[:4]
    assert first["candidate_count"] == second["candidate_count"] == 6
    assert first["total_matches"] is None
    assert first["count_exact"] is False


def test_hybrid_fusion_uses_stable_tie_breaking():
    lexical = [{"path": "z/file.py"}, {"path": "a/file.py"}]
    rag = [{"path": "a/file.py"}, {"path": "z/file.py"}]
    fused, _metadata = fuse_search_results(lexical, rag, limit=10, offset=0)
    assert [item["path"] for item in fused] == ["a/file.py", "z/file.py"]


def test_symbol_like_hybrid_queries_put_exact_lexical_hits_first():
    assert prefers_lexical_precision("repo_search")
    assert prefers_lexical_precision("C++")
    assert not prefers_lexical_precision("Local AI Hub installation")


def test_hybrid_fusion_retains_distinct_chunk_evidence_and_selects_relevant_match():
    lexical = [{"path": "src/Foo.php", "source_id": "repo", "chunk_id": "method-a", "content_hash": "a",
                "text": "wrong method", "relevance": 0.2, "start_line": 10}]
    rag = [{"path": "src/Foo.php", "source_id": "repo", "chunk_id": "method-b", "content_hash": "b",
            "text": "right method", "relevance": 0.9, "chunk_no": 1}]

    fused, _ = fuse_search_results(lexical, rag, limit=10, offset=0)

    assert fused[0]["primary_match"]["text"] == "right method"
    assert [match["text"] for match in fused[0]["alternative_matches"]] == ["wrong method"]
    assert fused[0]["source_breakdown"].keys() == {"lexical", "rag"}


def test_hybrid_fusion_truncates_matches_after_counting_and_uses_explicit_case_policy():
    rows = [
        {"path": "Src/Foo.php", "chunk_no": index, "content_hash": str(index), "text": str(index)}
        for index in range(3)
    ]
    fused, _ = fuse_search_results(rows, [], limit=10, offset=0, matches_per_file=1)
    assert fused[0]["truncated"] is True
    assert fused[0]["omitted_matches"] == 2

    case_sensitive, _ = fuse_search_results(
        [{"path": "Src/Foo.php"}], [{"path": "src/foo.php"}], limit=10, offset=0,
    )
    case_insensitive, _ = fuse_search_results(
        [{"path": "Src/Foo.php"}], [{"path": "src/foo.php"}], limit=10, offset=0, case_sensitive=False,
    )
    assert len(case_sensitive) == 2
    assert len(case_insensitive) == 1


def test_hybrid_path_identity_does_not_normalize_unicode_or_over_merge_casefold():
    composed = "café/file.py"
    decomposed = "cafe\u0301/file.py"
    fused, _ = fuse_search_results(
        [{"path": composed}], [{"path": decomposed}], limit=10, offset=0, case_sensitive=False,
    )
    assert len(fused) == 2


def test_czech_semantic_query_gets_bounded_english_terms_without_changing_lexical_text():
    original = "Jak nastavit limit code indexu?"
    expanded, applied = expand_semantic_query(original)

    assert applied is True
    assert expanded == (
        original + " code_index max_index_bytes eviction byte budget"
    )
    assert expand_semantic_query("repo_search") == ("repo_search", False)
    english, english_applied = expand_semantic_query("Local AI Hub installation")
    assert english == (
        "Local AI Hub installation install setup getting started bootstrap "
        "instalace nainstalovat"
    )
    assert english_applied is True
    assert expand_semantic_query("Jak instalace Local AI Hub?")[0].endswith(
        "how installation install setup getting started bootstrap"
    )
    assert expand_semantic_query("How to set a size limit?")[1] is False


def test_english_configuration_query_gets_bounded_czech_terms():
    original = "How to configure the software"
    expanded, applied = expand_semantic_query(original)

    assert applied is True
    assert expanded == original + " nastavit nastavení konfigurovat konfigurace"


def test_degraded_lexical_expansion_uses_only_direct_translation_terms():
    assert expand_lexical_fallback_query("Local AI Hub installation") == (
        "Local AI Hub installation instalace",
        True,
    )
    assert expand_lexical_fallback_query("How to configure the software") == (
        "How to configure the software konfigurace nastavení",
        True,
    )
    assert expand_lexical_fallback_query("repo_search") == ("repo_search", False)


def test_czech_pagination_fallback_adds_english_source_terms():
    original = "Kde se ověřuje limit a offset výsledků hledání?"

    assert expand_lexical_fallback_query(original) == (
        original + " valid size pagination results search",
        True,
    )


def test_installation_expansion_targets_semantic_candidates_only(monkeypatch):
    service = _service(monkeypatch, [{"path": "docs/INSTALLATION.md", "text": "install"}])
    rag_calls = []
    lexical_calls = []
    monkeypatch.setattr(
        service, "_repo_rag_search",
        lambda root, query, top_k: (rag_calls.append(query) or
                                   [{"path": "docs/INSTALLATION.md", "text": "install"}],
                                   {"success": True, "index_state": "current"}),
    )
    monkeypatch.setattr(
        service, "_repo_search_lexical",
        lambda root, query, *args, **kwargs: (
            lexical_calls.append(query) or
            {"success": True, "results": [{"path": "docs/INSTALLATION.md", "text": "install"}],
             "count_exact": False, "total_matches": None}
        ),
    )

    result = service.repo_search(".", "Local AI Hub installation", search_mode="hybrid")

    assert rag_calls == [
        "Local AI Hub installation install setup getting started bootstrap "
        "instalace nainstalovat"
    ]
    assert lexical_calls == ["Local AI Hub installation"]
    assert result["query_expansion_applied"] is True

    lexical_calls.clear()
    lexical = service.repo_search(".", "Local AI Hub installation", search_mode="lexical")
    assert lexical_calls == ["Local AI Hub installation"]
    assert lexical["search_mode"] == "lexical"


def test_hybrid_lexical_fallback_matches_original_and_ranks_with_expansion(monkeypatch):
    original = "How to configure the software"
    semantic_expanded = expand_semantic_query(original)[0]
    service = _service(monkeypatch, [])
    service.preprocessor = type(
        "Preprocessor", (), {"candidate_paths": lambda _self, _root, _query, _limit: []},
    )()
    rag_calls = []
    lexical_calls = []
    lexical_options = []
    monkeypatch.setattr(
        service, "_repo_rag_search",
        lambda root, query, top_k: (rag_calls.append(query) or [],
                                   {"success": False, "reason": "embedding_backend"}),
    )
    monkeypatch.setattr(
        service, "_repo_search_lexical",
        lambda root, query, *args, **kwargs: (
            lexical_calls.append(query) or lexical_options.append(kwargs) or
            {"success": True, "results": [], "count_exact": True, "total_matches": 0}
        ),
    )

    result = service.repo_search(".", original, search_mode="hybrid")

    assert rag_calls == [semantic_expanded]
    assert lexical_calls == [original]
    assert lexical_options[0]["candidate_query"] == semantic_expanded
    assert lexical_options[0]["exact_count"] is False
    assert result["query_expansion_applied"] is True
    assert result["result_source"] == "lexical_fallback"
    assert result["coverage_complete"] is False
    assert result["total_matches"] is None


def test_degraded_hybrid_fallback_keeps_original_lexical_query(monkeypatch):
    original = "Kde se ověřuje limit a offset výsledků hledání?"
    service = _service(monkeypatch, [])
    lexical_calls = []
    monkeypatch.setattr(
        service, "_repo_rag_search",
        lambda _root, _query, _top_k: ([], {
            "success": True,
            "degraded": True,
            "reason": "embedding_space_mismatch",
            "degradation_reason": "embedding_space_mismatch",
            "index_state": "stale",
        }),
    )
    monkeypatch.setattr(
        service, "_repo_search_lexical",
        lambda _root, query, *args, **kwargs: (
            lexical_calls.append(query) or
            {"success": True, "results": [], "count_exact": True, "total_matches": 0}
        ),
    )

    result = service.repo_search(".", original, search_mode="hybrid")

    assert lexical_calls == [original]
    assert result["result_source"] == "lexical_fallback"
    assert result["degraded"] is True
    assert result["coverage_complete"] is False
    assert result["count_exact"] is False
    assert result["total_matches"] is None


def test_degraded_hybrid_uses_preprocessed_candidates_when_available(monkeypatch):
    original = "Kde se ověřuje limit a offset výsledků hledání?"
    expanded = expand_semantic_query(original)[0]
    service = _service(monkeypatch, [])
    candidate_calls = []
    lexical_options = []

    class Preprocessor:
        def candidate_paths(self, root, query, limit):
            candidate_calls.append((root, query, limit))
            return ["src/local_ai_hub/search_pagination.py"]

    service.preprocessor = Preprocessor()
    monkeypatch.setattr(
        service, "_repo_rag_search",
        lambda _root, _query, _top_k: ([], {
            "success": True,
            "degraded": True,
            "reason": "embedding_space_mismatch",
            "degradation_reason": "embedding_space_mismatch",
            "index_state": "stale",
        }),
    )
    monkeypatch.setattr(
        service, "_repo_search_lexical",
        lambda _root, _query, *args, **kwargs: (
            lexical_options.append(kwargs) or
            {"success": True, "results": [], "count_exact": False, "total_matches": None}
        ),
    )

    result = service.repo_search("C:/workspace", original, search_mode="hybrid", limit=5)

    assert candidate_calls == [("C:/workspace", expanded, 128)]
    assert lexical_options[0]["candidate_paths"] == ("src/local_ai_hub/search_pagination.py",)
    assert lexical_options[0]["candidate_query"] == expanded
    assert lexical_options[0]["exact_count"] is False
    assert result["result_source"] == "lexical_fallback"
    assert result["coverage_complete"] is False
    assert result["count_exact"] is False
    assert result["total_matches"] is None
    assert result["lexical_candidate_source"] == "preprocess_index"
    assert result["lexical_preprocessed_candidate_count"] == 1


def test_rag_mode_applies_czech_expansion_only_to_semantic_candidates(monkeypatch):
    service = _service(monkeypatch, [{"path": "docs/index.md", "text": "index"}])
    calls = []
    monkeypatch.setattr(
        service, "_repo_rag_search",
        lambda root, query, top_k: (calls.append(query) or [{"path": "docs/index.md", "text": "index"}],
                                   {"success": True, "index_state": "available"}),
    )

    result = service.repo_search(".", "Jak nastavit limit code indexu?", search_mode="rag")

    assert calls == [
        "Jak nastavit limit code indexu? code_index max_index_bytes eviction byte budget"
    ]
    assert result["query_expansion_applied"] is True


def test_hybrid_expands_rag_and_candidate_queries_but_keeps_lexical_source_query(monkeypatch):
    service = _service(monkeypatch, [{"path": "docs/CODE_INDEX.md", "text": "index budget"}])
    rag_calls = []
    lexical_calls = []
    class Preprocessor:
        def candidate_paths(self, root, query, limit):
            assert root == "."
            assert query.endswith("code_index max_index_bytes eviction byte budget")
            assert limit >= 64
            return ["docs/CODE_INDEX.md", "src/local_ai_hub/code_index.py"]

    service.preprocessor = Preprocessor()
    monkeypatch.setattr(
        service, "_repo_rag_search",
        lambda root, query, top_k: (rag_calls.append(query) or
                                   [{"path": "docs/CODE_INDEX.md", "text": "index budget"}],
                                   {"success": True, "index_state": "available"}),
    )
    monkeypatch.setattr(
        service, "_repo_search_lexical",
        lambda root, query, *args, **kwargs: (
            lexical_calls.append((query, kwargs.get("exact_count"), kwargs.get("candidate_paths"))) or
            {"success": True, "results": [{"path": "docs/CODE_INDEX.md", "text": "index budget"}],
             "count_exact": False, "total_matches": None, "truncated": True}
        ),
    )

    result = service.repo_search(".", "Jak nastavit limit code indexu?", search_mode="hybrid")

    expanded = (
        "Jak nastavit limit code indexu? code_index max_index_bytes eviction byte budget"
    )
    assert rag_calls == [expanded]
    assert lexical_calls == [
        ("Jak nastavit limit code indexu?", False, ("docs/CODE_INDEX.md", "src/local_ai_hub/code_index.py"))
    ]
    assert result["query_expansion_applied"] is True
    assert result["lexical_candidate_source"] == "preprocessed_index"
    assert result["lexical_preprocessed_candidate_count"] == 2
    fused, _ = fuse_search_results(
        [{"path": "src/repo_search.py"}],
        [{"path": "docs/unrelated.md"}],
        limit=10,
        offset=0,
        lexical_first=True,
    )
    assert [item["path"] for item in fused] == ["src/repo_search.py", "docs/unrelated.md"]


def test_lexical_search_skips_large_code_index_candidate_scan(tmp_path, monkeypatch):
    calls = []
    source = tmp_path / "src" / "local_ai_hub" / "services.py"
    source.parent.mkdir(parents=True)
    source.write_text("def search_source(): pass\n", encoding="utf-8")

    class RepoTools:
        ignore_dirs = set()

        def search(self, *_args, **kwargs):
            if kwargs.get("exact_count") is False:
                return {"success": True, "results": [{"path": "src/local_ai_hub/services.py"}],
                        "total_matches": None, "count_exact": False, "truncated": True,
                        "has_more": True}
            return {"success": True, "results": [], "total_matches": 0, "count_exact": True}

    class CandidateIndex:
        def __init__(self, source):
            self.source = source

        def related_paths(self, root, query, limit):
            calls.append((self.source, query))
            return []

        def candidate_paths(self, root, query, limit):
            calls.append((self.source, query))
            return []

    service = object.__new__(LocalAIServices)
    service.config = {}
    service.repo_tools = RepoTools()
    service.code_index = CandidateIndex("code")
    service.deterministic = CandidateIndex("deterministic")
    service.preprocessor = CandidateIndex("preprocess")
    service.learner = None
    service.evidence_store = None
    monkeypatch.setattr(service, "_repo_cache_state", lambda _root: {})
    monkeypatch.setattr(service, "_repo_cached", lambda _op, _root, _params, compute, **_kwargs: compute())

    bounded = service._repo_search_lexical(
        str(tmp_path), "Local AI Hub installation", exact_count=False
    )
    assert bounded["success"] is True
    assert bounded["count_exact"] is False
    assert bounded["total_matches"] is None
    assert bounded["candidate_count"] == 1
    assert calls == []

    service._repo_search_lexical(str(tmp_path), "Local AI Hub installation")
    assert calls == []

    service._repo_search_lexical(str(tmp_path), "repo_search")
    assert calls == [("deterministic", "repo_search"), ("preprocess", "repo_search")]

    class OversizedCodeIndex:
        max_index_bytes = 512 * 1024 * 1024

        def measure_storage(self):
            return {"physical_bytes": 34_585_018_368}

    service.code_index = OversizedCodeIndex()
    calls.clear()
    result = service._repo_search_lexical(str(tmp_path), "repo_search")

    assert result["success"] is True
    assert result["count_exact"] is True
    assert result["total_matches"] == 0
    assert calls == [("preprocess", "repo_search")]

    class InBudgetCodeIndex:
        max_index_bytes = 512 * 1024 * 1024

        def measure_storage(self):
            return {"physical_bytes": 1024}

    service.code_index = InBudgetCodeIndex()
    calls.clear()
    result = service._repo_search_lexical(str(tmp_path), "repo_search")

    assert result["count_exact"] is True
    assert calls == [("deterministic", "repo_search"), ("preprocess", "repo_search")]

    class UnavailableCodeIndex:
        max_index_bytes = 512 * 1024 * 1024

        def measure_storage(self):
            raise OSError("index storage unavailable")

    service.code_index = UnavailableCodeIndex()
    calls.clear()
    result = service._repo_search_lexical(str(tmp_path), "repo_search")

    assert result["success"] is True
    assert result["count_exact"] is True
    assert calls == [("preprocess", "repo_search")]

    class NaturalQueryCodeIndex:
        max_index_bytes = 512 * 1024 * 1024

        def measure_storage(self):
            raise AssertionError("natural language search must not inspect code-index size")

    service.code_index = NaturalQueryCodeIndex()
    calls.clear()
    result = service._repo_search_lexical(str(tmp_path), "Local AI Hub installation")

    assert result["success"] is True
    assert calls == []


def test_rag_mode_never_claims_exact_corpus_count(monkeypatch):
    service = _service(monkeypatch, [{"path": "src/a.py", "text": "meaning"}])
    result = service.repo_search(".", "installation", search_mode="rag", limit=5)

    assert result["success"] is True
    assert result["count_exact"] is False
    assert result["total_matches"] is None
    assert result["coverage_complete"] is False
    assert result["result_source"] == "rag"


def test_symbol_like_rag_candidates_must_contain_exact_literal(monkeypatch):
    service = _service(monkeypatch, [
        {"path": "src/nearby.py", "text": "a semantically nearby parser"},
        {"path": "docs/CXX.md", "text": "The C++ parser is supported."},
    ])
    result = service.repo_search(".", "C++", search_mode="rag", limit=10)

    assert [row["path"] for row in result["results"]] == ["docs/CXX.md"]
    assert result["result_source"] == "rag"
    assert result["count_exact"] is False


def test_unknown_symbol_does_not_surface_semantic_noise_in_hybrid(monkeypatch):
    service = _service(monkeypatch, [
        {"path": "src/nearby.py", "text": "a semantically nearby parser"},
    ])
    monkeypatch.setattr(service, "_repo_search_lexical", lambda *args, **kwargs: {
        "success": True, "results": [], "total_matches": None,
        "count_exact": False, "truncated": False,
    })
    monkeypatch.setattr(
        service,
        "_repo_rag_search",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("RAG must be skipped")),
    )

    result = service.repo_search(
        ".", "unknown_agent_symbol_2048", search_mode="hybrid", limit=10,
    )

    assert result["results"] == []
    assert result["rag_candidate_count"] == 0
    assert result["rag_search_skipped"] is True


def test_hybrid_exact_symbol_uses_complete_lexical_path_without_rag(monkeypatch):
    service = _service(monkeypatch)
    lexical = {
        "success": True,
        "results": [{"path": "src/search.cpp", "text": "C++"}],
        "total_matches": 7,
        "count_exact": True,
        "truncated": False,
        "read_errors": 0,
        "has_more": False,
    }
    monkeypatch.setattr(service, "_repo_search_lexical", lambda *args, **kwargs: lexical)
    monkeypatch.setattr(
        service,
        "_repo_rag_search",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("RAG must be skipped")),
    )

    result = service.repo_search(".", "C++", search_mode="hybrid", limit=5)

    assert result["success"] is True
    assert result["search_mode"] == "hybrid"
    assert result["result_source"] == "lexical"
    assert result["total_matches"] == 7
    assert result["count_exact"] is True
    assert result["coverage_complete"] is True
    assert result["rag_search_skipped"] is True
    assert result["rag_skip_reason"] == "exact_lexical_precision"
    assert result["reranker"] == {
        "requested": True,
        "used": False,
        "degraded": False,
        "skipped_reason": "exact_lexical_precision",
    }
    assert result["results"][0]["sources"] == ["lexical"]


def test_hybrid_keeps_lexical_exact_count_separate_and_deduplicates(monkeypatch):
    service = _service(monkeypatch, [
        {"path": "src/a.py", "text": "semantic"},
        {"path": "docs/install.md", "text": "setup"},
    ])
    monkeypatch.setattr(service, "_repo_search_lexical", lambda *args, **kwargs: {
        "success": True, "results": [{"path": "src/a.py", "text": "exact"}],
        "total_matches": 37, "count_exact": True,
    })

    result = service.repo_search(".", "Local AI Hub installation", search_mode="hybrid", limit=10)

    assert result["success"] is True
    assert result["count_exact"] is False
    assert result["total_matches"] is None
    assert result["lexical_total_matches"] == 37
    assert result["lexical_count_exact"] is True
    assert len(result["results"]) == 2
    merged = next(row for row in result["results"] if row["path"] == "src/a.py")
    assert merged["sources"] == ["lexical", "rag"]
    assert merged["text"] == "exact"


def test_rag_and_hybrid_expose_backend_search_cache_state(monkeypatch):
    for mode in ("rag", "hybrid"):
        service = _service(monkeypatch, [
            {"path": "docs/install.md", "text": "installation setup instructions"},
        ], {
            "success": True,
            "index_state": "available",
            "search_cache": {"hit": True, "coalesced": False},
        })
        monkeypatch.setattr(service, "_repo_search_lexical", lambda *args, **kwargs: {
            "success": True,
            "results": [{"path": "src/setup.py", "text": "setup"}],
            "total_matches": 1,
            "count_exact": True,
        })

        result = service.repo_search(
            ".", "installation setup instructions", search_mode=mode, limit=5,
        )

        assert result["cache_hit"] is True
        assert result["coalesced"] is False


def test_hybrid_requests_bounded_lexical_candidates_without_exact_corpus_count(monkeypatch):
    service = _service(monkeypatch, [{"path": "docs/install.md", "text": "install"}])
    calls = []

    def lexical(*_args, **kwargs):
        calls.append(kwargs)
        return {"success": True, "results": [{"path": "src/setup.py"}],
                "total_matches": None, "count_exact": False, "truncated": True}

    monkeypatch.setattr(service, "_repo_search_lexical", lexical)

    result = service.repo_search(".", "Local AI Hub installation", search_mode="hybrid", limit=10)

    assert calls[0]["exact_count"] is False
    assert result["count_exact"] is False
    assert result["total_matches"] is None
    assert result["candidate_count"] == 2


def test_rag_candidate_window_is_stable_across_offsets(monkeypatch):
    service = _service(monkeypatch, [{"path": "docs/install.md", "text": "installation"}])
    calls = []

    def rag(root, query, top_k):
        calls.append(top_k)
        return [{"path": "docs/install.md", "text": "installation"}], {
            "success": True,
            "index_state": "available",
        }

    monkeypatch.setattr(service, "_repo_rag_search", rag)
    monkeypatch.setattr(service, "_repo_search_lexical", lambda *args, **kwargs: {
        "success": True,
        "results": [],
        "total_matches": 0,
        "count_exact": False,
    })

    service.repo_search(".", "installation guide", search_mode="hybrid", limit=10, offset=0)
    service.repo_search(".", "installation guide", search_mode="hybrid", limit=10, offset=20)

    assert calls == [32, 32]


def test_preprocessed_lexical_candidates_bound_source_search(tmp_path):
    selected = tmp_path / "src" / "selected.py"
    unselected = tmp_path / "src" / "unselected.py"
    selected.parent.mkdir()
    selected.write_text("installation setup needle\n", encoding="utf-8")
    unselected.write_text("installation setup needle\n", encoding="utf-8")
    tools = RepositoryTools({})

    result = tools.search(
        str(tmp_path), "installation setup", limit=10, exact_count=False,
        candidate_paths=["src/selected.py"],
    )

    assert result["success"] is True
    assert {row["path"] for row in result["results"]} == {"src/selected.py"}
    assert result.get("count_exact") is not True

    exact = tools.search(
        str(tmp_path), "installation setup", limit=10, exact_count=True,
        candidate_paths=["src/selected.py"],
    )
    empty = tools.search(
        str(tmp_path), "installation setup", limit=10, exact_count=False,
        candidate_paths=[],
    )
    assert exact["success"] is False
    assert "exact-count" in exact["error"]
    assert empty["success"] is False


def test_hybrid_rag_failure_preserves_page_but_marks_count_unknown(monkeypatch):
    service = _service(monkeypatch, rag_meta={"success": False, "reason": "rag_index_missing"})
    calls = []

    def lexical(*args, **kwargs):
        calls.append(kwargs)
        return {"success": True, "results": [{"path": "src/2.py"}],
                "total_matches": 31, "count_exact": True, "offset": kwargs["offset"], "limit": kwargs["limit"]}

    monkeypatch.setattr(service, "_repo_search_lexical", lexical)
    result = service.repo_search(".", "identifier", search_mode="hybrid", limit=1, offset=2)

    assert result["results"] == [{"path": "src/2.py", "sources": ["lexical"], "result_source": "lexical_fallback"}]
    assert result["total_matches"] is None
    assert result["count_exact"] is False
    assert result["lexical_total_matches"] is None
    assert result["lexical_count_exact"] is False
    assert result["has_more"] is None
    assert result["degraded"] is True
    assert calls[0]["exact_count"] is False
    assert calls[0]["offset"] == 2


def test_hybrid_rag_unavailable_keeps_bounded_natural_query_page(monkeypatch):
    service = _service(monkeypatch, rag_meta={
        "success": False, "reason": "rag_disabled", "index_state": "disabled",
    })
    calls = []

    def lexical(*args, **kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "results": [{"path": "docs/INSTALLATION.md"}],
            "total_matches": 23, "count_exact": kwargs["exact_count"],
            "has_more": True, "offset": kwargs["offset"], "limit": kwargs["limit"],
        }

    monkeypatch.setattr(service, "_repo_search_lexical", lexical)
    result = service.repo_search(
        ".", "Local AI Hub installation", search_mode="hybrid", limit=1, offset=2,
    )

    assert result["result_source"] == "lexical_fallback"
    assert result["degraded"] is True
    assert result["degradation_reason"] == "rag_disabled"
    assert result["results"][0]["path"] == "docs/INSTALLATION.md"
    assert result["total_matches"] is result["lexical_total_matches"] is None
    assert result["count_exact"] is result["lexical_count_exact"] is False
    assert result["has_more"] is None
    assert result["coverage_complete"] is False
    assert calls[0]["exact_count"] is False
    assert calls[0]["offset"] == 2
    assert calls[0]["limit"] == 1
    assert calls[0].get("candidate_paths") is None
    candidate_query = calls[0].get("candidate_query")
    assert isinstance(candidate_query, str)
    assert candidate_query.startswith("Local AI Hub installation ")
    assert "setup" in candidate_query


def test_hybrid_degraded_empty_rag_candidates_use_bounded_lexical_page(monkeypatch):
    service = _service(monkeypatch, rag_rows=[], rag_meta={
        "success": True, "degraded": True, "degradation_reason": "embedding_space_mismatch",
        "index_state": "stale", "reranker": {"requested": True, "used": False, "degraded": True},
    })
    calls = []

    def lexical(*args, **kwargs):
        calls.append(kwargs)
        all_results = [
            {"path": "docs/install.md"}, {"path": "docs/other.md"},
            {"path": "src/install.py"}, {"path": "src/setup.py"},
        ]
        return {
            "success": True, "results": all_results[kwargs["offset"]:kwargs["offset"] + kwargs["limit"]],
            "total_matches": 14, "count_exact": kwargs["exact_count"], "has_more": True,
            "offset": kwargs["offset"], "limit": kwargs["limit"],
        }

    monkeypatch.setattr(service, "_repo_search_lexical", lexical)

    result = service.repo_search(".", "Local AI Hub installation", search_mode="hybrid", limit=1, offset=3)

    assert result["result_source"] == "lexical_fallback"
    assert result["degradation_reason"] == "embedding_space_mismatch"
    assert result["total_matches"] is None
    assert result["lexical_total_matches"] is None
    assert result["count_exact"] is False
    assert result["lexical_count_exact"] is False
    assert result["has_more"] is None
    assert result["query_expansion_applied"] is True
    assert result["results"][0]["sources"] == ["lexical"]
    assert calls[0]["offset"] == 3
    assert calls[0]["limit"] == 1
    assert calls[0]["exact_count"] is False
    assert calls[0].get("candidate_paths") is None
    candidate_query = calls[0].get("candidate_query")
    assert isinstance(candidate_query, str)
    assert candidate_query.startswith("Local AI Hub installation ")
    assert "setup" in candidate_query


def test_invalid_search_mode_rejects(monkeypatch):
    service = _service(monkeypatch)
    result = service.repo_search(".", "x", search_mode="semantic")
    assert result["status_code"] == 400
    assert result["terminal"] is True


def test_rag_candidates_are_checked_against_current_source_and_policy(tmp_path):
    source = tmp_path / "current.py"
    source.write_text("def install_hub():\n    return True\n", encoding="utf-8")

    class FakeRag:
        def workspace_id(self, root):
            return "repo:test"

        def require_workspace_root(self, *, workspace, root):
            assert workspace == "repo:test"
            assert root == str(tmp_path)

        def list_workspaces(self):
            return [{"workspace": "repo:test", "files": 1}]

        def revision(self, *, workspace):
            return "rev-1"

        def search(self, query, **kwargs):
            assert kwargs["semantic_only"] is True
            assert kwargs["workspace"] == "repo:test"
            return {"success": True, "index_revision": "rev-1", "reranked": False, "results": [
                {"path": "current.py", "text": "def install_hub():\n    return True\n"},
                {"path": "../outside.py", "text": "outside"},
            ]}

        def project_context(self, root):
            return None

        def _project_path_decision(self, root, path, project_context, *, phase, size_bytes):
            assert phase == "search"
            return True, "text"

    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": False}, "rag": {"max_file_bytes": 1000}}
    service.rag = FakeRag()

    rows, meta = service._repo_rag_search(str(tmp_path), "installation", 8)

    assert [row["path"] for row in rows] == ["current.py"]
    assert meta["index_revision"] == "rev-1"
    assert meta["candidate_freshness"] == "verified_against_current_sources"


def test_stale_rag_candidate_is_dropped_and_reported(tmp_path):
    (tmp_path / "current.py").write_text("new source", encoding="utf-8")
    (tmp_path / "private.py").write_text("private new source", encoding="utf-8")

    class FakeRag:
        def workspace_id(self, root): return "repo:test"
        def require_workspace_root(self, *, workspace, root): pass
        def list_workspaces(self): return [{"workspace": "repo:test", "files": 1}]
        def revision(self, *, workspace): return "rev-1"
        def search(self, query, **kwargs):
            return {"success": True, "index_revision": "rev-1", "results": [
                {"path": "current.py", "chunk_no": 7, "text": "removed source"},
                {"path": "private.py", "chunk_no": 11, "text": "private old source"},
            ]}
        def project_context(self, root): return None
        def _project_path_decision(self, root, path, project_context, *, phase, size_bytes):
            if path.name == "private.py": return False, "denied"
            return True, "text"

    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": False}, "rag": {"max_file_bytes": 1000}}
    service.rag = FakeRag()
    rows, meta = service._repo_rag_search(str(tmp_path), "old source", 8)

    assert rows == []
    assert meta["degraded"] is True
    assert meta["index_state"] == "stale"
    assert meta["stale_candidate_count"] == 1
    assert meta["stale_candidate_reasons"] == {
        "source_changed_during_read": 0,
        "source_read_failed": 0,
        "fragment_mismatch": 1,
    }
    assert meta["stale_candidate_details"] == [
        {"path": "current.py", "reason": "fragment_mismatch", "chunk_no": 7}
    ]


def test_ast_chunk_module_context_is_verified_against_current_source(tmp_path):
    source = (
        "from pathlib import Path\n\n"
        "class IndexBudget:\n"
        "    def enforce(self):\n"
        "        return Path('state.sqlite3')\n"
    )
    (tmp_path / "budget.py").write_text(source, encoding="utf-8")
    ast_chunk = (
        "# [Module context]\nfrom pathlib import Path\n\n"
        "class IndexBudget:\n    # method enforce\n"
        "    def enforce(self):\n        return Path('state.sqlite3')"
    )

    class FakeRag:
        def workspace_id(self, root): return "repo:test"
        def require_workspace_root(self, *, workspace, root): pass
        def list_workspaces(self): return [{"workspace": "repo:test", "files": 1}]
        def revision(self, *, workspace): return "rev-1"
        def search(self, query, **kwargs):
            return {"success": True, "index_revision": "rev-1", "results": [
                {"path": "budget.py", "text": ast_chunk},
            ]}
        def project_context(self, root): return None
        def _project_path_decision(self, root, path, project_context, *, phase, size_bytes):
            return True, "text"

    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": False}, "rag": {"max_file_bytes": 1000}}
    service.rag = FakeRag()

    rows, meta = service._repo_rag_search(str(tmp_path), "index size", 8)

    assert [row["path"] for row in rows] == ["budget.py"]
    assert meta["stale_candidate_count"] == 0
    assert meta["index_state"] == "available"


def test_empty_rag_workspace_skips_embedding_search(tmp_path):
    calls = []

    class EmptyRag:
        def workspace_id(self, root):
            return "repo:empty"

        def require_workspace_root(self, *, workspace, root):
            assert workspace == "repo:empty"
            assert root == str(tmp_path)

        def list_workspaces(self):
            return []

        def has_workspace_chunks(self, *, workspace):
            assert workspace == "repo:empty"
            return False

        def search(self, query, **kwargs):
            calls.append((query, kwargs))
            return {"success": True, "results": []}

    service = object.__new__(LocalAIServices)
    service.config = {"features": {"rag": True, "reranker": True}}
    service.rag = EmptyRag()

    rows, meta = service._repo_rag_search(str(tmp_path), "installation", 8)

    assert rows == []
    assert calls == []
    assert meta["success"] is False
    assert meta["reason"] == "rag_index_missing"
    assert meta["index_state"] == "missing"


@pytest.mark.parametrize(
    ("query", "expected_terms"),
    [
        (
            "Jak preprocessing obnoví RAG po změně souborů?",
            ("preprocess", "refresh", "files"),
        ),
        (
            "Jak hybridní hledání označí nedostupný RAG index?",
            ("hybrid", "search", "indicate", "unavailable"),
        ),
    ],
)
def test_czech_hybrid_expansion_maps_terms_from_live_miss_cases(query, expected_terms):
    expanded, applied = expand_semantic_query(query)

    assert applied is True
    assert all(term in expanded.casefold().split() for term in expected_terms)
