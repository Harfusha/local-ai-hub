from local_ai_hub.cache import MemoryLRUCache, SingleFlightCache
from local_ai_hub.repo_state import RepoStateTracker
from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.services import LocalAIServices
from types import SimpleNamespace

import pytest


def test_cached_search_observes_file_change_before_fingerprint_ttl(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    path = root / "source.py"
    path.write_text("needle = 1\n", encoding="utf-8")
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path / "state")},
                      "workspace_cache": {"fingerprint_ttl_seconds": 60}}
    service.repo_state = RepoStateTracker(service.config)
    service.repo_tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    service.repo_flight = SingleFlightCache(MemoryLRUCache())
    service.learner = service.deterministic = service.code_index = service.preprocessor = service.evidence_store = None

    first = service.repo_search(str(root), "needle", limit=10)
    assert first["total_matches"] == 1
    unchanged = service.repo_search(str(root), "needle", limit=10)
    assert unchanged["cache_hit"] is True
    path.write_text("unrelated = 42\n", encoding="utf-8")
    second = service.repo_search(str(root), "needle", limit=10)

    assert second["success"] is True
    assert second["total_matches"] == 0
    assert second["results"] == []
    (root / "new.py").write_text("needle = 3\n", encoding="utf-8")
    third = service.repo_search(str(root), "needle", limit=10)
    assert third["total_matches"] == 1
    assert [hit["path"] for hit in third["results"]] == ["new.py"]


@pytest.mark.parametrize("state", [
    {"degraded": True, "stale": True},
    {"truncated": True},
    {"changed_files": 4},
])
def test_incomplete_search_fingerprint_does_not_reuse_cached_results(tmp_path, state):
    class Tracker:
        max_changed_paths = 3
        def fingerprint(self, root, force=False):
            assert force is True
            return {"fingerprint": "same", **state}

    service = LocalAIServices.__new__(LocalAIServices)
    service.repo_state = Tracker()
    service.repo_flight = SingleFlightCache(MemoryLRUCache())
    service.preprocessor = None
    calls = []

    def compute():
        calls.append(1)
        return {"success": True, "total_matches": len(calls)}

    first = service._repo_cached("search", str(tmp_path), {}, compute)
    second = service._repo_cached("search", str(tmp_path), {}, compute)

    assert [first["total_matches"], second["total_matches"]] == [1, 2]
    assert second["cache_hit"] is False
    assert second["workspace_cache"]["reason"] == "incomplete_search_fingerprint"


def test_search_with_forced_paths_bypasses_incomplete_git_inventory_cache(tmp_path):
    class Tracker:
        max_changed_paths = 100
        def fingerprint(self, root, force=False):
            return {"fingerprint": "same", "degraded": False, "stale": False}

    service = LocalAIServices.__new__(LocalAIServices)
    service.repo_state, service.preprocessor = Tracker(), None
    service.repo_flight = SingleFlightCache(MemoryLRUCache())
    calls = []

    def compute():
        calls.append(1)
        return {"success": True, "total_matches": len(calls)}

    params = {"force_include_patterns": [".ignored/forced.py"]}
    first = service._repo_cached("search", str(tmp_path), params, compute)
    second = service._repo_cached("search", str(tmp_path), params, compute)

    assert [first["total_matches"], second["total_matches"]] == [1, 2]
    assert second["workspace_cache"]["reason"] == "incomplete_search_fingerprint"


def test_enriched_search_has_distinct_cache_key_for_same_context_size(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "source.py").write_text("def needle():\n    return 42\n", encoding="utf-8")
    service = LocalAIServices.__new__(LocalAIServices)
    service.config = {"server": {"state_dir": str(tmp_path / "state")},
                      "features": {"enriched_search": True}}
    service.repo_state = RepoStateTracker(service.config)
    service.repo_tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    service.repo_flight = SingleFlightCache(MemoryLRUCache())
    service.learner = service.deterministic = service.code_index = service.preprocessor = service.evidence_store = None

    plain = service.repo_search(str(root), "needle", context_lines=8, enrich=False)
    enriched = service.repo_search(str(root), "needle", context_lines=8, enrich=True)

    assert plain["success"] is enriched["success"] is True
    assert "enriched" not in plain
    assert enriched["enriched"] is True
    assert enriched["cache_hit"] is False


def test_git_fingerprint_exposes_truncated_untracked_directory(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    untracked = root / "new"
    untracked.mkdir()
    for index in range(40):
        (untracked / f"{index:03}.py").write_text("needle\n", encoding="utf-8")
    tracker = RepoStateTracker({"workspace_cache": {"max_untracked_walk_files": 32}})
    tracker._run_git = lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stdout=b"# branch.oid abc123\0? new/\0")

    state = tracker.fingerprint(str(root), force=True)

    assert state["truncated"] is True


def test_unreadable_untracked_directory_is_incomplete(tmp_path):
    tracker = RepoStateTracker({})
    signature = tracker._directory_signature(tmp_path / "missing", tmp_path)
    assert signature["truncated"] is True
    result = tracker._filesystem_result(tmp_path / "missing", limit=50)
    assert result["truncated"] is True
