from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from local_ai_hub.evidence import EvidenceStore


def _source(root: Path) -> tuple[Path, str]:
    root.mkdir()
    file = root / "sample.py"
    file.write_text("value = 1\n", encoding="utf-8")
    return file, hashlib.sha256(file.read_bytes()).hexdigest()


def test_portable_locator_survives_new_checkout_without_original_state(tmp_path: Path) -> None:
    root = tmp_path / "original"
    file, digest = _source(root)
    clone = tmp_path / "clone"
    shutil.copytree(root, clone)
    store = EvidenceStore(tmp_path / "original-state")
    eid = store.put(str(root), {
        "path": file.name, "file_sha256": digest, "start_line": 1,
        "end_line": 1, "text": "value = 1",
    })
    assert eid is not None
    locator = store.export_portable_locator(eid, root=str(root))
    assert locator == {
        "schema_version": 1, "path": "sample.py", "content_digest": digest,
        "start_line": 1, "end_line": 1,
    }
    assert store.export_portable_locator(eid, root=str(clone)) is None
    assert EvidenceStore.portable_source_status(locator, root=str(clone)) == "matching_file"
    (clone / "unrelated.txt").write_text("unrelated", encoding="utf-8")
    assert EvidenceStore.portable_source_status(locator, root=str(clone)) == "matching_file"
    (clone / file.name).write_text("value = 2\n", encoding="utf-8")
    assert EvidenceStore.portable_source_status(locator, root=str(clone)) == "stale"
    (clone / file.name).unlink()
    assert EvidenceStore.portable_source_status(locator, root=str(clone)) == "unavailable"
    file.write_text("value = 3\n", encoding="utf-8")
    assert store.export_portable_locator(eid, root=str(root)) is None


@pytest.mark.parametrize("path", ["../secret", "/secret", "C:/secret", "C:\\secret", "a/../b", ".git/config", "a//b"])
def test_portable_locator_rejects_nonportable_paths(tmp_path: Path, path: str) -> None:
    root = tmp_path / "repo"
    _, digest = _source(root)
    locator = {
        "schema_version": 1, "path": path, "content_digest": digest,
        "start_line": 1, "end_line": 1,
    }
    assert EvidenceStore.portable_source_status(locator, root=str(root)) == "invalid"


def test_portable_locator_rejects_link_and_invalid_metadata(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _, digest = _source(root)
    outside = tmp_path / "outside"
    outside.write_text("value = 1\n", encoding="utf-8")
    link = root / "link"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    locator = {
        "schema_version": 1, "path": "link", "content_digest": digest,
        "start_line": 1, "end_line": 1,
    }
    assert EvidenceStore.portable_source_status(locator, root=str(root)) == "unavailable"
    assert EvidenceStore.portable_source_status({**locator, "start_line": True}, root=str(root)) == "invalid"
    assert EvidenceStore.portable_source_status({**locator, "root": str(root)}, root=str(root)) == "invalid"
    assert EvidenceStore.portable_source_status(locator, root=".") == "invalid"
