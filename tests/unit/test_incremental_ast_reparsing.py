"""Deferred bundle regressions; all state is temporary or in memory."""
from __future__ import annotations

import sqlite3

import pytest

from local_ai_hub import treesitter_parser as ts
from local_ai_hub.code_index import CodeIndex


@pytest.mark.parametrize("before,after", [
    ("a = 1\n", "a = 2\n"),
    ("čaj = 'ž'\n", "čaj = 'š'\n"),
    ("abc\ndef\n", "abc\nnew\ndef\n"),
    ("", "ž\n"), ("ž\n", ""),
])
def test_edit_reconstructs_utf8_and_uses_byte_points(before, after):
    old, new = before.encode(), after.encode()
    edit = ts._source_edit(old, new)
    start, old_end, new_end = (edit[k] for k in ("start_byte", "old_end_byte", "new_end_byte"))
    assert old[:start] + new[start:new_end] + old[old_end:] == new
    for data, offset, point in ((old, start, edit["start_point"]),
                                (old, old_end, edit["old_end_point"]),
                                (new, new_end, edit["new_end_point"])):
        data[:offset].decode("utf-8")
        assert point == (data[:offset].count(b"\n"), len(data[:offset].split(b"\n")[-1]))


def test_native_tree_reused_only_for_same_source_identity(monkeypatch):
    monkeypatch.setattr(ts, "_TREE_CACHE", ts.OrderedDict())
    monkeypatch.setattr(ts, "_TREE_CACHE_BYTES", 0)

    class Tree:
        def edit(self, **edit):
            self.edit_args = edit

    class Parser:
        def __init__(self):
            self.calls = []

        def parse(self, source, old_tree=None):
            self.calls.append((source, old_tree))
            return Tree()

    parser = Parser()
    first, report = ts._parse_tree(parser, b"x=1", "python", "one")
    assert report["incremental"] is False
    _, report = ts._parse_tree(parser, b"x=2", "python", "one")
    assert report["incremental"] is True
    assert parser.calls[-1][1] is first
    assert first.edit_args["start_byte"] == 2
    _, report = ts._parse_tree(parser, b"x=3", "python", "two")
    assert report["tree_cache_hit"] is False
    assert parser.calls[-1][1] is None


def test_metadata_delta_retains_rowids_and_duplicate_occurrences():
    with sqlite3.connect(":memory:") as con:
        con.execute("CREATE TABLE refs(root,path,name,line,kind)")
        con.executemany("INSERT INTO refs VALUES(?,?,?,?,?)", [
            ("root", "a.py", "keep", 1, "call"),
            ("root", "a.py", "keep", 1, "call"),
            ("root", "a.py", "remove", 2, "call"),
            ("other", "a.py", "untouched", 1, "call"),
        ])
        report = CodeIndex._sync_file_rows(con, "refs", "root", "a.py", [
            ("keep", 1, "call"), ("keep", 1, "call"), ("add", 3, "call"),
        ])
        assert report == {"retained": 2, "deleted": 1, "inserted": 1}
        assert con.execute("SELECT rowid FROM refs WHERE name='keep' ORDER BY rowid").fetchall() == [(1,), (2,)]
        assert con.execute("SELECT name FROM refs WHERE root='other'").fetchall() == [("untouched",)]


def test_timeout_cleanup_terminates_owned_worker(monkeypatch):
    class Worker:
        alive = True
        terminated = False

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.terminated = True
            self.alive = False

        def join(self, timeout):
            assert timeout <= 0.5

    worker = Worker()

    class Pool:
        _processes = {123: worker}

        def shutdown(self, *, wait, cancel_futures):
            assert wait is False and cancel_futures is True

    monkeypatch.setattr(ts, "_WORKER_POOL", Pool())
    assert ts._reset_worker_pool() is True
    assert worker.terminated
    assert ts._WORKER_POOL is None
