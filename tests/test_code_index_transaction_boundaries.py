from contextlib import closing

import pytest

from local_ai_hub import code_index, sqlite_support
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


def test_remove_indexed_paths_rolls_back_when_transaction_budget_expires(
    tmp_path, monkeypatch
):
    index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}},
        repo_tools=RepositoryTools({}),
    )
    root = str(tmp_path / "repo")
    indexed_path = "src/keep.py"
    canonical_root = code_index.canonical_root(root)
    with closing(index._connect()) as con:
        con.execute(
            "INSERT INTO files(root,path,content_hash,analyzer_version,language,updated_at,mtime_ns,size_bytes) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (canonical_root, indexed_path, "hash", "analyzer", "python", 1.0, 1, 1),
        )
        con.commit()

    def _expired_transaction(con, **kwargs):
        kwargs.pop("max_duration_seconds", None)
        return sqlite_support.write_transaction(
            con, max_duration_seconds=1e-12, **kwargs
        )

    monkeypatch.setattr(
        code_index, "write_transaction", _expired_transaction, raising=False
    )
    with pytest.raises(TimeoutError, match="duration budget"):
        index._remove_indexed_paths(root, [indexed_path])

    with closing(index._connect()) as con:
        row = con.execute(
            "SELECT path FROM files WHERE root=? AND path=?",
            (canonical_root, indexed_path),
        ).fetchone()
    assert row is not None


def test_update_file_uses_bounded_write_transaction(tmp_path, monkeypatch):
    index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}},
        repo_tools=RepositoryTools({}),
    )
    root = tmp_path / "repo"
    source = root / "src" / "example.py"
    source.parent.mkdir(parents=True)
    source.write_text("def example():\n    return 1\n", encoding="utf-8")
    observed = []
    real_write_transaction = sqlite_support.write_transaction

    def record_transaction(connection, **kwargs):
        observed.append(kwargs)
        return real_write_transaction(connection, **kwargs)

    monkeypatch.setattr(code_index, "write_transaction", record_transaction)
    result = index.update_file(str(root), "src/example.py")

    assert result["success"] is True
    update_transactions = [
        item for item in observed if item.get("rollback_label") == "code index update file"
    ]
    assert len(update_transactions) == 1
    assert update_transactions[0]["max_duration_seconds"] == 5.0


def test_code_index_prune_and_usage_writes_use_bounded_transactions(tmp_path, monkeypatch):
    index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}},
        repo_tools=RepositoryTools({}),
    )
    root = str(tmp_path / "repo")
    canonical_root = code_index.canonical_root(root)
    with closing(index._connect()) as con:
        con.execute(
            "INSERT INTO files(root,path,content_hash,analyzer_version,language,updated_at,mtime_ns,size_bytes) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (canonical_root, "src/stale.py", "hash", "analyzer", "python", 1.0, 1, 1),
        )
        con.commit()

    observed = []
    real_write_transaction = sqlite_support.write_transaction

    def record_transaction(connection, **kwargs):
        observed.append(kwargs)
        return real_write_transaction(connection, **kwargs)

    monkeypatch.setattr(code_index, "write_transaction", record_transaction)
    assert index.prune(root, [])["pruned"] == 1
    assert index.record_usage(
        root, [{"path": "src/used.py", "uses": 2, "last_used_at": 1.0}]
    ) == 1

    labels = {item.get("rollback_label"): item for item in observed}
    assert labels["code index prune"]["max_duration_seconds"] == 5.0
    assert labels["code index usage"]["max_duration_seconds"] == 5.0


def test_parse_blob_prune_uses_bounded_transaction(tmp_path, monkeypatch):
    index = CodeIndex(
        {"server": {"state_dir": str(tmp_path / "state")}},
        repo_tools=RepositoryTools({}),
    )
    with closing(index._connect()) as con:
        con.execute(
            "INSERT INTO parse_blobs(content_hash,analyzer_version,language,payload_json,updated_at) "
            "VALUES(?,?,?,?,?)",
            ("orphan", "analyzer", "python", "{}", 1.0),
        )
        con.commit()

    observed = []
    real_write_transaction = sqlite_support.write_transaction

    def record_transaction(connection, **kwargs):
        observed.append(kwargs)
        return real_write_transaction(connection, **kwargs)

    monkeypatch.setattr(code_index, "write_transaction", record_transaction)
    result = index.prune_unreferenced_parse_blobs(dry_run=False, max_blobs=1)

    assert result["success"] is True
    assert result["deleted_blob_count"] == 1
    transaction = next(
        item for item in observed if item.get("rollback_label") == "code index parse blob prune"
    )
    assert transaction["max_duration_seconds"] == 5.0
