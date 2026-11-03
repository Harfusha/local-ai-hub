from pathlib import Path
import subprocess
import sys

import pytest

from tools.prepare_local_model_eval_fixture import prepare_fixture
from local_ai_hub.process_utils import hidden_run_kwargs


@pytest.mark.parametrize("case,paths", [
    ("I1", ("src/clamp.py", "tests/test_clamp.py")),
    ("I2", ("index.html", "tests/test_ui.py")),
    ("C1", ("src/clamp.py",)),
    ("C2", ("src/clamp.py",)),
    ("C3", ("src/clamp.py",)),
    ("A1", ("src/checkout.py", "src/pricing.py")),
    ("A2", ("README.md", "src/dispatcher.py", "src/store.py")),
])
def test_fixture_is_clean_disposable_git_repository(tmp_path, case, paths):
    target = tmp_path / case
    result = prepare_fixture(target, case)
    assert result["case"] == case
    assert result["root"] == str(target.resolve())
    assert all((target / path).is_file() for path in paths)
    status = subprocess.run(["git", "-C", str(target), "status", "--porcelain"],
                            capture_output=True, text=True, timeout=10, check=True, **hidden_run_kwargs())
    assert status.stdout == ""


def test_fixture_refuses_existing_target_and_repository_checkout(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    marker = existing / "preserve.txt"
    marker.write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError):
        prepare_fixture(existing, "I1")
    assert marker.read_text(encoding="utf-8") == "preserve"
    with pytest.raises(ValueError):
        prepare_fixture(Path(__file__).resolve().parents[1] / "forbidden-fixture", "I1")


def test_fixture_refuses_relative_path_and_unknown_case(tmp_path):
    with pytest.raises(ValueError):
        prepare_fixture(Path("relative-fixture"), "I1")
    with pytest.raises(ValueError):
        prepare_fixture(tmp_path / "unknown", "unknown")
    assert not (tmp_path / "unknown").exists()


def test_i1_baseline_test_fails_for_the_intended_behavior(tmp_path):
    target = tmp_path / "I1"
    prepare_fixture(target, "I1")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_clamp.py"],
                            cwd=target, capture_output=True, text=True, timeout=30, **hidden_run_kwargs())
    assert result.returncode == 1
    assert "test_middle_value" in result.stdout
    assert "assert 10 == 5" in result.stdout


def test_a1_fixture_has_a_grounded_cross_file_rate_unit_mismatch(tmp_path):
    target = tmp_path / "A1"
    prepare_fixture(target, "A1")
    caller = (target / "src/checkout.py").read_text(encoding="utf-8")
    callee = (target / "src/pricing.py").read_text(encoding="utf-8")
    assert "tax_percent" in caller and "total_with_tax(lines, tax_percent)" in caller
    assert "decimal fraction" in callee and "tax_rate" in callee


def test_a2_fixture_exposes_delivery_retry_window_and_design_constraints(tmp_path):
    target = tmp_path / "A2"
    prepare_fixture(target, "A2")
    dispatcher = (target / "src/dispatcher.py").read_text(encoding="utf-8")
    store = (target / "src/store.py").read_text(encoding="utf-8")
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert dispatcher.index("gateway.send") < dispatcher.index("store.mark_sent")
    assert "def mark_sent" in store and "unique" in readme.lower()


def test_fixture_ignores_git_environment_pointing_at_another_repository(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other_info = prepare_fixture(other, "C1")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    target = tmp_path / "target"
    result = prepare_fixture(target, "I1")
    assert result["head"]
    assert (target / ".git").is_dir()
    assert (other / "src" / "clamp.py").is_file()
    assert other_info["head"] != result["head"]


def test_fixture_rejects_target_inside_another_git_checkout(tmp_path):
    other = tmp_path / "other"
    prepare_fixture(other, "C1")
    with pytest.raises(ValueError):
        prepare_fixture(other / "nested", "I1")
    assert not (other / "nested").exists()


def test_fixture_rejects_symlinked_parent(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError):
        prepare_fixture(link / "fixture", "I1")
    assert not (outside / "fixture").exists()
