from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.cache import MemoryLRUCache, SingleFlightCache, SingleFlightGroup, stable_hash
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.process_utils import canonical_root
from local_ai_hub.repo_tools import RepositoryTools
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
    preprocessor._write_retry = lambda operation, **_kwargs: write_retry(operation)
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


def test_touch_if_registered_degrades_on_writer_timeout():
    def time_out(_operation):
        raise TimeoutError("writer actor wait expired")

    preprocessor = _preprocessor_for_touch(time_out)

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


def test_live_lexical_repo_search_normalizes_equivalent_query_without_stale_cache(tmp_path: Path):
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
        def search(self, _root, query, *args, **_kwargs):
            return {"success": True, "query": query, "results": [{"path": "a.py"}], "count_exact": True, "total_matches": 1}

        def search_paths(self, _root, query, _paths, *args, **_kwargs):
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

    first = services.repo_search(str(tmp_path), "  Cache   Route  ", top_k=12, search_mode="lexical")
    second = services.repo_search(str(tmp_path), "cache route", top_k=12, search_mode="lexical")

    assert first["cache_hit"] is False
    assert second["cache_hit"] is False
    assert first["results"] == second["results"]


def test_enriched_repo_search_returns_symbol_and_evidence_for_hit(tmp_path: Path, monkeypatch):
    class _Tools:
        def search(self, _root, _query, *args, context_lines=None, **_kwargs):
            assert context_lines == 8
            return {"success": True, "results": [{"path": "module.py", "start_line": 2, "text": "def target():"}], "count_exact": True, "total_matches": 1}

        def search_paths(self, *_args, **_kwargs):
            return {"success": True, "results": []}

    class _Evidence:
        def put_many(self, _root, hits, *, source_code):
            assert source_code == "indexed"
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


