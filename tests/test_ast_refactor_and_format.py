from __future__ import annotations

from pathlib import Path
from local_ai_hub.deterministic import DeterministicEngine
from local_ai_hub.repo_tools import RepositoryTools


def test_ast_rename_symbol(tmp_path: Path):
    mod = tmp_path / "math_mod.py"
    mod.write_text("def old_calculate(x):\n    return x * 2\n", encoding="utf-8")

    caller = tmp_path / "main_app.py"
    caller.write_text("from math_mod import old_calculate\n\nres = old_calculate(5)\n", encoding="utf-8")

    rt = RepositoryTools({})
    det = DeterministicEngine({}, repo_tools=rt)

    # Preview first
    preview = det.ast_rename(str(tmp_path), target_file="math_mod.py", old_symbol="old_calculate", new_symbol="new_calculate", apply_changes=False)
    assert preview["success"] is True
    assert "math_mod.py" in [p.replace("\\", "/") for p in preview["affected_files"]]
    assert "def new_calculate" in preview["diffs"]["math_mod.py"]

    # File should not be modified yet
    assert "old_calculate" in mod.read_text(encoding="utf-8")

    # Now apply
    applied = det.ast_rename(str(tmp_path), target_file="math_mod.py", old_symbol="old_calculate", new_symbol="new_calculate", apply_changes=True)
    assert applied["success"] is True
    assert "def new_calculate" in mod.read_text(encoding="utf-8")
    assert "new_calculate" in caller.read_text(encoding="utf-8")
    assert "old_calculate" not in caller.read_text(encoding="utf-8")
