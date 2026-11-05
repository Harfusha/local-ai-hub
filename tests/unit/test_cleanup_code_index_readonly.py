from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools
from tools import cleanup_code_index


def _database_snapshot(database: Path) -> dict[str, tuple[int, str | None]]:
    paths = sorted(database.parent.glob(database.name + "*"))
    return {
        path.name: (
            path.stat().st_size,
            None if path.name.endswith("-shm") else hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in paths
        if path.is_file()
    }


@pytest.mark.parametrize("hub_state", [True, None])
def test_online_dry_run_reads_orphans_without_mutating_sqlite(tmp_path, monkeypatch, capsys, hub_state):
    state_dir = tmp_path / "state"
    config = {"server": {"state_dir": str(state_dir)}}
    index = CodeIndex(config, RepositoryTools(config))
    database = index.db_path
    writer = index._connect()
    columns = [row["name"] for row in writer.execute("PRAGMA table_info(symbol_trigrams)")]
    values = {
        "root": str(tmp_path / "removed-worktree"),
        "path": "src/removed.py",
        "symbol_rowid": 987654321,
        "field": "name",
        "gram": "rem",
    }
    insert_columns = [name for name in columns if name in values]
    writer.execute(
        f"INSERT INTO symbol_trigrams ({','.join(insert_columns)}) "
        f"VALUES ({','.join('?' for _ in insert_columns)})",
        [values[name] for name in insert_columns],
    )
    writer.commit()
    index.close()
    before = _database_snapshot(database)

    monkeypatch.setattr(cleanup_code_index, "load_config", lambda **_kwargs: config)
    monkeypatch.setattr(cleanup_code_index, "_hub_is_online", lambda *_args: hub_state)
    monkeypatch.setattr(cleanup_code_index, "_active_preprocessing_roots", lambda _path: ())
    monkeypatch.setattr(
        CodeIndex,
        "_init_db",
        lambda *_args, **_kwargs: pytest.fail("read-only dry-run must not initialize or write the index"),
    )

    exit_code = cleanup_code_index.main(["--dry-run"])

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["hub_online"] is hub_state
    assert result["batches"][0]["orphan_trigrams_available"] == 1
    assert result["batches"][0]["rows_pruned"] == 0
    assert _database_snapshot(database) == before
    writer.close()


def test_online_apply_still_refuses_before_opening_the_index(tmp_path, monkeypatch, capsys):
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    monkeypatch.setattr(cleanup_code_index, "load_config", lambda **_kwargs: config)
    monkeypatch.setattr(cleanup_code_index, "_hub_is_online", lambda *_args: True)
    monkeypatch.setattr(
        cleanup_code_index,
        "CodeIndex",
        lambda *_args, **_kwargs: pytest.fail("online apply must be refused before opening SQLite"),
    )

    exit_code = cleanup_code_index.main(["--apply"])

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert result["error"] == "hub_online"


def test_read_only_index_rejects_prune_mutation(tmp_path):
    config = {"server": {"state_dir": str(tmp_path / "state")}}
    writer = CodeIndex(config, RepositoryTools(config))
    database = writer.db_path
    writer.close()
    before = _database_snapshot(database)

    reader = CodeIndex(config, RepositoryTools(config), read_only=True)
    result = reader.prune_orphaned_trigrams(dry_run=False)
    with closing(reader._connect()) as connection:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM symbol_trigrams")
    reader.close()

    assert result["success"] is False
    assert result["error"] == "read_only_index"
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before[database.name][1]
