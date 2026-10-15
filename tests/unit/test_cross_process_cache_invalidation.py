"""Deferred cross-process derived-cache validation, using only temporary SQLite."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import threading
from contextlib import closing
from types import SimpleNamespace

from local_ai_hub.cache import MemoryLRUCache
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.process_utils import hidden_run_kwargs
from local_ai_hub.sqlite_support import SQLiteChangeObserver


def _database(tmp_path):
    path = tmp_path / 'observer.sqlite3'
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('CREATE TABLE values_table(value INTEGER)')
        connection.execute('INSERT INTO values_table VALUES(1)')
        connection.commit()
    return path


def test_persistent_data_version_observer_detects_another_process(tmp_path):
    database = _database(tmp_path)
    observer = SQLiteChangeObserver(database)
    try:
        initial = observer.version()
        assert initial is not None
        subprocess.run([
            sys.executable, '-c',
            'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute("UPDATE values_table SET value=2"); c.commit(); c.close()',
            str(database),
        ], check=True, timeout=5, capture_output=True, **hidden_run_kwargs())
        assert observer.version() > initial
    finally:
        observer.close()
    assert observer.version() is None


def test_external_commit_clears_code_index_query_and_impact_caches(tmp_path):
    database = _database(tmp_path)
    index = CodeIndex.__new__(CodeIndex)
    index._cache_observer = SQLiteChangeObserver(database)
    index._cache_guard = threading.RLock()
    index._observed_data_version = None
    index._query_cache_generation_key = str(database)
    index._status_cache = {}
    names = ('_query_l1', '_parse_blob_l1', '_impact_result_l1', '_impact_path_format_l1', '_impact_candidate_count_l1')
    for name in names:
        setattr(index, name, MemoryLRUCache(max_entries=16, ttl_seconds=60))
    try:
        initial = index._cache_generation()
        for name in names:
            getattr(index, name).set('sentinel', {'old': True})
        with closing(sqlite3.connect(database)) as connection:
            connection.execute('UPDATE values_table SET value=3')
            connection.commit()
        assert index._cache_generation() > initial
        assert all(getattr(index, name).get('sentinel') is None for name in names)
    finally:
        index.close()


def test_external_fact_write_fences_both_deterministic_cache_tiers(tmp_path):
    engine = DeterministicEngine({'server': {'state_dir': str(tmp_path / 'state')}}, repo_tools=SimpleNamespace())
    root = engine._root(str(tmp_path))
    try:
        with closing(engine._connect()) as connection:
            connection.execute("INSERT INTO facts(root,path,kind,name,value,line,extra_json) VALUES(?,?,?,?,?,?,?)", (root, 'module.py', 'function', 'before', 'before', 1, '{}'))
            connection.commit()
        generation = engine._generation(root)
        engine._query_cache_put(root, generation, 'query', {'success': True, 'value': 'before'})
        assert engine._query_cache_get(root, generation, 'query')['value'] == 'before'
        with closing(engine._connect()) as connection:
            connection.execute("UPDATE facts SET value='after' WHERE root=?", (root,))
            connection.commit()
        current = engine._generation(root)
        assert current > generation
        assert engine._query_cache_get(root, current, 'query') is None
        engine._query_cache_put(root, generation, 'query', {'success': True, 'value': 'stale'})
        with closing(engine._connect()) as connection:
            assert connection.execute('SELECT COUNT(*) FROM query_cache WHERE root=?', (root,)).fetchone()[0] == 0
    finally:
        engine.close()
