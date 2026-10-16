"""Deferred bundle validation: use temporary DBs with a low variable ceiling."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing

from local_ai_hub.code_index import CodeIndex, _PARSER_ANALYZER_VERSION, canonical_root
from local_ai_hub.deterministic import DeterministicEngine


def _connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 512)
    return connection


def test_two_thousand_index_paths_preserve_all_rows_without_variable_overflow(tmp_path):
    database = tmp_path / 'index.sqlite3'
    root = canonical_root(str(tmp_path))
    items = [(f'source_{i}.py', f'hash_{i}') for i in range(2000)]
    with closing(_connect(database)) as connection:
        connection.execute('CREATE TABLE files(root TEXT,path TEXT,content_hash TEXT,analyzer_version TEXT,language TEXT,mtime_ns INTEGER,size_bytes INTEGER)')
        connection.execute('CREATE TABLE parse_blobs(content_hash TEXT,language TEXT,analyzer_version TEXT,payload_json TEXT)')
        connection.executemany('INSERT INTO files VALUES(?,?,?,?,?,?,?)', [
            (root, path, digest, _PARSER_ANALYZER_VERSION, 'python', None, None) for path, digest in items
        ])
        connection.executemany('INSERT INTO parse_blobs VALUES(?,?,?,?)', [
            (digest, 'python', _PARSER_ANALYZER_VERSION, json.dumps({'parse_outcome': {'status': 'ok'}}))
            for _, digest in items
        ])
        connection.commit()
    index = CodeIndex.__new__(CodeIndex)
    index._lock = threading.RLock()
    index._connect = lambda: _connect(database)
    index._project_config_context = lambda root: (None, None)
    index._language_for_path = lambda path, settings: 'python'
    index.repo_tools = None
    assert index.files_needing_reindex(str(tmp_path), items) == []
    paths = [path for path, _ in items]
    outcomes = index._parse_outcomes_for_paths(str(tmp_path), paths)
    assert outcomes['files_examined'] == 2000
    assert outcomes['complete'] is True
    assert index._candidate_freshness(str(tmp_path), paths)['status'] != 'verification_failed'


def test_two_thousand_test_links_are_complete_and_deduplicated(tmp_path):
    database = tmp_path / 'facts.sqlite3'
    root = str(tmp_path.resolve())
    paths = [f'src/source_{i}.py' for i in range(2000)]
    with closing(_connect(database)) as connection:
        connection.execute('CREATE TABLE test_source_links(root TEXT,source_path TEXT,test_path TEXT)')
        connection.executemany('INSERT INTO test_source_links VALUES(?,?,?)', [
            (root, path, f'tests/test_{i}.py') for i, path in enumerate(paths)
        ])
        connection.commit()
    engine = DeterministicEngine.__new__(DeterministicEngine)
    engine._lock = threading.RLock()
    engine._connect = lambda: _connect(database)
    engine._root = lambda value: tmp_path.resolve()
    result = engine.get_test_source_links(root, paths + paths)
    assert result == sorted(f'tests/test_{i}.py' for i in range(2000))
