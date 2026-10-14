from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from local_ai_hub.code_index import CodeIndex


def _setup_index(tmp_path: Path) -> tuple[CodeIndex, Path]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    f = repo / "service.py"
    f.write_text("class AwesomeService:\n    def run(self):\n        pass\n", encoding="utf-8")

    def read_snapshot(path: Path, **_kwargs):
        content = path.read_bytes()
        return hashlib.sha256(content).hexdigest(), content.decode("utf-8").splitlines()

    tools = SimpleNamespace(
        max_file_bytes=10_000_000,
        _read_snapshot=read_snapshot,
        ignore_dirs=[],
        iter_files=lambda r: [f],
    )
    idx = CodeIndex({"server": {"state_dir": str(tmp_path / "state")}}, tools)
    idx.update_file(str(repo), "service.py")
    return idx, repo


def test_find_symbol_uses_l1_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    idx, repo = _setup_index(tmp_path)

    # Check that _symbol_l1 cache attribute exists
    assert hasattr(idx, "_symbol_l1"), "CodeIndex must have _symbol_l1 MemoryLRUCache"

    # First call: executes query and populates cache
    res1 = idx.find_symbol(str(repo), "AwesomeService")
    assert res1["success"] is True
    assert len(res1["symbols"]) == 1
    assert res1["symbols"][0]["name"] == "AwesomeService"

    # Intercept queries to assert cache hit on second call
    db_queries = []
    orig_connect = idx._connect

    class InterceptingConn:
        def __init__(self, con):
            self._con = con

        def execute(self, sql, *args):
            db_queries.append(sql)
            return self._con.execute(sql, *args)

        def close(self):
            self._con.close()

        def __getattr__(self, item):
            return getattr(self._con, item)

    monkeypatch.setattr(idx, "_connect", lambda **kw: InterceptingConn(orig_connect(**kw)))

    # Second call for the same FQN symbol pattern
    res2 = idx.find_symbol(str(repo), "AwesomeService")
    assert res2 == res1
    # Must NOT have queried symbols table in SQLite
    symbol_queries = [q for q in db_queries if "symbols" in q.lower()]
    assert len(symbol_queries) == 0, f"Expected 0 SQLite queries for cached symbol, got: {symbol_queries}"


def test_find_symbol_l1_cache_owns_miss_and_hit_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    idx, repo = _setup_index(tmp_path)
    first = idx.find_symbol(str(repo), "AwesomeService")
    assert first["success"] is True

    db_queries = []
    orig_connect = idx._connect

    class InterceptingConn:
        def __init__(self, con):
            self._con = con

        def execute(self, sql, *args):
            db_queries.append(sql)
            return self._con.execute(sql, *args)

        def close(self):
            self._con.close()

        def __getattr__(self, item):
            return getattr(self._con, item)

    monkeypatch.setattr(idx, "_connect", lambda **kw: InterceptingConn(orig_connect(**kw)))

    first["symbols"][0]["name"] = "poisoned"
    first["symbols"].clear()
    first["root"] = "poisoned"
    second = idx.find_symbol(str(repo), "AwesomeService")
    assert db_queries == []
    assert second["root"] == str(repo)
    assert second["matches_count"] == 1
    assert second["symbols"][0]["name"] == "AwesomeService"

    second["symbols"][0]["name"] = "hit-poisoned"
    second["symbols"].clear()
    second["root"] = "hit-poisoned"
    second["pattern"] = "hit-poisoned"
    third = idx.find_symbol(str(repo), "AwesomeService")
    assert db_queries == []
    assert third["root"] == str(repo)
    assert third["matches_count"] == 1
    assert third["pattern"] == "AwesomeService"
    assert third["symbols"][0]["name"] == "AwesomeService"


def test_find_symbol_l1_cache_invalidates_on_update_file(tmp_path: Path) -> None:
    idx, repo = _setup_index(tmp_path)

    # Prime cache
    res1 = idx.find_symbol(str(repo), "AwesomeService")
    assert len(res1["symbols"]) == 1

    # Update the file to remove the symbol
    f = repo / "service.py"
    f.write_text("class ReplacedService:\n    pass\n", encoding="utf-8")
    idx.update_file(str(repo), "service.py")

    # Query should reflect updated index, not stale cache
    res2 = idx.find_symbol(str(repo), "AwesomeService")
    assert len(res2["symbols"]) == 0

    res3 = idx.find_symbol(str(repo), "ReplacedService")
    assert len(res3["symbols"]) == 1
