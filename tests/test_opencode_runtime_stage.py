import os

import pytest

from local_ai_hub.opencode_runtime_stage import stage_runtime, stage_session_bundle, _SESSION_ASSETS


@pytest.mark.skipif(os.name != "nt", reason="Windows runtime staging")
def test_runtime_staging_never_replaces_existing_destination(tmp_path):
    runtime = tmp_path / "python"
    runtime.mkdir()
    marker = runtime / "keep.txt"
    marker.write_text("existing", encoding="utf-8")
    with pytest.raises(FileExistsError):
        stage_runtime(tmp_path)
    assert marker.read_text(encoding="utf-8") == "existing"
    with pytest.raises(ValueError):
        stage_runtime("relative-path")


@pytest.mark.skipif(os.name != "nt", reason="Windows runtime staging")
def test_session_staging_rejects_unpinned_opencode_before_writing(tmp_path):
    install, dest = tmp_path / "install", tmp_path / "destination"
    dest.mkdir()
    for name in _SESSION_ASSETS:
        asset = install / "tools" / name
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text("fixture", encoding="utf-8")
    cli, node = tmp_path / "opencode.exe", tmp_path / "node.exe"
    cli.write_bytes(b"not the pinned release")
    node.write_bytes(b"fixture")
    with pytest.raises(ValueError, match="pinned release"):
        stage_session_bundle(dest, install, cli, node)
    assert list(dest.iterdir()) == []
