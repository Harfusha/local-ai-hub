import json
from types import SimpleNamespace

import pytest

from local_ai_hub.repo_plan import host_hooks


def test_gemini_dependency_uses_configured_home_and_authorized_pinned_installer(tmp_path, monkeypatch):
    executable = tmp_path / "gemini"
    executable.touch()
    home = tmp_path / "gemini-home"
    home.mkdir()
    monkeypatch.setenv("GEMINI_CLI_HOME", str(home))
    calls = []
    monkeypatch.setattr(host_hooks, "install_superpowers", lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True})
    result = host_hooks.ensure_gemini_superpowers(executable, repo_root=tmp_path)
    assert result["success"]
    assert calls[0][0] == ("gemini_cli",)
    assert calls[0][1]["package_root"] == home / ".gemini/extensions/superpowers"
    assert calls[0][1]["operator_authorized"] is True and calls[0][1]["consent"] is True


def test_npm_windows_shim_uses_native_node_and_manifest_entrypoint(tmp_path, monkeypatch):
    shim = tmp_path / "gemini.cmd"
    shim.touch()
    node = tmp_path / "node.exe"
    node.touch()
    package = tmp_path / "node_modules/@google/gemini-cli"
    (package / "bundle").mkdir(parents=True)
    entry = package / "bundle/gemini.js"
    entry.touch()
    (package / "package.json").write_text(json.dumps({"name": "@google/gemini-cli", "bin": {"gemini": "bundle/gemini.js"}}))
    monkeypatch.setattr("shutil.which", lambda name: str(node) if name == "node" else None)
    calls = []
    monkeypatch.setattr(host_hooks, "install_superpowers", lambda *args, **kwargs: calls.append(kwargs) or {"success": True})
    host_hooks.ensure_gemini_superpowers(shim, repo_root=tmp_path)
    assert calls[0]["executable"] == node
    assert calls[0]["entrypoint"] == entry


def test_npm_manifest_cannot_escape_package(tmp_path, monkeypatch):
    shim = tmp_path / "gemini.cmd"
    shim.touch()
    node = tmp_path / "node.exe"
    node.touch()
    package = tmp_path / "node_modules/@google/gemini-cli"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"name": "@google/gemini-cli", "bin": {"gemini": "../../../outside.js"}}))
    monkeypatch.setattr("shutil.which", lambda name: str(node) if name == "node" else None)
    with pytest.raises(ValueError):
        host_hooks.ensure_gemini_superpowers(shim, repo_root=tmp_path)


def test_missing_extension_installs_pinned_ref_and_checks_files(tmp_path, monkeypatch):
    import local_ai_hub.process_utils as process_utils

    executable = tmp_path / "gemini.exe"
    executable.touch()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("GEMINI_CLI_HOME", str(home))
    package = home / ".gemini/extensions/superpowers"
    calls = []

    def install(argv, **kwargs):
        calls.append(argv)
        (package / "skills/using-superpowers").mkdir(parents=True)
        (package / "skills/using-superpowers/SKILL.md").write_text("instructions")
        (package / "GEMINI.md").write_text("instructions")
        (package / "gemini-extension.json").write_text('{"name":"superpowers","version":"7.0.1"}')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(process_utils, "run_hidden", install)
    result = host_hooks.ensure_gemini_superpowers(executable, repo_root=tmp_path)
    assert result["success"] and result["changed"]
    assert result["dependency"]["install_executed"] is True
    assert calls == [[str(executable), "extensions", "install", "https://github.com/obra/superpowers",
                      "--ref", "v7.0.1", "--consent"]]
    assert result["host_activation"] == "not_verified"
