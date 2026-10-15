"""Deferred validation of index-only skeleton retrieval; no source-body reads."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from pathlib import Path

from local_ai_hub.code_index import CodeIndex, canonical_root
from local_ai_hub.deterministic import DeterministicEngine


def _index(tmp_path):
    file = tmp_path / 'source.py'
    file.write_text('def calculate():\n    return "body must not be loaded"\n', encoding='utf-8')
    metadata = file.stat()
    database = tmp_path / 'index.sqlite3'
    def connect():
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        return connection
    root = canonical_root(str(tmp_path))
    with closing(connect()) as connection:
        connection.execute('CREATE TABLE files(root TEXT,path TEXT,mtime_ns INTEGER,size_bytes INTEGER,language TEXT)')
        connection.execute('CREATE TABLE symbols(root TEXT,path TEXT,name TEXT,kind TEXT,name_path TEXT,signature TEXT,line INTEGER,end_line INTEGER)')
        connection.execute('INSERT INTO files VALUES(?,?,?,?,?)', (root, 'source.py', metadata.st_mtime_ns, metadata.st_size, 'python'))
        connection.execute('INSERT INTO symbols VALUES(?,?,?,?,?,?,?,?)', (root, 'source.py', 'calculate', 'function', 'calculate', 'def calculate():', 1, 2))
        connection.commit()
    index = CodeIndex.__new__(CodeIndex)
    index._lock = threading.RLock()
    index._connect = connect
    index._project_config_context = lambda root: (None, None)
    return index, file


def test_registered_file_skeleton_does_not_read_or_parse_source(tmp_path, monkeypatch):
    index, _ = _index(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('source content was read')
    monkeypatch.setattr(Path, 'read_text', forbidden)
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    engine = DeterministicEngine.__new__(DeterministicEngine)
    engine.code_index = index
    result = engine.skeletonize_code(root=str(tmp_path), path='source.py')
    assert result['success'] is True
    assert result['source'] == 'code_index'
    assert 'def calculate():' in result['skeleton_code']
    assert 'body must not be loaded' not in result['skeleton_code']
    assert result['imports_included'] is False


def test_stale_index_is_reported_without_hidden_source_fallback(tmp_path):
    index, file = _index(tmp_path)
    file.write_text('changed source with a different size\n', encoding='utf-8')
    result = index.indexed_skeleton(str(tmp_path), 'source.py')
    assert result['success'] is False
    assert result['stale'] is True


def test_indexed_skeleton_rejects_path_outside_root(tmp_path):
    index, _ = _index(tmp_path)
    root = tmp_path / 'nested'
    root.mkdir()
    result = index.indexed_skeleton(str(root), '../source.py')
    assert result['success'] is False
    assert result['terminal'] is True
