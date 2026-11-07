from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
import sqlite3
import pytest

from local_ai_hub.deterministic import DeterministicEngine


def test_deterministic_precompute_dead_code(tmp_path: Path) -> None:
    config = {"server": {"state_dir": str(tmp_path)}}
    engine = DeterministicEngine(config=config)

    root = str(tmp_path.resolve())
    (tmp_path / "src").mkdir()
    changed_source = tmp_path / "src" / "dead.py"
    changed_source.write_text("def dead_func(): return 2\n", encoding="utf-8")
    # Mock code_index attached to engine
    mock_code_index = MagicMock()
    code_index_db = tmp_path / "test_ci.sqlite3"
    ci_con = sqlite3.connect(code_index_db)
    ci_con.execute("""
        CREATE TABLE symbols (
            root TEXT, path TEXT, name TEXT, kind TEXT, line INTEGER, container TEXT
        )
    """)
    ci_con.execute("""
        CREATE TABLE refs (
            root TEXT, path TEXT, name TEXT, line INTEGER
        )
    """)
    # Insert symbols:
    # 1. used_func (has reference)
    # 2. dead_func (0 references)
    ci_con.execute("INSERT INTO symbols VALUES (?, 'src/app.py', 'used_func', 'function', 10, '')", (root,))
    ci_con.execute("INSERT INTO symbols VALUES (?, 'src/dead.py', 'dead_func', 'function', 20, '')", (root,))
    ci_con.execute("INSERT INTO refs VALUES (?, 'src/other.py', 'used_func', 5)", (root,))
    ci_con.commit()

    mock_code_index._connect.return_value = ci_con
    mock_code_index._lock = MagicMock()
    mock_code_index._lock.__enter__ = MagicMock()
    mock_code_index._lock.__exit__ = MagicMock()
    engine.code_index = mock_code_index

    # Precompute dead code
    result = engine.precompute_dead_code(root)
    assert result["count"] == 1
    assert result["symbols"][0]["name"] == "dead_func"

    # Fast retrieval from cache
    cached = engine.get_unreferenced_symbols(root)
    assert len(cached) == 1
    assert cached[0]["name"] == "dead_func"
    assert cached[0]["path"] == "src/dead.py"

    # A deterministic source generation change invalidates the cached scan.
    update = engine.update_file(root, "src/dead.py", content_hash="changed-content-hash")
    assert update["success"] is True
    assert engine.get_unreferenced_symbols(root) == []
    ci_con.close()
