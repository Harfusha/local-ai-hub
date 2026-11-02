from __future__ import annotations

import tempfile
import os
import stat
import subprocess
from types import SimpleNamespace
from pathlib import Path
import pytest

from local_ai_hub.rag import RAGStore


def test_safe_open_diagram_regular_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        svg_path = Path(tmpdir) / "test.svg"
        svg_path.write_text("<svg><text>hello</text></svg>", encoding="utf-8")

        fd, st = RAGStore._safe_open_diagram(Path(tmpdir), svg_path)
        try:
            assert st.st_size > 0
        finally:
            import os
            os.close(fd)


def test_safe_open_diagram_rejects_directory() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir) / "sub"
        dir_path.mkdir()

        with pytest.raises(Exception):
            RAGStore._safe_open_diagram(Path(tmpdir), dir_path)


def test_invalid_diagram_descriptor_is_closed_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "test.svg"
    image.write_bytes(b"<svg/>")
    original_fstat, original_close = os.fstat, os.close
    closed: list[int] = []
    checked: list[int] = []

    def invalid_stat(fd: int):
        checked.append(fd)
        return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0)

    def record_close(fd: int) -> None:
        if checked and fd == checked[-1]:
            closed.append(fd)
        original_close(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", invalid_stat)
        patch.setattr(os, "close", record_close)
        with pytest.raises(ValueError, match="regular file"):
            RAGStore._safe_open_diagram(tmp_path, image)
    assert len(checked) == 1
    assert closed == checked
    with pytest.raises(OSError):
        original_fstat(closed[0])


def test_oversized_svg_closes_open_descriptor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "large.svg"
    image.write_bytes(b"<svg>too-large</svg>")
    store = RAGStore.__new__(RAGStore)
    store.config = {"rag": {"max_file_bytes": 4}}
    monkeypatch.setattr(store, "_prepare_ingest_workspace", lambda **_kwargs: (tmp_path, "test"))
    original_open = store._safe_open_diagram
    opened: list[int] = []

    def observe_open(root: Path, path: Path):
        fd, stat_result = original_open(root, path)
        opened.append(fd)
        return fd, stat_result

    monkeypatch.setattr(store, "_safe_open_diagram", observe_open)
    result = store.ingest_diagram(root=str(tmp_path), workspace="test", image_path=str(image))

    assert result["success"] is False
    assert "size limit" in result["error"]
    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])


def test_parent_swap_cannot_ingest_external_svg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    parent = root / "diagrams"
    outside = tmp_path / "outside"
    parent.mkdir(parents=True)
    outside.mkdir()
    image = parent / "diagram.svg"
    image.write_text("<svg><text>inside</text></svg>", encoding="utf-8")
    (outside / "diagram.svg").write_text("<svg><text>outside-sentinel</text></svg>", encoding="utf-8")
    store = RAGStore.__new__(RAGStore)
    store.config = {"rag": {"max_file_bytes": 1024}}
    monkeypatch.setattr(store, "_prepare_ingest_workspace", lambda **_kwargs: (root, "test"))
    published: list[str] = []
    monkeypatch.setattr(store, "ingest_document", lambda **kwargs: published.append(kwargs["content"]) or {"success": True})
    original_open = store._safe_open_diagram

    def swap_parent(authorized_root: Path, path: Path):
        image.unlink()
        parent.rmdir()
        if os.name == "nt":
            completed = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(parent), str(outside)], capture_output=True, timeout=10)
            if completed.returncode:
                pytest.skip("Windows junction creation unavailable")
        else:
            parent.symlink_to(outside, target_is_directory=True)
        return original_open(authorized_root, path)

    monkeypatch.setattr(store, "_safe_open_diagram", swap_parent)
    try:
        result = store.ingest_diagram(root=str(root), workspace="test", image_path=str(image))
        assert result["success"] is False
        assert published == []
    finally:
        if getattr(parent, "is_junction", lambda: False)():
            parent.rmdir()
        elif parent.is_symlink():
            parent.unlink()


def test_final_file_swap_cannot_ingest_external_svg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    image = root / "diagram.svg"
    outside = tmp_path / "outside.svg"
    image.write_text("<svg><text>inside</text></svg>", encoding="utf-8")
    outside.write_text("<svg><text>outside-sentinel</text></svg>", encoding="utf-8")
    store = RAGStore.__new__(RAGStore)
    store.config = {"rag": {"max_file_bytes": 1024}}
    monkeypatch.setattr(store, "_prepare_ingest_workspace", lambda **_kwargs: (root, "test"))
    published: list[str] = []
    monkeypatch.setattr(store, "ingest_document", lambda **kwargs: published.append(kwargs["content"]) or {"success": True})
    original_open = store._safe_open_diagram

    def swap_file(authorized_root: Path, path: Path):
        image.unlink()
        try:
            image.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"file symlink creation unavailable: {exc}")
        return original_open(authorized_root, path)

    monkeypatch.setattr(store, "_safe_open_diagram", swap_file)
    result = store.ingest_diagram(root=str(root), workspace="test", image_path=str(image))
    assert result["success"] is False
    assert published == []
