import os
import subprocess

import pytest

from local_ai_hub.repo_tools import RepositoryTools
from local_ai_hub.project_config import ProjectSettings


@pytest.mark.parametrize("project_settings", [None, ProjectSettings()])
def test_inventory_never_scans_external_junction(tmp_path, monkeypatch, project_settings):
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "inside.py").write_text("safe = True\n", encoding="utf-8")
    (outside / "secret.py").write_text("synthetic = True\n", encoding="utf-8")
    link = root / "external-link"
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, text=True, check=False)
        if result.returncode:
            pytest.skip("junction creation unavailable")
    else:
        link.symlink_to(outside, target_is_directory=True)

    tools = RepositoryTools({})
    monkeypatch.setattr(tools, "_git_files", lambda *args, **kwargs: None)
    real_scandir = os.scandir
    scanned = []

    def guarded_scandir(path):
        scanned.append(os.fspath(path))
        if os.path.normcase(os.path.realpath(path)) == os.path.normcase(os.path.realpath(outside)):
            raise AssertionError("inventory scanned outside repository root")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", guarded_scandir)
    found = {path.name for path in tools.iter_files(str(root), project_settings=project_settings)}
    assert found == {"inside.py"}
    assert not any(os.path.normcase(os.path.realpath(p)) == os.path.normcase(os.path.realpath(outside)) for p in scanned)


def test_git_inventory_rejects_file_behind_junction(tmp_path, monkeypatch):
    root, outside = tmp_path / "repo", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "inside.py").write_text("safe = True\n", encoding="utf-8")
    (outside / "secret.py").write_text("synthetic = True\n", encoding="utf-8")
    link = root / "external-link"
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, text=True, check=False)
        if result.returncode:
            pytest.skip("junction creation unavailable")
    else:
        link.symlink_to(outside, target_is_directory=True)
    tools = RepositoryTools({})
    monkeypatch.setattr(tools, "_git_files", lambda *args, **kwargs: [root / "inside.py", link / "secret.py"])
    assert [path.name for path in tools.iter_files(str(root))] == ["inside.py"]
