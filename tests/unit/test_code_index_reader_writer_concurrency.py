from concurrent.futures import ThreadPoolExecutor

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


def test_query_does_not_wait_for_code_index_writer_mutex(tmp_path):
    root = tmp_path / "repo"
    source = root / "src" / "example.py"
    source.parent.mkdir(parents=True)
    source.write_text("def ConcurrentQueryNeedle():\n    return 1\n", encoding="utf-8")
    index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}},
        repo_tools=RepositoryTools({}),
    )
    try:
        assert index.update_file(str(root), "src/example.py")["success"] is True
        with ThreadPoolExecutor(max_workers=1) as executor:
            writer = index._connect()
            writer.execute("BEGIN IMMEDIATE")
            writer.execute(
                "UPDATE symbols SET name=? WHERE root=? AND path=?",
                ("UncommittedNeedle", str(root), "src/example.py"),
            )
            index._lock.acquire()
            try:
                result = executor.submit(
                    index.query, str(root), "ConcurrentQueryNeedle", 1,
                ).result(timeout=2)
            finally:
                index._lock.release()
                writer.rollback()
                writer.close()
        assert result["success"] is True
        assert result["symbols"][0]["name"] == "ConcurrentQueryNeedle"
    finally:
        index.close()
