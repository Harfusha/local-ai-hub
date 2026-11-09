import os

import pytest

from local_ai_hub.deterministic import DeterministicEngine


@pytest.mark.parametrize("pattern", ["fn:phantom", "function:phantom", "class:phantom"])
def test_python_declaration_search_ignores_string_literals(tmp_path, pattern):
    (tmp_path / "example.py").write_text('message = "def phantom(x): class phantom:"\n', encoding="utf-8")
    result = DeterministicEngine().structural_search(str(tmp_path), pattern, path="example.py")
    assert result["matches"] == []


@pytest.mark.parametrize("pattern", ["fn:actual", "function:actual", "class:widget"])
def test_python_declaration_search_finds_real_ast_nodes(tmp_path, pattern):
    (tmp_path / "example.py").write_text("async def actual():\n    pass\n\nclass Widget:\n    pass\n", encoding="utf-8")
    result = DeterministicEngine().structural_search(str(tmp_path), pattern, path="example.py")
    assert result["count"] == 1
    assert result["matches"][0]["line"] == (4 if pattern.startswith("class:") else 1)


def test_python_declaration_search_marks_invalid_source_incomplete(tmp_path):
    (tmp_path / "example.py").write_text('message = "def phantom():"\ndef broken(:\n', encoding="utf-8")
    result = DeterministicEngine().structural_search(str(tmp_path), "fn:phantom", path="example.py")
    assert result["matches"] == []
    assert result["truncated"] is True
    assert "parse_errors" in result["truncation_reasons"]


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "inside.py").write_text("def visible():\n    return 1\n", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text("def external_only():\n    return 2\n", encoding="utf-8")
    engine = object.__new__(DeterministicEngine)
    return engine, root, outside


def test_path_traversal_cannot_read_sibling(fixture):
    engine, root, outside = fixture
    result = engine.structural_search(str(root), "external_only", path=os.path.join("..", outside.name))
    assert result["success"] is False, result
    assert not result.get("matches")


def test_outside_absolute_path_cannot_be_read(fixture):
    engine, root, outside = fixture
    result = engine.structural_search(str(root), "external_only", path=str(outside))
    assert result["success"] is False, result
    assert not result.get("matches")


def test_regular_internal_file_remains_searchable(fixture):
    engine, root, _ = fixture
    result = engine.structural_search(str(root), "visible", path="inside.py")
    assert result["success"] is True
    assert result["matches"]


def test_symlink_file_cannot_be_read_even_during_recursive_scan(fixture):
    engine, root, outside = fixture
    link = root / "linked.py"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("file symlink creation unavailable")
    scoped = engine.structural_search(str(root), "external_only", path="linked.py")
    assert scoped["success"] is False
    recursive = engine.structural_search(str(root), "external_only")
    assert not recursive.get("matches")
    assert recursive.get("truncated") is True or recursive.get("read_errors", 0) > 0


def test_reparse_file_is_rejected_and_recursive_scan_reports_skip(fixture, monkeypatch):
    import local_ai_hub.deterministic as deterministic

    engine, root, _ = fixture
    (root / "linked.py").write_text("def external_only():\n    pass\n", encoding="utf-8")
    original = deterministic._is_symlink_or_reparse_point
    monkeypatch.setattr(deterministic, "_is_symlink_or_reparse_point", lambda path: path.name == "linked.py" or original(path))
    assert engine.structural_search(str(root), "external_only", path="linked.py")["success"] is False
    result = engine.structural_search(str(root), "external_only")
    assert result["matches"] == []
    assert result["truncated"] is True and result["read_errors"] > 0


def test_reparse_directory_is_not_walked(fixture, monkeypatch):
    import local_ai_hub.deterministic as deterministic

    engine, root, _ = fixture
    redirected = root / "redirected"
    redirected.mkdir()
    (redirected / "hidden.py").write_text("def external_only():\n    pass\n", encoding="utf-8")
    original = deterministic._is_symlink_or_reparse_point
    monkeypatch.setattr(deterministic, "_is_symlink_or_reparse_point", lambda path: path.name == "redirected" or original(path))
    result = engine.structural_search(str(root), "external_only")
    assert result["matches"] == []
    assert result["truncated"] is True and result["read_errors"] > 0


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_real_windows_junction_cannot_escape_root(fixture, tmp_path):
    import stat
    import subprocess

    engine, root, _ = fixture
    external = tmp_path / "external_dir"
    external.mkdir()
    marker = external / "outside.py"
    marker.write_text("def external_only():\n    pass\n", encoding="utf-8")
    link = root / "junction"
    assert link.parent.resolve() == root.resolve()
    assert external.resolve().parent == tmp_path.resolve()
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(external)],
        capture_output=True, text=True, timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if created.returncode != 0:
        pytest.skip("junction creation unavailable")
    try:
        info = os.lstat(link)
        assert info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT
        result = engine.structural_search(str(root), "external_only", path="junction/outside.py")
        assert result["success"] is False
        assert not result.get("matches")
        recursive = engine.structural_search(str(root), "external_only")
        assert recursive["matches"] == []
        assert recursive["truncated"] is True and recursive["read_errors"] > 0
    finally:
        os.rmdir(link)
    assert marker.is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_junction_swap_during_open_does_not_return_external_data(fixture, tmp_path, monkeypatch):
    import subprocess
    import local_ai_hub.deterministic as deterministic

    engine, root, _ = fixture
    safe = root / "safe"
    safe.mkdir()
    target = safe / "inside.py"
    target.write_text("def inside():\n    pass\n", encoding="utf-8")
    external = tmp_path / "external_swap"
    external.mkdir()
    marker = external / "inside.py"
    marker.write_text("def external_only():\n    pass\n", encoding="utf-8")
    link, held = root / "junction", root / "held"
    assert all(path.parent.resolve() == root.resolve() for path in (safe, link, held))
    assert external.resolve().parent == tmp_path.resolve()
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(external)],
        capture_output=True, text=True, timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if created.returncode != 0:
        pytest.skip("junction creation unavailable")
    original_open = os.open
    swapped = False

    def swap_then_open(path, *args, **kwargs):
        nonlocal swapped
        if not swapped and isinstance(path, (str, os.PathLike)) and os.fspath(path) == os.fspath(target):
            os.rename(safe, held)
            os.rename(link, safe)
            swapped = True
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(deterministic.os, "open", swap_then_open)
    try:
        result = engine.structural_search(str(root), "external_only", path="safe/inside.py")
        assert swapped, "test did not trigger the directory swap"
        assert not result.get("matches")
        assert result.get("read_errors", 0) > 0
    finally:
        if swapped:
            os.rmdir(safe)
            os.rename(held, safe)
        else:
            os.rmdir(link)
    assert marker.is_file() and target.is_file()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_junction_swap_before_stat_is_rejected_before_read(fixture, tmp_path, monkeypatch):
    import subprocess
    from pathlib import Path
    import local_ai_hub.deterministic as deterministic

    engine, root, _ = fixture
    safe = root / "safe"
    safe.mkdir()
    target = safe / "inside.py"
    target.write_text("def inside():\n    pass\n", encoding="utf-8")
    external = tmp_path / "external_before_stat"
    external.mkdir()
    marker = external / "inside.py"
    marker.write_text("def external_only():\n    pass\n", encoding="utf-8")
    link, held = root / "junction", root / "held"
    assert all(path.parent.resolve() == root.resolve() for path in (safe, link, held))
    assert external.resolve().parent == tmp_path.resolve()
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(external)],
        capture_output=True, text=True, timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if created.returncode != 0:
        pytest.skip("junction creation unavailable")
    original_stat, original_fdopen = Path.stat, os.fdopen
    swapped = False
    read_called = False

    def swap_then_stat(path, *args, **kwargs):
        nonlocal swapped
        if not swapped and path == target and kwargs.get("follow_symlinks") is False:
            os.rename(safe, held)
            os.rename(link, safe)
            swapped = True
        return original_stat(path, *args, **kwargs)

    class ObservedFile:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def fileno(self):
            return self.wrapped.fileno()

        def read(self, *args):
            nonlocal read_called
            read_called = True
            return self.wrapped.read(*args)

    monkeypatch.setattr(Path, "stat", swap_then_stat)
    monkeypatch.setattr(deterministic.os, "fdopen", lambda *args, **kwargs: ObservedFile(original_fdopen(*args, **kwargs)))
    try:
        result = engine.structural_search(str(root), "external_only", path="safe/inside.py")
        assert swapped, "test did not trigger the directory swap"
        assert read_called is False
        assert not result.get("matches")
        assert result.get("read_errors", 0) > 0
    finally:
        if swapped:
            os.rmdir(safe)
            os.rename(held, safe)
        else:
            os.rmdir(link)
    assert marker.is_file() and target.is_file()


