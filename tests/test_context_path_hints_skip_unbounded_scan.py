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
