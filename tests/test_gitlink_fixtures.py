from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
PATCH_FIXTURE = "docs/agent-evaluation/fixtures/case132_patch_20261109"


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout


def test_tracked_gitlinks_require_a_submodule_manifest():
    gitlinks = [line for line in git("ls-files", "--stage").splitlines() if line.startswith("160000 ")]

    assert not gitlinks or (ROOT / ".gitmodules").is_file(), (
        "tracked Git links require a corresponding .gitmodules manifest: "
        + ", ".join(line.split("\t", 1)[-1] for line in gitlinks)
    )


def test_patch_fixture_survives_a_clean_clone():
    expected = {"corrupt.patch", "known-good.patch", "sample.py"}
    head = git("rev-parse", "HEAD").strip()
    with TemporaryDirectory(prefix="lah-fixture-clone-") as directory:
        clone = Path(directory) / "clone"
        git("clone", "--shared", "--no-checkout", str(ROOT), str(clone))
        git("sparse-checkout", "set", "--cone", PATCH_FIXTURE, cwd=clone)
        git("checkout", "--detach", head, cwd=clone)
        git("submodule", "status", cwd=clone)

        entries = git("ls-files", "--stage", "--", PATCH_FIXTURE, cwd=clone).splitlines()
        assert {row.split("\t", 1)[1] for row in entries} == {f"{PATCH_FIXTURE}/{name}" for name in expected}
        assert all(row.startswith("100644 ") for row in entries)
        assert all((clone / PATCH_FIXTURE / name).is_file() for name in expected)
        assert git("status", "--porcelain", cwd=clone) == ""

    assert not clone.exists()
