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
        for archived_path in [*paths[:11], r"handoff\legacy.py"]:
            con.execute(
                "INSERT INTO symbols(root,path,name,kind,line,end_line,container,name_path,signature,access,docstring) "
                "SELECT root,?,name,kind,line,end_line,container,name_path,signature,access,docstring "
                "FROM symbols WHERE root=? AND path='src/current.py'",
                (archived_path, str(root.resolve())),
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
    assert not dead_paths.intersection({*paths[:11], r"handoff\legacy.py"})
    assert {
        "src/current.py",
        "src/pkg/handoff/nested.py",
        "artifacts/release/current.py",
        "src/T18-review-artifacts-20260928/current.py",
    }.issubset(dead_paths)
