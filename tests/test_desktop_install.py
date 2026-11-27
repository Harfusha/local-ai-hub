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
        archive.writestr("SHA256SUMS", f"{receipt['sha256']}  {receipt['binary']}\n")
    raw = output.getvalue()
    assert verify_archive(raw, version="8.2.2", revision=revision, system="Linux", arch="X64")[1] == payload
    with pytest.raises(ValueError, match="provenance"):
        verify_archive(raw, version="8.2.2", revision="b" * 40, system="Linux", arch="X64")
    with pytest.raises(ValueError, match="entries|provenance"):
        verify_archive(raw, version="8.2.2", revision=revision, system="Windows", arch="X64")


def test_v2_archive_binds_dependency_notices_lock_and_exact_checksums():
    import io
    import json
    import zipfile
    from tools.install_desktop import verify_archive

    binary = b"native executable"
    auxiliary = {"LICENSE": b"MIT", "THIRD-PARTY-NOTICES.txt": b"upstream notices",
                 "Cargo.lock": b"locked graph"}
    receipt = {"format": 2, "hub_version": "8.2.2", "repository_revision": "a" * 40,
               "os": "Linux", "architecture": "X64", "binary": "local-ai-hub-desktop",
               "sha256": hashlib.sha256(binary).hexdigest(),
               "auxiliary_sha256": {key: hashlib.sha256(data).hexdigest() for key, data in auxiliary.items()}}
    sums = f"{receipt['sha256']}  {receipt['binary']}\n" + "".join(
        f"{sha}  {key}\n" for key, sha in sorted(receipt["auxiliary_sha256"].items()))

    def make_archive(entries, checksums=sums):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(receipt["binary"], binary)
            archive.writestr("README.txt", "readme")
            archive.writestr("SHA256SUMS", checksums)
            archive.writestr("desktop-receipt.json", json.dumps(receipt))
            for key, value in entries.items():
                archive.writestr(key, value)
        return buffer.getvalue()

    def verify(raw):
        return verify_archive(raw, version="8.2.2", revision="a" * 40, system="Linux", arch="X64")

    assert verify(make_archive(auxiliary))[0]["format"] == 2
    with pytest.raises(ValueError, match="digest mismatch"):
        verify(make_archive({**auxiliary, "THIRD-PARTY-NOTICES.txt": b"tampered"}))
    with pytest.raises(ValueError, match="SHA256SUMS"):
        verify(make_archive(auxiliary, "forged checksum"))
    with pytest.raises(ValueError, match="entries"):
        verify(make_archive({"LICENSE": b"MIT", "Cargo.lock": b"locked graph"}))


def test_dependency_notices_use_locked_metadata_and_actual_source_text(tmp_path):
    from tools.package_desktop import dependency_notices

    crate = tmp_path / "fixture-crate"
    crate.mkdir()
    (crate / "Cargo.toml").write_text("[package]", encoding="utf-8")
    (crate / "LICENSE-MIT").write_text("Actual upstream license text", encoding="utf-8")
    package = {"name": "fixture", "version": "1.0.0", "source": "registry+fixture",
               "license": "MIT", "manifest_path": str(crate / "Cargo.toml"), "license_file": None}
    metadata = {"packages": [package]}
    lock = {"package": [{key: package[key] for key in ("name", "version", "source")}]}
    report = dependency_notices(metadata, lock).decode("utf-8")
    assert "fixture 1.0.0" in report and "License expression: MIT" in report
    assert "Actual upstream license text" in report
    with pytest.raises(ValueError, match="locked"):
        dependency_notices(metadata, {"package": [{**lock["package"][0], "version": "2.0.0"}]})
