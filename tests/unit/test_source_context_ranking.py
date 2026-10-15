from __future__ import annotations

from pathlib import Path

from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.retrieval import (
    is_source_context_query,
    prioritize_source_context_paths,
    source_context_path_tier,
)


def _tools() -> RepositoryTools:
    return RepositoryTools({"rag": {"extensions": [".py", ".md"]}, "search": {"max_files": 32}})


def _source_fixture(root: Path) -> list[str]:
    files = {
        "src/service.py": "def stop_runtime():\n    return runtime_service_stop_behavior\n",
        "docs/plans/old-runtime-plan.md": "Historical plan for runtime service stop behavior and implementation.\n",
        "API_COVERAGE.md": "Generated API coverage for runtime service stop behavior and implementation.\n",
        "docs/guide.md": "Documentation guide for runtime service behavior.\n",
        "docs/pinned-notes.md": "Pinned source audit note for runtime service stop behavior.\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return list(files)


def test_source_intent_demotes_historical_docs_but_keeps_pins(tmp_path: Path) -> None:
    paths = _source_fixture(tmp_path)
    query = "audit source runtime implementation service stop behavior"

    assert is_source_context_query(query)
    ranked = prioritize_source_context_paths(
        paths, query, priority_paths=["docs/pinned-notes.md"],
    )
    assert ranked[0] == "docs/pinned-notes.md"
    assert ranked.index("src/service.py") < ranked.index("docs/plans/old-runtime-plan.md")
    assert ranked.index("src/service.py") < ranked.index("API_COVERAGE.md")
    assert set(ranked) == set(paths)


def test_explicit_documentation_query_keeps_original_path_order(tmp_path: Path) -> None:
    paths = _source_fixture(tmp_path)
    query = "find documentation guide for runtime service behavior"

    assert not is_source_context_query(query)
    assert prioritize_source_context_paths(paths, query) == paths


def test_incidental_plan_and_coverage_terms_do_not_veto_source_intent() -> None:
    plan_query = "Fix runtime source that prioritizes historical plans"
    coverage_query = "Debug code_index coverage metadata"
    paths = ["docs/plans/old.md", "API_COVERAGE.md", "src/runtime.py"]

    assert is_source_context_query(plan_query)
    assert is_source_context_query(coverage_query)
    ranked = prioritize_source_context_paths(paths, plan_query)
    assert ranked[0] == "src/runtime.py"
    assert ranked.index("src/runtime.py") < ranked.index("docs/plans/old.md")


def test_explicit_doc_tasks_and_mixed_source_doc_paths_are_preserved() -> None:
    paths = ["src/runtime.py", "docs/INSTALL_PROMPT.md", "README.md"]

    assert not is_source_context_query("update README guide")
    assert not is_source_context_query("explain docs/INSTALL_PROMPT.md")
    assert not is_source_context_query("explain runtime source in docs/INSTALL_PROMPT.md")
    mixed_query = "debug source behavior in docs/INSTALL_PROMPT.md"
    assert is_source_context_query(mixed_query)
    ranked = prioritize_source_context_paths(
        paths, mixed_query, priority_paths=["docs/INSTALL_PROMPT.md"],
    )
    assert ranked[0] == "docs/INSTALL_PROMPT.md"


def test_runtime_config_and_ci_files_rank_as_source_but_docs_schema_does_not() -> None:
    assert source_context_path_tier("config/runtime.toml") == 0
    assert source_context_path_tier(".github/workflows/release.yml") == 0
    assert source_context_path_tier("docs/schema.json") == 1
    assert source_context_path_tier("src/runtime.py") == 0


def test_targeted_pack_ranks_source_before_historical_noise_and_preserves_force_include(
    tmp_path: Path,
) -> None:
    paths = _source_fixture(tmp_path)
    query = "audit source runtime implementation service stop behavior"

    result = _tools().context_pack_paths(
        str(tmp_path), query, paths, top_k=5, max_tokens=1600,
        force_include_paths=["docs/pinned-notes.md"],
    )

    assert result["success"] is True
    evidence_paths = [item["path"] for item in result["evidence"]]
    assert evidence_paths[0] == "docs/pinned-notes.md"
    assert evidence_paths.index("src/service.py") < evidence_paths.index("docs/plans/old-runtime-plan.md")
    assert evidence_paths.index("src/service.py") < evidence_paths.index("API_COVERAGE.md")


def test_full_context_pack_applies_source_ranking_only_for_source_queries(tmp_path: Path) -> None:
    paths = _source_fixture(tmp_path)
    source_result = _tools().context_pack(
        str(tmp_path), "audit source runtime implementation service stop behavior",
        top_k=5, max_tokens=1600,
    )
    docs_result = _tools().context_pack(
        str(tmp_path), "find documentation guide for runtime service behavior",
        top_k=5, max_tokens=1600,
    )

    assert source_result["success"] is True
    assert docs_result["success"] is True
    assert source_result["evidence"][0]["path"] == "src/service.py"
    assert docs_result["evidence"][0]["path"] == "docs/guide.md"


def test_source_context_expansion_never_shrinks_large_requested_top_k(monkeypatch) -> None:
    tools = _tools()
    observed = []

    def targeted_search(_root, _query, _paths, **kwargs):
        observed.append(kwargs["top_k"])
        return {"success": True, "root": ".", "results": [], "scanned_files": 0}

    def broad_search(_root, _query, **kwargs):
        observed.append(kwargs["top_k"])
        return {"success": True, "root": ".", "results": [], "scanned_files": 0}

    monkeypatch.setattr(tools, "search_paths", targeted_search)
    monkeypatch.setattr(tools, "search", broad_search)
    monkeypatch.setattr(tools, "_pack_ranked_context", lambda search, *_args, **_kwargs: search)

    tools.context_pack_paths(".", "audit source runtime", ["src/runtime.py"], top_k=100)
    tools.context_pack(".", "audit source runtime", top_k=100)

    assert observed == [100, 100]
