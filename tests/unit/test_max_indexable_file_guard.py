from contextlib import closing
import ast
from pathlib import Path

import pytest

from local_ai_hub.code_index import CodeIndex
from local_ai_hub.repo_tools import RepositoryTools


MAX_FILE_BYTES = 2_000_000


def _index(tmp_path: Path, *, max_file_bytes: int = MAX_FILE_BYTES) -> tuple[Path, RepositoryTools, CodeIndex]:
    root = tmp_path / "repo"
    root.mkdir()
    config = {
        "rag": {"extensions": [".py"], "max_file_bytes": max_file_bytes},
        "search": {"prefer_git_files": False},
        "server": {"state_dir": str(tmp_path / "state")},
    }
    tools = RepositoryTools(config)
    return root, tools, CodeIndex(config, repo_tools=tools)


def test_oversized_file_skips_full_snapshot_and_ast_but_keeps_path_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, tools, index = _index(tmp_path)
    small = root / "small.py"
    oversized = root / "oversized.py"
    small.write_text("def SmallSymbol(): pass\n", encoding="utf-8")
    oversized.write_bytes(
        b"def OversizedSymbol(): pass\n" + b" " * (MAX_FILE_BYTES + 1)
    )
    oversized_resolved = oversized.resolve()
    read_attempts: list[Path] = []
    original_reader = tools._read_snapshot

    def guarded_reader(path: Path, **kwargs: object) -> tuple[str, list[str]]:
        if Path(path).resolve() == oversized_resolved:
            read_attempts.append(Path(path))
            raise AssertionError("oversized file reached whole-file snapshot")
        return original_reader(path, **kwargs)

    monkeypatch.setattr(tools, "_read_snapshot", guarded_reader)
    parse_attempts: list[int] = []
    original_parser = index._parse_python

    def guarded_parser(text: str):
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            parse_attempts.append(len(text))
            raise AssertionError("oversized file reached Python AST parser")
        return original_parser(text)

    monkeypatch.setattr(index, "_parse_python", guarded_parser)

    result = index.update_files_batch(str(root), ["small.py", "oversized.py"])

    assert read_attempts == []
    assert parse_attempts == []
    assert result["success"] is True
    small_result = index.query(str(root), "SmallSymbol", verify_freshness=True)
    assert {symbol["path"] for symbol in small_result["symbols"]} == {"small.py"}
    large_result = index.query(str(root), "OversizedSymbol", verify_freshness=True)
    assert not any(
        symbol["name"] == "OversizedSymbol" or symbol["path"] == "oversized.py"
        for symbol in large_result["symbols"]
    )
    with index._lock, closing(index._connect()) as con:
        row = con.execute(
            "SELECT path, content_hash FROM files WHERE root=? AND path=?",
            (str(root.resolve()), "oversized.py"),
        ).fetchone()
    assert row is not None
    assert row["path"] == "oversized.py"
    assert row["content_hash"] is None


def test_growing_indexed_file_removes_stale_symbols_without_reading_oversized_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, tools, index = _index(tmp_path)
    target = root / "growing.py"
    target.write_text(
        "def FormerSymbol(): pass\ndef CallsFormer(): return FormerSymbol()\n",
        encoding="utf-8",
    )
    assert index.update_files_batch(str(root), ["growing.py"])["success"]
    with index._lock, closing(index._connect()) as con:
        refs_before = con.execute(
            "SELECT COUNT(*) FROM refs WHERE root=? AND path=?",
            (str(root.resolve()), "growing.py"),
        ).fetchone()[0]
        edges_before = con.execute(
            "SELECT COUNT(*) FROM edges WHERE root=? AND path=?",
            (str(root.resolve()), "growing.py"),
        ).fetchone()[0]
    assert refs_before + edges_before > 0
    target.write_bytes(
        b"def FormerSymbol(): pass\n" + b" " * (MAX_FILE_BYTES + 1)
    )
    target_resolved = target.resolve()
    read_attempts: list[Path] = []
    original_reader = tools._read_snapshot

    def guarded_reader(path: Path, **kwargs: object) -> tuple[str, list[str]]:
        if Path(path).resolve() == target_resolved:
            read_attempts.append(Path(path))
            raise AssertionError("grown oversized file reached whole-file snapshot")
        return original_reader(path, **kwargs)

    monkeypatch.setattr(tools, "_read_snapshot", guarded_reader)

    result = index.update_files_batch(str(root), ["growing.py"])

    assert read_attempts == []
    assert result["success"] is True
    stale = index.query(str(root), "FormerSymbol", verify_freshness=True)
    assert stale["symbols"] == []
    with index._lock, closing(index._connect()) as con:
        row = con.execute(
            "SELECT path, content_hash FROM files WHERE root=? AND path=?",
            (str(root.resolve()), "growing.py"),
        ).fetchone()
    assert row is not None
    assert row["path"] == "growing.py"
    assert row["content_hash"] is None
    with index._lock, closing(index._connect()) as con:
        assert con.execute(
            "SELECT COUNT(*) FROM refs WHERE root=? AND path=?",
            (str(root.resolve()), "growing.py"),
        ).fetchone()[0] == 0
        assert con.execute(
            "SELECT COUNT(*) FROM edges WHERE root=? AND path=?",
            (str(root.resolve()), "growing.py"),
        ).fetchone()[0] == 0


