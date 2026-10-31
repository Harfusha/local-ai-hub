from __future__ import annotations

import tempfile
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
