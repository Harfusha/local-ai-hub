from __future__ import annotations

from pathlib import Path

import local_ai_hub.services as services_module
from local_ai_hub.services import LocalAIServices


def test_fused_lexical_render_order_matches_provenance_before_rag_append(
    tmp_path: Path, monkeypatch
) -> None:
    high_path = "src/high.py"
    low_path = "src/low.py"

    def fused_paths(groups, *, limit, max_per_path):
        paths = {str(path) for group in groups.values() for path in group}
        priority = {high_path: 0, low_path: 1}
        return [
            (path, float(len(paths) - rank))
            for rank, path in enumerate(sorted(paths, key=lambda item: (priority.get(item, 2), item)))
        ][:limit]

    monkeypatch.setattr(services_module, "fuse_ranked_paths", fused_paths)

    class FakeRepoTools:
        @staticmethod
        def context_pack_paths(root, query, paths, *, max_tokens, top_k):
            low = f"--- {low_path}:3-4 score=0.8 ---\nLOW_RAW\n"
            high = f"--- {high_path}:7-8 score=0.9 ---\nHIGH_RAW\n"
            return {
                "success": True,
                "root": root,
                "query": query,
                "context": "\n".join((low, high)),
                "evidence": [
                    {"path": low_path, "start_line": 3, "end_line": 4, "score": 0.8, "raw": "LOW_RAW"},
                    {"path": high_path, "start_line": 7, "end_line": 8, "score": 0.9, "raw": "HIGH_RAW"},
                ],
                "scanned_files": 2,
            }

        @staticmethod
        def context_pack(*_args, **_kwargs):
            raise AssertionError("targeted evidence should be sufficient")

    class FakeDeterministic:
        @staticmethod
        def related_paths(*_args, **_kwargs):
            return [high_path, low_path]

    class FakeRag:
        @staticmethod
        def workspace_id(_root):
            return "workspace-1"

        @staticmethod
        def list_workspaces():
            return [{"workspace": "workspace-1"}]

        @staticmethod
        def search(*_args, **_kwargs):
            return {
                "success": True,
                "revision": "r1",
                "results": [{"path": "docs/semantic.md", "chunk_no": 1, "text": "RAG_RAW"}],
            }

    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"search": {}, "features": {"rag": True}, "preprocessing": {}}
    services.learner = None
    services.repo_tools = FakeRepoTools()
    services.deterministic = FakeDeterministic()
    services.code_index = None
    services.preprocessor = None
    services.external_tools = None
    services.evidence_store = None
    services.rag = FakeRag()

    result = services._hybrid_context_uncached(str(tmp_path), "route", workspace=None, max_tokens=1000)

    context = result["context"]
    high_text = f"--- {high_path}:7-8 score=0.9 ---\nHIGH_RAW\n"
    low_text = f"--- {low_path}:3-4 score=0.8 ---\nLOW_RAW\n"
    assert context.index(high_text) < context.index(low_text)
    assert result["evidence"][0]["raw"] == "HIGH_RAW"
    assert "RAG_RAW" in context and context.index("RAG_RAW") > context.index(low_text)
    assert result["evidence"][-1]["semantic"] is True
    assert result["estimated_tokens"] <= result["context_budget_tokens"]
