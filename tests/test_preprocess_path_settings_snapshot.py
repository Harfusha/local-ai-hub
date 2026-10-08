from types import SimpleNamespace

import pytest

from local_ai_hub.preprocess import ProjectPreprocessor
from local_ai_hub.project_config import ProjectSettings


@pytest.mark.parametrize("relative,size,expected", [
    ("src/main.py", 20, True),
    ("excluded/secret.py", 20, False),
    ("build/no.py", 20, False),
    ("build/keep.py", 20, True),
    (".git/config.py", 20, False),
    ("src/large.py", 200, False),
    ("src/data.bin", 20, False),
])
def test_path_check_uses_supplied_settings_without_reloading_project(tmp_path, relative, size, expected):
    preprocessor = object.__new__(ProjectPreprocessor)
    preprocessor.repo_tools = SimpleNamespace(
        ignore_dirs={"build"}, ignore_extensions={".bin"},
        extensions={".py"}, special_filenames=set(),
    )
    settings = ProjectSettings(
        exclude_paths=("excluded/**",), force_include_paths=("build/keep.py",),
        max_file_size_bytes=100,
    )
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("value = 1\n", encoding="utf-8")

    def unavailable_context(root):
        raise AssertionError("already supplied settings must not require another Git/config probe")

    preprocessor._project_config_context = unavailable_context

    assert preprocessor._project_path_allowed(
        str(tmp_path), relative, settings, phase="call_graph", size_bytes=size,
    ) is expected
