import sqlite3
import threading

from local_ai_hub.deterministic import DeterministicEngine


class EmptyImpactIndex:
    def __init__(self):
        self._lock = threading.RLock()

    def _connect(self):
        con = sqlite3.connect(":memory:")
        con.executescript(
            "CREATE TABLE symbols(root TEXT, path TEXT, name TEXT, kind TEXT);"
            "CREATE TABLE edges(root TEXT, src TEXT, dst TEXT, dst_name TEXT, path TEXT, line INTEGER, kind TEXT);"
            "CREATE TABLE refs(root TEXT, name TEXT, path TEXT, line INTEGER, kind TEXT);"
        )
        con.execute(
            "INSERT INTO symbols VALUES (?, ?, ?, ?)",
            (r"C:\fixture", "src/demo_core/paths.py", "normalize_path", "function"),
        )
        con.commit()
        return con


def test_refactor_impact_does_not_claim_no_dependencies_with_unverified_index(tmp_path):
    engine = object.__new__(DeterministicEngine)
    engine.code_index = EmptyImpactIndex()

    result = engine.refactor_impact(
        str(tmp_path), "src/demo_core/paths.py", "normalize_path"
    )

    assert result["success"] is True
    assert result["coverage"]["complete"] is False
    assert result["freshness"]["status"] == "not_checked"
    assert result["risk_level"] == "UNKNOWN"
    assert result["impacted_files_count"] == 0
    assert not any("no external dependencies affected" in item.lower() for item in result["recommendations"])
    assert any("freshness is unverified" in item.lower() for item in result["recommendations"])
