import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import local_ai_hub.repo_tools as repo_tools_module
from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


def _index_config(tmp_path: Path) -> dict[str, dict[str, str]]:
    return {"server": {"state_dir": str(tmp_path / "state")}}


def _create_legacy_files_table(config: dict[str, dict[str, str]]) -> None:
    db_path = Path(config["server"]["state_dir"]) / "code-index.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            "CREATE TABLE files(root TEXT,path TEXT,content_hash TEXT,analyzer_version TEXT,"
            "language TEXT,updated_at REAL,PRIMARY KEY(root,path))"
        )
        con.commit()


def _track_snapshot_work(monkeypatch, payloads: dict[Path, bytes]) -> dict[Path, dict[str, int]]:
    targets = {path.resolve(): payload for path, payload in payloads.items()}
    work = {path: {"bytes_read": 0, "sha256_calls": 0} for path in targets}
    original_open = Path.open

    class CountingReader:
        def __init__(self, reader, path: Path):
            self.reader = reader
            self.path = path

        def __enter__(self):
            self.reader.__enter__()
            return self

        def __exit__(self, *args):
            return self.reader.__exit__(*args)

        def read(self, *args):
            data = self.reader.read(*args)
            work[self.path]["bytes_read"] += len(data)
            return data

        def __getattr__(self, name):
            return getattr(self.reader, name)

    def tracked_open(path: Path, *args, **kwargs):
        resolved = path.resolve()
        reader = original_open(path, *args, **kwargs)
        if resolved in targets:
            return CountingReader(reader, resolved)
        return reader

    real_sha256 = repo_tools_module.hashlib.sha256

    def tracked_sha256(data=b"", *args, **kwargs):
        for path, payload in targets.items():
            if data == payload:
                work[path]["sha256_calls"] += 1
                break
        return real_sha256(data, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked_open)
    monkeypatch.setattr(repo_tools_module.hashlib, "sha256", tracked_sha256)
    return work


