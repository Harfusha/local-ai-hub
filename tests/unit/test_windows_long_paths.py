import os
import sys
from pathlib import Path
import pytest

from local_ai_hub.process_utils import ensure_extended_path


def test_ensure_extended_path_short():
    p = Path("C:/short/path")
    res = ensure_extended_path(p)
    assert not str(res).startswith("\\\\?\\")


def test_ensure_extended_path_long_rw(tmp_path: Path):
    # Construct a nested directory path > 260 chars
    long_subdirs = "segment_" + "a" * 45
    deep_dir = tmp_path
    for _ in range(6):
        deep_dir = deep_dir / long_subdirs

    assert len(str(deep_dir)) > 260

    ext_dir = ensure_extended_path(deep_dir)
    if os.name == "nt":
        assert str(ext_dir).startswith("\\\\?\\")

    ext_dir.mkdir(parents=True, exist_ok=True)
    target_file = ensure_extended_path(deep_dir / "deep_long_file.txt")
    target_file.write_text("extended path content successfully written", encoding="utf-8")
    assert target_file.read_text(encoding="utf-8") == "extended path content successfully written"