def test_traversal_denied_through_loopback_mcp(fixture, monkeypatch, tmp_path):
    import asyncio
    import threading

    from local_ai_hub import http_server, mcp_server
    from local_ai_hub.app import LocalAIApp
    from local_ai_hub.client import HubClient

    _, root, outside = fixture
    server = http_server.LocalAIHTTPServer(("127.0.0.1", 0), http_server.Handler)
    config = tmp_path / "hub-test.toml"
    config.write_text(
        f'[server]\nbind = "127.0.0.1"\nport = {server.server_address[1]}\n'
        f'state_dir = "{(tmp_path / "state").as_posix()}"\n'
        f'[security]\nallowed_roots = ["{root.as_posix()}"]\n', encoding="utf-8",
    )
    app = LocalAIApp(str(config))
    monkeypatch.setattr(http_server, "APP", app)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    client = HubClient(config_path=str(config), auto_start=False)
    monkeypatch.setattr(mcp_server, "CLIENT", client)
    monkeypatch.setattr(mcp_server, "_record_tool_accounting", lambda **_: None)
    monkeypatch.setattr(mcp_server._ACCOUNTING_REPORTER, "record", lambda _event: None)
    try:
        (root / "declarations.py").write_text('message = "def phantom():"\nasync def actual():\n    pass\n', encoding="utf-8")
        for query, expected in (("fn:phantom", 0), ("fn:actual", 1)):
            _, declaration_result = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
                "action": "structural_search", "root": str(root), "query": query,
                "path": "declarations.py", "response_profile": "compact",
            }))
            assert declaration_result["success"] is True, declaration_result
            assert declaration_result["count"] == expected, declaration_result
        _, result = asyncio.run(mcp_server.mcp.call_tool("local_ai_repo", {
            "action": "structural_search", "root": str(root), "query": "external_only",
            "path": f"../{outside.name}", "response_profile": "compact",
        }))
        assert result["success"] is False, result
        assert result.get("status_code") == 403
        assert not result.get("matches")
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
        app.close()
