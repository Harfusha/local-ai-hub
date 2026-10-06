from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("t19_verified_setup", ROOT / "tools" / "setup.py")
assert SPEC is not None and SPEC.loader is not None
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)

REVISION = "a" * 40


def _mock_git(monkeypatch, *, revision: str = REVISION, dirty: str = "") -> None:
    def fake_run(command, **kwargs):
        assert kwargs["capture"] is True
        if command[-3:-1] == ["rev-parse", "--verify"]:
            return subprocess.CompletedProcess(command, 0, stdout=revision + "\n")
        if command[-3:] == ["status", "--porcelain=v1", "--untracked-files=all"]:
            return subprocess.CompletedProcess(command, 0, stdout=dirty)
        raise AssertionError(f"unexpected git command: {command}")

    monkeypatch.setattr(setup, "run", fake_run)


def test_revision_preflight_requires_full_commit_sha() -> None:
    with pytest.raises(ValueError, match="40-character commit SHA"):
        setup.verify_source_revision("master", source_root=ROOT)


def test_revision_preflight_accepts_exact_clean_commit(tmp_path: Path, monkeypatch) -> None:
    _mock_git(monkeypatch)

    assert setup.verify_source_revision(REVISION, source_root=tmp_path) == REVISION


def test_revision_preflight_rejects_wrong_commit(tmp_path: Path, monkeypatch) -> None:
    _mock_git(monkeypatch, revision="b" * 40)

    with pytest.raises(RuntimeError, match="does not match expected verified commit"):
        setup.verify_source_revision(REVISION, source_root=tmp_path)


def test_revision_preflight_rejects_dirty_checkout(tmp_path: Path, monkeypatch) -> None:
    _mock_git(monkeypatch, dirty=" M docs/INSTALL_PROMPT.md\n")

    with pytest.raises(RuntimeError, match="source checkout is dirty"):
        setup.verify_source_revision(REVISION, source_root=tmp_path)


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [
        (0, "systemd-user\n", True),
        (0, "detached-fallback\n", False),
        (1, "", False),
    ],
)
def test_service_bootstrap_reports_only_persistent_success(
    tmp_path: Path, monkeypatch, capsys, returncode: int, stdout: str, expected: bool,
) -> None:
    command_result = subprocess.CompletedProcess([], returncode, stdout=stdout)
    monkeypatch.setattr(setup, "run", lambda *_args, **_kwargs: command_result)

    result = setup.install_persistent_service(tmp_path / "python", tmp_path)

    assert result is expected
    if not expected:
        assert "service registration" in capsys.readouterr().out.casefold()


def test_install_wrappers_require_revision_pin_before_setup() -> None:
    powershell = (ROOT / "install.ps1").read_text(encoding="utf-8")
    shell = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert "ExpectedRevision" in powershell and "--expected-revision" in powershell
    assert "--expected-revision" in shell and "status --porcelain=v1 --untracked-files=all" in shell


def test_install_update_prompts_require_t20_verified_revision() -> None:
    for name in ("INSTALL_PROMPT.md", "UPDATE_PROMPT.md"):
        prompt = (ROOT / "docs" / name).read_text(encoding="utf-8").casefold()
        assert "verified commit" in prompt
        assert "expected-revision" in prompt
        assert "dirty" in prompt
