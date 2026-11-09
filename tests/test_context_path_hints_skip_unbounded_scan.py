from __future__ import annotations

from pathlib import Path

from local_ai_hub.services import LocalAIServices


class _IndexedCandidates:
    def related_paths(self, root: str, query: str, *, limit: int):
        return ["src/button.py"]


class _TargetedRepoTools:
    def __init__(self):
        self.pack_calls = []

    def iter_files(self, root: str):
        raise AssertionError("path-hint retrieval must not walk the whole repository")

    def context_pack_paths(self, root: str, query: str, paths: list[str], **kwargs):
        self.pack_calls.append((paths, kwargs))
        return {
            "success": True,
            "root": root,
            "context": "button source",
            "evidence": [{
                "path": "src/button.py", "start_line": 1, "end_line": 1,
                "score": 1.0, "file_sha256": "a" * 64, "raw": "button source",
            }],
            "scanned_files": 1,
        }


def test_adaptive_path_hints_use_index_without_full_repository_walk(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "button.py").write_text("button source\n", encoding="utf-8")
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"features": {"rag": False}, "search": {"context_top_k": 10}}
    services.learner = None
    services.rag = None
    services.deterministic = _IndexedCandidates()
    services.code_index = None
    services.preprocessor = None
    services.evidence_store = None
    services.repo_tools = _TargetedRepoTools()
    services._external_context_candidates = lambda *_args, **_kwargs: (
        {}, [], {"serena": "skipped", "rag": "skipped"}
    )

    result = services._hybrid_context_uncached(
        str(root), "find button", workspace=None, max_tokens=400,
        quality_first=True,
        path_hints=({"path": "src/button.py", "provenance": "project_config:entry_point"},),
    )

    assert result["success"] is True
    assert result["evidence"][0]["path"] == "src/button.py"
    assert services.repo_tools.pack_calls
    assert services.repo_tools.pack_calls[0][0][0] == "src/button.py"


def test_sparse_unhinted_context_fills_candidates_with_bounded_lexical_search(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "checkout.py").write_text("checkout source\n", encoding="utf-8")
    (root / "src" / "pricing.py").write_text("pricing source\n", encoding="utf-8")

    class SparseRepoTools(_TargetedRepoTools):
        def __init__(self):
            super().__init__()
            self.search_calls = []

        def search(self, root, query, *, limit):
            self.search_calls.append((root, query, limit))
            return {
                "success": True,
                "results": [{"path": "src/checkout.py"}, {"path": "src/pricing.py"}],
            }

        def context_pack_paths(self, root, query, paths, **kwargs):
            self.pack_calls.append((paths, kwargs))
            evidence = [
                {
                    "path": path, "start_line": 1, "end_line": 1,
                    "score": 1.0, "file_sha256": "a" * 64, "raw": f"{path} source",
                }
                for path in paths
            ]
            return {
                "success": True, "root": root,
                "context": "\n".join(item["raw"] for item in evidence),
                "evidence": evidence, "scanned_files": len(evidence),
            }

        def context_pack(self, root, query, **kwargs):
            return self.context_pack_paths(root, query, ["src/checkout.py"], **kwargs)

    repo_tools = SparseRepoTools()

    class SparseIndexedCandidates:
        @staticmethod
        def related_paths(_root, _query, *, limit):
            return ["src/checkout.py"][:limit]

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {
        "features": {"rag": False},
        "search": {"context_top_k": 4},
        "preprocessing": {"lookup_file_cards": 1},
    }
    services.learner = None
    services.rag = None
    services.deterministic = SparseIndexedCandidates()
    services.code_index = None
    services.preprocessor = None
    services.evidence_store = None
    services.repo_tools = repo_tools
    services._external_context_candidates = lambda *_args, **_kwargs: (
        {}, [], {"serena": "skipped", "rag": "skipped"}
    )

    ordinary = services._hybrid_context_uncached(
        str(root), "compare checkout with pricing", workspace=None, max_tokens=400,
        quality_first=False,
    )

    assert ordinary["success"] is True
    assert repo_tools.search_calls == []
    assert {item["path"] for item in ordinary["evidence"]} == {"src/checkout.py"}

    result = services._hybrid_context_uncached(
        str(root), "compare checkout with pricing", workspace=None, max_tokens=400,
        quality_first=True,
    )

    assert result["success"] is True
    assert repo_tools.search_calls == [
        (str(root), "compare checkout with pricing", 4),
    ]
    assert {item["path"] for item in result["evidence"]} == {
        "src/checkout.py", "src/pricing.py",
    }
