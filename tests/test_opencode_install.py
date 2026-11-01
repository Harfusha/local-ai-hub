from __future__ import annotations

import hashlib
import io
import sys
import zipfile

import pytest

from tools import opencode_install


def _archive(name: str, content: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(name, content)
    return out.getvalue()


def _asset(monkeypatch, archive: bytes, executable: bytes):
    monkeypatch.setattr(opencode_install, "WINDOWS_X64_ARCHIVE_SHA256", hashlib.sha256(archive).hexdigest())
    monkeypatch.setattr(opencode_install, "WINDOWS_X64_EXECUTABLE_SHA256", hashlib.sha256(executable).hexdigest())


def test_verified_install_is_idempotent_and_preserves_existing_data(tmp_path, monkeypatch):
    executable = b"verified executable"
    archive = _archive("opencode.exe", executable)
    _asset(monkeypatch, archive, executable)
    calls = []
    monkeypatch.setattr(opencode_install, "_download", lambda: calls.append(True) or archive)
    destination = tmp_path / "path with spaces"
    destination.mkdir()
    (destination / "user.txt").write_text("keep", encoding="utf-8")

    assert opencode_install.install_windows_x64(destination) == destination / "opencode.exe"
    assert opencode_install.install_windows_x64(destination) == destination / "opencode.exe"
    assert calls == [True]
    assert (destination / "opencode.exe").read_bytes() == executable
    assert (destination / "user.txt").read_text(encoding="utf-8") == "keep"


def test_bad_archive_digest_does_not_install(tmp_path, monkeypatch):
    monkeypatch.setattr(opencode_install, "_download", lambda: b"untrusted")
    with pytest.raises(opencode_install.InstallError, match="checksum"):
        opencode_install.install_windows_x64(tmp_path)
    assert not (tmp_path / "opencode.exe").exists()


def test_foreign_existing_binary_is_never_overwritten(tmp_path, monkeypatch):
    target = tmp_path / "opencode.exe"
    target.write_bytes(b"user file")
    monkeypatch.setattr(opencode_install, "_download", lambda: pytest.fail("must not download"))
    with pytest.raises(opencode_install.InstallError, match="existing"):
        opencode_install.install_windows_x64(tmp_path)
    assert target.read_bytes() == b"user file"


@pytest.mark.parametrize("name", ["../opencode.exe", "subdir/opencode.exe", "other.exe"])
def test_unexpected_archive_member_is_rejected(tmp_path, monkeypatch, name):
    archive = _archive(name, b"executable")
    _asset(monkeypatch, archive, b"executable")
    monkeypatch.setattr(opencode_install, "_download", lambda: archive)
    with pytest.raises(opencode_install.InstallError, match="archive"):
        opencode_install.install_windows_x64(tmp_path)
    assert not (tmp_path / "opencode.exe").exists()


def test_download_failure_is_reported_without_installing(tmp_path, monkeypatch):
    def fail():
        raise OSError("network unavailable")
    monkeypatch.setattr(opencode_install, "_download", fail)
    with pytest.raises(opencode_install.InstallError, match="download"):
        opencode_install.install_windows_x64(tmp_path)
    assert not (tmp_path / "opencode.exe").exists()


def test_setup_cli_only_does_not_run_full_hub_install(tmp_path, monkeypatch, capsys):
    from tools import setup

    monkeypatch.setattr(sys, "argv", ["setup.py", "--install-opencode-cli-only", "--opencode-dir", str(tmp_path)])
    monkeypatch.setattr(setup.sys, "platform", "win32")
    monkeypatch.setattr(setup.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(setup._opencode_install_module, "install_windows_x64", lambda path: path / "opencode.exe")
    monkeypatch.setattr(setup, "select_config_source", lambda *_: pytest.fail("full setup must not start"))
    assert setup.main() == 0
    assert "not configured" in capsys.readouterr().out


def test_setup_cli_only_rejects_other_install_modes(tmp_path, monkeypatch):
    from tools import setup

    monkeypatch.setattr(sys, "argv", ["setup.py", "--install-opencode-cli-only", "--expected-revision", "a" * 40])
    monkeypatch.setattr(setup._opencode_install_module, "install_windows_x64", lambda _: pytest.fail("must reject conflicting flags"))
    with pytest.raises(SystemExit):
        setup.main()


def test_archive_with_wrong_binary_digest_is_rejected(tmp_path, monkeypatch):
    archive = _archive("opencode.exe", b"wrong executable")
    _asset(monkeypatch, archive, b"expected executable")
    monkeypatch.setattr(opencode_install, "_download", lambda: archive)
    with pytest.raises(opencode_install.InstallError, match="executable checksum"):
        opencode_install.install_windows_x64(tmp_path)
    assert not (tmp_path / "opencode.exe").exists()


def test_concurrent_destination_creation_never_overwrites(tmp_path, monkeypatch):
    executable = b"verified executable"
    archive = _archive("opencode.exe", executable)
    _asset(monkeypatch, archive, executable)
    monkeypatch.setattr(opencode_install, "_download", lambda: archive)

    def competing_create(_temporary, target):
        target.write_bytes(b"concurrent user file")
        raise FileExistsError("destination exists")

    monkeypatch.setattr(opencode_install.os, "link", competing_create)
    with pytest.raises(opencode_install.InstallError, match="without overwriting"):
        opencode_install.install_windows_x64(tmp_path)
    assert (tmp_path / "opencode.exe").read_bytes() == b"concurrent user file"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["opencode.exe"]
