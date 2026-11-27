"""Local native desktop installation never touches the service."""
import hashlib
import os

import pytest

from tools.install_desktop import install


@pytest.fixture
def files(tmp_path):
    root = tmp_path / "hub"
    (root / "tools").mkdir(parents=True)
    for name in ("hubctl.py", "desktop.py"):
        (root / "tools" / name).touch()
    name = "local-ai-hub-desktop.exe" if os.name == "nt" else "local-ai-hub-desktop"
    binary = tmp_path / name
    binary.write_bytes(b"desktop artifact")
    return root, binary


def test_install_verifies_and_places_native_binary(files):
    root, binary = files
    target = install(binary, root, hashlib.sha256(binary.read_bytes()).hexdigest())
    assert target == root / "bin" / binary.name
    assert target.read_bytes() == binary.read_bytes()
    if os.name != "nt":
        assert os.access(target, os.X_OK)


def test_digest_failure_preserves_existing_binary(files):
    root, binary = files
    target = install(binary, root, hashlib.sha256(binary.read_bytes()).hexdigest())
    binary.write_bytes(b"changed")
    with pytest.raises(ValueError, match="verification"):
        install(binary, root, "0" * 64)
    assert target.read_bytes() == b"desktop artifact"
    assert list(target.parent.iterdir()) == [target]


def test_versioned_install_does_not_overwrite_previous_running_binary(files):
    root, binary = files
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    old = install(binary, root, digest, version="8.2.1")
    binary.write_bytes(b"new release")
    new = install(binary, root, hashlib.sha256(binary.read_bytes()).hexdigest(), version="8.2.2")
    assert old.read_bytes() == b"desktop artifact"
    assert new.read_bytes() == b"new release"


def test_archive_receipt_binds_platform_and_revision():
    import io
    import json
    import zipfile
    from tools.install_desktop import verify_archive
    payload = b"desktop"
    revision = "a" * 40
    receipt = {"format": 1, "hub_version": "8.2.2", "repository_revision": revision,
               "os": "Linux", "architecture": "X64", "binary": "local-ai-hub-desktop",
               "sha256": hashlib.sha256(payload).hexdigest()}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(receipt["binary"], payload)
        archive.writestr("desktop-receipt.json", json.dumps(receipt))
        archive.writestr("README.txt", "")
        archive.writestr("SHA256SUMS", "")
    raw = output.getvalue()
    assert verify_archive(raw, version="8.2.2", revision=revision, system="Linux", arch="X64")[1] == payload
    with pytest.raises(ValueError, match="provenance"):
        verify_archive(raw, version="8.2.2", revision="b" * 40, system="Linux", arch="X64")
    with pytest.raises(ValueError, match="entries|provenance"):
        verify_archive(raw, version="8.2.2", revision=revision, system="Windows", arch="X64")
