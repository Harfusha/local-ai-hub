"""Deferred source/SQLite regression cases; do not run before bundle completion."""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from contextlib import closing
from types import SimpleNamespace

from local_ai_hub.code_index import CodeIndex, canonical_root
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.evidence import EvidenceStore


def _engine(tmp_path):
    source = 'def calculate():\n' + ''.join(f'    value_{i} = {i}\n' for i in range(40)) + '    return value_39\n'
    file = tmp_path / 'module.py'
    file.write_text(source, encoding='utf-8')
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    database = tmp_path / 'symbols.sqlite3'
    def connect():
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        return connection
    with closing(connect()) as connection:
        connection.execute('CREATE TABLE files(root TEXT,path TEXT,content_hash TEXT)')
        connection.execute('CREATE TABLE symbols(root TEXT,path TEXT,line INTEGER,end_line INTEGER,kind TEXT)')
        connection.execute('INSERT INTO files VALUES(?,?,?)', (canonical_root(str(tmp_path)), 'module.py', digest))
        connection.execute('INSERT INTO symbols VALUES(?,?,?,?,?)', (canonical_root(str(tmp_path)), 'module.py', 1, 42, 'function'))
        connection.commit()
    index = CodeIndex.__new__(CodeIndex)
    index._lock = threading.RLock()
    index._connect = connect
    engine = DeterministicEngine.__new__(DeterministicEngine)
    engine.code_index = SimpleNamespace(symbol_bounds_at=index.symbol_bounds_at, find_symbol=lambda *a, **kw: {'symbols': []})
    engine.repo_tools = SimpleNamespace(_read_snapshot=lambda target: (hashlib.sha256(target.read_bytes()).hexdigest(), target.read_text(encoding='utf-8').splitlines()))
    engine.evidence = EvidenceStore(tmp_path / 'state')
    engine.max_evidence = 12
    engine._root = lambda root: str(tmp_path.resolve())
    return engine, connect


def test_exact_evidence_contains_complete_function_and_deduplicates_ranges(tmp_path):
    engine, _ = _engine(tmp_path)
    evidence = engine._exact_evidence(str(tmp_path), [{'path': 'module.py', 'line': 1}, {'path': 'module.py', 'line': 12}])
    assert len(evidence) == 1
    assert evidence[0]['symbol_complete'] is True
    assert evidence[0]['end_line'] == 42
    exact = engine.evidence.get(evidence[0]['evidence_id'], verify=True)
    assert '42:     return value_39' in exact['text']
    engine.query = lambda *a, **kw: {'evidence': evidence}
    full = engine.context_pack(str(tmp_path), 'calculate', max_chars=5000)
    assert '42:     return value_39' in full['context']
    small = engine.context_pack(str(tmp_path), 'calculate', max_chars=128)
    assert len(small['context']) <= 128
    assert 'def calculate' not in small['context']
    assert small['truncated'] is True
    assert small['omitted_evidence'][0]['evidence_id'] == evidence[0]['evidence_id']


def test_stale_index_bounds_are_not_presented_as_complete_symbol(tmp_path):
    engine, connect = _engine(tmp_path)
    with closing(connect()) as connection:
        connection.execute("UPDATE files SET content_hash='stale'")
        connection.commit()
    evidence = engine._exact_evidence(str(tmp_path), [{'path': 'module.py', 'line': 1}])
    assert evidence[0]['symbol_complete'] is False
    assert evidence[0]['end_line'] == 3