def test_bounded_snapshot_detects_file_growth_after_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    max_bytes = 64
    target = tmp_path / "growing.py"
    target.write_bytes(b"x" * 8)
    tools = RepositoryTools({"rag": {"max_file_bytes": max_bytes}})
    original_open = Path.open
    grew = False

    def grow_before_read(path: Path, mode: str = "r", *args: object, **kwargs: object):
        nonlocal grew
        if path.resolve() == target.resolve() and mode == "rb" and not grew:
            grew = True
            target.write_bytes(b"x" * (max_bytes + 1))
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", grow_before_read)

    with pytest.raises(OSError):
        tools._read_snapshot(target, max_bytes=max_bytes)

    assert grew is True
    assert target.stat().st_size == max_bytes + 1


def test_configured_limit_allows_exact_boundary_and_skips_next_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    max_bytes = 64
    root, tools, index = _index(tmp_path, max_file_bytes=max_bytes)
    boundary = root / "boundary.py"
    oversized = root / "configured_oversized.py"
    boundary_source = b"def BoundarySymbol(): pass\n"
    boundary.write_bytes(boundary_source + b" " * (max_bytes - len(boundary_source)))
    oversized_source = b"def BeyondSymbol(): pass\n"
    oversized.write_bytes(oversized_source + b" " * (max_bytes + 1 - len(oversized_source)))
    oversized_resolved = oversized.resolve()
    original_reader = tools._read_snapshot
    read_attempts: list[Path] = []

    def guarded_reader(path: Path, **kwargs: object) -> tuple[str, list[str]]:
        if Path(path).resolve() == oversized_resolved:
            read_attempts.append(Path(path))
            raise AssertionError("configured oversized file reached whole-file snapshot")
        return original_reader(path, **kwargs)

    monkeypatch.setattr(tools, "_read_snapshot", guarded_reader)

    result = index.update_files_batch(str(root), ["boundary.py", "configured_oversized.py"])

    assert read_attempts == []
    assert result["success"] is True
    boundary_result = index.query(str(root), "BoundarySymbol")
    assert {symbol["path"] for symbol in boundary_result["symbols"] if symbol["name"] == "BoundarySymbol"} == {"boundary.py"}
    beyond_result = index.query(str(root), "BeyondSymbol")
    assert not any(symbol["name"] == "BeyondSymbol" for symbol in beyond_result["symbols"])


def test_update_file_skips_oversized_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, tools, index = _index(tmp_path)
    target = root / "single.py"
    target.write_bytes(b"def SingleSymbol(): pass\n" + b" " * (MAX_FILE_BYTES + 1))
    target_resolved = target.resolve()
    original_reader = tools._read_snapshot
    read_attempts: list[Path] = []

    def guarded_reader(path: Path, **kwargs: object) -> tuple[str, list[str]]:
        if Path(path).resolve() == target_resolved:
            read_attempts.append(Path(path))
            raise AssertionError("single oversized file reached whole-file snapshot")
        return original_reader(path, **kwargs)

    monkeypatch.setattr(tools, "_read_snapshot", guarded_reader)

    result = index.update_file(str(root), "single.py")

    assert result["success"] is True
    assert result["skipped"] is True
    assert read_attempts == []


def test_python_parser_rejects_oversized_direct_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, index = _index(tmp_path)
    parse_attempts: list[str] = []
    original_parse = ast.parse

    def track_parse(source: str, *args: object, **kwargs: object):
        parse_attempts.append(source)
        return original_parse(source, *args, **kwargs)

    monkeypatch.setattr(ast, "parse", track_parse)

    index._parse_python("def TooLarge(): pass\n" + " " * (MAX_FILE_BYTES + 1))

    assert parse_attempts == []


def test_diagnostics_do_not_read_oversized_python_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, index = _index(tmp_path)
    target = root / "diagnostics.py"
    target.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    target_resolved = target.resolve()
    read_attempts: list[Path] = []
    original_read_text = Path.read_text

    def track_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path.resolve() == target_resolved:
            read_attempts.append(Path(path))
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", track_read_text)

    result = index.get_diagnostics_for_file(str(root), "diagnostics.py")

    assert read_attempts == []
    assert result["success"] is True
    assert result["skipped"] is True


def test_find_symbol_body_does_not_read_oversized_python_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _, index = _index(tmp_path)
    target = root / "body.py"
    target.write_text("def BodySymbol(): return 1\n", encoding="utf-8")
    assert index.update_files_batch(str(root), ["body.py"])["success"]
    target.write_bytes(b"def BodySymbol(): return 1\n" + b" " * (MAX_FILE_BYTES + 1))
    target_resolved = target.resolve()
    read_attempts: list[Path] = []
    original_read_text = Path.read_text

    def track_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path.resolve() == target_resolved:
            read_attempts.append(Path(path))
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", track_read_text)

    index.find_symbol(str(root), "BodySymbol", include_body=True)

    assert read_attempts == []
