from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.services import LocalAIServices


class _Flight:
    def get_or_compute(self, _key, compute):
        return compute(), True, True


def _preprocessor_for_touch(write_retry):
    preprocessor = ProjectPreprocessor.__new__(ProjectPreprocessor)
    preprocessor._root = lambda root: root
    preprocessor._touch_lock = threading.Lock()
    preprocessor._last_touch = {}
    preprocessor._touch_debounce_seconds = 0.0
    preprocessor._write_retry = write_retry
    return preprocessor


def test_repo_cache_outcome_is_promoted_to_top_level_response():
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"features": {"enriched_search": True}}
    services.repo_flight = _Flight()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {"fingerprint": "rev", "kind": "filesystem"}

    result = services._repo_cached("search", "C:/repo", {"query": "x"}, lambda: {"success": True})

    assert result["cache_hit"] is True
    assert result["coalesced"] is True
    assert result["cache_layer"] == "workspace"


def test_project_touch_does_not_hide_unexpected_preprocessor_error():
    services = LocalAIServices.__new__(LocalAIServices)

    class BrokenPreprocessor:
        def touch_if_registered(self, _root):
            raise RuntimeError("unexpected touch failure")

    services.preprocessor = BrokenPreprocessor()

    with pytest.raises(RuntimeError, match="unexpected touch failure"):
        services._touch_project("C:/repo")


def test_repo_cache_state_does_not_hide_unexpected_preprocessor_error():
    services = LocalAIServices.__new__(LocalAIServices)

    class BrokenPreprocessor:
        def cache_fingerprint(self, _root):
            raise RuntimeError("unexpected fingerprint failure")

    class RepoState:
        def fingerprint(self, _root):
            return {"fingerprint": "fallback"}

    services.preprocessor = BrokenPreprocessor()
    services.repo_state = RepoState()

    with pytest.raises(RuntimeError, match="unexpected fingerprint failure"):
        services._repo_cache_state("C:/repo")


def test_cache_fingerprint_does_not_hide_unexpected_project_config_error(tmp_path: Path):
    db_path = tmp_path / "cache.sqlite3"
    with closing(sqlite3.connect(db_path)) as connection, connection:
        connection.execute(
            "CREATE TABLE projects (root TEXT, status TEXT, phase TEXT, generation INTEGER, "
            "inventory_hash TEXT, structural_hash TEXT, paused INTEGER)"
        )
        connection.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(tmp_path), "complete", "complete", 1, "inventory", "structure", 0),
        )

    def connect():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def fail_config(_root):
        raise RuntimeError("unexpected project config failure")

    preprocessor = ProjectPreprocessor.__new__(ProjectPreprocessor)
    preprocessor._watcher_active = True
    preprocessor._root = lambda root: root
    preprocessor._db_lock = threading.RLock()
    preprocessor._connect = connect
    preprocessor._dirty_lock = threading.RLock()
    preprocessor._watch_revisions = {}
    preprocessor._dirty_paths = {}
    preprocessor._project_config_context = fail_config

    with pytest.raises(RuntimeError, match="unexpected project config failure"):
        preprocessor.cache_fingerprint(str(tmp_path))


def test_touch_if_registered_degrades_on_sqlite_error():
    def fail_database(_operation):
        raise sqlite3.OperationalError("database unavailable")

    preprocessor = _preprocessor_for_touch(fail_database)

    assert preprocessor.touch_if_registered("C:/repo") is False


def test_touch_if_registered_propagates_unexpected_error():
    def fail_unexpectedly(_operation):
        raise RuntimeError("unexpected touch failure")

    preprocessor = _preprocessor_for_touch(fail_unexpectedly)

    with pytest.raises(RuntimeError, match="unexpected touch failure"):
        preprocessor.touch_if_registered("C:/repo")


def test_cache_fingerprint_degrades_on_sqlite_unavailability():
    preprocessor = ProjectPreprocessor.__new__(ProjectPreprocessor)
    preprocessor._watcher_active = True
    preprocessor._root = lambda root: root
    preprocessor._db_lock = threading.RLock()

    def fail_database():
        raise sqlite3.OperationalError("database unavailable")

    preprocessor._connect = fail_database

    assert preprocessor.cache_fingerprint("C:/repo") is None


def test_repo_search_reuses_cache_for_equivalent_query_whitespace_and_case(tmp_path: Path):
    class _Cache:
        def __init__(self):
            self.values = {}

        def get_or_compute(self, key, compute):
            if key in self.values:
                return self.values[key], True, False
            value = compute()
            self.values[key] = value
            return value, False, False

    class _Tools:
        def search(self, _root, query, top_k, context_lines=None, **_kwargs):
            return {"success": True, "query": query, "results": [{"path": "a.py"}]}

        def search_paths(self, _root, query, _paths, top_k, context_lines=None, **_kwargs):
            return {"success": True, "query": query, "results": []}

    services = LocalAIServices.__new__(LocalAIServices)
    services.repo_flight = _Cache()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {"fingerprint": "rev", "kind": "filesystem"}
    services.repo_tools = _Tools()
    services.learner = None
    services.deterministic = None
    services.code_index = None
    services.preprocessor = None
    services.evidence_store = None

    first = services.repo_search(str(tmp_path), "  Cache   Route  ", top_k=12)
    second = services.repo_search(str(tmp_path), "cache route", top_k=12)

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True


def test_enriched_repo_search_returns_symbol_and_evidence_for_hit(tmp_path: Path, monkeypatch):
    class _Tools:
        def search(self, _root, _query, _top_k, context_lines=None, **_kwargs):
            assert context_lines == 8
            return {"success": True, "results": [{"path": "module.py", "start_line": 2, "text": "def target():"}]}

        def search_paths(self, *_args, **_kwargs):
            return {"success": True, "results": []}

    class _Evidence:
        def put_many(self, _root, hits):
            hits[0]["evidence_id"] = "E-search"
            return hits

    (tmp_path / "module.py").write_text("def target():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "local_ai_hub.services.enclosing_symbol_at_line",
        lambda _source, _path, _line: {"name": "target", "kind": "function", "line": 1, "end_line": 2, "name_path": "target"},
    )
    services = LocalAIServices.__new__(LocalAIServices)
    services.config = {"features": {"enriched_search": True}}
    services.repo_flight = _Flight()
    services._touch_project = lambda _root: None
    services._repo_cache_state = lambda _root: {"fingerprint": "rev", "kind": "filesystem"}
    services.repo_tools = _Tools()
    services.learner = services.deterministic = services.code_index = services.preprocessor = None
    services.evidence_store = _Evidence()

    result = services.repo_search(str(tmp_path), "target", enrich=True)

    assert result["enriched"] is True
    assert result["progressive_disclosure"] is True
    assert result["results"][0]["enclosing_symbol"]["name"] == "target"
    assert result["results"][0]["evidence_id"] == "E-search"


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
