"""Bundle regression source; execution deferred by the operator."""
import os

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


def _indexed_file(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "alpha.py"
    source.write_text("def alpha():\n    return 1\n", encoding="utf-8")
    config = {"server": {"state_dir": str(tmp_path / "state")}, "rag": {"extensions": [".py"]}}
    index = CodeIndex(config, RepositoryTools(config))
    monkeypatch.setattr(index, "_parse_file_content", lambda *_args, **_kwargs: ([{
        "name": "alpha", "kind": "function", "line": 1, "end_line": 2,
        "name_path": "alpha", "container": "",
    }], [], []))
    assert index.update_file(str(root), "alpha.py")["success"]
    return index, root, source


def test_cached_query_rechecks_stat_and_coalesces_notifications(tmp_path, monkeypatch):
    index, root, source = _indexed_file(tmp_path, monkeypatch)
    queued = []
    index.set_reindex_callback(lambda path: queued.append(path) or True)
    try:
        first = index.query(str(root), "alpha")
        assert first["freshness"]["status"] == "stat_current_candidates"
        assert first["stale"] is False
        before = source.stat()
        source.write_text("def alpha():\n    return 2\n", encoding="utf-8")
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        second = index.query(str(root), "alpha")
        assert second["stale"] is True
        assert second["freshness"]["stale_paths"] == ["alpha.py"]
        assert second["confidence"] <= 0.5
        assert second["freshness"]["reindex_notifications_queued"] == 1
        index.query(str(root), "alpha")
        assert queued == [str(source)]
    finally:
        index.close()


def test_content_verification_distinguishes_preserved_mtime_and_size(tmp_path, monkeypatch):
    index, root, source = _indexed_file(tmp_path, monkeypatch)
    try:
        before = source.stat()
        source.write_text("def alpha():\n    return 2\n", encoding="utf-8")
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        stat_result = index.query(str(root), "alpha")
        assert stat_result["freshness"]["verification"] == "mtime_ns_and_size"
        assert stat_result["confidence"] <= 0.9
        verified = index.query(str(root), "alpha", verify_freshness=True)
        assert verified["freshness"]["verification"] == "content_hash"
        assert verified["stale"] is True
    finally:
        index.close()
