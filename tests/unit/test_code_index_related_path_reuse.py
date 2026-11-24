import sqlite3
import threading
from unittest.mock import Mock

from local_ai_hub.code_index import CodeIndex


def test_related_paths_reuses_precomputed_symbol_result(tmp_path):
    root = str(tmp_path)
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        "CREATE TABLE refs(root TEXT, path TEXT, name TEXT, kind TEXT);"
        "CREATE TABLE edges(root TEXT, src TEXT, dst TEXT, path TEXT);"
        "CREATE TABLE files(root TEXT, path TEXT);"
    )

    index = object.__new__(CodeIndex)
    index._query_terms = lambda _query: ["route"]
    index._norm_rel = lambda path: path
    index._lock = threading.RLock()
    index._connect = lambda: connection
    index.query = Mock(side_effect=AssertionError("query should reuse indexed result"))

    result = index.related_paths(
        root,
        "route",
        limit=5,
        result={"symbols": [{"path": "src/routes.py", "score": 2.0}]},
    )

    assert result == ["src/routes.py"]
    index.query.assert_not_called()