def test_update_file_skips_snapshot_io_and_hash_after_cold_reopen(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    source = root / "src" / "target.py"
    source.parent.mkdir(parents=True)
    content = b"def target():\n    return 1\n"
    source.write_bytes(content)
    config = _index_config(tmp_path)
    _create_legacy_files_table(config)

    initial = CodeIndex(config, repo_tools=RepositoryTools(config))
    assert initial.update_file(str(root), "src/target.py")["success"] is True

    reopened = CodeIndex(config, repo_tools=RepositoryTools(config))
    work = _track_snapshot_work(monkeypatch, {source: content})
    result = reopened.update_file(str(root), "src/target.py")

    assert result["success"] is True
    assert work[source.resolve()] == {"bytes_read": 0, "sha256_calls": 0}


def test_update_files_batch_skips_snapshot_io_and_hash_after_cold_reopen(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    contents = {
        root / "src" / "first.py": b"def first():\n    return 1\n",
        root / "src" / "second.py": b"def second():\n    return 2\n",
    }
    for source, content in contents.items():
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(content)
    config = _index_config(tmp_path)
    paths = [str(source.relative_to(root)) for source in contents]

    initial = CodeIndex(config, repo_tools=RepositoryTools(config))
    assert initial.update_files_batch(str(root), paths)["success"] is True

    reopened = CodeIndex(config, repo_tools=RepositoryTools(config))
    work = _track_snapshot_work(monkeypatch, contents)
    result = reopened.update_files_batch(str(root), paths)

    assert result["success"] is True
    assert all(counts == {"bytes_read": 0, "sha256_calls": 0} for counts in work.values())


@pytest.mark.parametrize("batch", [False, True])
def test_explicit_changed_hash_forces_read_when_stat_is_unchanged(tmp_path, monkeypatch, batch):
    root = tmp_path / "repo"
    source = root / "src" / "target.py"
    source.parent.mkdir(parents=True)
    original = b"def target():\n    return 1\n"
    changed = b"def target():\n    return 2\n"
    source.write_bytes(original)
    config = _index_config(tmp_path)
    initial = CodeIndex(config, repo_tools=RepositoryTools(config))
    if batch:
        assert initial.update_files_batch(str(root), ["src/target.py"])["success"] is True
    else:
        assert initial.update_file(str(root), "src/target.py")["success"] is True

    original_stat = source.stat()
    source.write_bytes(changed)
    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert source.stat().st_size == original_stat.st_size
    assert source.stat().st_mtime_ns == original_stat.st_mtime_ns

    reopened = CodeIndex(config, repo_tools=RepositoryTools(config))
    digest = hashlib.sha256(changed).hexdigest()
    work = _track_snapshot_work(monkeypatch, {source: changed})
    if batch:
        result = reopened.update_files_batch(str(root), [("src/target.py", digest)])
    else:
        result = reopened.update_file(str(root), "src/target.py", content_hash=digest)

    assert result["success"] is True
    assert work[source.resolve()] == {"bytes_read": len(changed), "sha256_calls": 1}


def test_parser_and_language_changes_invalidate_single_and_batch_fastpaths(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    contents = {
        root / "src" / "parser.py": b"def parser():\n    return 1\n",
        root / "src" / "language.py": b"def language():\n    return 2\n",
    }
    for source, content in contents.items():
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(content)
    config = _index_config(tmp_path)
    initial = CodeIndex(config, repo_tools=RepositoryTools(config))
    paths = [str(source.relative_to(root)) for source in contents]
    assert initial.update_files_batch(str(root), paths)["success"] is True

    with closing(sqlite3.connect(initial.db_path)) as con:
        con.execute(
            "UPDATE files SET analyzer_version=? WHERE root=? AND path=?",
            ("stale-parser", str(root.resolve()), "src/parser.py"),
        )
        con.execute(
            "UPDATE files SET language=? WHERE root=? AND path=?",
            ("stale-language", str(root.resolve()), "src/language.py"),
        )
        con.commit()

    reopened = CodeIndex(config, repo_tools=RepositoryTools(config))
    work = _track_snapshot_work(monkeypatch, contents)
    assert reopened.update_file(str(root), "src/parser.py")["success"] is True
    assert reopened.update_files_batch(str(root), ["src/language.py"])["success"] is True

    for counts, content in zip(work.values(), contents.values()):
        assert counts == {"bytes_read": len(content), "sha256_calls": 1}


def test_snapshot_race_does_not_persist_newer_file_stat_for_old_snapshot(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    source = root / "src" / "target.py"
    source.parent.mkdir(parents=True)
    first = b"def target():\n    return 1\n"
    second = b"def target():\n    return 2\n"
    source.write_bytes(first)
    config = _index_config(tmp_path)
    repo_tools = RepositoryTools(config)
    index = CodeIndex(config, repo_tools=repo_tools)
    read_snapshot = repo_tools._read_snapshot
    original_stat = source.stat()

    def read_then_mutate(path, **kwargs):
        snapshot = read_snapshot(path, **kwargs)
        path.write_bytes(second)
        os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 1_000_000_000))
        return snapshot

    monkeypatch.setattr(repo_tools, "_read_snapshot", read_then_mutate)
    assert index.update_file(str(root), "src/target.py")["success"] is True
    with closing(sqlite3.connect(index.db_path)) as con:
        row = con.execute(
            "SELECT mtime_ns,size_bytes FROM files WHERE root=? AND path=?",
            (str(root.resolve()), "src/target.py"),
        ).fetchone()
    assert row == (None, None)

    reopened = CodeIndex(config, repo_tools=RepositoryTools(config))
    work = _track_snapshot_work(monkeypatch, {source: second})
    assert reopened.update_file(str(root), "src/target.py")["success"] is True
    assert work[source.resolve()] == {"bytes_read": len(second), "sha256_calls": 1}
