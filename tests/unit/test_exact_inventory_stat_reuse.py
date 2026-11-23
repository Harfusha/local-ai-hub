from pathlib import Path

from local_ai_hub.project_config import ProjectSettings
from local_ai_hub.repo_tools import RepositoryTools


def test_exact_scan_bound_reuses_current_project_file_metadata(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    for name in ("first.py", "second.py"):
        (root / name).write_text("target\n", encoding="utf-8")
    tools = RepositoryTools({"rag": {"extensions": [".py"]}})
    monkeypatch.setattr(tools, "max_files", 1)
    monkeypatch.setattr(tools, "_rg", None)
    monkeypatch.setattr(tools, "prefer_git", False)

    stat = Path.stat
    duplicate_checks = []

    def record_stat(self, *, follow_symlinks=True):
        if follow_symlinks and (self == root or self.parent == root):
            duplicate_checks.append(self)
        return stat(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", record_stat)
    result = tools.search(str(root), "target", exact_count=True, project_settings=ProjectSettings())

    assert result["status_code"] == 503
    assert "1-file scan bound" in result["error"]
    assert not any(path.suffix == ".py" for path in duplicate_checks)


def test_inventory_validates_an_alternate_root_identity(tmp_path, monkeypatch):
    root = tmp_path / "repository"
    root.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    source = root / "first.py"
    source.write_text("target\n", encoding="utf-8")
    alias = root / ".." / root.name
    samefile = Path.samefile
    checked = []

    def record_samefile(self, candidate):
        checked.append((self, candidate))
        return samefile(self, candidate)

    monkeypatch.setattr(Path, "samefile", record_samefile)
    resolve = RepositoryTools._resolve_inventory_path_safe_with_stat

    assert resolve(root, source, resolved_base=other) is None
    assert resolve(root, source, resolved_base=alias) is not None
    assert checked == [(root, other), (root, alias)]
