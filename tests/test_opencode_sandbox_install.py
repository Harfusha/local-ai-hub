import base64
import hashlib
import io
import tarfile

import pytest

from tools import opencode_sandbox_install as install


def archive(data=b"verified sandbox executor", member="package/bin/x64/wxc-exec.exe"):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        entry = tarfile.TarInfo(member)
        entry.size = len(data)
        tar.addfile(entry, io.BytesIO(data))
    return stream.getvalue()


def pin(monkeypatch, data, executable=b"verified sandbox executor"):
    monkeypatch.setattr(install, "ARCHIVE_SHA512", base64.b64encode(hashlib.sha512(data).digest()).decode())
    monkeypatch.setattr(install, "EXECUTABLE_SHA256", hashlib.sha256(executable).hexdigest())
    monkeypatch.setattr(install, "_download", lambda: data)


def test_installs_verified_file_and_reuses_without_download(tmp_path, monkeypatch):
    data = archive()
    pin(monkeypatch, data)
    executable = install.install_windows_x64(tmp_path / "mxc")
    assert executable.read_bytes() == b"verified sandbox executor"
    monkeypatch.setattr(install, "_download", lambda: pytest.fail("unexpected download"))
    assert install.install_windows_x64(executable.parent) == executable


def test_refuses_foreign_existing_file(tmp_path, monkeypatch):
    target = tmp_path / "wxc-exec.exe"
    target.write_bytes(b"user file")
    monkeypatch.setattr(install, "_download", lambda: pytest.fail("unexpected download"))
    with pytest.raises(install.InstallError):
        install.install_windows_x64(tmp_path)
    assert target.read_bytes() == b"user file"


def test_rejects_bad_package_and_wrong_executable(tmp_path, monkeypatch):
    data = archive()
    pin(monkeypatch, data)
    monkeypatch.setattr(install, "_download", lambda: data + b"corrupt")
    with pytest.raises(install.InstallError, match="archive"):
        install.install_windows_x64(tmp_path / "bad-archive")
    monkeypatch.setattr(install, "_download", lambda: data)
    monkeypatch.setattr(install, "EXECUTABLE_SHA256", "0" * 64)
    with pytest.raises(install.InstallError, match="executable"):
        install.install_windows_x64(tmp_path / "bad-executable")
    assert not (tmp_path / "bad-executable" / "wxc-exec.exe").exists()


def test_rejects_missing_or_duplicate_member(tmp_path, monkeypatch):
    data = archive(member="package/bin/x64/other.exe")
    pin(monkeypatch, data)
    with pytest.raises(install.InstallError, match="member"):
        install.install_windows_x64(tmp_path)
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as tar:
        for _ in range(2):
            entry = tarfile.TarInfo("package/bin/x64/wxc-exec.exe")
            entry.size = 1
            tar.addfile(entry, io.BytesIO(b"x"))
    pin(monkeypatch, stream.getvalue())
    with pytest.raises(install.InstallError, match="member"):
        install.install_windows_x64(tmp_path)


def test_sandbox_cli_rejects_mixed_setup_modes(monkeypatch):
    import sys
    from tools import setup

    monkeypatch.setattr(sys, "argv", ["setup.py", "--install-opencode-sandbox-only", "--with-opencode"])
    with pytest.raises(SystemExit):
        setup.main()
    monkeypatch.setattr(sys, "argv", ["setup.py", "--opencode-sandbox-dir", "somewhere"])
    with pytest.raises(SystemExit):
        setup.main()
