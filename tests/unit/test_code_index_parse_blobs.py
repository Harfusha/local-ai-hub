import json
import sqlite3
import threading

from local_ai_hub.code_index_parse_blobs import load_parse_blobs


class FakeCodeIndex:
    def __init__(self, connection, parse_blob_l1=None):
        self._connection = connection
        self._parse_blob_l1 = parse_blob_l1 or {}
        self._lock = threading.RLock()

    def _connect(self):
        return self._connection


class CountingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.selects = 0

    def execute(self, statement, *args):
        if statement.startswith("SELECT"):
            self.selects += 1
        return self.connection.execute(statement, *args)

    def close(self):
        self.connection.close()


def _single_batch(items):
    if items:
        yield items


def test_load_parse_blobs_reuses_l1_entries_without_sqlite_access():
    cached = ([{"name": "run"}], [{"name": "call"}], [{"src": "a", "dst": "b"}], {"status": "parsed"})
    index = FakeCodeIndex(None, {"hash:v1:python": cached})

    result = load_parse_blobs(index, [("hash", "python")], "v1", _single_batch)

    assert result == {("hash", "python"): cached}


def test_load_parse_blobs_reads_l2_rows_in_bounded_batches():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE parse_blobs (content_hash TEXT, language TEXT, analyzer_version TEXT, payload_json TEXT)")
    payload = json.dumps({"symbols": [{"name": "run"}], "refs": [], "edges": [], "parse_outcome": {"status": "parsed"}})
    connection.execute("INSERT INTO parse_blobs VALUES (?, ?, ?, ?)", ("hash", "python", "v1", payload))
    counted = CountingConnection(connection)
    index = FakeCodeIndex(counted)

    result = load_parse_blobs(index, [("hash", "python"), ("hash", "python")], "v1", _single_batch)

    assert result[("hash", "python")] == ([{"name": "run"}], [], [], {"status": "parsed"})
    assert counted.selects == 1


def test_load_parse_blobs_ignores_corrupt_l2_payloads():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE parse_blobs (content_hash TEXT, language TEXT, analyzer_version TEXT, payload_json TEXT)")
    connection.execute("INSERT INTO parse_blobs VALUES (?, ?, ?, ?)", ("hash", "python", "v1", "{"))
    index = FakeCodeIndex(connection)

    result = load_parse_blobs(index, [("hash", "python")], "v1", _single_batch)

    assert result == {}
