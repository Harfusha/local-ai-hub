from local_ai_hub.repo_tools import RepositoryTools, is_root_archive_path

def test_repo_tools_ignores_system_generated_by_default(tmp_path):
    (tmp_path / ".system_generated").mkdir()
    (tmp_path / ".system_generated" / "gen.log").write_text("log")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "code.py").write_text("def ok(): pass")

    rt = RepositoryTools({})
    files = list(rt.iter_files(str(tmp_path)))
    file_names = [f.name for f in files]

    assert "code.py" in file_names
    assert "gen.log" not in file_names
    assert is_root_archive_path(".system_generated/tasks/task-1.log") is True


def test_repo_tools_honors_configured_ignore_dirs(tmp_path):
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "test.md").write_text("# Test")
    (tmp_path / ".validation").mkdir()
    (tmp_path / ".validation" / "result.json").write_text("{}")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "code.py").write_text("def ok(): pass")

    rt = RepositoryTools({"rag": {"ignore_dirs": ["artifacts", ".validation"]}})
    files = list(rt.iter_files(str(tmp_path)))
    file_names = [f.name for f in files]

    assert "code.py" in file_names
    assert "test.md" not in file_names
    assert "result.json" not in file_names