@pytest.mark.parametrize("failure", ["read", "partial_batch"])
def test_code_query_retries_failed_foreground_refresh_without_caching_old_symbols(tmp_path, monkeypatch, failure):
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "target.py"
    target.write_text("def old_beacon(): return 1\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    repo_tools = RepositoryTools(config)
    index = CodeIndex(config, repo_tools)
    assert index.update_file(str(root), "target.py")["success"] is True
    target.write_text("def new_beacon(): return 22\n", encoding="utf-8")

    services = LocalAIServices.__new__(LocalAIServices)
    services.repo_tools = repo_tools
    services.code_index = index
    services.deterministic = services.learner = None
    services._touch_project = lambda _root: None
    services._index_refresh_lock = threading.Lock()
    services._index_refresh_state = {}
    services.flight_group = SingleFlightGroup()
    cache = MemoryLRUCache()
    previous_key = stable_hash({
        "op": "code-index", "root": canonical_root(str(root)), "state": "edited-revision",
        "params": {"query": "beacon", "terms": ["beacon"], "limit": 24, "offset": 0, "include_code": False},
    })
    cache.set(previous_key, {"success": True, "symbols": [{"name": "old_beacon"}]})
    services.repo_flight = SingleFlightCache(cache)
    services._repo_cache_state = lambda _root: {
        "kind": "git", "fingerprint": "edited-revision", "changed_paths": ["target.py"],
    }
    hash_file = repo_tools._hash_file_only
    attempts = []

    def read_after_one_failure(path):
        attempts.append(path)
        if failure == "read" and len(attempts) == 1:
            raise PermissionError("temporary read failure")
        return hash_file(path)

    monkeypatch.setattr(repo_tools, "_hash_file_only", read_after_one_failure)
    if failure == "partial_batch":
        update_batch = index.update_files_batch

        def update_after_one_failure(root, items):
            if len(attempts) == 1:
                return {"success": True, "coverage_complete": False}
            return update_batch(root, items)

        monkeypatch.setattr(index, "update_files_batch", update_after_one_failure)

    with closing(index):
        first = services.code_query(str(root), "beacon")
        retry = services.code_query(str(root), "beacon")
        cached = services.code_query(str(root), "beacon")

    assert [item["name"] for item in first["symbols"]] == ["old_beacon"]
    assert [item["name"] for item in retry["symbols"]] == ["new_beacon"]
    assert first["stale"] is True and first["degraded"] is True
    assert "_cacheable" not in first
    assert retry["cache_hit"] is False and cached["cache_hit"] is True
    assert len(attempts) == 2


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


def test_code_queries_share_foreground_refresh_for_same_revision(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "target.py"
    target.write_text("def old_beacon(): return 1\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    repo_tools = RepositoryTools(config)
    index = CodeIndex(config, repo_tools)
    assert index.update_file(str(root), "target.py")["success"] is True
    target.write_text("def new_beacon(): return 22\n", encoding="utf-8")

    workers = 6
    arrived = set()
    arrivals_lock = threading.Lock()
    all_arrived = threading.Event()
    update_started = threading.Event()
    release_update = threading.Event()
    reads = []
    updates = []

    def mark_arrival():
        with arrivals_lock:
            arrived.add(threading.get_ident())
            if len(arrived) == workers:
                all_arrived.set()

    class ObservedFlight(SingleFlightGroup):
        def do(self, key, fn, timeout_seconds=None):
            mark_arrival()
            return super().do(key, fn, timeout_seconds=timeout_seconds)

    read = repo_tools._hash_file_only
    update = index.update_files_batch

    def read_file(path):
        reads.append(path)
        mark_arrival()
        return read(path)

    def update_batch(root, items):
        updates.append(items)
        update_started.set()
        assert release_update.wait(10)
        return update(root, items)

    monkeypatch.setattr(repo_tools, "_hash_file_only", read_file)
    monkeypatch.setattr(index, "update_files_batch", update_batch)
    services = LocalAIServices.__new__(LocalAIServices)
    services.repo_tools = repo_tools
    services.code_index = index
    services.deterministic = services.learner = None
    services._touch_project = lambda _root: None
    services._index_refresh_lock = threading.Lock()
    services._index_refresh_state = {}
    services.flight_group = ObservedFlight()
    services.repo_flight = SingleFlightCache(MemoryLRUCache())
    services._repo_cache_state = lambda _root: {
        "kind": "git", "fingerprint": "same-revision", "changed_paths": ["target.py"],
    }

    with closing(index), ThreadPoolExecutor(max_workers=workers) as pool:
        first = pool.submit(services.code_query, str(root), "beacon", 1)
        try:
            assert update_started.wait(10)
            queries = [pool.submit(services.code_query, str(root), "beacon", size) for size in range(2, workers + 1)]
            assert all_arrived.wait(10)
        finally:
            release_update.set()
        results = [future.result(timeout=10) for future in [first, *queries]]

    assert len(reads) == len(updates) == 1
    assert all([row["name"] for row in result["symbols"]] == ["new_beacon"] for result in results)


def test_foreground_refresh_updates_only_previously_indexed_code_paths(tmp_path: Path):
    class _CodeIndex:
        def __init__(self):
            self.updated = []

        def files_needing_reindex(self, _root, items, *, only_existing=False):
            assert only_existing is True
            return [item for item in items if item[0] == "src/used.py"]

        def update_files_batch(self, _root, items):
            self.updated.extend(items)
            return {}

        def update_file(self, *_args):
            return {"success": True}

    services = LocalAIServices.__new__(LocalAIServices)
    services._index_refresh_lock = threading.Lock()
    services._index_refresh_state = {}
    services.flight_group = SingleFlightGroup()
    for relative in ("src/used.py", "src/new.py"):
        target = tmp_path / relative
        target.parent.mkdir(exist_ok=True)
        target.write_text("def changed(): return 1\n", encoding="utf-8")
    services._repo_cache_state = lambda _root: {
        "kind": "filesystem",
        "fingerprint": "rev",
        "changed_paths": ["src/used.py", "src/new.py"],
    }
    services.repo_tools = type("_Tools", (), {"_hash_file_only": lambda *_args: "new-hash"})()
    services.code_index = _CodeIndex()
    services.deterministic = None

    services._refresh_changed_intelligence(str(tmp_path))

    assert services.code_index.updated == [("src/used.py", "new-hash")]
