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


def test_reachability_dead_code_scans_fixture_root(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixtures" / "alpha"
    source_dir = fixture_root / "src"
    test_dir = fixture_root / "tests"
    source_dir.mkdir(parents=True)
    test_dir.mkdir()
    (source_dir / "app.py").write_text(
        "def main():\n    return helper()\n\n"
        "def helper():\n    return 1\n\n"
        "def unused():\n    return 2\n",
        encoding="utf-8",
    )
    (test_dir / "test_noise.py").write_text(
        "def should_be_ignored():\n    return 3\n",
        encoding="utf-8",
    )
    engine = DeterministicEngine(config={"server": {"state_dir": str(tmp_path / "state")}})

    result = engine.reachability_dead_code(str(fixture_root))

    assert result["success"] is True
    assert result["total_symbols"] == 3
    assert result["entrypoints"] == ["src/app.py"]


def test_reachability_dead_code_preserves_duplicate_names(tmp_path: Path) -> None:
    fixture_root = tmp_path / "fixtures" / "alpha"
    core = fixture_root / "src" / "demo_core"
    ui = fixture_root / "src" / "demo_ui"
    core.mkdir(parents=True)
    ui.mkdir(parents=True)
    (core / "paths.py").write_text(
        "def normalize_path(path):\n    return path.strip()\n",
        encoding="utf-8",
    )
    (ui / "paths.py").write_text(
        "def normalize_path(path):\n    return path.replace('\\\\', '/')\n",
        encoding="utf-8",
    )
    (fixture_root / "src" / "app.py").write_text(
        "from demo_core.paths import normalize_path\n\n"
        "def app():\n    return normalize_path('x')\n",
        encoding="utf-8",
    )
    engine = DeterministicEngine(config={"server": {"state_dir": str(tmp_path / "state")}})

    result = engine.reachability_dead_code(str(fixture_root))

    assert result["success"] is True
    assert result["total_symbols"] == 3
    assert result["complete"] is False
    assert {item["name"] for item in result["ambiguous_symbols"]} == {"normalize_path"}
    assert len(result["ambiguous_symbols"]) == 2
    assert result["reachable_symbols_count"] + result["dead_code_count"] + len(result["ambiguous_symbols"]) == result["total_symbols"]
    assert result["warnings"]


def test_reachability_dead_code_reports_limited_candidates(tmp_path: Path) -> None:
    fixture_root = tmp_path / "src"
    fixture_root.mkdir()
    (fixture_root / "app.py").write_text(
        "def first_unused():\n    return 1\n\n"
        "def second_unused():\n    return 2\n\n"
        "def third_unused():\n    return 3\n",
        encoding="utf-8",
    )
    engine = DeterministicEngine(config={"server": {"state_dir": str(tmp_path / "state")}})

    result = engine.reachability_dead_code(str(fixture_root), limit=1)

    assert result["success"] is True
    assert result["dead_code_count"] == 3
    assert result["unreachable_symbols_count"] == 3
    assert len(result["unreachable_symbols"]) == 1
    assert result["truncated"] is True
