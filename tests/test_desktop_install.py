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
