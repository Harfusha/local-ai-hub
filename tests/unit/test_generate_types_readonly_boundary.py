from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_hub.deterministic import DeterministicEngine


def _engine() -> DeterministicEngine:
    return DeterministicEngine(repo_tools=object())


def test_generate_types_returns_stub_text_without_creating_stub(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    stub = source.with_suffix(".pyi")
    source.write_text("def greet(name: str) -> str: return name\n", encoding="utf-8")
    stub.write_text("preserve me\n", encoding="utf-8")

    result = _engine().generate_types(str(tmp_path), "sample.py")

    assert result["success"] is True
    assert "def greet" in result["stub_content"]
    assert result["stub_file"] is None
    assert stub.read_text(encoding="utf-8") == "preserve me\n"


def test_generate_types_rejects_write_request_without_touching_stub(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    stub = source.with_suffix(".pyi")
    source.write_text("def greet() -> None: pass\n", encoding="utf-8")

    result = _engine().generate_types(str(tmp_path), str(source), write_stub=True)

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert "read-only" in result["error"]
    assert not stub.exists()


def test_generate_types_accepts_absolute_path_inside_root(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("value: int = 1\n", encoding="utf-8")

    result = _engine().generate_types(str(tmp_path), str(source))

    assert result["success"] is True
    assert result["source_file"] == str(source.resolve())


def test_generate_types_rejects_absolute_path_outside_root_without_touching_sentinel(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside.py"
    sentinel = tmp_path / "outside.pyi"
    root.mkdir()
    outside.write_text("value: int = 1\n", encoding="utf-8")
    sentinel.write_text("preserve me\n", encoding="utf-8")

    result = _engine().generate_types(str(root), str(outside))

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert sentinel.read_text(encoding="utf-8") == "preserve me\n"


def test_generate_types_rejects_parent_path_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside.py"
    root.mkdir()
    outside.write_text("value: int = 1\n", encoding="utf-8")

    result = _engine().generate_types(str(root), "../outside.py")

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False


def test_generate_types_rejects_source_over_byte_limit(tmp_path: Path) -> None:
    source = tmp_path / "large.py"
    source.write_bytes(b"#" * (1_048_576 + 1))

    result = _engine().generate_types(str(tmp_path), "large.py")

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert "byte limit" in result["error"]


def test_generate_types_bounds_read_even_if_source_grows_after_stat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "growing.py"
    source.write_text("small before open\n", encoding="utf-8")
    read_sizes: list[int] = []
    real_open = Path.open

    class OversizeReader(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            read_sizes.append(size)
            return super().read(size)

    def open_source(path: Path, *args: object, **kwargs: object):
        if path == source:
            return OversizeReader(b"#" * (1_048_576 + 1))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_source)

    result = _engine().generate_types(str(tmp_path), "growing.py")

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert read_sizes == [1_048_577]


def test_generate_types_rejects_symlink_escaping_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.py"
    sentinel = outside.with_suffix(".pyi")
    outside.write_text("value: int = 1\n", encoding="utf-8")
    sentinel.write_text("preserve me\n", encoding="utf-8")
    link = root / "linked.py"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks are unavailable")

    result = _engine().generate_types(str(root), "linked.py")

    assert result["success"] is False
    assert "outside repository root" in result["error"]
    assert sentinel.read_text(encoding="utf-8") == "preserve me\n"


def test_mcp_generate_types_rejects_diff_without_posting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from local_ai_hub import mcp_server

    monkeypatch.setattr(
        mcp_server, "FEATURES", SimpleNamespace(repo=True, supported_repo_actions=lambda: {"generate_types"})
    )
    monkeypatch.setattr(mcp_server.CLIENT, "post", lambda *args, **kwargs: pytest.fail("unexpected API post"))

    result = mcp_server._local_ai_repo_impl(
        "generate_types", root=str(tmp_path), path="sample.py", diff="request a write"
    )

    assert result["success"] is False
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert "read-only" in result["error"]
