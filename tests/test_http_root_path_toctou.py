from pathlib import Path

import pytest

from local_ai_hub import http_server


def test_strict_root_path_rejects_resolution_target_swap(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate"
    outside = tmp_path / "outside"
    candidate.mkdir()
    outside.mkdir()
    original_resolve = Path.resolve

    def swapped_resolve(path, *args, **kwargs):
        if path == candidate:
            return outside
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", swapped_resolve)

    with pytest.raises(ValueError, match="changed during validation"):
        http_server._strict_root_path(str(candidate))
