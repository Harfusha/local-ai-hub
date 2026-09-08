from __future__ import annotations

from pathlib import Path

from local_ai_hub.services import LocalAIServices


class _Flight:
    def get_or_compute(self, _key, compute):
        return compute(), True, True


def test_repo_cache_outcome_is_promoted_to_top_level_response():
    services = LocalAIServices.__new__(LocalAIServices)
    services.repo_flight = _Flight()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {"fingerprint": "rev", "kind": "filesystem"}

    result = services._repo_cached("search", "C:/repo", {"query": "x"}, lambda: {"success": True})

    assert result["cache_hit"] is True
    assert result["coalesced"] is True
    assert result["cache_layer"] == "workspace"


def test_foreground_refresh_skips_active_background_preprocessing(tmp_path: Path):
    class _Index:
        def __init__(self):
            self.calls = 0

        def update_files_batch(self, *_args):
            self.calls += 1
            return {}

    services = LocalAIServices.__new__(LocalAIServices)
    services._index_refresh_lock = __import__("threading").Lock()
    services._index_refresh_state = {}
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('x')", encoding="utf-8")
    services._repo_cache_state = lambda _root: {
        "kind": "preprocessed-watcher",
        "status": "running",
        "phase": "lexical",
        "fingerprint": "rev",
        "changed_paths": ["src/main.py"],
    }
    services.repo_tools = type("_Tools", (), {"_hash_file_only": lambda *_args: "hash"})()
    services.code_index = _Index()
    services.deterministic = _Index()

    services._refresh_changed_intelligence(str(tmp_path))

    assert services.code_index.calls == 0
    assert services.deterministic.calls == 0


def test_foreground_refresh_never_syncs_watcher_owned_index(tmp_path: Path):
    class _Index:
        def __init__(self):
            self.calls = 0

        def update_files_batch(self, *_args):
            self.calls += 1
            return {}

    services = LocalAIServices.__new__(LocalAIServices)
    services._index_refresh_lock = __import__("threading").Lock()
    services._index_refresh_state = {}
    (tmp_path / "main.py").write_text("print('x')", encoding="utf-8")
    services._repo_cache_state = lambda _root: {
        "kind": "preprocessed-watcher",
        "status": "complete",
        "phase": "complete",
        "fingerprint": "rev",
        "changed_paths": ["main.py"],
    }
    services.repo_tools = type("_Tools", (), {"_hash_file_only": lambda *_args: "hash"})()
    services.code_index = _Index()
    services.deterministic = _Index()

    services._refresh_changed_intelligence(str(tmp_path))

    assert services.code_index.calls == 0
    assert services.deterministic.calls == 0
