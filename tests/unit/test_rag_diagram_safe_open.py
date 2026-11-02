from __future__ import annotations

import tempfile
import os
import stat
from types import SimpleNamespace
from pathlib import Path
import pytest

from local_ai_hub.rag import RAGStore


def test_safe_open_diagram_regular_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        svg_path = Path(tmpdir) / "test.svg"
        svg_path.write_text("<svg><text>hello</text></svg>", encoding="utf-8")

        fd, st = RAGStore._safe_open_diagram(svg_path)
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
            RAGStore._safe_open_diagram(dir_path)


def test_invalid_diagram_descriptor_is_closed_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image = tmp_path / "test.svg"
    image.write_bytes(b"<svg/>")
    original_fstat, original_close = os.fstat, os.close
    closed: list[int] = []

    def invalid_stat(_fd: int):
        return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0)

    def record_close(fd: int) -> None:
        closed.append(fd)
        original_close(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", invalid_stat)
        patch.setattr(os, "close", record_close)
        with pytest.raises(ValueError, match="regular file"):
            RAGStore._safe_open_diagram(image)
    assert len(closed) == 1
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

    def observe_open(path: Path):
        fd, stat_result = original_open(path)
        opened.append(fd)
        return fd, stat_result

    monkeypatch.setattr(store, "_safe_open_diagram", observe_open)
    result = store.ingest_diagram(root=str(tmp_path), workspace="test", image_path=str(image))

    assert result["success"] is False
    assert "size limit" in result["error"]
    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])
