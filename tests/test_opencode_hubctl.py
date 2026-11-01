import sys

import pytest

from tools import hubctl, opencode_local


def test_hubctl_opencode_forwards_explicit_launch_options(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(opencode_local, "main", lambda argv: seen.extend(argv) or 7)
    monkeypatch.setattr(sys, "argv", ["hubctl", "opencode", "--opencode-model", "qwen3.5:9b",
                                      "--root", str(tmp_path), "--config", str(tmp_path / "config.toml")])
    assert hubctl.main() == 7
    assert seen == ["--model", "qwen3.5:9b", "--project", str(tmp_path),
                    "--config", str(tmp_path / "config.toml")]


def test_hubctl_opencode_requires_explicit_model(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["hubctl", "opencode"])
    with pytest.raises(SystemExit) as error:
        hubctl.main()
    assert error.value.code == 2
