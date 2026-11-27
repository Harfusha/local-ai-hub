"""The native desktop has one current CLI entry point."""

import sys

import pytest

from tools import hubctl
from tools.hubctl import main


def test_dashboard_cli_alias_is_removed(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["hubctl", "dashboard"])

    with pytest.raises(SystemExit) as raised:
        main()

    assert raised.value.code == 2
    assert "invalid choice: 'dashboard'" in capsys.readouterr().err


def test_desktop_launcher_does_not_use_unversioned_install(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(hubctl, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["hubctl", "desktop"])
    monkeypatch.setattr(hubctl.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("launched retired binary"))
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
    legacy = tmp_path / "bin" / ("local-ai-hub-desktop.exe" if hubctl.os.name == "nt" else "local-ai-hub-desktop")
    legacy.parent.mkdir()
    legacy.write_bytes(b"old binary")

    assert main() == 1
    assert "Desktop binary missing" in capsys.readouterr().err
