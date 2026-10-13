import sqlite3
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools

def test_find_dead_code_sql_avoids_python_callback(tmp_path):
    cfg = {"server": {"state_dir": str(tmp_path)}}
    tools = RepositoryTools(cfg)
    idx = CodeIndex(cfg, tools)
    root = str(tmp_path)
    
    con = idx._connect()
    with con:
        con.execute(
            "INSERT INTO symbols (root, path, name, kind, line, end_line, container, name_path, signature, access, docstring) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (root, "src/unused.py", "orphan_function", "function", 10, 20, "", "orphan_function", "()", "private", ""),
        )
        con.execute(
            "INSERT INTO symbols (root, path, name, kind, line, end_line, container, name_path, signature, access, docstring) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (root, "src/used.py", "used_function", "function", 1, 5, "", "used_function", "()", "public", ""),
        )
        con.execute(
            "INSERT INTO refs (root, path, name, line, kind) VALUES (?, ?, ?, ?, ?)",
            (root, "src/main.py", "used_function", 15, "call"),
        )
        con.execute(
            "INSERT INTO refs (root, path, name, line, kind) VALUES (?, ?, ?, ?, ?)",
            (root, "handoff/archive.py", "orphan_function", 5, "call"),
        )
    con.close()
    
    calls = []
    con = idx._connect()
    # Track calls to hub_root_archive_path
    from local_ai_hub.repo_tools import is_root_archive_path
    def tracking_fn(val):
        calls.append(val)
        return is_root_archive_path(val)
    con.create_function("hub_root_archive_path", 1, tracking_fn, deterministic=True)
    idx._connect = lambda: con

    res = idx.find_dead_code(root, limit=10)
    con.close()

    assert res.get("success") is True
    dead = res.get("dead_code") or res.get("dead_symbols")
    dead_names = [d["name"] for d in dead]
    assert "orphan_function" in dead_names
    assert "used_function" not in dead_names
    # r.path should not trigger Python callbacks
    assert "handoff/archive.py" not in calls
    assert "src/main.py" not in calls

