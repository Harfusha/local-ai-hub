from contextlib import closing
from pathlib import Path

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


def test_query_excludes_symbols_from_ignored_overlay_paths(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    paths = [
        "handoff/snapshot.py",
        ".handoff/snapshot.py",
        "artifacts/handoff/snapshot.py",
        "artifacts/t05-fts-rollback-overlay-applypatch-20261002-v2/src/stale.py",
        ".merge-checks/snapshot.py",
        ".sync-checks/snapshot.py",
        ".t03-sync-checks/snapshot.py",
        ".t03-main-preflight-overlay/base/src/overlay.py",
        ".t03-root-current-overlay/base/src/overlay.py",
        ".t18-root-overlay-snapshot/src/overlay.py",
        ".t18-store-root-current-check-v2/src/stale.py",
        "T18-review-artifacts-20260928/src/stale.py",
        ".validation/t17-sync-20261006/package-pytest/test_generated_config/generated/schemas/stale.py",
        "artifacts/t08-ast-check-jbdqsv5y/tests/stale.py",
        "artifacts/t08-root-current-agent-tasks-preimage.py",
        "artifacts/t08-root-current-agent-task-replay.py",
        "artifacts/t08-root-current-agent-tasks-memory-transition.py",
        "artifacts/t08-global-tombstone-kaql2q6e/src/local_ai_hub/agent_memory.py",
        "artifacts/t08-refresh-8t1jjznh/src/local_ai_hub/agent_memory.py",
        "artifacts/t08-t05-final-check-vtmyznvd/tests/test_agent_memory.py",
        "src/current.py",
        "src/pkg/handoff/nested.py",
        "artifacts/release/current.py",
        "src/T18-review-artifacts-20260928/current.py",
    ]
    for relative in paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def ActiveHandler(): pass\n", encoding="utf-8")

    tools = RepositoryTools({"rag": {"extensions": [".py"]}, "search": {"prefer_git_files": False}})
    scanned = {path.relative_to(root).as_posix() for path in tools.iter_files(str(root))}
    assert scanned == {
        "src/current.py",
        "src/pkg/handoff/nested.py",
        "artifacts/release/current.py",
        "src/T18-review-artifacts-20260928/current.py",
    }

    index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}},
        repo_tools=tools,
    )
    indexed = index.update_files_batch(str(root), paths)
    assert indexed["success"] is True
    assert indexed["files_processed"] == 4

    # Simulate legacy rows that were indexed before root archive paths were filtered.
    with index._lock, closing(index._connect()) as con:
        archived_paths = [path for path in paths if path not in scanned]
        for archived_path in [*archived_paths, r"handoff\legacy.py"]:
            con.execute(
                "INSERT INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) "
                "SELECT root,?,name,kind,line,end_line,container,name_path,signature,access,docstring "
                "FROM symbols WHERE root=? AND path='src/current.py'",
                (archived_path, str(root.resolve())),
            )
        index._replace_symbol_trigrams(
            con,
            str(root.resolve()),
            [*archived_paths, r"handoff\legacy.py"],
        )
        con.commit()

    result = index.query(str(root), "ActiveHandler", verify_freshness=True)

    assert {symbol["path"] for symbol in result["symbols"]} == {
        "src/current.py",
        "src/pkg/handoff/nested.py",
        "artifacts/release/current.py",
        "src/T18-review-artifacts-20260928/current.py",
    }

    # Archived rows sort before live sources; filtering must happen before LIMIT.
    dead_code = index.find_dead_code(str(root), limit=4)
    dead_paths = {symbol["path"] for symbol in dead_code["dead_code"]}
    assert dead_code["success"] is True
    assert not dead_paths.intersection({*archived_paths, r"handoff\legacy.py"})
    assert {
        "src/current.py",
        "src/pkg/handoff/nested.py",
        "artifacts/release/current.py",
        "src/T18-review-artifacts-20260928/current.py",
    }.issubset(dead_paths)


def test_legacy_archive_rows_cannot_starve_current_query_candidates(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    current = root / "src/current.py"
    current.parent.mkdir(parents=True)
    current.write_text("def ActiveHandler(): pass\n", encoding="utf-8")
    index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}},
        repo_tools=RepositoryTools({"rag": {"extensions": [".py"]}}),
    )
    assert index.update_files_batch(str(root), ["src/current.py"])["success"]
    with index._lock, closing(index._connect()) as con:
        con.execute("CREATE TEMP TABLE current_symbol AS SELECT * FROM symbols")
        con.execute("DELETE FROM symbols")
        # More legacy matches than query's minimum candidate cap, inserted first.
        for ordinal in range(150):
            con.execute(
                "INSERT INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) "
                "SELECT root,?,name,kind,line,end_line,container,name_path,signature,access,docstring "
                "FROM current_symbol",
                (f"artifacts/t08-ast-check-{ordinal}/stale.py",),
            )
        con.execute("INSERT INTO symbols SELECT * FROM current_symbol")
        index._replace_symbol_trigrams(
            con,
            str(root.resolve()),
            [str(row[0]) for row in con.execute("SELECT DISTINCT path FROM symbols WHERE root=?", (str(root.resolve()),))],
        )
        con.commit()

    result = index.query(str(root), "ActiveHandler", limit=1, verify_freshness=True)
    assert result["success"] is True
    assert [symbol["path"] for symbol in result["symbols"]] == ["src/current.py"]
    assert result["truncated"] is False
