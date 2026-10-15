from __future__ import annotations

from pathlib import Path

from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.retrieval import (
    is_source_context_query,
    prioritize_source_context_paths,
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
